"""Focused transport and ownership checks for the assistant's isolated backend boundary."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta, tzinfo
from importlib.resources import files
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from stock_probs import api as application_api
from stock_probs.api import create_app
from stock_probs.assistant import api as assistant_api
from stock_probs.assistant import net
from stock_probs.assistant import storage as assistant_storage
from stock_probs.assistant.api import (
    _PROXY_MAX_NATIVE_JSON_BYTES,
    _native_websearch_declaration,
    _oauth_attempt_response,
    _opencode_model_review_response,
    _provider_proxy_chunks,
    _validated_provider_request,
)
from stock_probs.assistant.native_provider_adapters import (
    NATIVE_WEBFETCH_DESCRIPTION_SHA256,
    native_output_token_budget,
    native_webfetch_schema,
    output_token_budget_from_catalog,
    project_gemini_tool_schema,
)
from stock_probs.assistant.schemas import (
    AssistantContextRef,
    AssistantModelPolicy,
    AssistantTurnContext,
    AssistantTurnResult,
)
from stock_probs.assistant.service import AssistantService, AssistantUnavailable
from stock_probs.assistant.tools import _ACTION_TYPES, AssistantToolGateway
from stock_probs.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from stock_probs.config import Settings
from stock_probs.domain import Bar, HistoricalBarSeries
from stock_probs.provider import FixtureProvider

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
FORECAST_NOW = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)
NATIVE_SESSION_FIXTURE = "ses_0123456789abABCDEFGHIJKLMN"
NATIVE_PROJECT_FIXTURE = "global"
MODEL = AssistantModelPolicy(
    model_id="free/model-v1",
    provider_id="fixture-provider",
    display_name="Fixture model",
    available=True,
    free=True,
    training=False,
    terms_url="https://example.test/terms",
    terms_reviewed_at="2026-10-01",
    policy_version="policy-1",
    disclosure="Fixture model policy.",
    data_collection_allowed=False,
    data_collection_default=False,
)


class _FrozenHTTPDatetime(datetime):
    @classmethod
    def now(cls, tz: tzinfo | None = None) -> datetime:
        if tz is None:
            return NOW.replace(tzinfo=None)
        return NOW.astimezone(tz)


class _AssistantHTTPDatetime(datetime):
    """Freeze session rechecks while retaining process time for OAuth deadlines."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> datetime:
        # Assistant API also validates provider-issued OAuth expiries against process time. Freeze
        # only these request-auth call sites; changing their names without updating this seam must
        # surface as expired-session failures in the assistant route regressions.
        if sys._getframe(1).f_code.co_name in {
            "live_assistant_session",
            "live_oauth_admin",
            "events",
        }:
            if tz is None:
                return NOW.replace(tzinfo=None)
            return NOW.astimezone(tz)
        if tz is None:
            return datetime.now().replace(tzinfo=None)
        return datetime.now(tz)


@pytest.fixture(autouse=True)
def _freeze_http_auth_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep HTTP auth checks on the same instant as their synthetic session rows."""

    monkeypatch.setattr(application_api, "datetime", _FrozenHTTPDatetime)
    monkeypatch.setattr(assistant_api, "datetime", _AssistantHTTPDatetime)


class FakeCatalog:
    def __init__(self, model: AssistantModelPolicy = MODEL) -> None:
        self.model = model

    def list_models(self):
        return [
            {
                "model_id": self.model.model_id,
                "provider_id": self.model.provider_id,
                "native_provider_id": self.model.provider_id,
                "display_name": self.model.display_name,
                "available": self.model.available,
                "free": self.model.free,
                "training": self.model.training,
                "terms_url": self.model.terms_url,
                "terms_reviewed_at": self.model.terms_reviewed_at,
                "policy_version": self.model.policy_version,
                "disclosure": self.model.disclosure,
                "data_collection_allowed": self.model.data_collection_allowed,
                "data_collection_default": self.model.data_collection_default,
                "privacy_policy_version": self.model.policy_version,
                "privacy_disclosure": self.model.disclosure,
                "billing_class": "free",
                "billing_policy_version": MODEL.policy_version,
                "cost_disclosure": "Free fixture model.",
                "enabled": True,
                "usable": True,
                "revision": 1,
            }
        ]


class FakeRuntime:
    def __init__(self) -> None:
        self.native_provider_sessions: dict[str, tuple[str, str]] = {}

    async def start(self):
        return None

    def status(self):
        return {"status": "ready", "message": None}

    async def close(self):
        return None

    async def clear_conversation_cache(self, conversation_id):
        del conversation_id
        return True

    def native_provider_metadata(self, execution_id: str) -> tuple[str, str] | None:
        return self.native_provider_sessions.get(execution_id)


class FakeProviders:
    def __init__(self):
        self.calls: list[tuple[str, str, dict[str, object]]] = []
        self.call_contexts: list[dict[str, object]] = []

    async def proxy_chat_completion(self, provider_id, model_id, body, **context):
        self.calls.append((provider_id, model_id, body))
        self.call_contexts.append(context)
        yield b'data: {"choices":[] }\n\n'
        yield b"data: [DONE]\n\n"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _catalog_zen_test_policy() -> AssistantModelPolicy:
    catalog = json.loads(
        files("stock_probs.assistant")
        .joinpath("assistant_catalog.json")
        .read_text(encoding="utf-8")
    )
    zen = catalog["zen"]
    eligible = sorted(
        model_id
        for model_id, row in zen["reviewed_models"].items()
        if row.get("available") is True
        and row.get("free") is True
        and row.get("training") is False
        and row.get("data_collection_allowed") is False
        and row.get("data_collection_default") is False
        and row.get("route") == "openai-compatible"
    )
    assert eligible
    return replace(
        MODEL,
        model_id=f"{zen['provider_id']}/{eligible[0]}",
        provider_id=zen["provider_id"],
        display_name=eligible[0],
    )


def _oauth_deadline(seconds: int = 300) -> float:
    """Build a fresh native OAuth expiry against the process clock used by its validator."""

    return datetime.now(UTC).timestamp() + seconds


def _auth_settings(settings: Settings) -> Settings:
    return replace(
        settings,
        environment="test",
        auth_mode="github",
        auth_session_secret="test-only-session-secret-not-used-in-production-000000",  # noqa: S106
        auth_public_origin="http://testserver",
        auth_session_idle_seconds=86_400,
        github_client_id="test-client-id",
        github_client_secret="test-only-oauth-secret",  # noqa: S106
        github_redirect_uri="http://testserver/api/v1/auth/github/callback",
        assistant_enabled=True,
        assistant_rollout_mode="invited",
    )


def _add_signed_in_user(app, github_id: int, *, role: str = "member") -> dict[str, str | int]:
    """Create a test-only TOTP session through repository auth invariants."""

    repository = app.state.repository
    # Keep authentication records on the same injected clock used by lease, expiry, and policy
    # checks. A wall-clock timestamp makes this fixture invalid when the app's test clock is
    # deliberately frozen to a different instant.
    now = app.state.assistant.now().replace(microsecond=0)
    user = repository.auth_create_user(
        {
            "github_id": github_id,
            "github_login": f"user-{github_id}",
            "display_name": f"Test user {github_id}",
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
                "test-only-encrypted-factor-material",
                now.isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        factor_id = int(cursor.lastrowid)
        connection.commit()
    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    session_id = secrets.token_hex(16)
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
                _sha(session_token),
                _sha(csrf_token),
                now.isoformat(),
                now.isoformat(),
                expires.isoformat(),
                expires.isoformat(),
                now.isoformat(),
                factor_id,
            ),
        )
        connection.commit()
    assert repository.auth_get_session(_sha(session_token)) is not None
    return {
        "user_id": user_id,
        "session_id": session_id,
        "token": session_token,
        "token_hash": _sha(session_token),
        "csrf": csrf_token,
    }


def _browser_client(app, identity: dict[str, str | int]) -> TestClient:
    context = app.state.auth.authenticate(str(identity["token"]), app.state.assistant.now())
    assert context.user.id == identity["user_id"]
    client = TestClient(app, client=("127.0.0.1", 51000))
    client.cookies.set(SESSION_COOKIE_NAME, str(identity["token"]), path="/")
    client.cookies.set(CSRF_COOKIE_NAME, str(identity["csrf"]), path="/")
    return client


def test_http_assistant_request_rejects_and_revokes_idle_expired_session(settings):
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51000)) as browser:
        identity = _add_signed_in_user(application, 50000)
        browser.cookies.set(SESSION_COOKIE_NAME, str(identity["token"]), path="/")
        browser.cookies.set(CSRF_COOKIE_NAME, str(identity["csrf"]), path="/")

        valid = browser.get("/api/v1/assistant/context", params={"route": "/overview"})
        assert valid.status_code == 200
        session_before_expiry = application.state.repository.auth_get_session(
            str(identity["token_hash"])
        )
        assert session_before_expiry is not None

        expired_last_seen = NOW - timedelta(seconds=2)
        # Preserve the database's issued <= last-seen <= idle-expiry ordering while aging the row.
        with application.state.repository.connect() as connection:
            connection.execute(
                """UPDATE sessions SET issued_at = ?, last_seen_at = ?, idle_expires_at = ?
                WHERE token_hash = ?""",
                (
                    expired_last_seen.isoformat(),
                    expired_last_seen.isoformat(),
                    (NOW - timedelta(seconds=1)).isoformat(),
                    str(identity["token_hash"]),
                ),
            )
            connection.commit()

        expired = browser.get("/api/v1/assistant/context", params={"route": "/overview"})
        assert expired.status_code == 401
        assert expired.json()["error"]["code"] == "authentication_required"
        revoked = application.state.repository.auth_get_session(str(identity["token_hash"]))
        assert revoked is not None
        assert revoked["revoked_at"] is not None
        assert revoked["last_seen_at"] == expired_last_seen.isoformat()


def _mark_recent_test_step_up(app, identity: dict[str, str | int]) -> None:
    """Refresh a fixture session's proof timestamp without handling a real TOTP secret."""

    factor = app.state.repository.auth_get_totp_factor(int(identity["user_id"]))
    assert factor is not None
    verified_at = app.state.assistant.now().replace(microsecond=0).isoformat()
    assert app.state.repository.auth_set_session_mfa(
        str(identity["token_hash"]), "totp", verified_at, int(factor["id"])
    )


def _add_parallel_session(app, identity: dict[str, str | int]) -> dict[str, str | int]:
    """Create another authenticated session for one owner to test non-transferable approvals."""

    repository = app.state.repository
    now = app.state.assistant.now().replace(microsecond=0)
    user_id = int(identity["user_id"])
    factor = repository.auth_get_totp_factor(user_id)
    assert factor is not None
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    session_id = secrets.token_hex(16)
    expires = now + timedelta(hours=23)
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
                _sha(token),
                _sha(csrf),
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
        "token_hash": _sha(token),
        "csrf": csrf,
    }


def _conversation_and_running_turn(
    client: TestClient,
    identity: dict[str, str | int],
    *,
    route: str = "/overview",
    instrument: dict[str, str] | None = None,
    model_id: str = MODEL.model_id,
):
    headers = {"x-csrf-token": str(identity["csrf"])}
    context_query: dict[str, str] = {"route": route}
    if instrument is not None:
        context_query.update(instrument)
    context_response = client.get("/api/v1/assistant/context", params=context_query)
    assert context_response.status_code == 200, context_response.text
    context = context_response.json()["context"]
    created = client.post(
        "/api/v1/assistant/conversations", json={"context": context}, headers=headers
    )
    assert created.status_code == 201, created.text
    conversation = created.json()["conversation"]["conversation"]
    assistant = client.app.state.assistant
    policy_version = assistant.policy(model_id).policy_version
    assistant.storage.create_consent(
        int(identity["user_id"]),
        model_id=model_id,
        policy_version=policy_version,
        accepted_terms=True,
        data_collection_opt_in=False,
        recorded_at=NOW,
    )
    raw_capability = secrets.token_urlsafe(32)
    lease = assistant.storage.create_turn(
        int(identity["user_id"]),
        str(conversation["id"]),
        prompt="Review the workspace safely.",
        model_id=model_id,
        policy_version=policy_version,
        context=context,
        context_version=str(context["context_version"]),
        session_id=str(identity["session_id"]),
        session_token_hash=str(identity["token_hash"]),
        capability=raw_capability,
        now=NOW,
        expires_at=NOW + timedelta(seconds=120),
    )
    assistant.storage.set_turn_status(
        int(identity["user_id"]),
        str(conversation["id"]),
        str(lease["id"]),
        status="running",
        now=NOW,
    )
    lease_row = assistant.storage.execution_lease(str(lease["execution_id"]))
    return context, conversation, lease, lease_row, raw_capability


def _mcp(machine: TestClient, execution_id: str, capability: str, method: str, params=None):
    return machine.post(
        f"/api/v1/assistant/internal/mcp/{execution_id}",
        headers={"Authorization": f"Bearer {capability}"},
        json={"jsonrpc": "2.0", "id": "r1", "method": method, "params": params or {}},
    )


def test_provider_proxy_contract_rejects_model_path_and_unregistered_tools():
    app_tools = AssistantToolGateway.list_tools()
    messages = [{"role": "user", "content": "Summarize this."}]
    baseline = {"model": "assistant-selected", "messages": messages, "stream": True}
    budget = native_output_token_budget()
    assert _validated_provider_request(baseline, app_tools) == {
        **baseline,
        "store": False,
        "max_tokens": budget,
    }
    assert (
        _validated_provider_request({**baseline, "max_tokens": budget}, app_tools)["max_tokens"]
        == budget
    )
    assert _validated_provider_request({**baseline, "model": "other/model"}, app_tools) is None
    assert (
        _validated_provider_request({**baseline, "base_url": "https://example.test"}, app_tools)
        is None
    )
    assert (
        _validated_provider_request(
            {**baseline, "messages": [{"role": "tool", "content": "private result"}]}, app_tools
        )
        is None
    )
    assert (
        _validated_provider_request(
            {
                **baseline,
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "shell.exec",
                            "description": "execute arbitrary commands",
                            "parameters": {"type": "object"},
                        },
                    }
                ],
            },
            app_tools,
        )
        is None
    )
    action_tool = next(tool for tool in app_tools if tool["name"] == "assistant.propose_action")
    declaration = {
        "type": "function",
        "function": {
            "name": action_tool["name"],
            "description": action_tool["description"],
            "parameters": action_tool["inputSchema"],
            "strict": False,
        },
    }
    assert _validated_provider_request({**baseline, "tools": [declaration]}, app_tools) is not None
    for changed in (
        {**declaration, "function": {**declaration["function"], "description": "changed"}},
        {**declaration, "function": {**declaration["function"], "strict": True}},
    ):
        assert _validated_provider_request({**baseline, "tools": [changed]}, app_tools) is None


def test_native_output_budget_is_loaded_once_and_provider_counts_fail_closed() -> None:
    budget = native_output_token_budget()
    assert (
        output_token_budget_from_catalog({"runtime_policy": {"native_output_token_budget": budget}})
        == budget
    )
    lower_budget = max(1, budget // 2)
    assert (
        output_token_budget_from_catalog(
            {"runtime_policy": {"native_output_token_budget": lower_budget}}
        )
        == lower_budget
    )
    for invalid_catalog in (None, {}, {"runtime_policy": None}, {"runtime_policy": {}}):
        with pytest.raises(ValueError, match="assistant_output_policy_invalid"):
            output_token_budget_from_catalog(invalid_catalog)
    for invalid_budget in (True, False, 0, -1, str(budget), None):
        with pytest.raises(ValueError, match="assistant_output_policy_invalid"):
            output_token_budget_from_catalog(
                {"runtime_policy": {"native_output_token_budget": invalid_budget}}
            )

    app_tools = AssistantToolGateway.list_tools()
    baseline = {
        "model": "assistant-selected",
        "messages": [{"role": "user", "content": "bounded"}],
        "stream": True,
    }
    for invalid_count in (True, False, 0, -1, budget + 1, str(budget), None, 1.5):
        assert (
            _validated_provider_request({**baseline, "max_tokens": invalid_count}, app_tools)
            is None
        )


def test_provider_proxy_rejects_malformed_unicode_and_unbounded_integer_without_raising():
    baseline = {
        "model": "assistant-selected",
        "messages": [{"role": "user", "content": "\ud800"}],
        "stream": True,
    }
    assert _validated_provider_request(baseline, []) is None
    assert (
        _validated_provider_request(
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "valid"}],
                "stream": True,
                "temperature": 10**400,
            },
            [],
        )
        is None
    )


def test_provider_proxy_accepts_bounded_native_tool_continuation_fixture():
    """Protocol-derived V2 continuation shapes stay tied to declared tools and call IDs."""

    app_tools = AssistantToolGateway.list_tools()
    raw_tool = next(tool for tool in app_tools if tool["name"] == "workspace.summary")
    wire_name = "signal-ledger_workspace_summary"
    declaration = {
        "type": "function",
        "function": {
            "name": wire_name,
            "description": raw_tool["description"],
            "parameters": raw_tool["inputSchema"],
            "strict": False,
        },
    }
    baseline = {
        "model": "assistant-selected",
        "stream": True,
        "tools": [declaration],
        "messages": [
            {"role": "user", "content": "Summarize my workspace."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {"name": wire_name, "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_123", "content": "{}"},
            {"role": "assistant", "content": "Your workspace is ready."},
        ],
    }
    accepted = _validated_provider_request(baseline, app_tools)
    assert accepted == {
        **baseline,
        "store": False,
        "max_tokens": native_output_token_budget(),
    }
    native_request = {
        **baseline,
        "store": False,
        "stream_options": {"include_usage": True},
    }
    assert _validated_provider_request(native_request, app_tools) == {
        **native_request,
        "max_tokens": native_output_token_budget(),
    }
    for invalid_metadata in (
        {"store": True},
        {"store": "false"},
        {"stream_options": None},
        {"stream_options": {"include_usage": False}},
        {"stream_options": {"include_usage": True, "extra": False}},
        {"stream_options": [True]},
    ):
        assert _validated_provider_request({**baseline, **invalid_metadata}, app_tools) is None
    assert (
        _validated_provider_request(
            {
                **baseline,
                "messages": [
                    baseline["messages"][0],
                    baseline["messages"][1],
                    {"role": "tool", "tool_call_id": "call_other", "content": "{}"},
                ],
            },
            app_tools,
        )
        is None
    )
    assert (
        _validated_provider_request(
            {
                **baseline,
                "messages": [
                    baseline["messages"][0],
                    baseline["messages"][1],
                    baseline["messages"][2],
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_456",
                                "type": "function",
                                "function": {"name": "shell.exec", "arguments": "{}"},
                            }
                        ],
                    },
                ],
            },
            app_tools,
        )
        is None
    )


def test_provider_proxy_accepts_only_captured_native_websearch_descriptor():
    """The pinned V2 builtin schema is exact; query size stays app-bounded at call time."""

    app_tools = AssistantToolGateway.list_tools()
    expected = {
        "type": "function",
        "function": {
            "name": "websearch",
            "description": (
                "Search the web using the user's selected search integration. Use this for "
                "current information beyond knowledge cutoff.\n\n"
                f"The current year is {NOW.year}. Use this year when searching for recent "
                "information or current events."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Websearch query"}},
                "required": ["query"],
                "additionalProperties": False,
            },
            "strict": False,
        },
    }
    assert _native_websearch_declaration() == expected
    baseline = {
        "model": "assistant-selected",
        "stream": True,
        "tools": [expected],
        "messages": [{"role": "user", "content": "Find current market context."}],
    }
    accepted = _validated_provider_request(baseline, app_tools)
    assert accepted == {
        **baseline,
        "store": False,
        "max_tokens": native_output_token_budget(),
    }

    for invalid in (
        {**expected, "function": {**expected["function"], "description": "Search the web."}},
        {
            **expected,
            "function": {
                **expected["function"],
                "parameters": {
                    **expected["function"]["parameters"],
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Websearch query",
                            "maxLength": 1000,
                        }
                    },
                },
            },
        },
        {
            **expected,
            "function": {
                **expected["function"],
                "parameters": {
                    **expected["function"]["parameters"],
                    "additionalProperties": True,
                },
            },
        },
        {
            **expected,
            "function": {
                **expected["function"],
                "parameters": {
                    **expected["function"]["parameters"],
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Websearch query",
                            "pattern": ".*",
                        }
                    },
                },
            },
        },
    ):
        assert _validated_provider_request({**baseline, "tools": [invalid]}, app_tools) is None

    wire_messages = [
        {"role": "user", "content": "Search this query."},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_search",
                    "type": "function",
                    "function": {"name": "websearch", "arguments": '{"query":"market hours"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_search", "content": "Search results."},
        {"role": "assistant", "content": "Here is the summary."},
    ]
    assert (
        _validated_provider_request({**baseline, "messages": wire_messages}, app_tools) is not None
    )
    for arguments in (
        json.dumps({"query": "x" * 1001}),
        '{"query":"first","query":"second"}',
        json.dumps({"query": " query with outer spaces "}),
        json.dumps({"query": "valid", "extra": "widened"}),
    ):
        invalid_messages = [
            wire_messages[0],
            {
                **wire_messages[1],
                "tool_calls": [
                    {
                        **wire_messages[1]["tool_calls"][0],
                        "function": {"name": "websearch", "arguments": arguments},
                    }
                ],
            },
            wire_messages[2],
            wire_messages[3],
        ]
        assert (
            _validated_provider_request({**baseline, "messages": invalid_messages}, app_tools)
            is None
        )


def _webfetch_declaration():
    description = (
        "Fetch content from an HTTP or HTTPS URL and return it as text, markdown, or HTML. "
        "Markdown is the default.\n\nUse a more targeted tool when one is available. "
        "This tool is read-only. Large text results may be replaced with a preview while the "
        "complete output is retained in managed storage."
    )
    assert hashlib.sha256(description.encode("utf-8")).hexdigest() == (
        NATIVE_WEBFETCH_DESCRIPTION_SHA256
    )
    return {
        "type": "function",
        "function": {
            "name": "webfetch",
            "description": description,
            "parameters": native_webfetch_schema("openai-compatible-chat"),
            "strict": False,
        },
    }


def test_provider_proxy_accepts_exact_webfetch_and_thirteen_known_tools():
    app_tools = AssistantToolGateway.list_tools()
    declarations = []
    for tool in app_tools:
        name = "signal-ledger_" + tool["name"].replace(".", "_")
        declarations.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool["description"],
                    "parameters": tool["inputSchema"],
                    "strict": False,
                },
            }
        )
    declarations.extend((_native_websearch_declaration(), _webfetch_declaration()))
    assert len(app_tools) == 11
    assert len(declarations) == 13
    baseline = {
        "model": "assistant-selected",
        "stream": True,
        "tools": declarations,
        "messages": [{"role": "user", "content": "Fetch the public research note."}],
    }
    assert _validated_provider_request(baseline, app_tools) == {
        **baseline,
        "store": False,
        "max_tokens": native_output_token_budget(),
    }
    unknown = {
        "type": "function",
        "function": {
            "name": "unreviewed_native_tool",
            "description": "unreviewed",
            "parameters": {"type": "object", "properties": {}},
            "strict": False,
        },
    }
    assert (
        _validated_provider_request({**baseline, "tools": [*declarations, unknown]}, app_tools)
        is None
    )


def test_provider_proxy_rejects_changed_webfetch_descriptor_and_arguments():
    app_tools = AssistantToolGateway.list_tools()
    declaration = _webfetch_declaration()
    baseline = {
        "model": "assistant-selected",
        "stream": True,
        "tools": [declaration],
        "messages": [{"role": "user", "content": "Fetch the public note."}],
    }
    changed_description = {
        **declaration,
        "function": {**declaration["function"], "description": "changed"},
    }
    changed_schema = {
        **declaration,
        "function": {
            **declaration["function"],
            "parameters": {
                **declaration["function"]["parameters"],
                "properties": {
                    **declaration["function"]["parameters"]["properties"],
                    "url": {
                        **declaration["function"]["parameters"]["properties"]["url"],
                        "pattern": ".*",
                    },
                },
            },
        },
    }
    malformed_description = {
        **declaration,
        "function": {**declaration["function"], "description": "\ud800"},
    }
    for changed in (changed_description, changed_schema, malformed_description):
        assert _validated_provider_request({**baseline, "tools": [changed]}, app_tools) is None

    for arguments in (
        {"url": "http://example.com/"},
        {"url": "https://127.0.0.1/"},
        {"url": "https://user@example.com/"},
        {"url": "https://example.com/?%74oken=x"},
        {"url": "https://example.com/", "format": "pdf"},
        {"url": "https://example.com/", "format": None},
        {"url": "https://example.com/", "format": []},
        {"url": "\ud800"},
        {"url": "https://example.com/", "timeout": None},
        {"url": "https://example.com/", "timeout": 0},
        {"url": "https://example.com/", "timeout": True},
        {"url": "https://example.com/", "timeout": 10**400},
        {"url": "https://example.com/", "extra": "widened"},
    ):
        messages = [
            baseline["messages"][0],
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_fetch",
                        "type": "function",
                        "function": {
                            "name": "webfetch",
                            "arguments": json.dumps(arguments, separators=(",", ":")),
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_fetch", "content": "done"},
            {"role": "assistant", "content": "Finished."},
        ]
        assert _validated_provider_request({**baseline, "messages": messages}, app_tools) is None

    good_messages = [
        baseline["messages"][0],
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_fetch",
                    "type": "function",
                    "function": {
                        "name": "webfetch",
                        "arguments": '{"url":"https://example.com/research","format":"text","timeout":30}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_fetch", "content": "safe result"},
        {"role": "assistant", "content": "Finished."},
    ]
    assert _validated_provider_request({**baseline, "messages": good_messages}, app_tools)


def test_internal_provider_proxy_accepts_exact_thirteen_tool_webfetch_fixture(settings):
    providers = FakeProviders()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    with TestClient(application, client=("127.0.0.1", 51026)) as owner_client:
        owner = _add_signed_in_user(application, 50033)
        browser = _browser_client(application, owner)
        try:
            _context, _conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, owner
            )
            declarations = []
            for tool in AssistantToolGateway.list_tools():
                name = "signal-ledger_" + tool["name"].replace(".", "_")
                declarations.append(
                    {
                        "type": "function",
                        "function": {
                            "name": name,
                            "description": tool["description"],
                            "parameters": tool["inputSchema"],
                            "strict": False,
                        },
                    }
                )
            declarations.extend((_native_websearch_declaration(), _webfetch_declaration()))
            assert len(declarations) == 13
            body = {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "Fetch the public note."}],
                "stream": True,
                "store": False,
                "tools": declarations,
            }
            headers = {
                "Authorization": f"Bearer {capability}",
                "session-id": "ses_native_fetch_fixture_01",
            }
            response = owner_client.post(
                f"/api/v1/assistant/internal/provider/{turn['execution_id']}/chat/completions",
                headers=headers,
                json=body,
            )
            assert response.status_code == 200, response.text
            assert len(providers.calls) == 1
            assert providers.calls[0][2]["tools"] == declarations

            rejected_malformed = owner_client.post(
                f"/api/v1/assistant/internal/provider/{turn['execution_id']}/chat/completions",
                headers=headers,
                json={**body, "temperature": 10**400},
            )
            assert rejected_malformed.status_code == 422
            assert len(providers.calls) == 1

            unknown = {
                "type": "function",
                "function": {
                    "name": "unknown_builtin",
                    "description": "unknown",
                    "parameters": {"type": "object"},
                    "strict": False,
                },
            }
            rejected = owner_client.post(
                f"/api/v1/assistant/internal/provider/{turn['execution_id']}/chat/completions",
                headers=headers,
                json={**body, "tools": [*declarations, unknown]},
            )
            assert rejected.status_code == 422
            assert len(providers.calls) == 1
        finally:
            browser.close()


def test_mcp_auth_owner_isolation_proposals_and_browser_confirmation(settings):
    providers = FakeProviders()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        # Keep the API clock aligned with the synthetic repository/session timestamps below.
        # Wall-clock time would make an action created at NOW appear to predate its conversation.
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    with TestClient(application, client=("127.0.0.1", 51000)) as owner_client:
        owner = _add_signed_in_user(application, 50001)
        member = _add_signed_in_user(application, 50002)
        secondary_session = _add_parallel_session(application, owner)
        owner_browser = _browser_client(application, owner)
        member_browser = _browser_client(application, member)
        secondary_browser = _browser_client(application, secondary_session)
        try:
            context, conversation, turn, lease, raw_capability = _conversation_and_running_turn(
                owner_browser, owner
            )
            conversation_id = str(conversation["id"])
            execution_id = str(turn["execution_id"])
            test_service = application.state.assistant
            persisted_lease = test_service.storage.execution_lease(execution_id)
            raw_session = application.state.repository.get_session(
                str(persisted_lease["session_token_hash"]), now=NOW
            )
            assert raw_session is not None
            assert raw_session["session_id"] == owner["session_id"]
            assert raw_session["auth_method"] == "github"
            assert raw_session["mfa_method"] == "totp"
            assert (
                raw_session["mfa_factor_id"]
                == application.state.repository.auth_get_totp_factor(int(owner["user_id"]))["id"]
            )
            assert application.state.auth.user_from_record(
                application.state.auth.store.auth_get_user_by_id(int(owner["user_id"]))
            ).active
            assert test_service.validate_execution_session(persisted_lease)
            assert test_service.policy_still_authorized(
                int(owner["user_id"]), MODEL.model_id, MODEL.policy_version
            )
            assert test_service._execution_current(
                int(owner["user_id"]), execution_id, MODEL.model_id, MODEL.policy_version
            )
            # Authenticated web clients cannot use the machine route, even from loopback.
            browser_mcp = owner_browser.post(
                f"/api/v1/assistant/internal/mcp/{execution_id}",
                headers={"Authorization": "Bearer " + secrets.token_urlsafe(32)},
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            )
            assert browser_mcp.status_code == 404

            # Invalid capabilities are hidden consistently across initialize/list/call.
            for method, params in (
                ("initialize", {}),
                ("tools/list", {}),
                ("tools/call", {"name": "workspace.summary", "arguments": {}}),
            ):
                rejected = _mcp(owner_client, execution_id, "z" * 48, method, params)
                assert rejected.status_code == 404
                assert rejected.json()["error"]["code"] == "not_found"

            initialized = _mcp(owner_client, execution_id, raw_capability, "initialize")
            listed = _mcp(owner_client, execution_id, raw_capability, "tools/list")
            assert initialized.status_code == 200
            assert listed.status_code == 200
            tool_names = {item["name"] for item in listed.json()["result"]["tools"]}
            assert {
                "workspace.summary",
                "workspace.instrument_lists",
                "history.search",
                "history.saved_forecast",
                "history.outcomes",
                "market.instrument_search",
                "market.quote",
                "market.bars",
                "market.compare",
                "market.news",
                "assistant.propose_action",
            } <= tool_names
            action_declaration = next(
                tool
                for tool in listed.json()["result"]["tools"]
                if tool["name"] == "assistant.propose_action"
            )
            action_types = action_declaration["inputSchema"]["properties"]["action_type"]["enum"]
            assert {"portfolio.add", "portfolio.remove"} <= set(action_types)
            assert (
                application.state.assistant.storage.execution_lease(execution_id)["tool_calls"] == 0
            )

            proposed = _mcp(
                owner_client,
                execution_id,
                raw_capability,
                "tools/call",
                {
                    "name": "assistant.propose_action",
                    "arguments": {"action_type": "theme.set", "payload": {"theme": "dark"}},
                },
            )
            assert proposed.status_code == 200
            content = proposed.json()["result"]["content"][0]["text"]
            model_result = json.loads(content)
            assert model_result["status"] == "pending_user_confirmation"
            assert "confirmation_phrase" not in model_result
            assert (
                application.state.assistant.storage.execution_lease(execution_id)["tool_calls"] == 1
            )

            _member_context, member_conversation, member_turn, _member_lease, _member_capability = (
                _conversation_and_running_turn(member_browser, member)
            )
            member_execution_id = str(member_turn["execution_id"])
            forged_cross_lease = _mcp(
                owner_client,
                member_execution_id,
                raw_capability,
                "tools/call",
                {"name": "workspace.summary", "arguments": {}},
            )
            assert forged_cross_lease.status_code == 404
            assert test_service.storage.execution_lease(member_execution_id)["tool_calls"] == 0

            forged_native_correlation = _mcp(
                owner_client,
                execution_id,
                raw_capability,
                "tools/call",
                {
                    "name": "workspace.summary",
                    "arguments": {},
                    "_meta": {"sessionID": member["session_id"]},
                    "user_id": member["user_id"],
                    "execution_id": member_execution_id,
                },
            )
            assert forged_native_correlation.status_code == 200
            bound_owner_lease = test_service.storage.execution_lease(execution_id)
            assert bound_owner_lease["user_id"] == owner["user_id"]
            assert bound_owner_lease["session_id"] == owner["session_id"]
            assert bound_owner_lease["tool_calls"] == 2
            assert (
                test_service.storage.get_conversation(
                    int(member["user_id"]), str(member_conversation["id"])
                )["conversation"]["id"]
                == member_conversation["id"]
            )

            detail = owner_browser.get(f"/api/v1/assistant/conversations/{conversation_id}")
            assert detail.status_code == 200
            assert detail.json()["events"]["total"] >= 1
            persisted_proposal_event = next(
                event
                for event in detail.json()["events"]["items"]
                if event["type"] == "proposed_action"
            )
            assert "confirmation_phrase" not in persisted_proposal_event["data"]
            saved_proposal = next(
                action for action in detail.json()["actions"] if action["action_id"]
            )
            assert saved_proposal["availability"] == "confirmable"
            action_event = next(
                event
                for event in application.state.assistant.storage.events_after(
                    int(owner["user_id"]), conversation_id, str(turn["id"]), after=0, limit=20
                )
                if event["type"] == "proposed_action"
            )
            card = action_event["data"]
            assert card["action_type"] == "theme.set"
            assert card["changes"] == [{"label": "Theme", "after": "dark"}]
            assert "confirmation_phrase" in card

            # Reopening in the issuing session restores the exact preview and approval phrase.
            restored = saved_proposal["proposal"]
            assert restored["title"] == card["title"]
            assert restored["changes"] == card["changes"]
            assert restored["confirmation_phrase"] == card["confirmation_phrase"]
            # A second session on the same account sees the safe card but cannot transfer its
            # approval phrase or confirm through that session.
            secondary_detail = secondary_browser.get(
                f"/api/v1/assistant/conversations/{conversation_id}"
            )
            assert secondary_detail.status_code == 200
            secondary_action = next(
                action
                for action in secondary_detail.json()["actions"]
                if action["action_id"] == card["action_id"]
            )
            assert secondary_action["availability"] == "different_session"
            assert secondary_action["proposal"]["confirmation_phrase"] is None
            assert (
                "confirmation_phrase"
                not in next(
                    event
                    for event in secondary_detail.json()["events"]["items"]
                    if event["type"] == "proposed_action"
                )["data"]
            )

            other_owner = member_browser.get(f"/api/v1/assistant/conversations/{conversation_id}")
            assert other_owner.status_code == 404
            denied_csrf = owner_browser.post(
                f"/api/v1/assistant/conversations/{conversation_id}/actions/{card['action_id']}/confirm",
                json={
                    "action_version": 1,
                    "context": context,
                    "allow": True,
                    "confirmation_phrase": card["confirmation_phrase"],
                },
            )
            assert denied_csrf.status_code == 403
            stale_context = owner_browser.get(
                "/api/v1/assistant/context", params={"route": "/account"}
            ).json()["context"]
            stale = owner_browser.post(
                f"/api/v1/assistant/conversations/{conversation_id}/actions/{card['action_id']}/confirm",
                headers={"x-csrf-token": str(owner["csrf"])},
                json={
                    "action_version": 1,
                    "context": stale_context,
                    "allow": True,
                    "confirmation_phrase": card["confirmation_phrase"],
                },
            )
            assert stale.status_code == 409
            applied = owner_browser.post(
                f"/api/v1/assistant/conversations/{conversation_id}/actions/{card['action_id']}/confirm",
                headers={"x-csrf-token": str(owner["csrf"])},
                json={
                    "action_version": 1,
                    "context": context,
                    "allow": True,
                    "confirmation_phrase": card["confirmation_phrase"],
                },
            )
            assert applied.status_code == 200, applied.text
            receipt = applied.json()
            assert receipt["status"] == "handed_off"
            assert receipt["receipt_id"]
            replay = owner_browser.post(
                f"/api/v1/assistant/conversations/{conversation_id}/actions/{card['action_id']}/confirm",
                headers={"x-csrf-token": str(owner["csrf"])},
                json={
                    "action_version": 1,
                    "context": context,
                    "allow": True,
                    "confirmation_phrase": card["confirmation_phrase"],
                },
            )
            assert replay.status_code == 409
        finally:
            owner_browser.close()
            member_browser.close()
            secondary_browser.close()


def test_mcp_proposal_only_turn_completes_with_one_durable_action_card(settings):
    """The MCP's persisted proposal is a useful result and is not emitted twice."""

    class ProposalOnlyRuntime(FakeRuntime):
        async def run_turn(self, *, context, prompt, emit):
            del context, prompt, emit
            return AssistantTurnResult(status="completed")

    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=ProposalOnlyRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51002)) as machine:
        identity = _add_signed_in_user(application, 50004)
        browser = _browser_client(application, identity)
        try:
            context, conversation, turn, lease, capability = _conversation_and_running_turn(
                browser, identity
            )
            response = _mcp(
                machine,
                str(turn["execution_id"]),
                capability,
                "tools/call",
                {
                    "name": "assistant.propose_action",
                    "arguments": {"action_type": "theme.set", "payload": {"theme": "dark"}},
                },
            )
            assert response.status_code == 200, response.text
            app = application.state.assistant
            auth_context = application.state.auth.authenticate(str(identity["token"]), app.now())
            awaitable = app._run_turn(
                context=auth_context,
                conversation_id=str(conversation["id"]),
                turn_id=str(turn["id"]),
                execution_id=str(turn["execution_id"]),
                capability=capability,
                model_id=MODEL.model_id,
                policy=MODEL,
                prompt="Set theme dark.",
                canonical_context=context,
            )
            import asyncio

            asyncio.run(awaitable)
            saved = app.storage.get_turn(
                int(identity["user_id"]), str(conversation["id"]), str(turn["id"])
            )
            events = app.storage.events_after(
                int(identity["user_id"]),
                str(conversation["id"]),
                str(turn["id"]),
                after=0,
            )
            assert saved["status"] == "completed"
            assert [event["type"] for event in events].count("proposed_action") == 1
            assert [event["type"] for event in events][-1] == "complete"
        finally:
            browser.close()


def test_mcp_reads_persist_compact_receipts_and_validated_market_sources(settings, monkeypatch):
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51010)) as machine:
        identity = _add_signed_in_user(application, 50013)
        browser = _browser_client(application, identity)
        try:
            context, conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, identity
            )
            service = application.state.service
            monkeypatch.setattr(
                service,
                "news",
                lambda symbol, limit: {
                    "provider": "Yahoo Finance",
                    "as_of": NOW.isoformat(),
                    "items": [
                        {
                            "id": "fixture-story-1",
                            "title": "Fixture public headline",
                            "publisher": "Fixture Publisher",
                            "url": "https://news.example.test/story/1",
                            "published_at": NOW.isoformat(),
                            "related_symbols": [symbol],
                        }
                    ][:limit],
                    "coverage": {
                        "returned_count": 1,
                        "partial_metadata": False,
                        "refresh_failed": False,
                    },
                    "cache_state": "miss",
                },
            )
            identity_response = service.lookup("SPY", 1)["items"][0]
            instrument = {
                "symbol": identity_response["canonical_symbol"],
                "asset_type": identity_response["asset_type"],
                "provider": identity_response["provider"],
                "exchange": identity_response["exchange"],
            }
            news = _mcp(
                machine,
                str(turn["execution_id"]),
                capability,
                "tools/call",
                {"name": "market.news", "arguments": instrument},
            )
            assert news.status_code == 200, news.text
            private_query = "private acct sentinel 48q9"
            history = _mcp(
                machine,
                str(turn["execution_id"]),
                capability,
                "tools/call",
                {
                    "name": "history.search",
                    "arguments": {"query": private_query, "page": 1, "page_size": 3},
                },
            )
            assert history.status_code == 200, history.text
            events = application.state.assistant.storage.events_after(
                int(identity["user_id"]),
                str(conversation["id"]),
                str(turn["id"]),
                after=0,
                limit=20,
            )
            receipts = [event["data"] for event in events if event["type"] == "tool"]
            sources = [event["data"] for event in events if event["type"] == "source"]
            assert [item["name"] for item in receipts] == ["market.news", "history.search"]
            assert all(item["status"] == "completed" for item in receipts)
            assert all(item["context_version"] == context["context_version"] for item in receipts)
            assert all(len(item["result_sha256"]) == 64 for item in receipts)
            assert all(item["result_bytes"] <= 65_536 for item in receipts)
            assert receipts[0]["provider"] == "Yahoo Finance"
            assert receipts[0]["source_ids"] == [sources[0]["source_id"]]
            assert sources[0]["title"] == "Fixture public headline"
            assert sources[0]["url"] == "https://news.example.test/story/1"
            assert all(private_query not in json.dumps(item) for item in receipts)
            detail_pages = [
                browser.get(
                    f"/api/v1/assistant/conversations/{conversation['id']}",
                    params={"event_page": page, "event_page_size": 1},
                )
                for page in range(1, 4)
            ]
            assert all(response.status_code == 200 for response in detail_pages)
            assert all(response.json()["events"]["total"] == 3 for response in detail_pages)
            assert all(
                response.json()["event_pagination"]
                == {
                    "page": page,
                    "page_size": 1,
                    "total": 3,
                }
                for page, response in enumerate(detail_pages, start=1)
            )
            replayed_events = [response.json()["events"]["items"][0] for response in detail_pages]
            replayed_receipts = [
                event["data"] for event in replayed_events if event["type"] == "tool"
            ]
            assert [item["name"] for item in replayed_receipts] == [
                "history.search",
                "market.news",
            ]
            assert all(private_query not in json.dumps(event) for event in replayed_events)
            assert {event["turn_id"] for event in replayed_events} == {str(turn["id"])}
        finally:
            browser.close()


def test_market_bars_is_daily_only_and_returns_matching_provenance(settings, monkeypatch):
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51029)) as machine:
        identity = _add_signed_in_user(application, 50037)
        browser = _browser_client(application, identity)
        try:
            context, conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, identity
            )
            execution_id = str(turn["execution_id"])
            listed = _mcp(machine, execution_id, capability, "tools/list")
            declaration = next(
                tool for tool in listed.json()["result"]["tools"] if tool["name"] == "market.bars"
            )
            interval = declaration["inputSchema"]["properties"]["interval"]
            assert interval == {"type": "string", "enum": ["daily"]}
            assert declaration["inputSchema"]["required"] == [
                "symbol",
                "asset_type",
                "provider",
                "exchange",
                "interval",
            ]
            service = application.state.service
            instrument_data = service.lookup("SPY", 1)["items"][0]
            instrument = {
                "symbol": instrument_data["canonical_symbol"],
                "asset_type": instrument_data["asset_type"],
                "provider": instrument_data["provider"],
                "exchange": instrument_data["exchange"],
            }
            bar_start = NOW - timedelta(days=1)
            daily_bar = {
                "timestamp": bar_start.isoformat(),
                "end": NOW.isoformat(),
                "close": 605.0,
                "duration_seconds": 86_400,
            }
            calls: list[tuple[str, str, datetime, str]] = []

            def historical_bars(
                symbol: str,
                asset_type: str,
                requested_at: datetime,
                *,
                range: str,
            ) -> HistoricalBarSeries:
                calls.append((symbol, asset_type, requested_at, range))
                return HistoricalBarSeries(
                    symbol=symbol,
                    range=range,
                    interval="1d",
                    adjustment_basis="unadjusted closes",
                    as_of=requested_at,
                    provider="Yahoo Finance",
                    bars=(Bar(timestamp=bar_start, close=605.0, duration_seconds=86_400),),
                    delayed=True,
                    delay_minutes=15,
                    label="Delayed provider chart.",
                )

            monkeypatch.setattr(service.provider, "historical_bars", historical_bars)
            daily = _mcp(
                machine,
                execution_id,
                capability,
                "tools/call",
                {
                    "name": "market.bars",
                    "arguments": {**instrument, "interval": "daily"},
                },
            )
            assert daily.status_code == 200
            result = json.loads(daily.json()["result"]["content"][0]["text"])
            assert result["data"]["interval"] == "1d"
            assert result["data"]["bars"] == [daily_bar]
            assert result["data"]["as_of"] == NOW.isoformat()
            assert result["data"]["provider"] == "Yahoo Finance"
            assert result["data"]["delayed"] is True
            assert result["data"]["delay_minutes"] == 15

            unsupported = _mcp(
                machine,
                execution_id,
                capability,
                "tools/call",
                {
                    "name": "market.bars",
                    "arguments": {**instrument, "interval": "intraday"},
                },
            )
            assert unsupported.status_code == 200
            assert unsupported.json()["result"]["isError"] is True
            assert unsupported.json()["result"]["content"][0]["text"] == json.dumps(
                {"error": "invalid_tool_arguments"}
            )
            assert calls == [("SPY", "etf", NOW, "1mo")]
            events = application.state.assistant.storage.events_after(
                int(identity["user_id"]),
                str(conversation["id"]),
                str(turn["id"]),
                after=0,
                limit=20,
            )
            receipts = [event["data"] for event in events if event["type"] == "tool"]
            assert len(receipts) == 1
            assert receipts[0]["name"] == "market.bars"
            assert receipts[0]["provider"] == "Yahoo Finance"
            assert receipts[0]["as_of"] == NOW.isoformat()
            assert receipts[0]["context_version"] == context["context_version"]
        finally:
            browser.close()


def test_all_eleven_mcp_tools_dispatch_and_private_saved_ids_remain_owner_scoped(
    settings, monkeypatch
):
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    identity_row = {
        "canonical_symbol": "ACDC",
        "asset_type": "stock",
        "provider": "deterministic fixture",
        "exchange": "NMS",
        "display_name": "ACME Corporation",
    }
    saved_event_id = 501
    saved_result_id = 601
    saved_record = {
        "event": {
            "id": saved_event_id,
            "submitted_symbol": "ACDC",
            "normalized_symbol": "ACDC",
            "asset_type": "stock",
            "status": "success",
            "is_repeat": False,
            "submitted_at": NOW.isoformat(),
            "completed_at": NOW.isoformat(),
            "analysis_kind": "forecast",
        },
        "input": {"id": 701, "symbol": "ACDC", "asset_type": "stock", "quality": "current"},
        "results": [
            {
                "id": saved_result_id,
                "interval": "daily",
                "horizon": "daily_1",
                "direction_probabilities": {"down": 0.2, "unchanged": 0.3, "up": 0.5},
                "private_result_field": "must-not-escape",
            }
        ],
    }
    expected_owner: dict[str, int] = {}

    with TestClient(application, client=("127.0.0.1", 51031)) as machine:
        owner = _add_signed_in_user(application, 50039)
        member = _add_signed_in_user(application, 50040)
        owner_id = int(owner["user_id"])
        expected_owner["id"] = owner_id
        owner_browser = _browser_client(application, owner)
        member_browser = _browser_client(application, member)
        service = application.state.service
        assistant = application.state.assistant

        def lookup(query: str, limit: int):
            del limit
            return {
                "query": query,
                "items": [identity_row] if query.strip().upper() in {"ACDC", "ACME"} else [],
                "total": 1 if query.strip().upper() in {"ACDC", "ACME"} else 0,
            }

        monkeypatch.setattr(service, "lookup", lookup)
        monkeypatch.setattr(
            service,
            "quote_snapshot",
            lambda symbol, asset_type: {
                "symbol": symbol,
                "asset_type": asset_type,
                "provider": "deterministic fixture",
                "price": 42.0,
                "as_of": NOW.isoformat(),
            },
        )
        chart_bar_calls: list[tuple[str, str, datetime, str]] = []
        chart_bar = Bar(
            timestamp=NOW - timedelta(days=1),
            close=42.0,
            duration_seconds=24 * 60 * 60,
        )

        def historical_bars(
            symbol: str,
            asset_type: str,
            requested_at: datetime,
            *,
            range: str,
        ) -> HistoricalBarSeries:
            chart_bar_calls.append((symbol, asset_type, requested_at, range))
            return HistoricalBarSeries(
                symbol=symbol,
                range=range,
                interval="1d",
                adjustment_basis="unadjusted simulated closes",
                as_of=requested_at,
                provider="deterministic fixture",
                bars=(chart_bar,),
                delayed=False,
                delay_minutes=None,
                label="Deterministic simulated fixture chart; not live market data.",
            )

        monkeypatch.setattr(service.provider, "historical_bars", historical_bars)
        monkeypatch.setattr(
            service,
            "news",
            lambda symbol, limit: {
                "provider": "deterministic fixture",
                "as_of": NOW.isoformat(),
                "items": [
                    {
                        "id": "fixture-news-1",
                        "title": "Synthetic public headline",
                        "publisher": "Fixture Publisher",
                        "url": "https://news.example.test/acdc",
                        "published_at": NOW.isoformat(),
                        "related_symbols": [symbol],
                    }
                ][:limit],
            },
        )
        monkeypatch.setattr(
            service,
            "saved_forecast",
            lambda event_id, *, owner_user_id: (
                saved_record
                if owner_user_id == expected_owner["id"] and event_id == saved_event_id
                else None
            ),
        )
        monkeypatch.setattr(
            application.state.repository,
            "historical_series",
            lambda owner_user_id, event_id, *, series, limit: (
                {
                    "event_id": event_id,
                    "symbol": "ACDC",
                    "series": series,
                    "interval": "1d" if series == "daily" else "5m",
                    "items": [{"timestamp": NOW.isoformat(), "close": 42.0}][:limit],
                    "available": True,
                    "future_field": "must-not-escape",
                }
                if owner_user_id == expected_owner["id"]
                else None
            ),
        )
        monkeypatch.setattr(
            application.state.repository,
            "forecast_result",
            lambda owner_user_id, result_id: (
                {"id": result_id}
                if owner_user_id == expected_owner["id"] and result_id == saved_result_id
                else None
            ),
        )
        monkeypatch.setattr(
            application.state.repository,
            "outcome_history",
            lambda owner_user_id, result_id, *, page, page_size: {
                "items": [
                    {
                        "id": 801,
                        "result_id": result_id,
                        "state": "observed",
                        "observed_close": 42.0,
                        "observed_at": NOW.isoformat(),
                        "created_at": NOW.isoformat(),
                        "note": "private observation note",
                    }
                ][:page_size],
                "page": page,
                "page_size": page_size,
                "total": 1,
            }
            if owner_user_id == expected_owner["id"]
            else {"items": [], "page": page, "page_size": page_size, "total": 0},
        )

        def invoke_tools(browser, identity, cases):
            _context, _conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, identity
            )
            execution_id = str(turn["execution_id"])
            completed_names = set()
            for name, arguments in cases:
                response = _mcp(
                    machine,
                    execution_id,
                    capability,
                    "tools/call",
                    {"name": name, "arguments": arguments},
                )
                assert response.status_code == 200, response.text
                assert response.json()["result"]["isError"] is False, (name, response.text)
                content = response.json()["result"]["content"][0]["text"]
                result_payload = json.loads(content)
                assert isinstance(result_payload, dict), (name, content)
                if name == "market.bars":
                    assert result_payload["instrument"] == {
                        **instrument,
                        "display_name": "ACME Corporation",
                    }
                    assert result_payload["data"] == {
                        "range": "1mo",
                        "interval": "1d",
                        "adjustment_basis": "unadjusted simulated closes",
                        "provider": "deterministic fixture",
                        "as_of": NOW.isoformat(),
                        "delayed": False,
                        "delay_minutes": None,
                        "label": "Deterministic simulated fixture chart; not live market data.",
                        "bars": [
                            {
                                "timestamp": chart_bar.timestamp.isoformat(),
                                "end": chart_bar.end.isoformat(),
                                "close": chart_bar.close,
                                "duration_seconds": chart_bar.duration_seconds,
                            }
                        ],
                        "total_available": 1,
                        "truncated": False,
                    }
                completed_names.add(name)
            assistant.storage.close_execution(execution_id, now=NOW)
            assistant.storage.set_turn_status(
                int(identity["user_id"]),
                str(_conversation["id"]),
                str(turn["id"]),
                status="completed",
                now=NOW,
            )
            return completed_names

        instrument = {
            "symbol": "ACDC",
            "asset_type": "stock",
            "provider": "deterministic fixture",
            "exchange": "NMS",
        }
        tool_cases = [
            ("workspace.summary", {}),
            ("workspace.instrument_lists", {"kind": "all"}),
            ("history.search", {"query": "ACDC", "page": 1, "page_size": 5}),
            ("history.saved_forecast", {"event_id": saved_event_id, "series": "daily", "limit": 2}),
            ("history.outcomes", {"result_id": saved_result_id, "page": 1, "page_size": 5}),
            ("market.instrument_search", {"query": "ACDC"}),
            ("market.quote", instrument),
            ("market.bars", {**instrument, "interval": "daily"}),
            ("market.compare", {"instruments": [instrument, instrument]}),
            ("market.news", instrument),
            (
                "assistant.propose_action",
                {"action_type": "theme.set", "payload": {"theme": "dark"}},
            ),
        ]
        try:
            dispatched = invoke_tools(owner_browser, owner, tool_cases[:8])
            dispatched |= invoke_tools(owner_browser, owner, tool_cases[8:])
            assert dispatched == {name for name, _ in tool_cases}
            assert chart_bar_calls == [("ACDC", "stock", NOW, "1mo")]

            _context, _conversation, turn, _lease, capability = _conversation_and_running_turn(
                member_browser, member
            )
            execution_id = str(turn["execution_id"])
            for name, arguments in (
                ("history.saved_forecast", {"event_id": saved_event_id}),
                ("history.outcomes", {"result_id": saved_result_id}),
            ):
                response = _mcp(
                    machine,
                    execution_id,
                    capability,
                    "tools/call",
                    {"name": name, "arguments": arguments},
                )
                assert response.status_code == 200, response.text
                assert response.json()["result"]["isError"] is True
                assert "private observation note" not in response.text
            owner_saved = _mcp(
                machine,
                execution_id,
                capability,
                "tools/call",
                {"name": "history.saved_forecast", "arguments": {"event_id": saved_event_id}},
            )
            assert owner_saved.json()["result"]["isError"] is True
        finally:
            owner_browser.close()
            member_browser.close()


def test_known_secret_in_model_or_market_tool_output_never_persists(settings, monkeypatch):
    providers = FakeProviders()

    class LeakingRuntime(FakeRuntime):
        async def run_turn(self, *, context, prompt, emit):
            del context, prompt
            await emit({"type": "token", "data": {"text": "sk-ant-api03-"}})
            await emit({"type": "token", "data": {"text": "a" * 40}})
            return AssistantTurnResult(status="completed")

    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=LeakingRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    with TestClient(application, client=("127.0.0.1", 51030)) as machine:
        identity = _add_signed_in_user(application, 50038)
        browser = _browser_client(application, identity)
        try:
            _context, conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, identity
            )
            assistant = application.state.assistant

            secret = "sk-ant-api03-" + "a" * 40
            # Search/tool data is scanned before the receipt and source rows are persisted.
            monkeypatch.setattr(
                application.state.service,
                "news",
                lambda symbol, limit: {
                    "provider": "Yahoo Finance",
                    "as_of": NOW.isoformat(),
                    "items": [
                        {
                            "id": "malicious-fixture",
                            "title": "Public headline " + secret,
                            "url": "https://news.example.test/story/1",
                            "related_symbols": [symbol],
                        }
                    ][:limit],
                },
            )
            identity_data = application.state.service.lookup("SPY", 1)["items"][0]
            instrument = {
                "symbol": identity_data["canonical_symbol"],
                "asset_type": identity_data["asset_type"],
                "provider": identity_data["provider"],
                "exchange": identity_data["exchange"],
            }
            tool = _mcp(
                machine,
                str(turn["execution_id"]),
                capability,
                "tools/call",
                {"name": "market.news", "arguments": instrument},
            )
            assert tool.status_code == 200
            assert tool.json()["result"]["isError"] is True
            assert "sensitive_output_rejected" in tool.text
            assert secret not in tool.text

            auth_context = application.state.auth.authenticate(
                str(identity["token"]), assistant.now()
            )
            asyncio.run(
                assistant._run_turn(
                    context=auth_context,
                    conversation_id=str(conversation["id"]),
                    turn_id=str(turn["id"]),
                    execution_id=str(turn["execution_id"]),
                    capability=capability,
                    model_id=MODEL.model_id,
                    policy=MODEL,
                    prompt="Provide a summary.",
                    canonical_context=_context,
                )
            )
            saved_turn = assistant.storage.get_turn(
                int(identity["user_id"]), str(conversation["id"]), str(turn["id"])
            )
            assert saved_turn["status"] == "failed"
            assert saved_turn["error_code"] == "sensitive_output_rejected"
            detail = browser.get(f"/api/v1/assistant/conversations/{conversation['id']}")
            assert detail.status_code == 200
            assert secret not in detail.text
            assert not any(event["type"] == "token" for event in detail.json()["events"]["items"])
            assert providers.calls == []
            after = browser.get(f"/api/v1/assistant/conversations/{conversation['id']}")
            assert secret not in after.text
            assert not any(event["type"] == "source" for event in after.json()["events"]["items"])
            assert not any(
                event["type"] == "tool" and event["data"]["name"] == "market.news"
                for event in after.json()["events"]["items"]
            )
        finally:
            browser.close()


def test_unicode_model_output_keeps_every_token_event_within_utf8_byte_limit(settings):
    emoji_prefix = "😀" * 256
    ascii_suffix = "a" * 8192

    class UnicodeRuntime(FakeRuntime):
        async def run_turn(self, *, context, prompt, emit):
            del context, prompt
            await emit({"type": "token", "data": {"text": emoji_prefix}})
            await emit({"type": "token", "data": {"text": ascii_suffix}})
            return AssistantTurnResult(status="completed")

    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=UnicodeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51031)):
        identity = _add_signed_in_user(application, 50039)
        browser = _browser_client(application, identity)
        try:
            canonical_context, conversation, turn, _lease, capability = (
                _conversation_and_running_turn(browser, identity)
            )
            assistant = application.state.assistant
            auth_context = application.state.auth.authenticate(
                str(identity["token"]), assistant.now()
            )
            asyncio.run(
                assistant._run_turn(
                    context=auth_context,
                    conversation_id=str(conversation["id"]),
                    turn_id=str(turn["id"]),
                    execution_id=str(turn["execution_id"]),
                    capability=capability,
                    model_id=MODEL.model_id,
                    policy=MODEL,
                    prompt="Summarize the market.",
                    canonical_context=canonical_context,
                )
            )

            detail = browser.get(f"/api/v1/assistant/conversations/{conversation['id']}")
            assert detail.status_code == 200
            events = detail.json()["events"]["items"]
            token_texts = [event["data"]["text"] for event in events if event["type"] == "token"]
            assert token_texts
            assert all(len(text.encode("utf-8")) <= 8192 for text in token_texts)
            assert "".join(token_texts) == emoji_prefix + ascii_suffix
            saved = assistant.storage.get_turn(
                int(identity["user_id"]), str(conversation["id"]), str(turn["id"])
            )
            assert saved["status"] == "completed"
        finally:
            browser.close()


def test_saved_forecast_tool_preserves_reviewed_probability_data_and_drops_unknown_fields(
    settings, monkeypatch
):
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    secret = "sk-ant-api03-" + "b" * 40
    recorded_result = {
        "id": 23,
        "recorded_at": NOW.isoformat(),
        "horizon": "close_to_close",
        "interval": "1d",
        "origin_price": 100.0,
        "target_timestamp": NOW.isoformat(),
        "direction_probabilities": {
            "down": 0.2,
            "flat": 0.3,
            "unchanged": 0.3,
            "up": 0.5,
            "unit": "probability",
            "definitions": {"down": "down", "up": "up", "private": secret},
            "event_counts": {"down": 2, "up": 5, "private": secret},
            "uncertainty": {
                "down": {"low": 0.1, "high": 0.4},
                "private": secret,
            },
            "future_private_field": secret,
        },
        "threshold_probabilities": [
            {
                "operator": "gte",
                "threshold": 5,
                "unit": "percent_return",
                "probability": 0.2,
                "uncertainty": {"low": 0.1, "high": 0.3},
                "private_field": secret,
            }
        ],
        "magnitude_intervals": [
            {
                "level": 0.8,
                "percent": {"low": -2, "high": 3, "unit": "percent_return"},
                "price": {"low": 98, "high": 103, "unit": "quote_currency"},
                "private_field": secret,
            }
        ],
        "evaluation": {
            "version": "evaluation-v1",
            "status": "insufficient_history",
            "reason": "not enough outcomes",
            "private_customer_field": secret,
            "forecast_model": {
                "name": "bounded model",
                "direction_brier": {
                    "multiclass_mean": 0.4,
                    "components": {"down": 0.1, "unchanged": 0.1, "up": 0.2},
                    "private_field": secret,
                },
                "future_private_field": secret,
            },
        },
        "outcomes": [{"note": secret}],
        "future_repository_field": secret,
    }
    monkeypatch.setattr(
        application.state.assistant.forecast_service,
        "saved_forecast",
        lambda _event_id, *, owner_user_id: {
            "event": {"id": 9, "normalized_symbol": "SPY", "future_private_field": secret},
            "input": {
                "id": 4,
                "symbol": "SPY",
                "asset_type": "etf",
                "provider": "Yahoo Finance",
                "exchange": "NYSE Arca",
                "company_name": "Fixture ETF",
                "currency": "USD",
                "provider_as_of": NOW.isoformat(),
                "quality": {"state": "stale", "private_customer_note": secret},
                "forecast_contract_version": "forecast-v1",
                "future_private_field": secret,
            },
            "results": [recorded_result],
            "private_provider_called": True,
        },
    )
    monkeypatch.setattr(
        application.state.repository,
        "historical_series",
        lambda *_args, **_kwargs: {
            "event_id": 9,
            "symbol": "SPY",
            "series": "daily",
            "interval": "1d",
            "currency": "USD",
            "provider_as_of": NOW.isoformat(),
            "quality": {"state": "stale", "private_customer_note": secret},
            "items": [
                {
                    "timestamp": NOW.isoformat(),
                    "end": NOW.isoformat(),
                    "close": 600.25,
                    "duration_seconds": 86400,
                    "private_bar_field": secret,
                }
            ],
            "total_available": 12,
            "truncated": True,
            "available": True,
            "private_series_field": secret,
        },
    )

    result = application.state.assistant.tool_gateway._read_saved_forecast(
        1, 9, series="daily", limit=5
    )
    serialized = json.dumps(result)
    safe_forecast = result["results"][0]
    assert safe_forecast["direction_probabilities"]["up"] == 0.5
    assert safe_forecast["threshold_probabilities"][0]["probability"] == 0.2
    assert safe_forecast["magnitude_intervals"][0]["price"]["high"] == 103
    assert (
        safe_forecast["evaluation"]["forecast_model"]["direction_brier"]["multiclass_mean"] == 0.4
    )
    assert result["immutable"] is True
    assert result["recalculated"] is False
    assert result["input"]["provider_as_of"] == NOW.isoformat()
    assert "quality" not in result["input"]
    assert result["price_series"].get("quality") is None
    assert result["price_series"]["items"][0]["close"] == 600.25
    assert "private_series_field" not in result["price_series"]
    assert "private_bar_field" not in json.dumps(result["price_series"])
    assert secret not in serialized
    assert "future_repository_field" not in serialized
    assert "private_customer_field" not in serialized
    assert "outcomes" not in safe_forecast

    history_summary = AssistantToolGateway._history_item(
        {
            "id": 7,
            "submitted_symbol": "SPY",
            "run_id": 3,
            "forecast_available": True,
            "horizons": ["close_to_close", "future_private_horizon", secret],
            "outcome_count": 2,
            "evaluation_statuses": ["available", "private_customer_status", secret],
            "forecast_summary": {"private_customer_field": secret},
            "future_repository_field": secret,
        }
    )
    assert history_summary["horizons"] == ["close_to_close"]
    assert history_summary["outcome_count"] == 2
    assert history_summary["evaluation_statuses"] == ["available"]
    assert "forecast_summary" not in history_summary
    assert secret not in json.dumps(history_summary)


def test_native_search_approval_consumes_shared_call_slot_and_clamps_expiry(settings):
    """Builtin search shares the eight-call lease budget and exact browser preview."""

    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51003)):
        identity = _add_signed_in_user(application, 50005)
        browser = _browser_client(application, identity)
        try:
            page_context, conversation, turn, lease, capability = _conversation_and_running_turn(
                browser, identity
            )
            app = application.state.assistant
            execution_id = str(turn["execution_id"])
            for _ in range(7):
                app.storage.authorize_tool_call(
                    execution_id,
                    capability,
                    now=NOW,
                    marks_private_read=False,
                )
            owner_context = application.state.auth.authenticate(str(identity["token"]), app.now())
            runtime_context = AssistantTurnContext(
                user_id=int(identity["user_id"]),
                app_id="signal-ledger",
                conversation_id=str(conversation["id"]),
                turn_id=str(turn["id"]),
                execution_id=execution_id,
                capability=capability,
                model_id=MODEL.model_id,
                policy_version=MODEL.policy_version,
                context_version=str(page_context["context_version"]),
                page_context=page_context,
                history=(),
            )
            previews = []

            async def approve_exact_preview(event):
                previews.append(event)
                data = event["data"]
                result = app.confirm_search_preview(
                    owner_context,
                    str(conversation["id"]),
                    str(turn["id"]),
                    str(data["preview_id"]),
                    page_context=AssistantContextRef.model_validate(page_context),
                    context_version=str(data["context_version"]),
                    confirmation_phrase=str(data["confirmation_phrase"]),
                    allow=True,
                )
                assert result["status"] == "approved"

            import asyncio

            query = "private account balance from the current conversation"
            approved = asyncio.run(
                app.await_search_approval(runtime_context, query, approve_exact_preview)
            )
            assert approved == query
            assert len(previews) == 1
            data = previews[0]["data"]
            saved_preview = app.storage.get_search_preview(
                int(identity["user_id"]),
                str(conversation["id"]),
                str(turn["id"]),
                str(data["preview_id"]),
            )
            assert saved_preview["query"] == query
            assert datetime.fromisoformat(
                str(saved_preview["expires_at"])
            ) <= datetime.fromisoformat(str(lease["expires_at"]))
            current_lease = app.storage.execution_lease(execution_id)
            assert current_lease["tool_calls"] == 8
            assert execution_id not in app._emitters

            denied = asyncio.run(
                app.await_search_approval(runtime_context, "another query", approve_exact_preview)
            )
            assert denied is None
            assert len(previews) == 1
        finally:
            browser.close()


def test_native_webfetch_preview_is_exact_session_bound_and_single_use(settings):
    """Only the issuing session can approve the exact URL while its turn is still live."""

    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51031)):
        identity = _add_signed_in_user(application, 50031)
        other_session = _add_parallel_session(application, identity)
        browser = _browser_client(application, identity)
        same_session_browser = _browser_client(application, identity)
        other_browser = _browser_client(application, other_session)
        try:
            page_context, conversation, turn, lease, capability = _conversation_and_running_turn(
                browser, identity
            )
            app = application.state.assistant
            execution_id = str(turn["execution_id"])
            for _ in range(7):
                app.storage.authorize_tool_call(
                    execution_id,
                    capability,
                    now=NOW,
                    marks_private_read=False,
                )
            runtime_context = AssistantTurnContext(
                user_id=int(identity["user_id"]),
                app_id="signal-ledger",
                conversation_id=str(conversation["id"]),
                turn_id=str(turn["id"]),
                execution_id=execution_id,
                capability=capability,
                model_id=MODEL.model_id,
                policy_version=MODEL.policy_version,
                context_version=str(page_context["context_version"]),
                page_context=page_context,
                history=(),
            )
            event_seen = threading.Event()
            captured: list[dict[str, object]] = []

            async def emit(event):
                event_type, data = app._normalize_runtime_event(
                    str(event["type"]),
                    event["data"],
                    int(identity["user_id"]),
                    str(conversation["id"]),
                    str(turn["id"]),
                    execution_id=execution_id,
                )
                app.storage.append_event(
                    int(identity["user_id"]),
                    str(conversation["id"]),
                    str(turn["id"]),
                    event_type=event_type,
                    data=data,
                    now=NOW,
                )
                captured.append({"type": event_type, "data": data})
                event_seen.set()

            exact_url = "https://example.com/research?q=SPY%20%26%20QQ"
            events_path = (
                f"/api/v1/assistant/conversations/{conversation['id']}/turns/{turn['id']}/events"
            )

            def read_preview_event():
                with browser.stream("GET", events_path, params={"after": 0}) as response:
                    assert response.status_code == 200
                    event_type = None
                    for line in response.iter_lines():
                        if line.startswith("event:"):
                            event_type = line.partition(":")[2].strip()
                        elif line.startswith("data:") and event_type == "webfetch_preview":
                            return json.loads(line.partition(":")[2].strip())
                raise AssertionError("the live assistant stream ended before the fetch preview")

            with ThreadPoolExecutor(max_workers=2) as executor:
                streamed_event = executor.submit(read_preview_event)
                pending = executor.submit(
                    lambda: asyncio.run(
                        app.await_webfetch_approval(runtime_context, exact_url, emit)
                    )
                )
                if not event_seen.wait(timeout=2):
                    pending.result(timeout=1)
                    pytest.fail("native WebFetch approval returned without a preview event")
                event = captured[0]
                preview_id = str(event["data"]["preview_id"])
                path = (
                    f"/api/v1/assistant/conversations/{conversation['id']}"
                    f"/turns/{turn['id']}/webfetch-previews/{preview_id}"
                )
                loaded = browser.get(path)
                assert loaded.status_code == 200, loaded.text
                preview = loaded.json()["preview"]
                assert preview["url"] == exact_url
                assert preview["confirmation_phrase"].startswith("FETCH ")
                assert datetime.fromisoformat(preview["expires_at"]) <= datetime.fromisoformat(
                    str(lease["expires_at"])
                )
                original_waiter = app._webfetch_waiters[preview_id]
                replacement_waiter = replace(original_waiter, url="https://example.com/replacement")
                with app._webfetch_waiter_lock:
                    app._webfetch_waiters[preview_id] = replacement_waiter
                app._cancel_webfetch_waiter(preview_id, original_waiter)
                assert app._webfetch_waiters[preview_id] is replacement_waiter
                with app._webfetch_waiter_lock:
                    app._webfetch_waiters[preview_id] = original_waiter

                other_loaded = other_browser.get(path)
                assert other_loaded.status_code == 404
                detail = other_browser.get(
                    f"/api/v1/assistant/conversations/{conversation['id']}"
                ).json()
                other_event = next(
                    item for item in detail["events"]["items"] if item["type"] == "webfetch_preview"
                )
                assert "url" not in other_event["data"]
                assert "confirmation_phrase" not in other_event["data"]
                assert exact_url not in json.dumps(detail)

                confirm_path = f"{path}/confirm"
                headers = {"x-csrf-token": str(identity["csrf"])}
                wrong_phrase = browser.post(
                    confirm_path,
                    json={
                        "context_version": preview["context_version"],
                        "context": page_context,
                        "confirmation_phrase": "FETCH wrong",
                        "allow": True,
                    },
                    headers=headers,
                )
                assert wrong_phrase.status_code == 409
                missing_context = browser.post(
                    confirm_path,
                    json={
                        "context_version": preview["context_version"],
                        "confirmation_phrase": preview["confirmation_phrase"],
                        "allow": True,
                    },
                    headers=headers,
                )
                assert missing_context.status_code == 422
                changed_context_response = browser.get(
                    "/api/v1/assistant/context", params={"route": "/research"}
                )
                assert changed_context_response.status_code == 200
                changed_context = changed_context_response.json()["context"]
                stale_context = browser.post(
                    confirm_path,
                    json={
                        "context_version": preview["context_version"],
                        "context": changed_context,
                        "confirmation_phrase": preview["confirmation_phrase"],
                        "allow": True,
                    },
                    headers=headers,
                )
                assert stale_context.status_code == 409
                assert stale_context.json()["error"]["code"] == "webfetch_context_stale"
                assert app._webfetch_waiters[preview_id] is original_waiter
                assert not original_waiter.future.done()
                confirmation = {
                    "context_version": preview["context_version"],
                    "context": page_context,
                    "confirmation_phrase": preview["confirmation_phrase"],
                    "allow": True,
                }
                original_live_waiter = app._require_live_webfetch_waiter
                both_live_checks_complete = threading.Barrier(2)

                def wait_after_live_check(*args, **kwargs):
                    waiter = original_live_waiter(*args, **kwargs)
                    both_live_checks_complete.wait(timeout=3)
                    return waiter

                app._require_live_webfetch_waiter = wait_after_live_check
                try:
                    with ThreadPoolExecutor(max_workers=2) as confirmations:
                        first = confirmations.submit(
                            browser.post,
                            confirm_path,
                            json=confirmation,
                            headers=headers,
                        )
                        second = confirmations.submit(
                            same_session_browser.post,
                            confirm_path,
                            json=confirmation,
                            headers=headers,
                        )
                        responses = [first.result(timeout=5), second.result(timeout=5)]
                finally:
                    app._require_live_webfetch_waiter = original_live_waiter
                assert sorted(response.status_code for response in responses) == [200, 409]
                approved = next(response for response in responses if response.status_code == 200)
                assert approved.json()["status"] == "approved"
                assert pending.result(timeout=2) == exact_url
                app.storage.set_turn_status(
                    int(identity["user_id"]),
                    str(conversation["id"]),
                    str(turn["id"]),
                    status="completed",
                    now=NOW,
                )
                app.storage.append_event(
                    int(identity["user_id"]),
                    str(conversation["id"]),
                    str(turn["id"]),
                    event_type="complete",
                    data={"status": "completed"},
                    now=NOW,
                )
                assert streamed_event.result(timeout=3)["url"] == exact_url
                assert app.storage.execution_lease(execution_id)["tool_calls"] == 8
                assert (
                    browser.post(
                        confirm_path,
                        json={
                            "context_version": preview["context_version"],
                            "context": page_context,
                            "confirmation_phrase": preview["confirmation_phrase"],
                            "allow": True,
                        },
                        headers=headers,
                    ).status_code
                    == 404
                )
        finally:
            other_browser.close()
            same_session_browser.close()
            browser.close()


def test_native_webfetch_decline_does_not_require_current_page_context(settings):
    """A live same-session denial releases no URL and needs only the original preview version."""

    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51034)):
        identity = _add_signed_in_user(application, 50034)
        browser = _browser_client(application, identity)
        try:
            page_context, conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, identity
            )
            app = application.state.assistant
            execution_id = str(turn["execution_id"])
            runtime_context = AssistantTurnContext(
                user_id=int(identity["user_id"]),
                app_id="signal-ledger",
                conversation_id=str(conversation["id"]),
                turn_id=str(turn["id"]),
                execution_id=execution_id,
                capability=capability,
                model_id=MODEL.model_id,
                policy_version=MODEL.policy_version,
                context_version=str(page_context["context_version"]),
                page_context=page_context,
                history=(),
            )
            preview_event_seen = threading.Event()
            preview_events: list[dict[str, object]] = []

            async def capture_preview(event):
                preview_events.append(dict(event))
                preview_event_seen.set()

            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(
                    lambda: asyncio.run(
                        app.await_webfetch_approval(
                            runtime_context,
                            "https://example.com/research?fixture=decline",
                            capture_preview,
                        )
                    )
                )
                assert preview_event_seen.wait(timeout=2)
                data = preview_events[0]["data"]
                preview_id = str(data["preview_id"])
                waiter = app._webfetch_waiters[preview_id]
                response = browser.post(
                    f"/api/v1/assistant/conversations/{conversation['id']}"
                    f"/turns/{turn['id']}/webfetch-previews/{preview_id}/confirm",
                    json={
                        "context_version": str(data["context_version"]),
                        "confirmation_phrase": str(data["confirmation_phrase"]),
                        "allow": False,
                    },
                    headers={"x-csrf-token": str(identity["csrf"])},
                )
                assert response.status_code == 200, response.text
                assert response.json() == {"preview_id": preview_id, "status": "denied"}
                assert pending.result(timeout=3) is None
                assert waiter.future.done()
                assert waiter.future.result() is None
                assert app._webfetch_waiters == {}
        finally:
            browser.close()


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/private",
        "https://127.0.0.1/admin",
        "https://[::1]/admin",
        "https://service.localhost/private",
        "https://user:password@example.com/private",
        "https://example.com/private?access_token=credential-like",
    ],
)
def test_native_webfetch_rejects_hostile_destination_before_preview(settings, url):
    """Private, credential-bearing, and non-HTTPS URLs never create browser approvals."""

    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51032)):
        identity = _add_signed_in_user(application, 50032)
        browser = _browser_client(application, identity)
        try:
            page_context, conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, identity
            )
            app = application.state.assistant
            runtime_context = AssistantTurnContext(
                user_id=int(identity["user_id"]),
                app_id="signal-ledger",
                conversation_id=str(conversation["id"]),
                turn_id=str(turn["id"]),
                execution_id=str(turn["execution_id"]),
                capability=capability,
                model_id=MODEL.model_id,
                policy_version=MODEL.policy_version,
                context_version=str(page_context["context_version"]),
                page_context=page_context,
                history=(),
            )
            emitted: list[object] = []

            async def capture_event(event):
                await _capture(emitted, event)

            result = asyncio.run(app.await_webfetch_approval(runtime_context, url, capture_event))
            assert result is None
            assert emitted == []
            assert app.storage.execution_lease(str(turn["execution_id"]))["tool_calls"] == 0
            assert app._webfetch_waiters == {}
        finally:
            browser.close()


@pytest.mark.parametrize("invalidation", ["cancel", "revoke"])
def test_native_webfetch_pending_approval_is_cancelled_with_turn_or_session(settings, invalidation):
    """A pending browser approval cannot outlive its active turn or authenticated session."""

    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51033)):
        identity = _add_signed_in_user(application, 50033)
        browser = _browser_client(application, identity)
        try:
            page_context, conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, identity
            )
            app = application.state.assistant
            execution_id = str(turn["execution_id"])
            runtime_context = AssistantTurnContext(
                user_id=int(identity["user_id"]),
                app_id="signal-ledger",
                conversation_id=str(conversation["id"]),
                turn_id=str(turn["id"]),
                execution_id=execution_id,
                capability=capability,
                model_id=MODEL.model_id,
                policy_version=MODEL.policy_version,
                context_version=str(page_context["context_version"]),
                page_context=page_context,
                history=(),
            )
            event_seen = threading.Event()

            async def emit(_event):
                event_seen.set()

            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(
                    lambda: asyncio.run(
                        app.await_webfetch_approval(
                            runtime_context, "https://example.com/research", emit
                        )
                    )
                )
                assert event_seen.wait(timeout=2)
                if invalidation == "cancel":
                    cancelled = browser.post(
                        f"/api/v1/assistant/conversations/{conversation['id']}"
                        f"/turns/{turn['id']}/cancel",
                        headers={"x-csrf-token": str(identity["csrf"])},
                    )
                    assert cancelled.status_code == 200, cancelled.text
                else:
                    application.state.repository.auth_revoke_session(
                        str(identity["token_hash"]), NOW.isoformat()
                    )
                assert pending.result(timeout=3) is None
                assert app._webfetch_waiters == {}
        finally:
            browser.close()


async def _capture(target: list[object], value: object) -> None:
    target.append(value)


def test_root_context_accepts_only_owner_validated_saved_forecast_references(settings):
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: FORECAST_NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    # Keep auth records on the deterministic HTTP clock; forecasts retain their historical clock.
    application.state.assistant.clock = lambda: NOW
    with TestClient(application, client=("127.0.0.1", 51004)):
        owner = _add_signed_in_user(application, 50006)
        other = _add_signed_in_user(application, 50007)
        browser = _browser_client(application, owner)
        other_browser = _browser_client(application, other)
        try:
            forecast = browser.post(
                "/api/v1/forecasts",
                json={"symbol": "ACDC", "asset_type": "stock"},
                headers={"x-csrf-token": str(owner["csrf"])},
            )
            assert forecast.status_code == 201, forecast.text
            event_id = forecast.json()["event"]["id"]
            result_id = forecast.json()["results"][0]["id"]
            resolved = browser.get(
                "/api/v1/assistant/context",
                params={"route": "/", "event_id": event_id, "result_id": result_id},
            )
            assert resolved.status_code == 200, resolved.text
            context = resolved.json()["context"]
            assert context["route"] == "/"
            assert context["event_ref"]["id"] == event_id
            assert context["result_ref"]["id"] == result_id
            assert len(context["event_ref"]["version"]) == 64
            assert len(context["result_ref"]["version"]) == 64
            decimal_query = browser.get(
                "/api/v1/assistant/context",
                params={"route": "/", "event_id": str(event_id), "result_id": str(result_id)},
            )
            assert decimal_query.status_code == 200, decimal_query.text
            nondecimal_query = browser.get(
                "/api/v1/assistant/context", params={"route": "/", "event_id": "1.0"}
            )
            assert nondecimal_query.status_code == 422

            for bad_event_id, bad_result_id in ((True, result_id), (event_id, 1.5)):
                forged_context = json.loads(json.dumps(context))
                forged_context["event_ref"]["id"] = bad_event_id
                forged_context["result_ref"]["id"] = bad_result_id
                forged = browser.post(
                    "/api/v1/assistant/conversations",
                    json={"context": forged_context},
                    headers={"x-csrf-token": str(owner["csrf"])},
                )
                assert forged.status_code == 422, forged.text
            reopened = browser.post(
                "/api/v1/assistant/conversations",
                json={"context": context},
                headers={"x-csrf-token": str(owner["csrf"])},
            )
            assert reopened.status_code == 201, reopened.text
            denied = other_browser.get(
                "/api/v1/assistant/context",
                params={"route": "/", "event_id": event_id},
            )
            assert denied.status_code == 404
        finally:
            browser.close()
            other_browser.close()


def test_context_query_validation_returns_safe_422_for_invalid_http_queries(settings):
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51014)):
        identity = _add_signed_in_user(application, 50020)
        browser = _browser_client(application, identity)
        try:
            invalid_queries = (
                {"route": "/not-a-route"},
                {"route": "/", "symbol": "SPY", "asset_type": "etf"},
                {"route": "/", "symbol": "SPY", "asset_type": "etf", "provider": "fixture"},
                {"route": "/", "event_id": "not-a-number"},
                {"route": "/", "event_id": "0"},
                {"route": "/", "result_id": "1"},
                {"route": "/", "unknown": "value"},
            )
            for params in invalid_queries:
                response = browser.get("/api/v1/assistant/context", params=params)
                assert response.status_code == 422, (params, response.text)
                assert response.json()["error"]["code"] == "invalid_context_query"
        finally:
            browser.close()


def test_model_consent_route_preserves_catalog_ids_with_encoded_slashes(settings):
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51016)):
        identity = _add_signed_in_user(application, 50023)
        browser = _browser_client(application, identity)
        try:
            encoded_model_id = quote(MODEL.model_id, safe="")
            accepted = browser.put(
                f"/api/v1/assistant/models/{encoded_model_id}/consent",
                headers={"x-csrf-token": str(identity["csrf"])},
                json={
                    "policy_version": MODEL.policy_version,
                    "accepted_terms": True,
                    "data_collection_opt_in": False,
                },
            )
            assert accepted.status_code == 200, accepted.text
            assert accepted.json()["model_id"] == MODEL.model_id
            assert accepted.json()["policy_version"] == MODEL.policy_version

            unknown = browser.put(
                "/api/v1/assistant/models/free%2Funknown/consent",
                headers={"x-csrf-token": str(identity["csrf"])},
                json={
                    "policy_version": MODEL.policy_version,
                    "accepted_terms": True,
                    "data_collection_opt_in": False,
                },
            )
            assert unknown.status_code == 503
            assert unknown.json()["error"]["code"] == "model_unavailable"
        finally:
            browser.close()


@pytest.mark.parametrize("auth_change", ("session_revoked", "csrf_rotated"))
def test_model_consent_route_rechecks_live_auth_before_persisting_after_inventory_await(
    settings, monkeypatch, auth_change
):
    providers = FakeProviders()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    inventory_started = threading.Event()
    release_inventory = threading.Event()
    with TestClient(application, client=("127.0.0.1", 51052)):
        owner = _add_signed_in_user(application, 50089)
        browser = _browser_client(application, owner)
        assistant = application.state.assistant
        authorization_callbacks: list[bool] = []

        async def hold_inventory(*, owner_id, authorization_check=None):
            assert owner_id == owner["user_id"]
            if callable(authorization_check):
                authorization_callbacks.append(authorization_check())
            inventory_started.set()
            if not await asyncio.to_thread(release_inventory.wait, timeout=5):
                raise RuntimeError("test consent inventory wait expired")
            return tuple(assistant.catalog.list_models())

        monkeypatch.setattr(assistant, "ensure_model_inventory", hold_inventory)
        try:
            path = f"/api/v1/assistant/models/{quote(MODEL.model_id, safe='')}/consent"
            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(
                    browser.put,
                    path,
                    headers={"x-csrf-token": str(owner["csrf"])},
                    json={
                        "policy_version": MODEL.policy_version,
                        "accepted_terms": True,
                        "data_collection_opt_in": False,
                    },
                    timeout=5,
                )
                assert inventory_started.wait(timeout=5), "consent missed held inventory"
                if auth_change == "session_revoked":
                    application.state.repository.auth_revoke_session(
                        str(owner["token_hash"]), NOW.isoformat()
                    )
                else:
                    with application.state.repository.connect() as connection:
                        connection.execute(
                            "UPDATE sessions SET csrf_token_hash = ? WHERE token_hash = ?",
                            (_sha("rotated-test-only-csrf-token"), str(owner["token_hash"])),
                        )
                        connection.commit()
                release_inventory.set()
                rejected = pending.result(timeout=8)

            assert rejected.status_code == 403, rejected.text
            assert rejected.json()["error"]["code"] == "assistant_authorization_required"
            assert (
                assistant.storage.current_consent(
                    int(owner["user_id"]), MODEL.model_id, MODEL.policy_version
                )
                is None
            )
            assert authorization_callbacks == [True]
            assert providers.calls == []
        finally:
            release_inventory.set()
            browser.close()


def test_model_policy_route_requires_admin_step_up_and_projects_closed_dto(settings):
    model = {
        "model_id": MODEL.model_id,
        "provider_id": MODEL.provider_id,
        "native_provider_id": "opencode",
        "display_name": MODEL.display_name,
        "available": True,
        "enabled": True,
        "free": False,
        "training": False,
        "terms_url": MODEL.terms_url,
        "terms_reviewed_at": MODEL.terms_reviewed_at,
        "policy_version": MODEL.policy_version,
        "disclosure": MODEL.disclosure,
        "privacy_policy_version": "privacy-v1",
        "privacy_disclosure": "Reviewed privacy terms.",
        "billing_class": "unknown",
        "billing_policy_version": None,
        "cost_disclosure": "Billing is unknown; do not assume free service.",
        "revision": 1,
        "usable": True,
        "availability_reason": None,
        "private_credential": "must-not-escape",
    }

    class Catalog:
        def list_models(self):
            return [model]

    class ProviderManager:
        def __init__(self):
            self.calls = []

        def list_providers(self):
            return [
                {
                    "provider_id": MODEL.provider_id,
                    "display_name": "Fixture provider",
                    "auth_methods": ["none"],
                    "selected_model_id": MODEL.model_id,
                    "selected_base_url": "https://provider.example/v1",
                    "credential_required": False,
                    "credential_configured": False,
                    "oauth_connected": False,
                    "connection_status": "ready",
                    "terms_url": MODEL.terms_url,
                    "native_provider_id": "opencode",
                    "adapter_id": "opencode-openai-compatible",
                    "protocol": "openai-compatible",
                    "endpoint_editable": False,
                    "credential_supported": False,
                    "validation_requires_credential": False,
                    "unsupported_reason": None,
                    "credential": "must-not-escape",
                }
            ]

        def model_policy_state(self, model_id, *, owner_id=None):
            del owner_id
            assert model_id == MODEL.model_id
            return model

        def update_model_policy(self, model_id, **values):
            self.calls.append((model_id, values))
            return {
                "model_id": model_id,
                "enabled": values["enabled"],
                "revision": values["expected_revision"] + 1,
                "usable": values["enabled"],
                "credential": "must-not-escape",
            }

    providers = ProviderManager()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=Catalog(),
        assistant_providers=providers,
    )
    with TestClient(application, client=("127.0.0.1", 51018)):
        admin = _add_signed_in_user(application, 50024, role="admin")
        _mark_recent_test_step_up(application, admin)
        browser = _browser_client(application, admin)
        try:
            models = browser.get("/api/v1/assistant/models")
            assert models.status_code == 200, models.text
            row = models.json()["items"][0]
            assert row["model_id"] == MODEL.model_id
            assert row["id"] == MODEL.model_id
            assert row["training"] == "no_training"
            assert row["training_uses_data"] is False
            assert row["enabled"] is True
            assert row["usable"] is True
            assert row["billing_class"] == "unknown"
            assert row["revision"] == 1
            assert "private_credential" not in models.text

            provider_rows = browser.get("/api/v1/assistant/providers")
            assert provider_rows.status_code == 200, provider_rows.text
            provider = provider_rows.json()["providers"][0]
            assert provider["selected_model_id"] == MODEL.model_id
            assert provider["selected_base_url"] == "https://provider.example/v1"
            assert provider["adapter_id"] == "opencode-openai-compatible"
            assert provider["supported_auth_methods"] == ["none"]
            assert "must-not-escape" not in provider_rows.text

            path = f"/api/v1/assistant/models/{quote(MODEL.model_id, safe='')}/policy"
            headers = {"x-csrf-token": str(admin["csrf"])}
            updated = browser.put(
                path,
                headers=headers,
                json={
                    "enabled": False,
                    "acknowledged_privacy_policy_version": None,
                    "acknowledged_billing_policy_version": None,
                    "expected_revision": 1,
                },
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["model"]["model_id"] == MODEL.model_id
            assert updated.json()["model"]["enabled"] is False
            assert updated.json()["model"]["revision"] == 2
            assert "credential" not in updated.text
            assert providers.calls == [
                (
                    MODEL.model_id,
                    {
                        "enabled": False,
                        "acknowledged_privacy_policy_version": None,
                        "acknowledged_billing_policy_version": None,
                        "expected_revision": 1,
                        "owner_id": admin["user_id"],
                    },
                )
            ]

            strict = browser.put(
                path,
                headers=headers,
                json={"enabled": "true", "expected_revision": 1},
            )
            assert strict.status_code == 422
            assert len(providers.calls) == 1
        finally:
            browser.close()


@pytest.mark.parametrize("auth_change", ["session_revoked", "admin_demoted", "totp_expired"])
def test_model_policy_route_rechecks_admin_auth_after_inventory_await(
    settings, monkeypatch, auth_change
):
    class Catalog:
        def list_models(self):
            return [MODEL]

    class ProviderManager:
        def __init__(self):
            self.calls = []
            self.policy = {
                "model_id": MODEL.model_id,
                "enabled": True,
                "privacy_policy_version": "privacy-v1",
                "privacy_disclosure": "Reviewed privacy terms.",
                "billing_class": "unknown",
                "billing_policy_version": None,
                "cost_disclosure": "Billing is unknown; do not assume free service.",
                "revision": 1,
                "usable": True,
                "availability_reason": None,
                "policy_version": MODEL.policy_version,
            }

        def model_policy_state(self, model_id, *, owner_id=None):
            del owner_id
            assert model_id == MODEL.model_id
            return dict(self.policy)

        def update_model_policy(self, model_id, **values):
            self.calls.append((model_id, values))
            self.policy.update(values)
            self.policy["revision"] = values["expected_revision"] + 1
            self.policy["usable"] = values["enabled"]
            return {
                "model_id": model_id,
                "enabled": values["enabled"],
                "revision": self.policy["revision"],
                "usable": self.policy["usable"],
            }

    providers = ProviderManager()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=Catalog(),
        assistant_providers=providers,
    )
    inventory_started = threading.Event()
    release_inventory = threading.Event()
    with TestClient(application, client=("127.0.0.1", 51049)):
        admin = _add_signed_in_user(application, 50086, role="admin")
        _mark_recent_test_step_up(application, admin)
        browser = _browser_client(application, admin)
        assistant = application.state.assistant

        async def hold_inventory(*, owner_id, authorization_check):
            assert owner_id == admin["user_id"]
            assert authorization_check()
            inventory_started.set()
            if not await asyncio.to_thread(release_inventory.wait, timeout=5):
                raise RuntimeError("test inventory wait expired")
            return (MODEL,)

        monkeypatch.setattr(assistant, "ensure_model_inventory", hold_inventory)
        path = f"/api/v1/assistant/models/{quote(MODEL.model_id, safe='')}/policy"
        before_policy = dict(providers.policy)
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(
                    browser.put,
                    path,
                    headers={"x-csrf-token": str(admin["csrf"])},
                    json={
                        "enabled": False,
                        "acknowledged_privacy_policy_version": None,
                        "acknowledged_billing_policy_version": None,
                        "expected_revision": 1,
                    },
                    timeout=5,
                )
                assert inventory_started.wait(timeout=5), "inventory did not reach the held await"
                if auth_change == "session_revoked":
                    application.state.repository.auth_revoke_session(
                        str(admin["token_hash"]), NOW.isoformat()
                    )
                elif auth_change == "admin_demoted":
                    application.state.repository.auth_update_user(
                        int(admin["user_id"]), {"role": "member"}
                    )
                else:
                    with application.state.repository.connect() as connection:
                        connection.execute(
                            "UPDATE sessions SET mfa_verified_at = ? WHERE token_hash = ?",
                            (
                                (NOW - timedelta(seconds=301)).isoformat(),
                                str(admin["token_hash"]),
                            ),
                        )
                        connection.commit()
                release_inventory.set()
                rejected = pending.result(timeout=8)
            assert rejected.status_code == 403, rejected.text
            assert rejected.json()["error"]["code"] == "assistant_authorization_required"
            assert providers.calls == []
            assert providers.policy == before_policy
        finally:
            release_inventory.set()
            browser.close()


def test_opencode_owner_inventory_review_and_clear_are_closed_and_session_bound(settings):
    fingerprint = "a" * 64

    def row_for(owner_id: int) -> dict[str, object]:
        return {
            "model_id": f"opencode-console/{owner_id:064x}",
            "provider_id": "opencode-console",
            "display_name": f"Reviewed console model {owner_id}",
            "native_model_id": f"model-{owner_id}",
            "adapter_id": "openai-responses",
            "protocol": "openai-responses",
            "package_id": "@opencode/ai/providers/openai",
            "endpoint": "https://api.openai.com/v1",
            "available": True,
            "enabled": False,
            "reviewed": False,
            "billing_class": "unknown",
            "training_policy": "unknown",
            "confidential_data_policy": "unknown",
            "terms_url": None,
            "privacy_disclosure": None,
            "billing_disclosure": None,
            "privacy_policy_version": None,
            "billing_policy_version": None,
            "revision": 0,
            "review_revision": 0,
            "usable": False,
            "availability_reason": "model_policy_review_required",
            "config_fingerprint": fingerprint,
            "native_settings": {"headers": {"authorization": "never expose"}},
        }

    class ProviderManager:
        def __init__(self):
            self.calls = []
            self.rows = {}

        async def ensure_opencode_model_inventory(self, *, owner_id, authorization_check):
            self.calls.append(("discover", owner_id))
            assert authorization_check() is True
            self.rows.setdefault(owner_id, row_for(owner_id))
            return (dict(self.rows[owner_id]),)

        def opencode_inventory_summary(self, *, owner_id):
            return {"model_count": 1, "unsupported_model_count": 2}

        async def review_opencode_model(self, model_id, **values):
            self.calls.append(("review", model_id, values["owner_id"]))
            assert values["authorization_check"]() is True
            current = self.rows[values["owner_id"]]
            assert model_id == current["model_id"]
            assert values["expected_config_fingerprint"] == fingerprint
            current.update(
                {
                    "terms_url": values["terms_url"],
                    "privacy_disclosure": values["privacy_disclosure"],
                    "billing_disclosure": values["billing_disclosure"],
                    "billing_class": values["billing_class"],
                    "training_policy": values["training_policy"],
                    "confidential_data_policy": values["confidential_data_policy"],
                    "reviewed": True,
                    "review_revision": current["review_revision"] + 1,
                }
            )
            return dict(current)

        async def clear_opencode_model_review(
            self, model_id, *, owner_id, expected_revision, authorization_check
        ):
            self.calls.append(("clear", model_id, owner_id, expected_revision))
            assert authorization_check() is True
            current = self.rows[owner_id]
            assert model_id == current["model_id"]
            assert expected_revision == current["review_revision"]
            current.update(
                {
                    "reviewed": False,
                    "review_revision": current["review_revision"] + 1,
                    "terms_url": None,
                    "privacy_disclosure": None,
                    "billing_disclosure": None,
                    "billing_class": "unknown",
                    "training_policy": "unknown",
                    "confidential_data_policy": "unknown",
                    "usable": False,
                }
            )
            return True

    providers = ProviderManager()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    with TestClient(application, client=("127.0.0.1", 51082)):
        first = _add_signed_in_user(application, 50082, role="admin")
        second = _add_signed_in_user(application, 50083, role="admin")
        _mark_recent_test_step_up(application, first)
        _mark_recent_test_step_up(application, second)
        first_browser = _browser_client(application, first)
        second_browser = _browser_client(application, second)
        try:
            listed = first_browser.get("/api/v1/assistant/providers/opencode/models")
            assert listed.status_code == 200, listed.text
            assert listed.json()["unsupported_model_count"] == 2
            model = listed.json()["models"][0]
            first_model_id = str(model["model_id"])
            assert first_model_id == providers.rows[first["user_id"]]["model_id"]
            assert model["provider_id"] == "opencode-console"
            assert model["enabled"] is False
            assert model["training_policy"] == "unknown"
            assert model["confidential_data_policy"] == "unknown"
            assert model["billing_class"] == "unknown"
            assert model["usable"] is False
            assert model["review_revision"] == 0
            assert _opencode_model_review_response({**model, "enabled": True})["enabled"] is True
            for invalid_enabled in (None, 1, "true"):
                assert (
                    _opencode_model_review_response({**model, "enabled": invalid_enabled}) is None
                )
            assert "native_settings" not in listed.text
            assert "never expose" not in listed.text

            # A second owner sees a different opaque model identity and cannot review the first
            # owner's Console row, even if the ID is copied into an authenticated request.
            second_list = second_browser.get("/api/v1/assistant/providers/opencode/models")
            assert second_list.status_code == 200, second_list.text
            assert second_list.json()["models"][0]["model_id"] != first_model_id
            review_body = {
                "terms_url": "https://example.org/terms",
                "privacy_disclosure": "Administrator assertion; unverified. Training is not used.",
                "billing_disclosure": "Charges are unknown and require separate review.",
                "billing_class": "unknown",
                "training_policy": "no_training",
                "confidential_data_policy": "allowed",
                "endpoint_policy_reviewed": True,
                "expected_revision": 0,
                "expected_config_fingerprint": fingerprint,
            }
            first_review_path = (
                f"/api/v1/assistant/providers/opencode/models/"
                f"{quote(first_model_id, safe='')}/review"
            )
            csrf_first = {"x-csrf-token": str(first["csrf"])}
            csrf_second = {"x-csrf-token": str(second["csrf"])}
            wrong_owner = second_browser.put(
                first_review_path, headers=csrf_second, json=review_body
            )
            assert wrong_owner.status_code == 404
            assert not any(call[0] == "review" for call in providers.calls)

            missing_csrf = first_browser.put(first_review_path, json=review_body)
            assert missing_csrf.status_code == 403
            assert not any(call[0] == "review" for call in providers.calls)

            reviewed = first_browser.put(first_review_path, headers=csrf_first, json=review_body)
            assert reviewed.status_code == 200, reviewed.text
            assert reviewed.json()["model"]["reviewed"] is True
            assert reviewed.json()["model"]["enabled"] is False
            assert reviewed.json()["model"]["review_revision"] == 1
            assert reviewed.json()["model"]["usable"] is False
            assert "never expose" not in reviewed.text

            strict_unknown = first_browser.put(
                first_review_path,
                headers=csrf_first,
                json={**review_body, "surprise": "private"},
            )
            assert strict_unknown.status_code == 422

            cleared = first_browser.delete(
                f"{first_review_path}?expected_revision=1", headers=csrf_first
            )
            assert cleared.status_code == 200, cleared.text
            assert cleared.json() == {
                "model_id": first_model_id,
                "reviewed": False,
                "usable": False,
            }
            assert providers.rows[first["user_id"]]["confidential_data_policy"] == "unknown"
        finally:
            first_browser.close()
            second_browser.close()


def test_opencode_real_manager_http_inventory_is_owner_scoped_and_projects_review_cas(
    settings, tmp_path, monkeypatch
):
    """Exercise the real provider manager behind owner-authenticated Console routes."""
    from stock_probs.assistant import providers as provider_module
    from stock_probs.assistant.providers import AssistantProviderManager

    requested: list[tuple[str, str]] = []
    access_owner: dict[str, int] = {}
    identity_by_owner: dict[int, dict[str, str | int]] = {}
    application = None
    revoke_owner_on_next_config: int | None = None
    unsafe_endpoint_owner: int | None = None

    async def fake_request(url, *, headers, **_kwargs):
        nonlocal application, revoke_owner_on_next_config
        assert url == "https://opencode.ai/console/api/v2/config"
        authorization = headers.get("authorization")
        assert isinstance(authorization, str) and authorization.startswith("Bearer ")
        token = authorization.removeprefix("Bearer ")
        requested.append((url, token))
        endpoint = (
            "https://api.openai.com/v1"
            if unsafe_endpoint_owner != access_owner.get(token)
            else "https://127.0.0.1/private"
        )
        if revoke_owner_on_next_config == access_owner.get(token):
            assert application is not None
            identity = identity_by_owner[revoke_owner_on_next_config]
            application.state.repository.auth_revoke_session(
                str(identity["token_hash"]), NOW.isoformat()
            )
            revoke_owner_on_next_config = None
        return type(
            "Response",
            (),
            {
                "status_code": 200,
                "content": json.dumps(
                    {
                        "providers": {
                            "reviewed-openai": {
                                "canonical": "openai",
                                "settings": {"baseURL": "https://api.openai.com/v1"},
                                "models": {
                                    "synthetic-model": {
                                        "modelID": "vendor/synthetic-model",
                                        "name": "Synthetic Console model",
                                        "settings": {"baseURL": endpoint},
                                        "headers": {"authorization": "private-not-project"},
                                        "body": {"model": "private-not-project"},
                                    }
                                },
                            },
                            "unreviewed-provider": {
                                "package": "npm:untrusted/package",
                                "models": {"unsafe": {"modelID": "unsafe"}},
                            },
                        },
                        "websearch": {"providerID": "private-not-project"},
                    }
                ).encode("utf-8"),
            },
        )()

    monkeypatch.setattr(provider_module, "request_public_https", fake_request)

    class ConsoleCatalog(FakeCatalog):
        def get_model(self, model_id):
            del model_id
            return None

    catalog = ConsoleCatalog()
    config = replace(_auth_settings(settings), data_dir=tmp_path)
    providers = AssistantProviderManager(
        config,
        catalog=catalog,
        vault_dir=tmp_path / "assistant-vault",
    )
    application = create_app(
        config,
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=catalog,
        assistant_providers=providers,
    )
    with TestClient(application, client=("127.0.0.1", 51084)):
        first = _add_signed_in_user(application, 50084, role="admin")
        second = _add_signed_in_user(application, 50085, role="admin")
        _mark_recent_test_step_up(application, first)
        _mark_recent_test_step_up(application, second)
        for identity in (first, second):
            providers._write_oauth_credential(
                "opencode",
                "device",
                int(identity["user_id"]),
                {
                    "type": "oauth",
                    "methodID": "device",
                    "access": f"synthetic-access-{identity['user_id']}",
                    "refresh": f"synthetic-refresh-{identity['user_id']}",
                    "expires": int(_oauth_deadline(3600) * 1000),
                    "metadata": {
                        "server": "https://opencode.ai/console",
                        "accountID": f"synthetic-account-{identity['user_id']}",
                    },
                },
            )
            access_owner[f"synthetic-access-{identity['user_id']}"] = int(identity["user_id"])
            identity_by_owner[int(identity["user_id"])] = identity
        first_browser = _browser_client(application, first)
        second_browser = _browser_client(application, second)
        try:
            first_admin = first_browser.get("/api/v1/assistant/providers/opencode/models")
            second_admin = second_browser.get("/api/v1/assistant/providers/opencode/models")
            assert first_admin.status_code == second_admin.status_code == 200
            first_row = first_admin.json()["models"][0]
            second_row = second_admin.json()["models"][0]
            first_id = first_row["model_id"]
            assert first_id != second_row["model_id"]
            assert first_row["provider_id"] == "opencode-console"
            assert first_row["protocol"] == first_row["adapter_id"] == "openai-responses"
            assert first_row["package_id"] == "@opencode/ai/providers/openai"
            assert first_row["enabled"] is False
            assert first_row["review_revision"] == first_row["revision"] == 0
            assert first_row["usable"] is False and first_row["reviewed"] is False
            assert "private-not-project" not in first_admin.text
            assert "untrusted/package" not in first_admin.text
            assert "synthetic-access-" not in first_admin.text

            first_models = first_browser.get("/api/v1/assistant/models")
            second_models = second_browser.get("/api/v1/assistant/models")
            assert first_models.status_code == second_models.status_code == 200
            first_ids = {item["model_id"] for item in first_models.json()["items"]}
            second_ids = {item["model_id"] for item in second_models.json()["items"]}
            assert first_id in first_ids and first_id not in second_ids
            assert second_row["model_id"] in second_ids

            fingerprint = first_row["config_fingerprint"]
            review = first_browser.put(
                f"/api/v1/assistant/providers/opencode/models/{quote(first_id, safe='')}/review",
                headers={"x-csrf-token": str(first["csrf"])},
                json={
                    "terms_url": "https://example.org/terms",
                    "privacy_disclosure": "Administrator assertion, unverified: training reviewed.",
                    "billing_disclosure": "Administrator assertion, unverified: billing unknown.",
                    "billing_class": "unknown",
                    "training_policy": "no_training",
                    "confidential_data_policy": "allowed",
                    "endpoint_policy_reviewed": True,
                    "expected_revision": 0,
                    "expected_config_fingerprint": fingerprint,
                },
            )
            assert review.status_code == 200, review.text
            reviewed_row = review.json()["model"]
            assert reviewed_row["reviewed"] is True
            assert reviewed_row["enabled"] is False
            assert reviewed_row["review_revision"] == 1
            assert reviewed_row["revision"] == 0
            assert reviewed_row["usable"] is False
            assert "private-not-project" not in review.text

            stale = first_browser.put(
                f"/api/v1/assistant/providers/opencode/models/{quote(first_id, safe='')}/review",
                headers={"x-csrf-token": str(first["csrf"])},
                json={
                    "terms_url": "https://example.org/terms",
                    "privacy_disclosure": "Stale review must not replace current policy.",
                    "billing_disclosure": "Administrator assertion, unverified.",
                    "billing_class": "unknown",
                    "training_policy": "no_training",
                    "confidential_data_policy": "allowed",
                    "endpoint_policy_reviewed": True,
                    "expected_revision": 0,
                    "expected_config_fingerprint": fingerprint,
                },
            )
            assert stale.status_code == 409
            assert stale.json()["error"]["code"] == "model_policy_conflict"

            wrong_owner = second_browser.put(
                f"/api/v1/assistant/providers/opencode/models/{quote(first_id, safe='')}/review",
                headers={"x-csrf-token": str(second["csrf"])},
                json={
                    "terms_url": "https://example.org/terms",
                    "privacy_disclosure": "Administrator assertion, unverified.",
                    "billing_disclosure": "Administrator assertion, unverified.",
                    "billing_class": "unknown",
                    "training_policy": "no_training",
                    "confidential_data_policy": "allowed",
                    "endpoint_policy_reviewed": True,
                    "expected_revision": 1,
                    "expected_config_fingerprint": fingerprint,
                },
            )
            assert wrong_owner.status_code == 404

            cleared = first_browser.delete(
                f"/api/v1/assistant/providers/opencode/models/{quote(first_id, safe='')}/review"
                "?expected_revision=1",
                headers={"x-csrf-token": str(first["csrf"])},
            )
            assert cleared.status_code == 200, cleared.text
            assert cleared.json() == {
                "model_id": first_id,
                "reviewed": False,
                "usable": False,
            }
            tombstone_row = first_browser.get("/api/v1/assistant/providers/opencode/models").json()[
                "models"
            ][0]
            assert tombstone_row["review_revision"] == 2
            assert tombstone_row["revision"] == 0
            rereview = first_browser.put(
                f"/api/v1/assistant/providers/opencode/models/{quote(first_id, safe='')}/review",
                headers={"x-csrf-token": str(first["csrf"])},
                json={
                    "terms_url": "https://example.org/terms",
                    "privacy_disclosure": "Administrator assertion, unverified: reviewed again.",
                    "billing_disclosure": "Administrator assertion, unverified: billing unknown.",
                    "billing_class": "unknown",
                    "training_policy": "no_training",
                    "confidential_data_policy": "allowed",
                    "endpoint_policy_reviewed": True,
                    "expected_revision": 2,
                    "expected_config_fingerprint": fingerprint,
                },
            )
            assert rereview.status_code == 200, rereview.text
            assert rereview.json()["model"]["review_revision"] == 3
            review_state_before_revocation = providers._read_opencode_reviews(int(first["user_id"]))
            revoke_owner_on_next_config = int(first["user_id"])
            revoked_review = first_browser.put(
                f"/api/v1/assistant/providers/opencode/models/{quote(first_id, safe='')}/review",
                headers={"x-csrf-token": str(first["csrf"])},
                json={
                    "terms_url": "https://example.org/terms",
                    "privacy_disclosure": "Administrator assertion, unverified.",
                    "billing_disclosure": "Administrator assertion, unverified.",
                    "billing_class": "unknown",
                    "training_policy": "no_training",
                    "confidential_data_policy": "allowed",
                    "endpoint_policy_reviewed": True,
                    "expected_revision": 3,
                    "expected_config_fingerprint": fingerprint,
                },
            )
            assert revoked_review.status_code == 403
            assert revoked_review.json()["error"]["code"] == "assistant_authorization_required"
            assert (
                providers._read_opencode_reviews(int(first["user_id"]))
                == review_state_before_revocation
            )

            unsafe_endpoint_owner = int(second["user_id"])
            providers._opencode_loaded_at.pop(unsafe_endpoint_owner, None)
            unsafe_endpoint = second_browser.get("/api/v1/assistant/providers/opencode/models")
            assert unsafe_endpoint.status_code == 200, unsafe_endpoint.text
            assert unsafe_endpoint.json()["models"] == []
            assert unsafe_endpoint.json()["unsupported_model_count"] == 2
            assert "127.0.0.1" not in unsafe_endpoint.text
            assert all(url == "https://opencode.ai/console/api/v2/config" for url, _ in requested)
        finally:
            first_browser.close()
            second_browser.close()
    assert len(requested) >= 4
    assert {token for _, token in requested} == {
        f"synthetic-access-{first['user_id']}",
        f"synthetic-access-{second['user_id']}",
    }


def test_model_policy_route_rejects_non_admin_without_dispatch(settings):
    class ProviderManager:
        def __init__(self):
            self.calls = 0

        def update_model_policy(self, *_args, **_kwargs):
            self.calls += 1
            return {}

    providers = ProviderManager()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    with TestClient(application, client=("127.0.0.1", 51019)):
        member = _add_signed_in_user(application, 50025)
        browser = _browser_client(application, member)
        try:
            response = browser.put(
                f"/api/v1/assistant/models/{quote(MODEL.model_id, safe='')}/policy",
                headers={"x-csrf-token": str(member["csrf"])},
                json={"enabled": False, "expected_revision": 0},
            )
            assert response.status_code == 403
            assert providers.calls == 0
        finally:
            browser.close()


def test_model_discovery_route_refreshes_inventory_for_authenticated_user(settings):
    row = {
        "model_id": MODEL.model_id,
        "provider_id": MODEL.provider_id,
        "native_provider_id": MODEL.provider_id,
        "display_name": MODEL.display_name,
        "available": True,
        "free": True,
        "training": False,
        "terms_url": MODEL.terms_url,
        "terms_reviewed_at": MODEL.terms_reviewed_at,
        "policy_version": MODEL.policy_version,
        "disclosure": MODEL.disclosure,
        "privacy_policy_version": MODEL.policy_version,
        "privacy_disclosure": MODEL.disclosure,
        "billing_class": "free",
        "billing_policy_version": MODEL.policy_version,
        "cost_disclosure": "Free fixture model.",
        "enabled": True,
        "usable": True,
        "revision": 1,
    }

    class Catalog:
        def __init__(self):
            self.rows = []
            self.refresh_calls = []

        def list_models(self):
            return list(self.rows)

        async def ensure_model_inventory(self, *, minimum_validity_seconds):
            self.refresh_calls.append(minimum_validity_seconds)
            self.rows = [row]
            return tuple(self.rows)

    catalog = Catalog()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=catalog,
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51022)):
        member = _add_signed_in_user(application, 50028)
        browser = _browser_client(application, member)
        try:
            response = browser.get("/api/v1/assistant/models")
            assert response.status_code == 200, response.text
            assert response.json()["items"][0]["model_id"] == MODEL.model_id
            # Ordinary listing only needs a current inventory. The 120-second horizon is
            # reserved for turn creation, which must keep discovery valid through the turn.

            context_response = browser.get(
                "/api/v1/assistant/context", params={"route": "/overview"}
            )
            assert context_response.status_code == 200, context_response.text
            context = context_response.json()["context"]
            created = browser.post(
                "/api/v1/assistant/conversations",
                headers={"x-csrf-token": str(member["csrf"])},
                json={"context": context},
            )
            assert created.status_code == 201, created.text
            conversation_id = str(created.json()["conversation"]["conversation"]["id"])
            application.state.assistant.storage.create_consent(
                int(member["user_id"]),
                model_id=MODEL.model_id,
                policy_version=MODEL.policy_version,
                accepted_terms=True,
                data_collection_opt_in=False,
                recorded_at=NOW,
            )
            turn = browser.post(
                f"/api/v1/assistant/conversations/{conversation_id}/turns",
                headers={"x-csrf-token": str(member["csrf"])},
                json={
                    "prompt": "Summarize my workspace safely.",
                    "model_id": MODEL.model_id,
                    "policy_version": MODEL.policy_version,
                    "context": context,
                    "context_preview_accepted": True,
                },
            )
            assert turn.status_code == 202, turn.text
            assert catalog.refresh_calls == [0.0, 120.0]
        finally:
            browser.close()


@pytest.mark.parametrize("await_boundary", ["runtime_readiness", "model_inventory"])
@pytest.mark.parametrize("auth_change", ("session_revoked", "csrf_rotated"))
def test_create_turn_rechecks_live_session_and_csrf_after_readiness_or_inventory_await(
    settings, monkeypatch, await_boundary, auth_change
):
    providers = FakeProviders()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    await_started = threading.Event()
    release_await = threading.Event()
    release_run = threading.Event()
    run_started = threading.Event()
    with TestClient(application, client=("127.0.0.1", 51050)):
        owner = _add_signed_in_user(application, 50087)
        browser = _browser_client(application, owner)
        assistant = application.state.assistant
        try:
            context_response = browser.get(
                "/api/v1/assistant/context", params={"route": "/overview"}
            )
            assert context_response.status_code == 200, context_response.text
            context = context_response.json()["context"]
            created = browser.post(
                "/api/v1/assistant/conversations",
                headers={"x-csrf-token": str(owner["csrf"])},
                json={"context": context},
            )
            assert created.status_code == 201, created.text
            conversation_id = str(created.json()["conversation"]["conversation"]["id"])
            assistant.storage.create_consent(
                int(owner["user_id"]),
                model_id=MODEL.model_id,
                policy_version=MODEL.policy_version,
                accepted_terms=True,
                data_collection_opt_in=False,
                recorded_at=NOW,
            )

            async def held_await():
                await_started.set()
                if not await asyncio.to_thread(release_await.wait, timeout=5):
                    raise RuntimeError("test create-turn wait expired")

            if await_boundary == "runtime_readiness":
                monkeypatch.setattr(assistant, "_ensure_runtime_ready", held_await)
            else:

                async def held_inventory(
                    *, minimum_validity_seconds, owner_id, authorization_check
                ):
                    assert minimum_validity_seconds == 120.0
                    assert owner_id == owner["user_id"]
                    assert authorization_check()
                    await_started.set()
                    if not await asyncio.to_thread(release_await.wait, timeout=5):
                        raise RuntimeError("test inventory wait expired")
                    return tuple(assistant.catalog.list_models())

                monkeypatch.setattr(assistant, "ensure_model_inventory", held_inventory)

            async def record_scheduled_turn(**_kwargs):
                run_started.set()
                if not await asyncio.to_thread(release_run.wait, timeout=5):
                    raise RuntimeError("test scheduled-turn wait expired")

            monkeypatch.setattr(assistant, "_run_turn", record_scheduled_turn)
            turn_path = f"/api/v1/assistant/conversations/{conversation_id}/turns"
            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(
                    browser.post,
                    turn_path,
                    headers={"x-csrf-token": str(owner["csrf"])},
                    json={
                        "prompt": "Summarize my workspace safely.",
                        "model_id": MODEL.model_id,
                        "policy_version": MODEL.policy_version,
                        "context": context,
                        "context_preview_accepted": True,
                    },
                    timeout=5,
                )
                assert await_started.wait(timeout=5), "request did not reach the held await"
                if auth_change == "session_revoked":
                    application.state.repository.auth_revoke_session(
                        str(owner["token_hash"]), NOW.isoformat()
                    )
                else:
                    with application.state.repository.connect() as connection:
                        connection.execute(
                            "UPDATE sessions SET csrf_token_hash = ? WHERE token_hash = ?",
                            (_sha("rotated-test-only-csrf-token"), str(owner["token_hash"])),
                        )
                        connection.commit()
                release_await.set()
                rejected = pending.result(timeout=8)

            assert rejected.status_code == 403, rejected.text
            assert rejected.json()["error"]["code"] == "assistant_authorization_required"
            detail = assistant.storage.get_conversation(
                int(owner["user_id"]),
                conversation_id,
                session_id=str(owner["session_id"]),
                now=NOW,
            )
            assert detail["messages"]["total"] == 0
            assert detail["turns"] == []
            assert assistant._tasks == {}
            assert run_started.is_set() is False
            assert providers.calls == []
        finally:
            release_await.set()
            release_run.set()
            browser.close()


def test_model_discovery_hides_stale_rows_when_refresh_fails(settings):
    class Catalog:
        def list_models(self):
            return [
                {
                    "model_id": MODEL.model_id,
                    "provider_id": MODEL.provider_id,
                    "display_name": MODEL.display_name,
                    "available": True,
                    "free": True,
                    "training": False,
                    "terms_url": MODEL.terms_url,
                    "terms_reviewed_at": MODEL.terms_reviewed_at,
                    "policy_version": MODEL.policy_version,
                    "disclosure": MODEL.disclosure,
                    "enabled": True,
                    "usable": True,
                }
            ]

        async def ensure_model_inventory(self, *, minimum_validity_seconds):
            assert minimum_validity_seconds == 0.0
            return ()

    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=Catalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51023)):
        owner = _add_signed_in_user(application, 50029)
        browser = _browser_client(application, owner)
        try:
            response = browser.get("/api/v1/assistant/models")
            assert response.status_code == 200, response.text
            assert response.json() == {"items": []}
        finally:
            browser.close()


def test_provider_endpoint_schema_rejects_local_http_and_unsafe_https_before_update(settings):
    class ProviderManager:
        def __init__(self):
            self.calls = []

        def configure_custom_endpoint(self, **values):
            self.calls.append(values)
            return {
                "provider_id": "custom",
                "display_name": "Custom endpoint",
                "selected_model_id": values.get("model_id"),
                "selected_base_url": values["base_url"],
                "selected_terms_url": values["terms_url"],
                "selected_privacy_disclosure": values["privacy_disclosure"],
                "selected_billing_disclosure": values["billing_disclosure"],
                "selected_billing_class": values["billing_class"],
                "selected_endpoint_policy_reviewed": values["endpoint_policy_reviewed"],
                "connection_status": "unconfigured",
                "credential": "must-not-escape",
            }

    providers = ProviderManager()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    with TestClient(application, client=("127.0.0.1", 51020)):
        admin = _add_signed_in_user(application, 50026, role="admin")
        _mark_recent_test_step_up(application, admin)
        browser = _browser_client(application, admin)
        headers = {"x-csrf-token": str(admin["csrf"])}
        try:
            invalid_urls = (
                "http://127.0.0.1:80/v1",
                "http://127.0.0.1:11434/v1",
                "http://localhost:11434/v1",
                "https://127.0.0.1:443/v1",
                "https://[::1]/v1",
                "https://provider.example:8443/v1",
                "https://user:pass@provider.example/v1",
                "https://provider.example/v1?key=secret",
                "https://provider.example/v1#secret",
                "https://provider.example\\@127.0.0.1/v1",
                "https://provider.example/../private",
                " https://provider.example/v1",
            )
            for base_url in invalid_urls:
                response = browser.put(
                    "/api/v1/assistant/providers/custom",
                    headers=headers,
                    json={
                        "base_url": base_url,
                        "terms_url": "https://provider.example/terms",
                        "privacy_disclosure": "The endpoint may process submitted research data.",
                        "billing_disclosure": "Billing is unknown; review the linked terms.",
                        "billing_class": "unknown",
                        "endpoint_policy_reviewed": True,
                    },
                )
                assert response.status_code == 422, (base_url, response.text)
            assert providers.calls == []

            valid_fields = {
                "base_url": "https://provider.example/v1",
                "terms_url": "https://provider.example/terms",
                "privacy_disclosure": "Admin-provided, unverified: data use is unknown.",
                "billing_disclosure": "Admin-provided, unverified: billing is unknown.",
                "billing_class": "unknown",
                "endpoint_policy_reviewed": True,
            }
            invalid_policies = (
                {key: value for key, value in valid_fields.items() if key != "terms_url"},
                {**valid_fields, "endpoint_policy_reviewed": False},
                {**valid_fields, "terms_url": "http://provider.example/terms"},
                {**valid_fields, "terms_url": "https://provider.example/terms?token=x"},
                {**valid_fields, "privacy_disclosure": "\x01secret"},
                {**valid_fields, "billing_class": "paid-ish"},
                {**valid_fields, "unknown_field": "must be rejected"},
            )
            for invalid in invalid_policies:
                response = browser.put(
                    "/api/v1/assistant/providers/custom", headers=headers, json=invalid
                )
                assert response.status_code == 422, response.text
            assert providers.calls == []

            accepted = browser.put(
                "/api/v1/assistant/providers/custom",
                headers=headers,
                json={
                    **valid_fields,
                    "credential": "synthetic-private-credential",
                    "model_id": "custom/model-1",
                },
            )
            assert accepted.status_code == 200, accepted.text
            assert accepted.json()["provider"]["selected_billing_class"] == "unknown"
            assert accepted.json()["provider"]["selected_endpoint_policy_reviewed"] is True
            assert accepted.json()["provider"]["selected_privacy_disclosure"].startswith(
                "Admin-provided, unverified:"
            )
            assert '"credential":' not in accepted.text
            assert "synthetic-private-credential" not in accepted.text
            assert providers.calls == [
                {
                    **valid_fields,
                    "credential": "synthetic-private-credential",
                    "model_id": "custom/model-1",
                }
            ]

            partial_generic = browser.put(
                "/api/v1/assistant/providers/custom",
                headers=headers,
                json={"base_url": "https://provider.example/v1"},
            )
            assert partial_generic.status_code == 422
            assert len(providers.calls) == 1

            credential_clear = browser.delete("/api/v1/assistant/providers/custom", headers=headers)
            assert credential_clear.status_code == 422
            assert len(providers.calls) == 1
        finally:
            browser.close()


def test_native_oauth_routes_are_admin_step_up_session_bound_and_secret_free(settings):
    class OAuthFailure(Exception):
        def __init__(self, code: str):
            super().__init__("private native detail must not escape")
            self.code = code

    class OAuthProviders(FakeProviders):
        def __init__(self):
            super().__init__()
            self.identity = None
            self.app = None
            self.attempts = {}
            self.calls = []
            self.revoke_on_complete = False
            self.vault_writes = 0
            self.discarded_handoffs = 0

        async def list_native_oauth_methods(self):
            return (
                {
                    "integration_id": "openai",
                    "method_id": "chatgpt-headless",
                    "label": "OpenAI account",
                    "mode": "device",
                    "connection_status": "unconfigured",
                    "connection_supported": True,
                    "model_access_supported": True,
                    "availability_reason": None,
                    "native_attempt_id": "must-not-escape",
                    "credential": "must-not-escape",
                },
            )

        def _attempt(self, attempt_id, status="pending"):
            return {
                "attempt_id": attempt_id,
                "integration_id": "openai",
                "method_id": "chatgpt-headless",
                "status": status,
                "mode": "device",
                "expires_at": _oauth_deadline(),
                "authorization_url": "https://auth.openai.com/codex/device",
                "instructions": "Finish authorization in the provider window.",
                "native_attempt_id": "must-not-escape",
                "credential": {"access": "synthetic-access-token"},
            }

        async def begin_native_oauth(
            self,
            integration_id,
            method_id,
            *,
            owner_id,
            session_id,
            session_token_hash,
        ):
            self.calls.append(("begin", integration_id, method_id, owner_id, session_id))
            self.session_token_hash = session_token_hash
            attempt_id = "a" * 32
            self.attempts[attempt_id] = (owner_id, session_id)
            return self._attempt(attempt_id)

        async def native_oauth_status(self, attempt_id, *, owner_id, session_id):
            self.calls.append(("status", attempt_id, owner_id, session_id))
            if self.attempts.get(attempt_id) != (owner_id, session_id):
                raise OAuthFailure("oauth_attempt_not_found")
            return self._attempt(attempt_id)

        async def complete_native_oauth(
            self, attempt_id, *, owner_id, session_id, code=None, authorization_check
        ):
            self.calls.append(("complete", attempt_id, owner_id, session_id, code))
            if self.attempts.get(attempt_id) != (owner_id, session_id):
                raise OAuthFailure("oauth_attempt_not_found")
            if self.revoke_on_complete:
                self.app.state.repository.auth_revoke_session(
                    str(self.identity["token_hash"]), NOW.isoformat()
                )
            if not await authorization_check():
                self.discarded_handoffs += 1
                raise OAuthFailure("oauth_authorization_rejected")
            self.vault_writes += 1
            return self._attempt(attempt_id, "connected")

        async def submit_native_oauth_callback(
            self, attempt_id, *, owner_id, session_id, callback_url
        ):
            self.calls.append(("callback", attempt_id, owner_id, session_id, callback_url))
            if self.attempts.get(attempt_id) != (owner_id, session_id):
                raise OAuthFailure("oauth_attempt_not_found")
            return self._attempt(attempt_id, "handoff_ready")

        async def cancel_native_oauth(self, attempt_id, *, owner_id, session_id):
            self.calls.append(("cancel", attempt_id, owner_id, session_id))
            if self.attempts.get(attempt_id) != (owner_id, session_id):
                raise OAuthFailure("oauth_attempt_not_found")
            self.attempts.pop(attempt_id, None)
            return self._attempt(attempt_id, "cancelled")

    providers = OAuthProviders()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    providers.app = application
    with TestClient(application, client=("127.0.0.1", 51031)):
        admin = _add_signed_in_user(application, 50041, role="admin")
        providers.identity = admin
        _mark_recent_test_step_up(application, admin)
        browser = _browser_client(application, admin)
        headers = {"x-csrf-token": str(admin["csrf"])}
        try:
            methods = browser.get("/api/v1/assistant/providers/oauth/methods")
            assert methods.status_code == 200, methods.text
            assert methods.json()["methods"] == [
                {
                    "integration_id": "openai",
                    "method_id": "chatgpt-headless",
                    "label": "OpenAI account",
                    "mode": "device",
                    "connection_status": "unconfigured",
                    "connection_supported": True,
                    "model_access_supported": True,
                    "availability_reason": None,
                }
            ]
            assert "must-not-escape" not in methods.text

            missing_csrf = browser.post(
                "/api/v1/assistant/providers/oauth/attempts",
                json={"provider_id": "openai", "method_id": "chatgpt-headless"},
            )
            assert missing_csrf.status_code == 403
            assert providers.calls == []

            started = browser.post(
                "/api/v1/assistant/providers/oauth/attempts",
                headers=headers,
                json={"provider_id": "openai", "method_id": "chatgpt-headless"},
            )
            assert started.status_code == 200, started.text
            attempt = started.json()["attempt"]
            assert attempt["attempt_id"] == "a" * 32
            assert attempt["status"] == "pending"
            assert attempt["authorization_url"].startswith("https://auth.openai.com/")
            assert "synthetic-access-token" not in started.text
            assert "native_attempt_id" not in started.text

            parallel = _add_parallel_session(application, admin)
            parallel_browser = _browser_client(application, parallel)
            try:
                transferred = parallel_browser.get(
                    f"/api/v1/assistant/providers/oauth/attempts/{attempt['attempt_id']}"
                )
                assert transferred.status_code == 404
            finally:
                parallel_browser.close()

            status = browser.get(
                f"/api/v1/assistant/providers/oauth/attempts/{attempt['attempt_id']}"
            )
            assert status.status_code == 200, status.text
            assert status.json()["attempt"]["status"] == "pending"

            callback = browser.post(
                f"/api/v1/assistant/providers/oauth/attempts/{attempt['attempt_id']}/callback",
                headers=headers,
                json={
                    "callback_url": "http://localhost:1455/auth/callback?code=synthetic-code&state=opaque-state"
                },
            )
            assert callback.status_code == 200, callback.text
            assert callback.json()["attempt"]["status"] == "handoff_ready"
            assert "synthetic-code" not in callback.text
            assert "opaque-state" not in callback.text

            factor = application.state.repository.auth_get_totp_factor(int(admin["user_id"]))
            assert factor is not None
            stale_proof = (NOW - timedelta(minutes=10)).isoformat()
            assert application.state.repository.auth_set_session_mfa(
                str(admin["token_hash"]), "totp", stale_proof, int(factor["id"])
            )
            stale_step_up = browser.post(
                f"/api/v1/assistant/providers/oauth/attempts/{attempt['attempt_id']}/complete",
                headers=headers,
                json={},
            )
            assert stale_step_up.status_code == 403
            assert providers.calls[-1][0] == "callback"
            _mark_recent_test_step_up(application, admin)

            completed = browser.post(
                f"/api/v1/assistant/providers/oauth/attempts/{attempt['attempt_id']}/complete",
                headers=headers,
                json={},
            )
            assert completed.status_code == 200, completed.text
            assert completed.json()["attempt"]["status"] == "connected"
            assert providers.vault_writes == 1
            assert "synthetic-access-token" not in completed.text
            assert providers.calls[0] == (
                "begin",
                "openai",
                "chatgpt-headless",
                admin["user_id"],
                admin["session_id"],
            )
            assert providers.session_token_hash == admin["token_hash"]
            assert providers.calls[2:5] == [
                ("status", "a" * 32, admin["user_id"], admin["session_id"]),
                (
                    "callback",
                    "a" * 32,
                    admin["user_id"],
                    admin["session_id"],
                    "http://localhost:1455/auth/callback?code=synthetic-code&state=opaque-state",
                ),
                ("complete", "a" * 32, admin["user_id"], admin["session_id"], None),
            ]
        finally:
            browser.close()


@pytest.mark.parametrize("auth_change", ["session_revoked", "role_demoted"])
def test_native_oauth_live_auth_check_discards_handoff_after_authorization_change(
    settings, auth_change
):
    class OAuthFailure(Exception):
        code = "oauth_authorization_rejected"

    class OAuthProviders(FakeProviders):
        async def begin_native_oauth(
            self,
            integration_id,
            method_id,
            *,
            owner_id,
            session_id,
            session_token_hash,
        ):
            self.owner_id = owner_id
            self.session_id = session_id
            self.attempt_id = "b" * 32
            return {
                "attempt_id": self.attempt_id,
                "integration_id": integration_id,
                "method_id": method_id,
                "status": "pending",
                "mode": "device",
                "expires_at": _oauth_deadline(),
                "authorization_url": None,
                "instructions": "Authorize this app.",
            }

        async def complete_native_oauth(
            self, attempt_id, *, owner_id, session_id, code=None, authorization_check
        ):
            assert (attempt_id, owner_id, session_id) == (
                self.attempt_id,
                self.owner_id,
                self.session_id,
            )
            if auth_change == "session_revoked":
                self.app.state.repository.auth_revoke_session(
                    str(self.identity["token_hash"]), NOW.isoformat()
                )
            else:
                self.app.state.repository.auth_update_user(
                    int(self.identity["user_id"]), {"role": "member"}
                )
            if not await authorization_check():
                self.discarded = True
                raise OAuthFailure()
            self.vault_writes = getattr(self, "vault_writes", 0) + 1
            return {}

        async def cancel_native_oauth(self, attempt_id, *, owner_id, session_id):
            assert attempt_id == self.attempt_id
            self.cancelled = True
            return {
                "attempt_id": attempt_id,
                "integration_id": "openai",
                "method_id": "chatgpt-headless",
                "status": "cancelled",
                "mode": "device",
                "expires_at": _oauth_deadline(),
                "authorization_url": None,
                "instructions": None,
            }

    providers = OAuthProviders()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    providers.app = application
    with TestClient(application, client=("127.0.0.1", 51032)):
        admin = _add_signed_in_user(application, 50042, role="admin")
        providers.identity = admin
        _mark_recent_test_step_up(application, admin)
        browser = _browser_client(application, admin)
        headers = {"x-csrf-token": str(admin["csrf"])}
        try:
            started = browser.post(
                "/api/v1/assistant/providers/oauth/attempts",
                headers=headers,
                json={"provider_id": "openai", "method_id": "chatgpt-headless"},
            )
            assert started.status_code == 200, started.text
            completed = browser.post(
                f"/api/v1/assistant/providers/oauth/attempts/{providers.attempt_id}/complete",
                headers=headers,
                json={},
            )
            assert completed.status_code == 403, completed.text
            assert completed.json()["error"]["code"] == "oauth_authorization_required"
            assert providers.discarded is True
            assert getattr(providers, "vault_writes", 0) == 0
            assert providers.cancelled is True
            assert "synthetic" not in completed.text
        finally:
            browser.close()


def test_native_oauth_begin_rejects_manager_method_mismatch(settings):
    class OAuthProviders(FakeProviders):
        async def begin_native_oauth(
            self,
            integration_id,
            method_id,
            *,
            owner_id,
            session_id,
            session_token_hash,
        ):
            self.attempt_id = "e" * 32
            self.owner_id = owner_id
            self.session_id = session_id
            return {
                "attempt_id": self.attempt_id,
                "integration_id": integration_id,
                "method_id": "chatgpt-browser",
                "status": "pending",
                "mode": "browser",
                "expires_at": _oauth_deadline(),
                "authorization_url": "https://auth.openai.com/codex/device",
                "instructions": None,
            }

        async def cancel_native_oauth(self, attempt_id, *, owner_id, session_id):
            self.cancelled = (attempt_id, owner_id, session_id)
            return {
                "attempt_id": attempt_id,
                "integration_id": "openai",
                "method_id": "chatgpt-browser",
                "status": "cancelled",
                "mode": "browser",
                "expires_at": _oauth_deadline(),
                "authorization_url": None,
                "instructions": None,
            }

    providers = OAuthProviders()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    with TestClient(application, client=("127.0.0.1", 51034)):
        admin = _add_signed_in_user(application, 50044, role="admin")
        _mark_recent_test_step_up(application, admin)
        browser = _browser_client(application, admin)
        try:
            response = browser.post(
                "/api/v1/assistant/providers/oauth/attempts",
                headers={"x-csrf-token": str(admin["csrf"])},
                json={"provider_id": "openai", "method_id": "chatgpt-headless"},
            )
            assert response.status_code == 503, response.text
            assert response.json()["error"]["code"] == "oauth_unavailable"
            assert providers.cancelled == (
                "e" * 32,
                admin["user_id"],
                admin["session_id"],
            )
            assert "chatgpt-browser" not in response.text
        finally:
            browser.close()


def test_native_oauth_callback_schema_rejects_non_native_redirects(settings):
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51033)):
        admin = _add_signed_in_user(application, 50043, role="admin")
        _mark_recent_test_step_up(application, admin)
        browser = _browser_client(application, admin)
        try:
            headers = {"x-csrf-token": str(admin["csrf"])}
            invalid_callbacks = (
                "https://localhost:1455/auth/callback?code=x&state=y",
                "http://127.0.0.1:1455/auth/callback?code=x&state=y",
                "http://localhost:1456/auth/callback?code=x&state=y",
                "http://localhost:1455/other?code=x&state=y",
                "http://localhost:1455/auth/callback?code=x&state=y&code=z",
                "http://localhost:1455/auth/callback?code=x%0a&state=y",
                "http://localhost:1455/auth/callback?error=denied&code=x&state=y",
                "http://localhost:1455/auth/callback?code=x&state=y&next=https%3A%2F%2Fevil.test",
            )
            for callback_url in invalid_callbacks:
                response = browser.post(
                    "/api/v1/assistant/providers/oauth/attempts/" + "c" * 32 + "/callback",
                    headers=headers,
                    json={"callback_url": callback_url},
                )
                assert response.status_code == 422, response.text
                assert "evil.test" not in response.text
        finally:
            browser.close()


def test_native_oauth_projection_binds_authorization_url_to_fixed_provider_hosts():
    attempt = {
        "attempt_id": "d" * 32,
        "integration_id": "openai",
        "method_id": "chatgpt-headless",
        "status": "pending",
        "mode": "device",
        "expires_at": _oauth_deadline(),
        "authorization_url": "https://auth.openai.com/codex/device",
        "instructions": "Authorize the connection.",
    }
    projected = _oauth_attempt_response(attempt)
    assert projected is not None
    assert projected["authorization_url"] == attempt["authorization_url"]
    for unsafe_url in (
        "https://attacker.example/oauth",
        "https://auth.openai.com.evil.test/oauth",
        "https://user@auth.openai.com/oauth",
        "https://auth.openai.com:8443/oauth",
        "https://auth.openai.com/codex/device#access_token=synthetic",
        "https://auth.openai.com/codex/device?state=x",
    ):
        assert _oauth_attempt_response({**attempt, "authorization_url": unsafe_url}) is None


def test_native_oauth_projection_rejects_expired_attempt():
    attempt = {
        "attempt_id": "d" * 32,
        "integration_id": "openai",
        "method_id": "chatgpt-headless",
        "status": "pending",
        "mode": "device",
        "expires_at": _oauth_deadline(-601),
        "authorization_url": "https://auth.openai.com/codex/device",
        "instructions": "Authorize the connection.",
    }

    assert _oauth_attempt_response(attempt) is None


def test_native_oauth_projection_allows_only_reviewed_browser_and_device_routes():
    from urllib.parse import urlencode

    base = {
        "attempt_id": "e" * 32,
        "integration_id": "openai",
        "method_id": "chatgpt-browser",
        "status": "pending",
        "mode": "browser",
        "expires_at": _oauth_deadline(),
        "instructions": "Complete authorization in your browser.",
    }
    query = urlencode(
        {
            "response_type": "code",
            "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
            "redirect_uri": "http://localhost:1455/auth/callback",
            "scope": "openid profile email offline_access",
            "code_challenge": "c" * 43,
            "code_challenge_method": "S256",
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "state": "s" * 43,
            "originator": "opencode",
        }
    )
    valid_browser_url = f"https://auth.openai.com/oauth/authorize?{query}"
    assert _oauth_attempt_response({**base, "authorization_url": valid_browser_url}) is not None
    for invalid_url in (
        valid_browser_url + "&redirect_uri=http%3A%2F%2Flocalhost%3A1457%2Fauth%2Fcallback",
        valid_browser_url.replace("/oauth/authorize", "/oauth/other"),
        valid_browser_url.replace("client_id=app_EMoamEEZ73f0CkXaXp7hrann", "client_id=attacker"),
        f"https://auth.openai.com/oauth/authorize?{query}&next=https%3A%2F%2Fevil.test",
    ):
        assert _oauth_attempt_response({**base, "authorization_url": invalid_url}) is None

    opencode_attempt = {
        **base,
        "integration_id": "opencode",
        "method_id": "device",
        "mode": "device",
        "instructions": "Enter code: ABCD-EFGH",
        "authorization_url": "https://opencode.ai/console/device?user_code=ABCD-EFGH&client_id=opencode-cli",
    }
    assert _oauth_attempt_response(opencode_attempt) is not None
    assert (
        _oauth_attempt_response(
            {
                **opencode_attempt,
                "authorization_url": "https://opencode.ai/other?user_code=ABCD-EFGH&client_id=opencode-cli",
            }
        )
        is None
    )


def test_native_oauth_egress_requires_live_attempt_admin_and_closed_request(settings, monkeypatch):
    from stock_probs.assistant import api as assistant_api
    from stock_probs.assistant.net import PublicHTTPResponse

    native_capability = None
    fetched: list[tuple[str, str, dict[str, str], bytes]] = []

    async def fake_request(url, *, method, headers, body=b"", authorization_check, **_options):
        assert await authorization_check() is True
        fetched.append((url, method, dict(headers), body))
        return PublicHTTPResponse(
            200,
            {"content-type": "application/json"},
            b'{"device_auth_id":"device-id","user_code":"WXYZ-1234","interval":"5"}',
        )

    transport_type = assistant_api.OAuthTransport
    monkeypatch.setattr(
        assistant_api,
        "OAuthTransport",
        lambda: transport_type(request=fake_request),
    )

    class OAuthProviders(FakeProviders):
        def attach_oauth_transport(self, register, revoke):
            self.register_transport = register
            self.revoke_transport = revoke

        async def begin_native_oauth(
            self,
            integration_id,
            method_id,
            *,
            owner_id,
            session_id,
            session_token_hash,
        ):
            nonlocal native_capability
            self.registered_session_hash = session_token_hash
            self.attempt_id = "f" * 32
            native_capability = await self.register_transport(
                self.attempt_id,
                integration_id,
                method_id,
                owner_id,
                session_id,
                _oauth_deadline(),
                session_token_hash=session_token_hash,
            )
            return {
                "attempt_id": self.attempt_id,
                "integration_id": integration_id,
                "method_id": method_id,
                "status": "pending",
                "mode": "device",
                "expires_at": _oauth_deadline(),
                "authorization_url": "https://auth.openai.com/codex/device",
                "instructions": "Enter code: WXYZ-1234",
            }

    providers = OAuthProviders()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    with TestClient(application, client=("127.0.0.1", 51035)) as internal_client:
        admin = _add_signed_in_user(application, 50045, role="admin")
        _mark_recent_test_step_up(application, admin)
        browser = _browser_client(application, admin)
        try:
            started = browser.post(
                "/api/v1/assistant/providers/oauth/attempts",
                headers={"x-csrf-token": str(admin["csrf"])},
                json={"provider_id": "openai", "method_id": "chatgpt-headless"},
            )
            assert started.status_code == 200, started.text
            assert native_capability is not None
            assert providers.registered_session_hash == admin["token_hash"]
            assert admin["token_hash"] not in native_capability

            denied = internal_client.post(
                "/api/v1/assistant/internal/oauth",
                headers={"authorization": "Bearer " + "0" * 32},
                json={
                    "attempt_id": "f" * 32,
                    "operation": "openai.device_start",
                    "input": {},
                },
            )
            assert denied.status_code == 404
            assert fetched == []

            malformed = internal_client.post(
                "/api/v1/assistant/internal/oauth",
                headers={"authorization": "Bearer " + native_capability},
                json={
                    "attempt_id": "f" * 32,
                    "operation": "openai.device_start",
                    "input": {"url": "https://attacker.example"},
                },
            )
            assert malformed.status_code == 422
            assert fetched == []

            response = internal_client.post(
                "/api/v1/assistant/internal/oauth",
                headers={"authorization": "Bearer " + native_capability},
                json={"attempt_id": "f" * 32, "operation": "openai.device_start", "input": {}},
            )
            assert response.status_code == 200, response.text
            assert response.json() == {
                "result": {
                    "device_auth_id": "device-id",
                    "user_code": "WXYZ-1234",
                    "interval": "5",
                }
            }
            assert fetched[0][0] == "https://auth.openai.com/api/accounts/deviceauth/usercode"
            assert json.loads(fetched[0][3]) == {"client_id": "app_EMoamEEZ73f0CkXaXp7hrann"}
            assert "token_hash" not in response.text and admin["token_hash"] not in response.text

            application.state.repository.auth_revoke_session(
                str(admin["token_hash"]), NOW.isoformat()
            )
            after_revoke = internal_client.post(
                "/api/v1/assistant/internal/oauth",
                headers={"authorization": "Bearer " + native_capability},
                json={"attempt_id": "f" * 32, "operation": "openai.device_start", "input": {}},
            )
            assert after_revoke.status_code == 404
            assert len(fetched) == 1
        finally:
            browser.close()


def test_native_oauth_real_manager_route_binds_and_rechecks_live_session(
    settings, tmp_path, monkeypatch
):
    """Exercise the shipped manager and app transport together, including mid-call revocation."""
    import time

    from stock_probs.assistant import api as assistant_api
    from stock_probs.assistant.net import PublicHTTPError, PublicHTTPResponse
    from stock_probs.assistant.providers import AssistantProviderManager

    application = None
    request_mode = "success"
    fetched: list[str] = []
    writes: list[str] = []

    async def fake_request(url, *, method, headers, body=b"", authorization_check, **_options):
        nonlocal request_mode
        fetched.append(url)
        if request_mode == "dns_revoke":
            assert await authorization_check() is True
            assert application is not None
            application.state.repository.auth_revoke_session(
                str(admin_identity["token_hash"]), NOW.isoformat()
            )
            assert await authorization_check() is False
            raise PublicHTTPError("provider_authorization_required")
        if request_mode == "totp_tls_expiry":
            assert await authorization_check() is True
            assert await authorization_check() is True
            assert application is not None
            application.state.assistant.clock = lambda: NOW + timedelta(minutes=6)
            assert await authorization_check() is False
            raise PublicHTTPError("provider_authorization_required")
        if request_mode == "response_body_expiry":
            assert await authorization_check() is True
            assert await authorization_check() is True
            assert await authorization_check() is True
            assert application is not None
            writes.append(url)
            application.state.assistant.clock = lambda: NOW + timedelta(minutes=6)
            assert await authorization_check() is False
            raise PublicHTTPError("provider_authorization_required")
        assert await authorization_check() is True
        writes.append(url)
        if request_mode == "provider_failure":
            return PublicHTTPResponse(503, {"content-type": "application/json"}, b"{}")
        return PublicHTTPResponse(
            200,
            {"content-type": "application/json"},
            b'{"device_auth_id":"device-id","user_code":"WXYZ-1234","interval":"5"}',
        )

    transport_type = assistant_api.OAuthTransport
    monkeypatch.setattr(
        assistant_api,
        "OAuthTransport",
        lambda: transport_type(request=fake_request),
    )

    class OAuthRuntime(FakeRuntime):
        def __init__(self):
            self.capability = None

        async def list_native_integrations(self):
            return [
                {
                    "integration_id": "openai",
                    "methods": [{"method_id": "chatgpt-headless", "kind": "oauth"}],
                }
            ]

        async def begin_native_oauth(
            self,
            integration_id,
            method_id,
            *,
            attempt_id,
            owner_id,
            session_id,
            capability,
        ):
            assert (integration_id, method_id) == ("openai", "chatgpt-headless")
            assert len(attempt_id) == 32 and owner_id == int(admin_identity["user_id"])
            assert session_id == admin_identity["session_id"]
            self.capability = capability
            return {
                "attempt_id": attempt_id,
                "url": "https://auth.openai.com/codex/device",
                "instructions": "Enter code: WXYZ-1234",
                "mode": "auto",
                "expires_at": time.time() + 300,
            }

        async def native_oauth_status(self, integration_id, attempt_id, *, owner_id, session_id):
            assert integration_id == "openai" and len(attempt_id) == 32
            assert owner_id == int(admin_identity["user_id"])
            assert session_id == admin_identity["session_id"]
            return "pending"

        async def cancel_native_oauth(self, integration_id, attempt_id, *, owner_id, session_id):
            return None

    runtime = OAuthRuntime()
    config = replace(_auth_settings(settings), data_dir=tmp_path)
    providers = AssistantProviderManager(
        config,
        catalog=FakeCatalog(),
        vault_dir=tmp_path / "assistant-vault",
    )
    application = create_app(
        config,
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=runtime,
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    with TestClient(application, client=("127.0.0.1", 51036)) as internal_client:
        admin_identity = _add_signed_in_user(application, 50046, role="admin")
        _mark_recent_test_step_up(application, admin_identity)
        browser = _browser_client(application, admin_identity)
        try:
            methods = browser.get("/api/v1/assistant/providers/oauth/methods")
            assert methods.status_code == 200
            assert methods.json()["methods"] == [
                {
                    "integration_id": "openai",
                    "method_id": "chatgpt-headless",
                    "label": "ChatGPT headless sign-in",
                    "mode": "device",
                    "connection_status": "available",
                    "connection_supported": True,
                    "model_access_supported": True,
                    "availability_reason": None,
                }
            ]
            started = browser.post(
                "/api/v1/assistant/providers/oauth/attempts",
                headers={"x-csrf-token": str(admin_identity["csrf"])},
                json={"provider_id": "openai", "method_id": "chatgpt-headless"},
            )
            assert started.status_code == 200, started.text
            attempt = started.json()["attempt"]
            assert attempt["status"] == "pending"
            assert attempt["mode"] == "device"
            assert "capability" not in json.dumps(attempt)

            status = browser.get(
                f"/api/v1/assistant/providers/oauth/attempts/{attempt['attempt_id']}"
            )
            assert status.status_code == 200
            assert status.json()["attempt"]["status"] == "pending"
            attempts = browser.get("/api/v1/assistant/providers/oauth/attempts")
            assert attempts.status_code == 200
            assert [row["attempt_id"] for row in attempts.json()["attempts"]] == [
                attempt["attempt_id"]
            ]
            assert browser.get("/api/v1/assistant/providers/oauth/connections").json() == {
                "connections": []
            }
            assert runtime.capability is not None

            providers._write_oauth_credential(
                "openai",
                "chatgpt-headless",
                int(admin_identity["user_id"]),
                {
                    "type": "oauth",
                    "methodID": "chatgpt-headless",
                    "access": "synthetic-vault-access-token",
                    "refresh": "synthetic-vault-refresh-token",
                    "expires": int((time.time() + 300) * 1000),
                    "metadata": {"accountID": "synthetic-account"},
                },
            )
            connections = browser.get("/api/v1/assistant/providers/oauth/connections")
            assert connections.status_code == 200
            assert connections.json() == {
                "connections": [
                    {
                        "integration_id": "openai",
                        "method_id": "chatgpt-headless",
                        "status": "connected",
                        "model_access_supported": True,
                        "availability_reason": None,
                    }
                ]
            }
            assert "synthetic-vault-access-token" not in connections.text
            assert "synthetic-vault-refresh-token" not in connections.text
            disconnected = browser.delete(
                "/api/v1/assistant/providers/oauth/connections/openai/chatgpt-headless",
                headers={"x-csrf-token": str(admin_identity["csrf"])},
            )
            assert disconnected.status_code == 200
            assert disconnected.json()["connection"]["status"] == "disconnected"
            assert (
                providers._read_oauth_credential(
                    "openai", "chatgpt-headless", int(admin_identity["user_id"])
                )
                is None
            )

            headers = {"authorization": "Bearer " + runtime.capability}
            started_native = internal_client.post(
                "/api/v1/assistant/internal/oauth",
                headers=headers,
                json={
                    "attempt_id": attempt["attempt_id"],
                    "operation": "openai.device_start",
                    "input": {},
                },
            )
            assert started_native.status_code == 200
            assert started_native.json()["result"] == {
                "device_auth_id": "device-id",
                "user_code": "WXYZ-1234",
                "interval": "5",
            }

            malformed_native = internal_client.post(
                "/api/v1/assistant/internal/oauth",
                headers=headers,
                json={
                    "attempt_id": attempt["attempt_id"],
                    "operation": "openai.device_start",
                    "input": {"unexpected": "field"},
                },
            )
            assert malformed_native.status_code == 422
            assert len(fetched) == 1

            request_mode = "provider_failure"
            provider_failure = internal_client.post(
                "/api/v1/assistant/internal/oauth",
                headers=headers,
                json={
                    "attempt_id": attempt["attempt_id"],
                    "operation": "openai.device_start",
                    "input": {},
                },
            )
            assert provider_failure.status_code == 502
            assert provider_failure.json()["error"]["code"] == "oauth_provider_unavailable"
            assert len(writes) == 2

            def start_attempt() -> tuple[dict[str, object], str]:
                new_started = browser.post(
                    "/api/v1/assistant/providers/oauth/attempts",
                    headers={"x-csrf-token": str(admin_identity["csrf"])},
                    json={"provider_id": "openai", "method_id": "chatgpt-headless"},
                )
                assert new_started.status_code == 200, new_started.text
                assert runtime.capability is not None
                return new_started.json()["attempt"], runtime.capability

            request_mode = "totp_tls_expiry"
            totp_attempt, totp_capability = start_attempt()
            before_totp_write = len(writes)
            expired_step_up = internal_client.post(
                "/api/v1/assistant/internal/oauth",
                headers={"authorization": "Bearer " + totp_capability},
                json={
                    "attempt_id": totp_attempt["attempt_id"],
                    "operation": "openai.device_start",
                    "input": {},
                },
            )
            assert expired_step_up.status_code == 404
            assert expired_step_up.json()["error"]["code"] == "not_found"
            assert len(writes) == before_totp_write
            assert "oauth_provider_unavailable" not in expired_step_up.text
            application.state.assistant.clock = lambda: NOW
            request_mode = "success"
            fetched_before_retry = len(fetched)
            revoked_attempt_retry = internal_client.post(
                "/api/v1/assistant/internal/oauth",
                headers={"authorization": "Bearer " + totp_capability},
                json={
                    "attempt_id": totp_attempt["attempt_id"],
                    "operation": "openai.device_start",
                    "input": {},
                },
            )
            assert revoked_attempt_retry.status_code == 404
            assert len(fetched) == fetched_before_retry

            request_mode = "response_body_expiry"
            response_attempt, response_capability = start_attempt()
            held_body_revocation = internal_client.post(
                "/api/v1/assistant/internal/oauth",
                headers={"authorization": "Bearer " + response_capability},
                json={
                    "attempt_id": response_attempt["attempt_id"],
                    "operation": "openai.device_start",
                    "input": {},
                },
            )
            assert held_body_revocation.status_code == 404
            assert held_body_revocation.json()["error"]["code"] == "not_found"
            assert "device-id" not in held_body_revocation.text
            assert "WXYZ-1234" not in held_body_revocation.text
            assert "synthetic" not in held_body_revocation.text
            assert len(writes) == before_totp_write + 1
            application.state.assistant.clock = lambda: NOW

            request_mode = "dns_revoke"
            session_attempt, session_capability = start_attempt()
            before_dns_write = len(writes)
            revoked_during_dns = internal_client.post(
                "/api/v1/assistant/internal/oauth",
                headers={"authorization": "Bearer " + session_capability},
                json={
                    "attempt_id": session_attempt["attempt_id"],
                    "operation": "openai.device_start",
                    "input": {},
                },
            )
            assert revoked_during_dns.status_code == 404
            assert revoked_during_dns.json()["error"]["code"] == "not_found"
            assert len(writes) == before_dns_write
            assert "oauth_provider_unavailable" not in revoked_during_dns.text
        finally:
            browser.close()


def test_model_admin_disable_invalidates_only_that_model_policy(settings):
    other_model = replace(
        MODEL,
        model_id="free/model-v2",
        display_name="Second fixture model",
        policy_version="policy-2",
    )

    class Catalog:
        def list_models(self):
            return [
                {
                    "model_id": item.model_id,
                    "provider_id": item.provider_id,
                    "native_provider_id": item.provider_id,
                    "display_name": item.display_name,
                    "available": True,
                    "free": True,
                    "training": False,
                    "terms_url": item.terms_url,
                    "terms_reviewed_at": item.terms_reviewed_at,
                    "policy_version": item.policy_version,
                    "disclosure": item.disclosure,
                    "privacy_policy_version": item.policy_version,
                    "billing_policy_version": item.policy_version,
                    "billing_class": "free",
                    "enabled": True,
                    "usable": True,
                }
                for item in (MODEL, other_model)
            ]

    class ProviderManager(FakeProviders):
        def __init__(self):
            super().__init__()
            self.states = {
                item.model_id: {
                    "enabled": True,
                    "usable": True,
                    "policy_version": item.policy_version,
                    "privacy_policy_version": item.policy_version,
                    "acknowledged_privacy_policy_version": item.policy_version,
                    "billing_class": "free",
                    "billing_policy_version": item.policy_version,
                    "revision": 1,
                }
                for item in (MODEL, other_model)
            }
            self.default_model_id = MODEL.model_id

        def model_policy_state(self, model_id, *, owner_id=None):
            del owner_id
            return dict(self.states[model_id])

    providers = ProviderManager()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=Catalog(),
        assistant_providers=providers,
    )
    with TestClient(application, client=("127.0.0.1", 51021)):
        owner = _add_signed_in_user(application, 50027)
        browser = _browser_client(application, owner)
        try:
            _, _, turn, lease, _ = _conversation_and_running_turn(browser, owner)
            service = application.state.assistant
            assert service._execution_current(
                int(owner["user_id"]),
                str(turn["execution_id"]),
                MODEL.model_id,
                MODEL.policy_version,
            )
            assert service.policy(other_model.model_id).model_id == other_model.model_id

            providers.states[MODEL.model_id].update(enabled=False, usable=False, revision=2)
            assert not service._execution_current(
                int(owner["user_id"]),
                str(turn["execution_id"]),
                MODEL.model_id,
                MODEL.policy_version,
            )
            with pytest.raises(AssistantUnavailable) as disabled:
                service.policy(MODEL.model_id)
            assert disabled.value.code == "model_unavailable"

            providers.default_model_id = other_model.model_id
            assert service.policy(other_model.model_id).model_id == other_model.model_id
            assert (
                service._execution_current(
                    int(owner["user_id"]),
                    str(turn["execution_id"]),
                    MODEL.model_id,
                    MODEL.policy_version,
                )
                is False
            )
            assert lease["status"] == "active"
        finally:
            browser.close()


def test_turn_context_uses_admin_policy_generation_not_catalog_base(settings):
    catalog_generation = "catalog-policy-v0"
    reviewed_generation = "ap1-reviewed-policy-generation"

    class Catalog:
        def list_models(self):
            items = FakeCatalog().list_models()
            items[0]["policy_version"] = catalog_generation
            return items

    class ProviderManager(FakeProviders):
        def model_policy_state(self, model_id, *, owner_id=None):
            del owner_id
            assert model_id == MODEL.model_id
            return {
                "enabled": True,
                "usable": True,
                "policy_version": reviewed_generation,
                "privacy_policy_version": MODEL.policy_version,
                "acknowledged_privacy_policy_version": MODEL.policy_version,
                "billing_class": "free",
                "billing_policy_version": MODEL.policy_version,
                "revision": 2,
            }

    class CapturingRuntime(FakeRuntime):
        def __init__(self):
            self.contexts = []

        async def run_turn(self, *, context, prompt, emit):
            del prompt
            self.contexts.append(context)
            await emit({"type": "token", "data": {"text": "Policy-bound answer."}})
            return AssistantTurnResult(status="completed")

    runtime = CapturingRuntime()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=runtime,
        assistant_catalog=Catalog(),
        assistant_providers=ProviderManager(),
    )
    with TestClient(application, client=("127.0.0.1", 51032)):
        owner = _add_signed_in_user(application, 50040)
        browser = _browser_client(application, owner)
        try:
            canonical_context, conversation, turn, _lease, capability = (
                _conversation_and_running_turn(browser, owner)
            )
            assistant = application.state.assistant
            policy = assistant.policy(MODEL.model_id)
            assert policy.policy_version == reviewed_generation
            assert Catalog().list_models()[0]["policy_version"] == catalog_generation
            auth_context = application.state.auth.authenticate(str(owner["token"]), assistant.now())
            asyncio.run(
                assistant._run_turn(
                    context=auth_context,
                    conversation_id=str(conversation["id"]),
                    turn_id=str(turn["id"]),
                    execution_id=str(turn["execution_id"]),
                    capability=capability,
                    model_id=MODEL.model_id,
                    policy=policy,
                    prompt="Answer from the reviewed policy generation.",
                    canonical_context=canonical_context,
                )
            )
            assert len(runtime.contexts) == 1
            assert runtime.contexts[0].policy_version == reviewed_generation
            saved = assistant.storage.get_turn(
                int(owner["user_id"]), str(conversation["id"]), str(turn["id"])
            )
            assert saved["status"] == "completed"
            assert assistant.policy_still_authorized(
                int(owner["user_id"]), MODEL.model_id, reviewed_generation
            )
        finally:
            browser.close()


def test_conversation_http_envelopes_and_owner_crud(settings):
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51015)):
        owner = _add_signed_in_user(application, 50021)
        other = _add_signed_in_user(application, 50022)
        owner_browser = _browser_client(application, owner)
        other_browser = _browser_client(application, other)
        try:
            context = owner_browser.get(
                "/api/v1/assistant/context", params={"route": "/overview"}
            ).json()["context"]
            created = owner_browser.post(
                "/api/v1/assistant/conversations",
                headers={"x-csrf-token": str(owner["csrf"])},
                json={"title": "Initial title", "context": context},
            )
            assert created.status_code == 201, created.text
            # The create handler wraps storage detail, whose public item is itself named
            # `conversation`; this is the browser contract the frontend consumes.
            detail = created.json()["conversation"]
            conversation = detail["conversation"]
            assert conversation["title"] == "Initial title"
            conversation_id = str(conversation["id"])
            assert detail["messages"] == {"items": [], "page": 1, "page_size": 50, "total": 0}

            denied = other_browser.patch(
                f"/api/v1/assistant/conversations/{conversation_id}",
                headers={"x-csrf-token": str(other["csrf"])},
                json={"title": "Not yours", "expected_revision": 1},
            )
            assert denied.status_code == 404
            renamed = owner_browser.patch(
                f"/api/v1/assistant/conversations/{conversation_id}",
                headers={"x-csrf-token": str(owner["csrf"])},
                json={"title": "Reviewed title", "expected_revision": 1},
            )
            assert renamed.status_code == 200, renamed.text
            assert renamed.json()["conversation"]["title"] == "Reviewed title"
            assert renamed.json()["conversation"]["revision"] == 2

            stale = owner_browser.request(
                "DELETE",
                f"/api/v1/assistant/conversations/{conversation_id}",
                headers={"x-csrf-token": str(owner["csrf"])},
                json={
                    "expected_revision": 1,
                    "confirmation_phrase": conversation["delete_confirmation_phrase"],
                },
            )
            assert stale.status_code == 409
            deleted = owner_browser.request(
                "DELETE",
                f"/api/v1/assistant/conversations/{conversation_id}",
                headers={"x-csrf-token": str(owner["csrf"])},
                json={
                    "expected_revision": 2,
                    "confirmation_phrase": conversation["delete_confirmation_phrase"],
                },
            )
            assert deleted.status_code == 200, deleted.text
            assert deleted.json()["canonical_content_removed"] is True
            assert (
                owner_browser.get(f"/api/v1/assistant/conversations/{conversation_id}").status_code
                == 404
            )
        finally:
            owner_browser.close()


def test_secret_prompt_is_rejected_without_echo_or_durable_transcript(settings):
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51027)):
        owner = _add_signed_in_user(application, 50035)
        browser = _browser_client(application, owner)
        try:
            context_response = browser.get(
                "/api/v1/assistant/context", params={"route": "/overview"}
            )
            assert context_response.status_code == 200
            context = context_response.json()["context"]
            created = browser.post(
                "/api/v1/assistant/conversations",
                headers={"x-csrf-token": str(owner["csrf"])},
                json={"context": context},
            )
            assert created.status_code == 201
            conversation_id = str(created.json()["conversation"]["conversation"]["id"])
            application.state.assistant.storage.create_consent(
                int(owner["user_id"]),
                model_id=MODEL.model_id,
                policy_version=MODEL.policy_version,
                accepted_terms=True,
                data_collection_opt_in=False,
                recorded_at=NOW,
            )
            sentinel = "private-output-sentinel-91a6d3"
            response = browser.post(
                f"/api/v1/assistant/conversations/{conversation_id}/turns",
                headers={"x-csrf-token": str(owner["csrf"])},
                json={
                    "prompt": f"api_key={sentinel}",
                    "model_id": MODEL.model_id,
                    "policy_version": MODEL.policy_version,
                    "context": context,
                    "context_preview_accepted": True,
                },
            )
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == "sensitive_input_rejected"
            assert sentinel not in response.text
            detail = browser.get(f"/api/v1/assistant/conversations/{conversation_id}")
            assert detail.status_code == 200
            assert detail.json()["messages"]["total"] == 0
            assert detail.json()["turns"] == []
            assert sentinel not in detail.text
        finally:
            browser.close()


def test_provider_credentials_and_authenticator_codes_are_rejected_preflight(settings):
    providers = FakeProviders()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    google_api_key = "AIza" + "A" * 35
    secret_prompts = (
        "-----BEGIN PRIVATE KEY-----\nfake key bytes\n-----END PRIVATE KEY-----",
        "sk-" + "A" * 40,
        "sk-ant-api03-" + "a" * 40,
        google_api_key,
        f"Search the web using this key: {google_api_key}.",
        f"Search using joined key: x{google_api_key}z.",
        f"Search using Unicode-adjacent key: é{google_api_key}ø.",
        "123456",
        "my authenticator code 123456",
        "The TOTP verification code is 123456.",
    )
    ordinary_prompts = (
        "Compare market levels 123456 and 123457.",
        "Research AAPL earnings and compare its latest forecast with SPY.",
    )
    for prompt in ordinary_prompts:
        assert AssistantService._validate_prompt(prompt) == prompt
    assert AssistantService.contains_known_secret_text({"text": google_api_key})
    with TestClient(application, client=("127.0.0.1", 51028)):
        owner = _add_signed_in_user(application, 50036)
        browser = _browser_client(application, owner)
        try:
            context_response = browser.get(
                "/api/v1/assistant/context", params={"route": "/overview"}
            )
            assert context_response.status_code == 200
            context = context_response.json()["context"]
            created = browser.post(
                "/api/v1/assistant/conversations",
                headers={"x-csrf-token": str(owner["csrf"])},
                json={"context": context},
            )
            assert created.status_code == 201
            conversation_id = str(created.json()["conversation"]["conversation"]["id"])
            application.state.assistant.storage.create_consent(
                int(owner["user_id"]),
                model_id=MODEL.model_id,
                policy_version=MODEL.policy_version,
                accepted_terms=True,
                data_collection_opt_in=False,
                recorded_at=NOW,
            )

            for prompt in secret_prompts:
                response = browser.post(
                    f"/api/v1/assistant/conversations/{conversation_id}/turns",
                    headers={"x-csrf-token": str(owner["csrf"])},
                    json={
                        "prompt": prompt,
                        "model_id": MODEL.model_id,
                        "policy_version": MODEL.policy_version,
                        "context": context,
                        "context_preview_accepted": True,
                    },
                )
                assert response.status_code == 422, response.text
                assert response.json()["error"]["code"] == "sensitive_input_rejected"

            with pytest.raises(AssistantUnavailable) as output_rejection:
                application.state.assistant._normalize_runtime_event(
                    "token",
                    {"text": google_api_key},
                    int(owner["user_id"]),
                    conversation_id,
                    "synthetic-output-turn",
                    execution_id="synthetic-output-execution",
                )
            assert output_rejection.value.code == "sensitive_output_rejected"

            detail = browser.get(f"/api/v1/assistant/conversations/{conversation_id}")
            assert detail.status_code == 200
            assert detail.json()["messages"]["total"] == 0
            assert detail.json()["turns"] == []
            assert providers.calls == []
            for prompt in secret_prompts:
                assert prompt not in detail.text
        finally:
            browser.close()


def test_provider_proxy_iterator_cancellation_defers_close_until_anext_finishes():
    async def exercise() -> None:
        class SlowIterator:
            def __init__(self):
                self.started = asyncio.Event()
                self.cancel_seen = asyncio.Event()
                self.resume = asyncio.Event()
                self.closed = asyncio.Event()
                self.running = False
                self.closed_while_running = False

            def __aiter__(self):
                return self

            async def __anext__(self):
                self.running = True
                self.started.set()
                try:
                    await self.resume.wait()
                    return b"data: late chunk\n\n"
                except asyncio.CancelledError:
                    self.cancel_seen.set()
                    await self.resume.wait()
                    return b"data: late chunk\n\n"
                finally:
                    self.running = False

            async def aclose(self):
                if self.running:
                    self.closed_while_running = True
                    raise RuntimeError("close raced with __anext__")
                self.closed.set()

        upstream = SlowIterator()
        bridge = _provider_proxy_chunks(upstream, lambda: True)
        consumer = asyncio.create_task(bridge.__anext__())
        await upstream.started.wait()
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer
        await upstream.cancel_seen.wait()
        assert not upstream.closed.is_set()
        upstream.resume.set()
        await asyncio.wait_for(upstream.closed.wait(), timeout=1.0)
        assert not upstream.closed_while_running

    asyncio.run(exercise())


def test_provider_proxy_second_cancellation_still_consumes_anext_and_closes_later():
    async def exercise() -> None:
        import gc

        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        unhandled: list[dict[str, object]] = []
        loop.set_exception_handler(lambda _loop, context: unhandled.append(context))

        class SlowIterator:
            def __init__(self):
                self.started = asyncio.Event()
                self.cancel_seen = asyncio.Event()
                self.resume = asyncio.Event()
                self.closed = asyncio.Event()
                self.running = False

            def __aiter__(self):
                return self

            async def __anext__(self):
                self.running = True
                self.started.set()
                try:
                    await self.resume.wait()
                    return b"late"
                except asyncio.CancelledError:
                    self.cancel_seen.set()
                    await self.resume.wait()
                    raise StopAsyncIteration from None
                finally:
                    self.running = False

            async def aclose(self):
                assert not self.running
                self.closed.set()

        upstream = SlowIterator()
        consumer = asyncio.create_task(_provider_proxy_chunks(upstream, lambda: True).__anext__())
        try:
            await upstream.started.wait()
            consumer.cancel()
            await upstream.cancel_seen.wait()
            # This second cancellation interrupts the bridge's bounded cleanup wait.
            consumer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await consumer
            upstream.resume.set()
            await asyncio.wait_for(upstream.closed.wait(), timeout=1.0)
            await asyncio.sleep(0)
            gc.collect()
            await asyncio.sleep(0)
            assert unhandled == []
        finally:
            loop.set_exception_handler(previous_handler)

    asyncio.run(exercise())


def test_provider_proxy_cancellation_consumes_simultaneous_iterator_eof():
    async def exercise() -> None:
        import gc

        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        unhandled: list[dict[str, object]] = []
        loop.set_exception_handler(lambda _loop, context: unhandled.append(context))

        class EndingIterator:
            def __init__(self):
                self.started = asyncio.Event()
                self.finish = asyncio.Event()
                self.ended = asyncio.Event()
                self.closed = False

            def __aiter__(self):
                return self

            async def __anext__(self):
                self.started.set()
                try:
                    await self.finish.wait()
                finally:
                    self.ended.set()
                raise StopAsyncIteration

            async def aclose(self):
                self.closed = True

        upstream = EndingIterator()
        bridge = _provider_proxy_chunks(upstream, lambda: True)
        consumer = asyncio.create_task(bridge.__anext__())
        try:
            await upstream.started.wait()
            upstream.finish.set()
            await upstream.ended.wait()
            consumer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await consumer
            await asyncio.sleep(0)
            gc.collect()
            await asyncio.sleep(0)
            assert upstream.closed
            assert unhandled == []
        finally:
            loop.set_exception_handler(previous_handler)

    asyncio.run(exercise())


def test_provider_proxy_iterator_exception_is_sanitized_and_not_clean_eof():
    async def exercise() -> None:
        class BrokenIterator:
            def __init__(self):
                self.emitted = False
                self.closed = False

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self.emitted:
                    raise ValueError("private upstream detail")
                self.emitted = True
                return b"data: partial\n\n"

            async def aclose(self):
                self.closed = True

        upstream = BrokenIterator()
        bridge = _provider_proxy_chunks(upstream, lambda: True)
        assert await bridge.__anext__() == b"data: partial\n\n"
        with pytest.raises(AssistantUnavailable) as failure:
            await bridge.__anext__()
        assert str(failure.value) == "provider_unavailable"
        assert "private upstream detail" not in str(failure.value)
        assert upstream.closed

    asyncio.run(exercise())


def test_provider_proxy_records_closed_transport_failure_fields(caplog: pytest.LogCaptureFixture):
    async def exercise() -> None:
        class Runtime:
            def __init__(self) -> None:
                self.failures: list[tuple[object, ...]] = []

            def _record_provider_stream_start(self, *_args: object) -> int:
                return 1

            def _record_provider_stream_failure(self, *args: object) -> None:
                self.failures.append(args)

            def _record_provider_stream_end(self, *_args: object) -> None:
                return None

        runtime = Runtime()

        async def upstream():
            raise net.PublicHTTPError("provider_upstream_unavailable", status_code=503)
            yield b"unreachable"

        bridge = assistant_api._provider_proxy_chunks_with_timing(
            upstream(),
            lambda: True,
            runtime=runtime,
            execution_id="a" * 32,
            owner_id=1,
        )
        with pytest.raises(AssistantUnavailable) as failure:
            await bridge.__anext__()
        assert failure.value.code == "provider_unavailable"
        await bridge.aclose()
        assert runtime.failures == [
            (
                "a" * 32,
                1,
                1,
                "upstream_stream",
                "provider_upstream_unavailable",
                503,
            )
        ]

    with caplog.at_level("WARNING", logger="stock_probs.assistant.api"):
        asyncio.run(exercise())

    assert "ASSISTANT_PROVIDER_STREAM_FAILURE_V1" not in caplog.text
    assert "provider_unavailable" not in caplog.text


def test_provider_proxy_records_only_closed_403_transport_classes() -> None:
    assert assistant_api._PROVIDER_403_ERROR_TYPE_CLASSES == net._PROVIDER_403_ERROR_TYPE_CLASSES

    async def exercise(
        failure: net.PublicHTTPError,
        expected_failure: tuple[object, ...],
    ) -> None:
        class Runtime:
            def __init__(self) -> None:
                self.failures: list[tuple[object, ...]] = []

            def _record_provider_stream_start(self, *_args: object) -> int:
                return 1

            def _record_provider_stream_failure(self, *args: object) -> None:
                self.failures.append(args)

            def _record_provider_stream_end(self, *_args: object) -> None:
                return None

        runtime = Runtime()

        async def upstream():
            raise failure
            yield b"unreachable"

        bridge = assistant_api._provider_proxy_chunks_with_timing(
            upstream(),
            lambda: True,
            runtime=runtime,
            execution_id="d" * 32,
            owner_id=4,
        )
        with pytest.raises(AssistantUnavailable) as caught:
            await bridge.__anext__()
        assert caught.value.code == "provider_unavailable"
        assert str(caught.value) == "provider_unavailable"
        await bridge.aclose()
        assert runtime.failures == [expected_failure]

    known = net.PublicHTTPError(
        "provider_upstream_unavailable",
        status_code=403,
        content_type_class="json",
        cf_mitigated_class="challenge",
        provider_error_type_class="free_usage_limit_error",
    )
    asyncio.run(
        exercise(
            known,
            (
                "d" * 32,
                4,
                1,
                "upstream_stream",
                "provider_upstream_unavailable",
                403,
                "json",
                "challenge",
                "free_usage_limit_error",
            ),
        )
    )

    legacy = net.PublicHTTPError("provider_upstream_unavailable", status_code=403)
    asyncio.run(
        exercise(
            legacy,
            (
                "d" * 32,
                4,
                1,
                "upstream_stream",
                "provider_upstream_unavailable",
                403,
            ),
        )
    )

    malicious = net.PublicHTTPError(
        "provider_upstream_unavailable",
        status_code=403,
        content_type_class="json",
        cf_mitigated_class="absent",
    )
    malicious.content_type_class = "html token=synthetic-private"
    malicious.cf_mitigated_class = object()
    malicious.provider_error_type_class = "free_usage_limit_error token=synthetic-private"
    asyncio.run(
        exercise(
            malicious,
            (
                "d" * 32,
                4,
                1,
                "upstream_stream",
                "provider_upstream_unavailable",
                403,
            ),
        )
    )

    invalid_error_type = net.PublicHTTPError(
        "provider_upstream_unavailable",
        status_code=403,
        content_type_class="json",
        cf_mitigated_class="absent",
        provider_error_type_class="free_usage_limit_error",
    )
    invalid_error_type.provider_error_type_class = "FreeUsageLimitError token=synthetic-private"
    asyncio.run(
        exercise(
            invalid_error_type,
            (
                "d" * 32,
                4,
                1,
                "upstream_stream",
                "provider_upstream_unavailable",
                403,
                "json",
                "absent",
            ),
        )
    )

    non_403_error_type = net.PublicHTTPError("provider_upstream_unavailable", status_code=503)
    non_403_error_type.provider_error_type_class = "free_usage_limit_error"
    asyncio.run(
        exercise(
            non_403_error_type,
            (
                "d" * 32,
                4,
                1,
                "upstream_stream",
                "provider_upstream_unavailable",
                503,
            ),
        )
    )


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("token=synthetic-private-provider-detail"),
        net.PublicHTTPError("provider_upstream_unavailable"),
    ],
)
def test_provider_proxy_unknown_failures_do_not_log_exception_contents(
    caplog: pytest.LogCaptureFixture, failure: Exception
) -> None:
    async def exercise() -> None:
        class Runtime:
            def __init__(self) -> None:
                self.failures: list[tuple[object, ...]] = []

            def _record_provider_stream_start(self, *_args: object) -> int:
                return 1

            def _record_provider_stream_failure(self, *args: object) -> None:
                self.failures.append(args)

            def _record_provider_stream_end(self, *_args: object) -> None:
                return None

        runtime = Runtime()

        if isinstance(failure, net.PublicHTTPError):
            failure.code = "private-code token=synthetic-private-provider-detail"
            failure.status_code = 999

        async def upstream():
            raise failure
            yield b"unreachable"

        bridge = assistant_api._provider_proxy_chunks_with_timing(
            upstream(),
            lambda: True,
            runtime=runtime,
            execution_id="b" * 32,
            owner_id=2,
        )
        with pytest.raises(AssistantUnavailable) as caught:
            await bridge.__anext__()
        assert caught.value.code == "provider_unavailable"
        await bridge.aclose()
        assert runtime.failures == [
            (
                "b" * 32,
                2,
                1,
                "upstream_stream",
                "upstream_error_unknown",
                None,
            )
        ]

    with caplog.at_level("WARNING", logger="stock_probs.assistant.api"):
        asyncio.run(exercise())

    assert "ASSISTANT_PROVIDER_STREAM_FAILURE_V1" not in caplog.text
    assert "synthetic-private-provider-detail" not in caplog.text
    assert "private-code" not in caplog.text


def test_provider_proxy_cancellation_does_not_emit_failure_diagnostic(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def exercise() -> None:
        started = asyncio.Event()

        class Runtime:
            def __init__(self) -> None:
                self.failures: list[tuple[object, ...]] = []

            def _record_provider_stream_start(self, *_args: object) -> int:
                return 1

            def _record_provider_stream_failure(self, *args: object) -> None:
                self.failures.append(args)

            def _record_provider_stream_end(self, *_args: object) -> None:
                return None

        runtime = Runtime()

        async def upstream():
            started.set()
            await asyncio.Future()
            yield b"unreachable"

        bridge = assistant_api._provider_proxy_chunks_with_timing(
            upstream(),
            lambda: True,
            runtime=runtime,
            execution_id="c" * 32,
            owner_id=3,
        )
        consumer = asyncio.create_task(bridge.__anext__())
        await started.wait()
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer
        await bridge.aclose()
        assert runtime.failures == []

    with caplog.at_level("WARNING", logger="stock_probs.assistant.api"):
        asyncio.run(exercise())

    assert "ASSISTANT_PROVIDER_STREAM_FAILURE_V1" not in caplog.text


def test_provider_proxy_failure_diagnostics_stop_at_registered_stream_cap(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def exercise() -> list[tuple[object, ...]]:
        class Runtime:
            def __init__(self) -> None:
                self.started = 0
                self.failures: list[tuple[object, ...]] = []

            def _record_provider_stream_start(self, *_args: object) -> int | None:
                self.started += 1
                return self.started if self.started <= 8 else None

            def _record_provider_stream_failure(self, *args: object) -> None:
                self.failures.append(args)

            def _record_provider_stream_end(self, *_args: object) -> None:
                return None

        runtime = Runtime()

        async def upstream():
            raise RuntimeError("token=synthetic-private-provider-detail")
            yield b"unreachable"

        for _attempt in range(9):
            bridge = assistant_api._provider_proxy_chunks_with_timing(
                upstream(),
                lambda: True,
                runtime=runtime,
                execution_id="d" * 32,
                owner_id=4,
            )
            with pytest.raises(AssistantUnavailable):
                await bridge.__anext__()
            await bridge.aclose()
        return runtime.failures

    with caplog.at_level("WARNING", logger="stock_probs.assistant.api"):
        failures = asyncio.run(exercise())

    assert len(failures) == 8
    assert "synthetic-private-provider-detail" not in caplog.text
    assert "execution_id" not in caplog.text


def test_filter_confirmation_handoff_targets_actual_dashboard_history(settings):
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51005)) as machine:
        identity = _add_signed_in_user(application, 50008)
        browser = _browser_client(application, identity)
        try:
            context, conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, identity, route="/"
            )
            history_form_payload = {
                "query": "ACDC",
                "asset_type": "",
                "status": "successful",
                "analysis_kind": "",
                "submitted_from": "",
                "submitted_to": "",
                "model": "",
                "horizon": "",
                "sort": "event_id:desc",
                "page_size": 10,
            }
            proposal = _mcp(
                machine,
                str(turn["execution_id"]),
                capability,
                "tools/call",
                {
                    "name": "assistant.propose_action",
                    "arguments": {
                        "action_type": "filters.apply",
                        "payload": history_form_payload,
                    },
                },
            )
            assert proposal.status_code == 200, proposal.text
            events = application.state.assistant.storage.events_after(
                int(identity["user_id"]),
                str(conversation["id"]),
                str(turn["id"]),
                after=0,
            )
            card = next(event["data"] for event in events if event["type"] == "proposed_action")
            confirmed = browser.post(
                f"/api/v1/assistant/conversations/{conversation['id']}/actions/{card['action_id']}/confirm",
                headers={"x-csrf-token": str(identity["csrf"])},
                json={
                    "action_version": 1,
                    "context": context,
                    "allow": True,
                    "confirmation_phrase": card["confirmation_phrase"],
                },
            )
            assert confirmed.status_code == 200, confirmed.text
            result = confirmed.json()
            assert result["status"] == "handed_off"
            assert result["destination"] == "/#history-heading"
            assert result["browser_action"]["type"] == "filters.apply"
            assert result["browser_action"]["destination"] == {
                "kind": "current-page",
                "route": "/",
            }
            assert result["browser_action"]["payload"] == history_form_payload
            reopened = browser.get(f"/api/v1/assistant/conversations/{conversation['id']}").json()
            saved_action = next(
                item for item in reopened["actions"] if item["action_id"] == card["action_id"]
            )
            assert saved_action["receipt"]["outcome"] == "handed_off"
            assert saved_action["receipt"]["destination"] == "/#history-heading"

            # Reopen a persisted receipt even if an older/corrupt row contains a non-local
            # destination. The projection must not turn stored data into an external navigation.
            unsafe_destinations = (
                "https://untrusted.example/?event_id=1#result-section",
                "//untrusted.example/?event_id=1#result-section",
                "/\\\\untrusted.example/?event_id=1#result-section",
                "/?q=ACDC\x7f#history-heading",
            )
            with application.state.repository.connect() as connection:
                connection.execute("DROP TRIGGER assistant_action_receipts_update_guard")
            for unsafe_destination in unsafe_destinations:
                with application.state.repository.connect() as connection:
                    connection.execute(
                        "UPDATE assistant_action_receipts SET result_json = ? WHERE action_id = ?",
                        (
                            json.dumps(
                                {
                                    "message": "Action completed.",
                                    "destination": unsafe_destination,
                                }
                            ),
                            card["action_id"],
                        ),
                    )
                    connection.commit()
                reopened = browser.get(
                    f"/api/v1/assistant/conversations/{conversation['id']}"
                ).json()
                saved_action = next(
                    item for item in reopened["actions"] if item["action_id"] == card["action_id"]
                )
                assert "destination" not in saved_action["receipt"]
        finally:
            browser.close()


def test_confirmation_receipt_failure_returns_durable_unknown_without_handoff(
    settings, monkeypatch
):
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51017)) as machine:
        owner = _add_signed_in_user(application, 50024)
        browser = _browser_client(application, owner)
        try:
            context, conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, owner, route="/"
            )
            conversation_id = str(conversation["id"])
            response = _mcp(
                machine,
                str(turn["execution_id"]),
                capability,
                "tools/call",
                {
                    "name": "assistant.propose_action",
                    "arguments": {
                        "action_type": "filters.apply",
                        "payload": {"query": "ACDC", "status": "successful"},
                    },
                },
            )
            assert response.status_code == 200, response.text
            app = application.state.assistant
            card = next(
                event["data"]
                for event in app.storage.events_after(
                    int(owner["user_id"]), conversation_id, str(turn["id"]), after=0
                )
                if event["type"] == "proposed_action"
            )

            # Force the terminal receipt write to fail after dispatch. The fallback transition
            # must persist unknown and suppress the destination/browser bridge from the success.
            from stock_probs.assistant.storage import AssistantStorageError

            def fail_finish(*_args, **_kwargs):
                raise AssistantStorageError("injected receipt persistence failure")

            monkeypatch.setattr(app.storage, "finish_action", fail_finish)
            confirmed = browser.post(
                f"/api/v1/assistant/conversations/{conversation_id}/actions/{card['action_id']}/confirm",
                headers={"x-csrf-token": str(owner["csrf"])},
                json={
                    "action_version": 1,
                    "context": context,
                    "allow": True,
                    "confirmation_phrase": card["confirmation_phrase"],
                },
            )
            assert confirmed.status_code == 200, confirmed.text
            result = confirmed.json()
            assert result["status"] == "unknown"
            assert "destination" not in result
            assert "browser_action" not in result
            receipt = app.storage.get_action_receipt(int(owner["user_id"]), str(card["action_id"]))
            assert receipt is not None and receipt["outcome"] == "unknown"
            reopened = browser.get(f"/api/v1/assistant/conversations/{conversation_id}")
            saved = next(
                action
                for action in reopened.json()["actions"]
                if action["action_id"] == card["action_id"]
            )
            assert saved["receipt"]["outcome"] == "unknown"
            assert "destination" not in saved["receipt"]
            assert "browser_action" not in saved["receipt"]
        finally:
            browser.close()


@pytest.mark.parametrize("auth_change", ["session_revoked", "factor_invalidated", "role_demoted"])
def test_action_confirmation_rechecks_live_auth_after_target_validation(
    settings, monkeypatch, auth_change
):
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51035)) as machine:
        role = "admin" if auth_change == "role_demoted" else "member"
        identity = _add_signed_in_user(application, 50045, role=role)
        if role == "admin":
            factor = application.state.repository.auth_get_totp_factor(int(identity["user_id"]))
            assert factor is not None
            assert application.state.repository.auth_set_session_mfa(
                str(identity["token_hash"]), "totp", NOW.isoformat(), int(factor["id"])
            )
        browser = _browser_client(application, identity)
        try:
            context, conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, identity
            )
            if auth_change == "role_demoted":
                action_type = "provider.settings"
                payload: dict[str, object] = {}
            else:
                action_type = "portfolio.add"
                resolved = application.state.assistant.forecast_service.lookup("SPY", 1)["items"][0]
                payload = {
                    "symbol": resolved["canonical_symbol"],
                    "asset_type": resolved["asset_type"],
                    "provider": resolved["provider"],
                    "exchange": resolved["exchange"],
                    "quantity": 1.0,
                }
            proposed = _mcp(
                machine,
                str(turn["execution_id"]),
                capability,
                "tools/call",
                {
                    "name": "assistant.propose_action",
                    "arguments": {"action_type": action_type, "payload": payload},
                },
            )
            assert proposed.status_code == 200, proposed.text
            card = next(
                event["data"]
                for event in application.state.assistant.storage.events_after(
                    int(identity["user_id"]),
                    str(conversation["id"]),
                    str(turn["id"]),
                    after=0,
                    limit=20,
                )
                if event["type"] == "proposed_action"
            )
            application.state.assistant.storage.set_turn_status(
                int(identity["user_id"]),
                str(conversation["id"]),
                str(turn["id"]),
                status="completed",
                now=NOW,
            )
            application.state.assistant.storage.close_execution(str(turn["execution_id"]), now=NOW)

            assistant = application.state.assistant
            validate_target = assistant._validate_action_target
            resolve_identity = assistant._resolve_identity

            def invalidate_session() -> None:
                if auth_change == "session_revoked":
                    application.state.repository.auth_revoke_session(
                        str(identity["token_hash"]), NOW.isoformat()
                    )
                elif auth_change == "factor_invalidated":
                    with application.state.repository.connect() as connection:
                        connection.execute(
                            """UPDATE sessions SET mfa_method = NULL, mfa_verified_at = NULL,
                            mfa_factor_id = NULL WHERE token_hash = ?""",
                            (str(identity["token_hash"]),),
                        )
                        connection.commit()
                else:
                    application.state.repository.auth_update_user(
                        int(identity["user_id"]), {"role": "member"}
                    )

            if auth_change == "role_demoted":

                def demote_after_target(*args, **kwargs):
                    validate_target(*args, **kwargs)
                    invalidate_session()

                monkeypatch.setattr(assistant, "_validate_action_target", demote_after_target)
            else:

                def revoke_after_identity(*args, **kwargs):
                    result = resolve_identity(*args, **kwargs)
                    invalidate_session()
                    return result

                monkeypatch.setattr(assistant, "_resolve_identity", revoke_after_identity)

            rejected = browser.post(
                f"/api/v1/assistant/conversations/{conversation['id']}/actions/{card['action_id']}/confirm",
                headers={"x-csrf-token": str(identity["csrf"])},
                json={
                    "action_version": card["version"],
                    "context": context,
                    "allow": True,
                    "confirmation_phrase": card["confirmation_phrase"],
                },
            )
            assert rejected.status_code in {403, 404}, rejected.text
            assert (
                assistant.storage.get_action(int(identity["user_id"]), card["action_id"])["status"]
                == "pending"
            )
            assert (
                assistant.storage.get_action_receipt(int(identity["user_id"]), card["action_id"])
                is None
            )
            assert (
                application.state.repository.instrument_list_items(
                    int(identity["user_id"]), "portfolio"
                )
                == []
            )
        finally:
            browser.close()


@pytest.mark.parametrize("action_type", ["forecast.create", "reconstruction.run"])
@pytest.mark.parametrize("provider_failure", [False, True])
def test_assistant_provider_revocation_blocks_success_and_failure_audits(
    settings, monkeypatch, action_type, provider_failure
):
    from stock_probs.domain import DomainError

    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    application.state.assistant.forecast_service.clock = lambda: FORECAST_NOW
    with TestClient(application, client=("127.0.0.1", 51036)) as machine:
        owner = _add_signed_in_user(application, 50046)
        browser = _browser_client(application, owner)
        try:
            app = application.state.assistant
            source_event_id: int | None = None
            if action_type == "reconstruction.run":
                seeded = browser.post(
                    "/api/v1/forecasts",
                    json={"symbol": "ACDC", "asset_type": "stock"},
                    headers={"x-csrf-token": str(owner["csrf"])},
                )
                assert seeded.status_code == 201, seeded.text
                source_event_id = int(seeded.json()["event"]["id"])
                instrument = app.forecast_service.lookup("ACDC", 1)["items"][0]
                payload = {"event_id": source_event_id, "cutoff": FORECAST_NOW.isoformat()}
            else:
                instrument = app.forecast_service.lookup("SPY", 1)["items"][0]
                payload = {
                    "symbol": instrument["canonical_symbol"],
                    "asset_type": instrument["asset_type"],
                    "provider": instrument["provider"],
                    "exchange": instrument["exchange"],
                }
            context, conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, owner, route="/tools/forecast"
            )
            proposed = _mcp(
                machine,
                str(turn["execution_id"]),
                capability,
                "tools/call",
                {
                    "name": "assistant.propose_action",
                    "arguments": {"action_type": action_type, "payload": payload},
                },
            )
            assert proposed.status_code == 200, proposed.text
            card = next(
                event["data"]
                for event in app.storage.events_after(
                    int(owner["user_id"]),
                    str(conversation["id"]),
                    str(turn["id"]),
                    after=0,
                    limit=20,
                )
                if event["type"] == "proposed_action"
            )
            app.storage.set_turn_status(
                int(owner["user_id"]),
                str(conversation["id"]),
                str(turn["id"]),
                status="completed",
                now=NOW,
            )
            app.storage.close_execution(str(turn["execution_id"]), now=NOW)
            before_runs = application.state.repository.history(owner_user_id=int(owner["user_id"]))[
                "total"
            ]
            original_fetch = (
                app.forecast_service.provider.fetch
                if action_type == "forecast.create"
                else app.forecast_service.provider.fetch_at_cutoff
            )

            def revoke_then_fetch(*args, **kwargs):
                application.state.repository.auth_revoke_session(
                    str(owner["token_hash"]), NOW.isoformat()
                )
                if provider_failure:
                    raise DomainError(
                        "provider_unavailable", "The market data provider failed.", status_code=502
                    )
                return original_fetch(*args, **kwargs)

            if action_type == "forecast.create":
                monkeypatch.setattr(app.forecast_service.provider, "fetch", revoke_then_fetch)
            else:
                monkeypatch.setattr(
                    app.forecast_service.provider, "fetch_at_cutoff", revoke_then_fetch
                )
            rejected = browser.post(
                f"/api/v1/assistant/conversations/{conversation['id']}/actions/{card['action_id']}/confirm",
                headers={"x-csrf-token": str(owner["csrf"])},
                json={
                    "action_version": card["version"],
                    "context": context,
                    "allow": True,
                    "confirmation_phrase": card["confirmation_phrase"],
                },
            )
            assert rejected.status_code == 403, rejected.text
            assert (
                application.state.repository.history(owner_user_id=int(owner["user_id"]))["total"]
                == before_runs
            )
            action = app.storage.get_action(int(owner["user_id"]), card["action_id"])
            assert action["status"] == "unknown"
            receipt = app.storage.get_action_receipt(int(owner["user_id"]), card["action_id"])
            assert receipt is not None and receipt["outcome"] == "unknown"
            if source_event_id is not None:
                source = application.state.repository.reconstruction(
                    int(owner["user_id"]), source_event_id
                )
                assert source is not None
        finally:
            browser.close()


def test_action_decline_does_not_resolve_market_target_during_provider_outage(
    settings, monkeypatch
):
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51037)) as machine:
        owner = _add_signed_in_user(application, 50047)
        browser = _browser_client(application, owner)
        try:
            assistant = application.state.assistant
            identity = assistant.forecast_service.lookup("SPY", 1)["items"][0]
            payload = {
                "symbol": identity["canonical_symbol"],
                "asset_type": identity["asset_type"],
                "provider": identity["provider"],
                "exchange": identity["exchange"],
            }
            context, conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, owner
            )
            proposed = _mcp(
                machine,
                str(turn["execution_id"]),
                capability,
                "tools/call",
                {
                    "name": "assistant.propose_action",
                    "arguments": {"action_type": "market.open", "payload": payload},
                },
            )
            assert proposed.status_code == 200, proposed.text
            card = next(
                event["data"]
                for event in assistant.storage.events_after(
                    int(owner["user_id"]),
                    str(conversation["id"]),
                    str(turn["id"]),
                    after=0,
                    limit=20,
                )
                if event["type"] == "proposed_action"
            )
            assistant.storage.set_turn_status(
                int(owner["user_id"]),
                str(conversation["id"]),
                str(turn["id"]),
                status="completed",
                now=NOW,
            )
            assistant.storage.close_execution(str(turn["execution_id"]), now=NOW)
            resolutions = 0

            def unavailable_identity(*_args, **_kwargs):
                nonlocal resolutions
                resolutions += 1
                raise AssistantUnavailable("provider_unavailable", 503)

            monkeypatch.setattr(assistant, "_resolve_identity", unavailable_identity)
            declined = browser.post(
                f"/api/v1/assistant/conversations/{conversation['id']}/actions/{card['action_id']}/confirm",
                headers={"x-csrf-token": str(owner["csrf"])},
                json={
                    "action_version": card["version"],
                    "context": context,
                    "allow": False,
                    "confirmation_phrase": card["confirmation_phrase"],
                },
            )
            assert declined.status_code == 200, declined.text
            assert declined.json()["status"] == "denied"
            assert resolutions == 0
            action = assistant.storage.get_action(int(owner["user_id"]), card["action_id"])
            assert action["status"] == "denied"
            receipt = assistant.storage.get_action_receipt(int(owner["user_id"]), card["action_id"])
            assert receipt is not None and receipt["outcome"] == "denied"
        finally:
            browser.close()


def test_expired_action_preview_and_sse_replay_do_not_retain_confirmation_phrase(settings):
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51018)) as machine:
        owner = _add_signed_in_user(application, 50025)
        browser = _browser_client(application, owner)
        try:
            context, conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, owner
            )
            conversation_id = str(conversation["id"])
            proposed = _mcp(
                machine,
                str(turn["execution_id"]),
                capability,
                "tools/call",
                {
                    "name": "assistant.propose_action",
                    "arguments": {"action_type": "theme.set", "payload": {"theme": "dark"}},
                },
            )
            assert proposed.status_code == 200, proposed.text
            app = application.state.assistant
            event = next(
                item
                for item in app.storage.events_after(
                    int(owner["user_id"]), conversation_id, str(turn["id"]), after=0
                )
                if item["type"] == "proposed_action"
            )
            card = event["data"]
            app.clock = lambda: NOW + timedelta(minutes=10)
            detail = browser.get(f"/api/v1/assistant/conversations/{conversation_id}")
            assert detail.status_code == 200
            saved_action = next(
                action
                for action in detail.json()["actions"]
                if action["action_id"] == card["action_id"]
            )
            assert saved_action["availability"] == "expired"
            assert saved_action["proposal"]["confirmation_phrase"] is None
            app.storage.set_turn_status(
                int(owner["user_id"]),
                conversation_id,
                str(turn["id"]),
                status="completed",
                now=app.now(),
            )
            app.storage.close_execution(str(turn["execution_id"]), now=app.now())

            replay = browser.get(
                f"/api/v1/assistant/conversations/{conversation_id}/turns/{turn['id']}/events",
                params={"after": 0},
            )
            assert replay.status_code == 200
            assert card["confirmation_phrase"] not in replay.text

            rejected = browser.post(
                f"/api/v1/assistant/conversations/{conversation_id}/actions/{card['action_id']}/confirm",
                headers={"x-csrf-token": str(owner["csrf"])},
                json={
                    "action_version": 1,
                    "context": context,
                    "allow": True,
                    "confirmation_phrase": card["confirmation_phrase"],
                },
            )
            assert rejected.status_code == 409
        finally:
            browser.close()


def test_portfolio_actions_use_approved_quantity_snapshot_and_atomic_cas(settings, monkeypatch):
    """Use exact provider identity and repository transactions for holding changes."""

    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51011)) as machine:
        owner = _add_signed_in_user(application, 50015)
        browser = _browser_client(application, owner)
        try:
            lookup = application.state.assistant.forecast_service.lookup("SPY", 1)
            identity = lookup["items"][0]
            payload = {
                "symbol": identity["canonical_symbol"],
                "asset_type": identity["asset_type"],
                "provider": identity["provider"],
                "exchange": identity["exchange"],
                "quantity": 2.5,
            }

            def propose(action_type: str) -> tuple[dict[str, object], dict[str, object], str]:
                context, conversation, turn, _lease, capability = _conversation_and_running_turn(
                    browser, owner
                )
                action_payload = dict(payload)
                if action_type == "portfolio.remove":
                    action_payload.pop("quantity")
                result = _mcp(
                    machine,
                    str(turn["execution_id"]),
                    capability,
                    "tools/call",
                    {
                        "name": "assistant.propose_action",
                        "arguments": {"action_type": action_type, "payload": action_payload},
                    },
                )
                assert result.status_code == 200, result.text
                event = next(
                    item
                    for item in application.state.assistant.storage.events_after(
                        int(owner["user_id"]),
                        str(conversation["id"]),
                        str(turn["id"]),
                        after=0,
                        limit=20,
                    )
                    if item["type"] == "proposed_action"
                )
                app = application.state.assistant
                app.storage.set_turn_status(
                    int(owner["user_id"]),
                    str(conversation["id"]),
                    str(turn["id"]),
                    status="completed",
                    now=NOW,
                )
                app.storage.close_execution(str(turn["execution_id"]), now=NOW)
                return context, event["data"], str(conversation["id"])

            def confirm(context: dict[str, object], card: dict[str, object], conversation_id: str):
                return browser.post(
                    f"/api/v1/assistant/conversations/{conversation_id}/actions/{card['action_id']}/confirm",
                    headers={"x-csrf-token": str(owner["csrf"])},
                    json={
                        "action_version": 1,
                        "context": context,
                        "allow": True,
                        "confirmation_phrase": card["confirmation_phrase"],
                    },
                )

            context, add_card, conversation_id = propose("portfolio.add")
            assert add_card["title"] == "Add holding"
            assert {change["label"] for change in add_card["changes"]} >= {
                "Instrument",
                "Provider",
                "Exchange",
                "Quantity",
            }
            added = confirm(context, add_card, conversation_id)
            assert added.status_code == 200, added.text
            assert added.json()["status"] == "applied"
            items = application.state.assistant.repository.instrument_list_items(
                int(owner["user_id"]), "portfolio"
            )
            assert len(items) == 1 and items[0]["quantity"] == 2.5

            # The persisted preview names both the approved prior value and requested result.
            context, quantity_card, conversation_id = propose("portfolio.set_quantity")
            assert {change["label"]: change["after"] for change in quantity_card["changes"]}[
                "Current quantity"
            ] == "2.5"
            assert {change["label"]: change["after"] for change in quantity_card["changes"]}[
                "Quantity"
            ] == "2.5"
            app = application.state.assistant
            dispatch = app.dispatch_confirmed_action

            def concurrent_set_then_dispatch(
                user_id, action_type, action_payload, *, confirmed_by, authorization_check=None
            ):
                if action_type == "portfolio.set_quantity":
                    changed = app.repository.set_instrument_list_item_holding(
                        "portfolio",
                        owner_user_id=user_id,
                        provider=str(identity["provider"]),
                        canonical_symbol=str(identity["canonical_symbol"]),
                        asset_type=str(identity["asset_type"]),
                        quantity=7.0,
                        expected_quantity=2.5,
                    )
                    assert changed
                return dispatch(
                    user_id,
                    action_type,
                    action_payload,
                    confirmed_by=confirmed_by,
                    authorization_check=authorization_check,
                )

            monkeypatch.setattr(app, "dispatch_confirmed_action", concurrent_set_then_dispatch)
            raced_set = confirm(context, quantity_card, conversation_id)
            assert raced_set.status_code == 409
            set_receipt = app.storage.get_action_receipt(
                int(owner["user_id"]), str(quantity_card["action_id"])
            )
            assert set_receipt["outcome"] == "unknown"
            items = app.repository.instrument_list_items(int(owner["user_id"]), "portfolio")
            assert len(items) == 1 and items[0]["quantity"] == 7.0
            monkeypatch.setattr(app, "dispatch_confirmed_action", dispatch)

            # A second matching proposal cannot replay or silently overwrite the current item.
            context, repeated_card, conversation_id = propose("portfolio.add")
            repeated = confirm(context, repeated_card, conversation_id)
            assert repeated.status_code == 409, repeated.text
            items = application.state.assistant.repository.instrument_list_items(
                int(owner["user_id"]), "portfolio"
            )
            assert len(items) == 1 and items[0]["quantity"] == 7.0

            context, update_card, conversation_id = propose("portfolio.set_quantity")
            updated = confirm(context, update_card, conversation_id)
            assert updated.status_code == 200, updated.text
            assert updated.json()["status"] == "applied"
            items = application.state.assistant.repository.instrument_list_items(
                int(owner["user_id"]), "portfolio"
            )
            assert len(items) == 1 and items[0]["quantity"] == 2.5

            context, remove_card, conversation_id = propose("portfolio.remove")
            app = application.state.assistant
            dispatch = app.dispatch_confirmed_action

            def concurrent_remove_then_dispatch(
                user_id, action_type, action_payload, *, confirmed_by, authorization_check=None
            ):
                if action_type == "portfolio.remove":
                    changed = app.repository.set_instrument_list_item_holding(
                        "portfolio",
                        owner_user_id=user_id,
                        provider=str(identity["provider"]),
                        canonical_symbol=str(identity["canonical_symbol"]),
                        asset_type=str(identity["asset_type"]),
                        quantity=11.0,
                        expected_quantity=2.5,
                    )
                    assert changed
                return dispatch(
                    user_id,
                    action_type,
                    action_payload,
                    confirmed_by=confirmed_by,
                    authorization_check=authorization_check,
                )

            monkeypatch.setattr(app, "dispatch_confirmed_action", concurrent_remove_then_dispatch)
            raced_remove = confirm(context, remove_card, conversation_id)
            assert raced_remove.status_code == 409
            remove_receipt = app.storage.get_action_receipt(
                int(owner["user_id"]), str(remove_card["action_id"])
            )
            assert remove_receipt["outcome"] == "unknown"
            items = app.repository.instrument_list_items(int(owner["user_id"]), "portfolio")
            assert len(items) == 1 and items[0]["quantity"] == 11.0

            monkeypatch.setattr(app, "dispatch_confirmed_action", dispatch)
            context, remove_card, conversation_id = propose("portfolio.remove")
            removed = confirm(context, remove_card, conversation_id)
            assert removed.status_code == 200, removed.text
            assert removed.json()["status"] == "applied"
            assert not application.state.assistant.repository.instrument_list_items(
                int(owner["user_id"]), "portfolio"
            )
        finally:
            browser.close()


def test_all_twenty_three_action_types_execute_or_handoff_with_two_owner_guards(settings):
    """Exercise each advertised proposal against populated owner data and real confirmation."""

    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    # The checked-in fixture's latest 5-minute bars are historical. Keep user/session and
    # assistant lease clocks at NOW while using its explicit fixture clock for forecasts.
    application.state.assistant.forecast_service.clock = lambda: FORECAST_NOW
    with TestClient(application, client=("127.0.0.1", 51024)) as machine:
        owner = _add_signed_in_user(application, 50030, role="admin")
        member = _add_signed_in_user(application, 50031)
        owner_browser = _browser_client(application, owner)
        member_browser = _browser_client(application, member)
        try:
            repository = application.state.repository
            factor = repository.auth_get_totp_factor(int(owner["user_id"]))
            assert factor is not None
            assert repository.auth_set_session_mfa(
                str(owner["token_hash"]),
                "totp",
                NOW.isoformat(),
                int(factor["id"]),
            )
            initial_forecast = owner_browser.post(
                "/api/v1/forecasts",
                json={"symbol": "ACDC", "asset_type": "stock"},
                headers={"x-csrf-token": str(owner["csrf"])},
            )
            assert initial_forecast.status_code == 201, initial_forecast.text
            saved_event = initial_forecast.json()["event"]
            saved_result = initial_forecast.json()["results"][0]
            event_id = int(saved_event["id"])
            result_id = int(saved_result["id"])
            source = application.state.assistant.repository.reconstruction(
                int(owner["user_id"]), event_id
            )
            assert source is not None and isinstance(source.get("event"), dict)

            instrument = application.state.assistant.forecast_service.lookup("ACDC", 1)["items"][0]
            exact_instrument = {
                key: instrument[key]
                for key in ("canonical_symbol", "asset_type", "provider", "exchange")
            }
            instrument_payload = {
                "symbol": exact_instrument["canonical_symbol"],
                "asset_type": exact_instrument["asset_type"],
                "provider": exact_instrument["provider"],
                "exchange": exact_instrument["exchange"],
            }
            outcome_at = datetime.fromisoformat(str(saved_result["target_timestamp"])) + timedelta(
                seconds=1
            )
            actions: list[tuple[str, dict[str, object]]] = [
                ("watchlist.add", instrument_payload),
                ("watchlist.remove", instrument_payload),
                ("portfolio.add", {**instrument_payload, "quantity": 1.5}),
                ("portfolio.set_quantity", {**instrument_payload, "quantity": 2.5}),
                ("portfolio.remove", instrument_payload),
                ("forecast.create", instrument_payload),
                ("forecast.create", instrument_payload),
                ("forecast.create", {**instrument_payload, "interval": "5min"}),
                ("forecast.create", {**instrument_payload, "interval": "daily"}),
                ("forecast.create", {**instrument_payload, "interval": "daily"}),
                ("forecast.create", {**instrument_payload, "interval": "weekly"}),
                ("forecast.create", {**instrument_payload, "interval": "monthly"}),
                ("forecast.create", {**instrument_payload, "interval": "quarterly"}),
                (
                    "outcome.record",
                    {
                        "result_id": result_id,
                        "observed_at": outcome_at.isoformat(),
                        "state": "unavailable",
                    },
                ),
                (
                    "reconstruction.run",
                    {"event_id": event_id, "cutoff": FORECAST_NOW.isoformat()},
                ),
                ("invitation.create", {}),
                ("backup.create", {}),
                ("restore.promote", {}),
                ("provider.settings", {}),
                ("account.sessions.manage", {}),
                ("history.export.csv", {}),
                ("history.export.json", {}),
                ("theme.set", {"theme": "dark"}),
                (
                    "filters.apply",
                    {"query": "ACDC", "status": "successful", "page_size": "20"},
                ),
                ("notes.set", instrument_payload),
                ("notes.clear", instrument_payload),
                ("alerts.add", {**instrument_payload, "threshold": 123.45}),
                ("alerts.remove", instrument_payload),
                (
                    "forecast.reopen",
                    {
                        "event_id": event_id,
                        "event_version": application.state.assistant._digest(source["event"]),
                    },
                ),
                ("market.open", instrument_payload),
                (
                    "market.filters.apply",
                    {
                        "query": "ACDC",
                        "exchange": instrument_payload["exchange"],
                        "asset_type": instrument_payload["asset_type"],
                        "sort": "symbol:asc",
                        "min_price": "",
                        "max_price": "",
                        "min_change": "",
                        "max_change": "",
                        "min_volume": "",
                        "quote_field": "",
                        "quote_min": "",
                        "quote_max": "",
                    },
                ),
                ("market.chart_range.set", {**instrument_payload, "range": "3mo"}),
                ("market.columns.set", {"show_all_columns": True}),
                ("market.refresh", {"kind": "quotes"}),
            ]
            action_tool = next(
                item
                for item in AssistantToolGateway.list_tools()
                if item["name"] == "assistant.propose_action"
            )
            advertised_types = set(action_tool["inputSchema"]["properties"]["action_type"]["enum"])
            assert advertised_types == set(_ACTION_TYPES)
            assert {action_type for action_type, _payload in actions} == advertised_types
            projected_action_schema = project_gemini_tool_schema(action_tool["inputSchema"])
            assert isinstance(projected_action_schema, dict)
            projected_filter_action = next(
                branch
                for branch in projected_action_schema["anyOf"]
                if branch["properties"]["action_type"]["enum"] == ["filters.apply"]
            )
            assert projected_filter_action["properties"]["payload"]["properties"]["page_size"] == {
                "type": "string",
                "enum": ["10", "20", "50"],
            }

            applied_types = {
                "watchlist.add",
                "watchlist.remove",
                "portfolio.add",
                "portfolio.set_quantity",
                "portfolio.remove",
                "forecast.create",
                "outcome.record",
                "reconstruction.run",
            }
            outcomes: dict[str, str] = {}

            def propose(
                action_type: str,
                payload: dict[str, object],
                *,
                route: str = "/overview",
                context_instrument: dict[str, str] | None = None,
            ):
                context, conversation, turn, _lease, capability = _conversation_and_running_turn(
                    owner_browser, owner, route=route, instrument=context_instrument
                )
                tool_call = _mcp(
                    machine,
                    str(turn["execution_id"]),
                    capability,
                    "tools/call",
                    {
                        "name": "assistant.propose_action",
                        "arguments": {"action_type": action_type, "payload": payload},
                    },
                )
                assert tool_call.status_code == 200, tool_call.text
                app = application.state.assistant
                cards = [
                    event["data"]
                    for event in app.storage.events_after(
                        int(owner["user_id"]),
                        str(conversation["id"]),
                        str(turn["id"]),
                        after=0,
                        limit=20,
                    )
                    if event["type"] == "proposed_action"
                ]
                assert len(cards) == 1
                card = cards[0]
                assert card["action_type"] == action_type
                app.storage.set_turn_status(
                    int(owner["user_id"]),
                    str(conversation["id"]),
                    str(turn["id"]),
                    status="completed",
                    now=NOW,
                )
                app.storage.close_execution(str(turn["execution_id"]), now=NOW)
                return context, str(conversation["id"]), card

            def confirm(identity, browser, conversation_id: str, context, card):
                return browser.post(
                    f"/api/v1/assistant/conversations/{conversation_id}/actions/{card['action_id']}/confirm",
                    headers={"x-csrf-token": str(identity["csrf"])},
                    json={
                        "action_version": card["version"],
                        "context": context,
                        "allow": True,
                        "confirmation_phrase": card["confirmation_phrase"],
                    },
                )

            for index, (action_type, payload) in enumerate(actions):
                route = "/overview"
                context_instrument = None
                if action_type == "filters.apply":
                    route = "/"
                elif action_type in {
                    "market.filters.apply",
                    "market.chart_range.set",
                    "market.columns.set",
                    "market.refresh",
                }:
                    route = "/tools/markets"
                    if action_type == "market.chart_range.set":
                        context_instrument = instrument_payload
                context, conversation_id, card = propose(
                    action_type,
                    payload,
                    route=route,
                    context_instrument=context_instrument,
                )
                if action_type == "market.filters.apply":
                    assert {item["label"]: item["after"] for item in card["changes"]} == {
                        "Search query": "ACDC",
                        "Exchange": instrument_payload["exchange"],
                        "Asset type": instrument_payload["asset_type"],
                        "Sort": "symbol:asc",
                        "Minimum price": "(empty; clear this control)",
                        "Maximum price": "(empty; clear this control)",
                        "Minimum percent change": "(empty; clear this control)",
                        "Maximum percent change": "(empty; clear this control)",
                        "Minimum volume": "(empty; clear this control)",
                        "Additional quote metric": "(empty; clear this control)",
                        "Metric minimum": "(empty; clear this control)",
                        "Metric maximum": "(empty; clear this control)",
                    }
                elif action_type == "filters.apply":
                    assert {item["label"]: item["after"] for item in card["changes"]} == {
                        "Search query": "ACDC",
                        "Asset type": "(empty; clear this control)",
                        "History status": "successful",
                        "Analysis type": "(empty; clear this control)",
                        "Submitted from": "(empty; clear this control)",
                        "Submitted through": "(empty; clear this control)",
                        "Model name or version": "(empty; clear this control)",
                        "Forecast horizon": "(empty; clear this control)",
                        "Sort": "event_id:desc",
                        "Rows per page": "20",
                    }
                elif action_type == "market.chart_range.set":
                    assert {item["label"]: item["after"] for item in card["changes"]} == {
                        "Instrument": instrument_payload["symbol"],
                        "Asset type": instrument_payload["asset_type"],
                        "Provider": instrument_payload["provider"],
                        "Exchange": instrument_payload["exchange"],
                        "Chart range": "3mo",
                    }
                elif action_type == "market.columns.set":
                    assert card["changes"] == [{"label": "Show all quote columns", "after": "true"}]
                elif action_type == "market.refresh":
                    assert card["changes"] == [{"label": "Refresh target", "after": "quotes"}]
                if index == 0:
                    member_context = member_browser.get(
                        "/api/v1/assistant/context", params={"route": "/overview"}
                    ).json()["context"]
                    forged_owner_confirmation = member_browser.post(
                        f"/api/v1/assistant/conversations/{conversation_id}/actions/{card['action_id']}/confirm",
                        headers={"x-csrf-token": str(member["csrf"])},
                        json={
                            "action_version": card["version"],
                            "context": member_context,
                            "allow": True,
                            "confirmation_phrase": card["confirmation_phrase"],
                        },
                    )
                    assert forged_owner_confirmation.status_code == 404
                    assert (
                        application.state.assistant.storage.get_action_receipt(
                            int(owner["user_id"]), str(card["action_id"])
                        )
                        is None
                    )

                if action_type == "filters.apply":
                    stored_action = application.state.assistant.storage.get_action(
                        int(owner["user_id"]), str(card["action_id"])
                    )
                    assert type(stored_action["payload"]["page_size"]) is int
                    assert stored_action["payload"]["page_size"] == 20

                if action_type == "forecast.reopen":
                    forecast_search = application.state.assistant.forecast_service.search

                    def reject_provider_replay(*_args, **_kwargs):
                        raise AssertionError("saved forecast reopen must not call the provider")

                    application.state.assistant.forecast_service.search = reject_provider_replay
                    try:
                        response = confirm(owner, owner_browser, conversation_id, context, card)
                    finally:
                        application.state.assistant.forecast_service.search = forecast_search
                else:
                    response = confirm(owner, owner_browser, conversation_id, context, card)
                assert response.status_code == 200, (action_type, response.text)
                result = response.json()
                expected_status = "applied" if action_type in applied_types else "handed_off"
                assert result["status"] == expected_status, (action_type, result)
                outcomes[action_type] = result["status"]

                if action_type == "history.export.csv":
                    csv_download = owner_browser.get(result["destination"])
                    assert csv_download.status_code == 200
                    assert "text/csv" in csv_download.headers["content-type"]
                    other_download = member_browser.get(result["destination"])
                    assert other_download.status_code == 200
                    assert "ACDC" not in other_download.text
                elif action_type == "history.export.json":
                    json_download = owner_browser.get(result["destination"])
                    assert json_download.status_code == 200
                    assert len(json_download.json()["records"]) >= 1
                    other_download = member_browser.get(result["destination"])
                    assert other_download.status_code == 200
                    assert other_download.json()["records"] == []
                elif action_type == "invitation.create":
                    assert result["destination"] == "/admin#invitations"
                elif action_type == "backup.create":
                    assert result["destination"] == "/admin#backups"
                elif action_type == "restore.promote":
                    assert result["destination"] == "/admin#restore"
                elif action_type == "provider.settings":
                    assert result["destination"] == "/admin#assistant-providers"
                elif action_type == "account.sessions.manage":
                    assert result["destination"] == "/account#sessions"
                elif action_type in {
                    "theme.set",
                    "notes.set",
                    "notes.clear",
                    "alerts.add",
                    "alerts.remove",
                }:
                    assert isinstance(result.get("browser_action"), dict)
                    assert result["browser_action"]["type"] == action_type
                elif action_type == "filters.apply":
                    browser_action = result.get("browser_action")
                    assert isinstance(browser_action, dict)
                    assert browser_action["type"] == action_type
                    assert browser_action["destination"] == {
                        "kind": "current-page",
                        "route": "/",
                    }
                    assert browser_action["payload"] == {
                        "query": "ACDC",
                        "asset_type": "",
                        "status": "successful",
                        "analysis_kind": "",
                        "submitted_from": "",
                        "submitted_to": "",
                        "model": "",
                        "horizon": "",
                        "sort": "event_id:desc",
                        "page_size": 20,
                    }
                    assert result["destination"] == "/#history-heading"
                elif action_type in {
                    "market.filters.apply",
                    "market.chart_range.set",
                    "market.columns.set",
                    "market.refresh",
                }:
                    browser_action = result.get("browser_action")
                    assert isinstance(browser_action, dict)
                    assert browser_action["type"] == action_type
                    assert browser_action["destination"] == {
                        "kind": "current-page",
                        "route": "/tools/markets",
                    }
                    if action_type == "market.chart_range.set":
                        assert browser_action["payload"] == {
                            **instrument_payload,
                            "range": "3mo",
                        }
                    elif action_type == "market.filters.apply":
                        assert browser_action["payload"] == payload
                    elif action_type == "market.columns.set":
                        assert browser_action["payload"] == {"show_all_columns": True}
                    elif action_type == "market.refresh":
                        assert browser_action["payload"] == {"kind": "quotes"}
                elif action_type == "forecast.reopen":
                    assert result["destination"] == f"/?event_id={event_id}#result-section"
                elif action_type == "market.open":
                    assert result["destination"].startswith("/tools/markets?")

                replay = confirm(owner, owner_browser, conversation_id, context, card)
                assert replay.status_code == 409, (action_type, replay.text)

            assert outcomes.keys() == {action_type for action_type, _payload in actions}
            assert set(outcomes.values()) == {"applied", "handed_off"}
            owner_portfolio = repository.instrument_list_items(int(owner["user_id"]), "portfolio")
            member_portfolio = repository.instrument_list_items(int(member["user_id"]), "portfolio")
            assert owner_portfolio == []
            assert member_portfolio == []
            assert (
                len(
                    repository.outcome_history(
                        int(owner["user_id"]), result_id, page=1, page_size=10
                    )["items"]
                )
                == 1
            )
            assert (
                repository.history(
                    owner_user_id=int(owner["user_id"]),
                    analysis_kind="fresh_historical_reconstruction",
                    include_analysis=True,
                )["total"]
                == 1
            )
            submitted_events = repository.history(
                owner_user_id=int(owner["user_id"]),
                analysis_kind="submitted_forecast",
                include_analysis=True,
                page_size=100,
            )["items"]
            submitted_intervals = [
                repository.reconstruction(int(owner["user_id"]), int(item["id"]))["input"].get(
                    "requested_interval"
                )
                for item in submitted_events
                if int(item["id"]) > event_id
            ]
            assert submitted_intervals.count(None) >= 2
            assert all(
                submitted_intervals.count(interval) >= 1
                for interval in ("5min", "daily", "weekly", "monthly", "quarterly")
            )

            # A member may not attach an owner's saved result to their own proposal.
            member_context, member_conversation, member_turn, _lease, member_capability = (
                _conversation_and_running_turn(member_browser, member)
            )
            forged = _mcp(
                machine,
                str(member_turn["execution_id"]),
                member_capability,
                "tools/call",
                {
                    "name": "assistant.propose_action",
                    "arguments": {
                        "action_type": "outcome.record",
                        "payload": {
                            "result_id": result_id,
                            "observed_at": outcome_at.isoformat(),
                            "state": "unavailable",
                        },
                    },
                },
            )
            assert forged.status_code == 200, forged.text
            member_action = next(
                event["data"]
                for event in application.state.assistant.storage.events_after(
                    int(member["user_id"]),
                    str(member_conversation["id"]),
                    str(member_turn["id"]),
                    after=0,
                )
                if event["type"] == "proposed_action"
            )
            application.state.assistant.storage.set_turn_status(
                int(member["user_id"]),
                str(member_conversation["id"]),
                str(member_turn["id"]),
                status="completed",
                now=NOW,
            )
            application.state.assistant.storage.close_execution(
                str(member_turn["execution_id"]), now=NOW
            )
            denied_owner_target = member_browser.post(
                f"/api/v1/assistant/conversations/{member_conversation['id']}/actions/{member_action['action_id']}/confirm",
                headers={"x-csrf-token": str(member["csrf"])},
                json={
                    "action_version": member_action["version"],
                    "context": member_context,
                    "allow": True,
                    "confirmation_phrase": member_action["confirmation_phrase"],
                },
            )
            assert denied_owner_target.status_code == 404
            assert (
                application.state.assistant.storage.get_action_receipt(
                    int(member["user_id"]), str(member_action["action_id"])
                )
                is None
            )

            # Expiry is checked before reservation: no dispatch or receipt is created.
            expired_context, expired_conversation, expired_card = propose(
                "theme.set", {"theme": "light"}
            )
            application.state.assistant.clock = lambda: NOW + timedelta(minutes=6)
            expired = confirm(
                owner,
                owner_browser,
                expired_conversation,
                expired_context,
                expired_card,
            )
            assert expired.status_code == 409
            assert (
                application.state.assistant.storage.get_action_receipt(
                    int(owner["user_id"]), str(expired_card["action_id"])
                )
                is None
            )
        finally:
            owner_browser.close()
            member_browser.close()


def test_startup_timeout_keeps_authenticated_workspace_available(settings, monkeypatch):
    import asyncio

    from stock_probs.assistant import service as assistant_service_module

    class SlowStartupRuntime(FakeRuntime):
        async def start(self):
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                # Simulate a worker cleanup that takes longer than the startup deadline.
                await asyncio.sleep(0.02)

        def status(self):
            return {"status": "unavailable", "message": None}

    monkeypatch.setattr(assistant_service_module, "ASSISTANT_RUNTIME_START_SECONDS", 0.001)
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=SlowStartupRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51006)):
        identity = _add_signed_in_user(application, 50009)
        browser = _browser_client(application, identity)
        try:
            status = browser.get("/api/v1/assistant/status")
            history = browser.get("/api/v1/history")
            assert status.status_code == 200
            assert status.json()["available"] is False
            assert status.json()["worker"]["status"] == "unavailable"
            assert history.status_code == 200
        finally:
            browser.close()


def test_operator_kill_keeps_app_ready_but_denies_new_assistant_turns(settings):
    """A same-container kill disables the assistant surface without taking down the app."""

    class OperatorDisabledRuntime(FakeRuntime):
        operator_disabled = False

        def status(self):
            status = "disabled" if self.operator_disabled else "ready"
            return {"status": status, "message": None}

    runtime = OperatorDisabledRuntime()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=runtime,
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51011)) as machine:
        identity = _add_signed_in_user(application, 50014)
        browser = _browser_client(application, identity)
        try:
            context_response = browser.get(
                "/api/v1/assistant/context", params={"route": "/overview"}
            )
            assert context_response.status_code == 200
            page_context = context_response.json()["context"]
            headers = {"x-csrf-token": str(identity["csrf"])}
            conversation_response = browser.post(
                "/api/v1/assistant/conversations",
                json={"context": page_context},
                headers=headers,
            )
            assert conversation_response.status_code == 201
            conversation_id = conversation_response.json()["conversation"]["conversation"]["id"]
            policy = application.state.assistant.policy(MODEL.model_id)

            runtime.operator_disabled = True

            readiness = machine.get("/api/v1/readiness")
            status = browser.get("/api/v1/assistant/status")
            new_turn = browser.post(
                f"/api/v1/assistant/conversations/{conversation_id}/turns",
                json={
                    "prompt": "This turn must not start.",
                    "model_id": MODEL.model_id,
                    "policy_version": policy.policy_version,
                    "context": page_context,
                    "context_preview_accepted": False,
                },
                headers=headers,
            )

            assert readiness.status_code == 200
            assert readiness.json()["assistant"] == {"enabled": False, "status": "disabled"}
            assert status.status_code == 200
            assert status.json()["enabled"] is False
            assert status.json()["available"] is False
            assert status.json()["worker"]["status"] == "disabled"
            assert new_turn.status_code == 503
            assert new_turn.json()["error"]["code"] == "assistant_worker_unavailable"
            detail = application.state.assistant.storage.get_conversation(
                int(identity["user_id"]), conversation_id
            )
            assert detail["turns"] == []
        finally:
            browser.close()


def test_runtime_retries_from_status_poll_and_recovers_after_startup_failure(settings, monkeypatch):
    from stock_probs.assistant import service as assistant_service_module

    class RecoveringRuntime(FakeRuntime):
        def __init__(self):
            self.calls = 0
            self.ready = False

        async def start(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("worker was temporarily unavailable")
            self.ready = True

        def status(self):
            return {"status": "ready" if self.ready else "unavailable", "message": None}

    monkeypatch.setattr(assistant_service_module, "ASSISTANT_RUNTIME_START_SECONDS", 0.01)
    monkeypatch.setattr(assistant_service_module, "ASSISTANT_RUNTIME_RETRY_SECONDS", 0.0)
    runtime = RecoveringRuntime()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=runtime,
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51009)):
        identity = _add_signed_in_user(application, 50012)
        browser = _browser_client(application, identity)
        try:
            after = browser.get("/api/v1/assistant/status")
            assert after.status_code == 200
            assert runtime.calls == 2
            assert after.json()["available"] is True
            assert browser.get("/api/v1/history").status_code == 200
        finally:
            browser.close()


def test_committed_holding_with_interrupted_receipt_is_unknown_after_restart(settings):
    import asyncio

    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51007)):
        identity = _add_signed_in_user(application, 50010)
        browser = _browser_client(application, identity)
        try:
            context, conversation, turn, lease, _capability = _conversation_and_running_turn(
                browser, identity
            )
            app = application.state.assistant
            lookup = app.forecast_service.lookup("SPY", 1)
            identity_record = lookup["items"][0]
            app.repository.add_instrument_list_item(
                "portfolio",
                owner_user_id=int(identity["user_id"]),
                provider=str(identity_record["provider"]),
                canonical_symbol=str(identity_record["canonical_symbol"]),
                asset_type=str(identity_record["asset_type"]),
                exchange=str(identity_record["exchange"]),
                display_name=str(identity_record["display_name"]),
                added_at=NOW,
                quantity=1.0,
            )
            created = app.storage.create_action(
                int(identity["user_id"]),
                str(conversation["id"]),
                str(turn["id"]),
                action_type="portfolio.set_quantity",
                payload={
                    "symbol": str(identity_record["canonical_symbol"]),
                    "asset_type": str(identity_record["asset_type"]),
                    "provider": str(identity_record["provider"]),
                    "exchange": str(identity_record["exchange"]),
                    "quantity": 4.0,
                    "_approved_current_quantity": 1.0,
                },
                action_version=1,
                session_id=str(identity["session_id"]),
                context_version=str(context["context_version"]),
                execution_id=str(turn["execution_id"]),
                confirmation_phrase="CONFIRM ignored-input",
                now=NOW,
                expires_at=NOW + timedelta(seconds=60),
            )
            app.storage.claim_action(
                int(identity["user_id"]),
                str(created["id"]),
                action_version=1,
                confirmation_phrase=str(created["confirmation_phrase"]),
                session_id=str(identity["session_id"]),
                context_version=str(context["context_version"]),
                now=NOW,
            )
            confirmed_by = application.state.auth.authenticate(
                str(identity["token"]), application.state.assistant.now()
            )
            outcome, _detail = app.dispatch_confirmed_action(
                int(identity["user_id"]),
                "portfolio.set_quantity",
                created["payload"],
                confirmed_by=confirmed_by,
            )
            assert outcome == "applied"
            saved = app.repository.instrument_list_items(int(identity["user_id"]), "portfolio")[0]
            assert saved["quantity"] == 4.0

            # A process restart finds the reserved receipt and reports unknown, never replaying.
            app._started = False
            asyncio.run(app.start())
            detail = app.storage.get_conversation(
                int(identity["user_id"]),
                str(conversation["id"]),
                message_page=1,
                message_page_size=50,
            )
            receipt = next(
                action for action in detail["actions"] if action["action_id"] == created["id"]
            )
            assert receipt["status"] == "unknown"
            assert receipt["receipt"]["outcome"] == "unknown"
            assert "outcome is unknown" in receipt["receipt"]["message"].lower()
            assert app.storage.reconcile_interrupted_actions(now=NOW + timedelta(seconds=1)) == 0
            assert (
                app.repository.instrument_list_items(int(identity["user_id"]), "portfolio")[0][
                    "quantity"
                ]
                == 4.0
            )
        finally:
            browser.close()


def test_turn_timeout_is_hard_bounded_when_runtime_suppresses_cancellation(settings, monkeypatch):
    import asyncio

    from stock_probs.assistant import service as assistant_service_module

    class DelayedCancelRuntime(FakeRuntime):
        def __init__(self):
            self.started = asyncio.Event()
            self.cancellation_caught = asyncio.Event()
            self.cancel_requested = asyncio.Event()
            self.release = asyncio.Event()
            self.finished = asyncio.Event()
            self.worker_task = None

        async def run_turn(self, *, context, prompt, emit):
            del context, prompt, emit
            self.worker_task = asyncio.current_task()
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancellation_caught.set()
                await self.release.wait()
                return AssistantTurnResult(status="completed")
            finally:
                self.finished.set()

        async def cancel_execution(self, execution_id):
            del execution_id
            self.cancel_requested.set()
            await self.cancellation_caught.wait()

    monkeypatch.setattr(assistant_service_module, "ASSISTANT_TURN_SECONDS", 0.01)
    runtime = DelayedCancelRuntime()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=runtime,
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51008)):
        identity = _add_signed_in_user(application, 50011)
        browser = _browser_client(application, identity)
        try:
            context, conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, identity
            )
            auth_context = application.state.auth.authenticate(
                str(identity["token"]), application.state.assistant.now()
            )
            app = application.state.assistant

            async def exercise_timeout() -> bool:
                turn_task = asyncio.create_task(
                    app._run_turn(
                        context=auth_context,
                        conversation_id=str(conversation["id"]),
                        turn_id=str(turn["id"]),
                        execution_id=str(turn["execution_id"]),
                        capability=capability,
                        model_id=MODEL.model_id,
                        policy=MODEL,
                        prompt="Run a bounded response.",
                        canonical_context=context,
                    )
                )
                returned_while_suppressed = False
                try:
                    done, _ = await asyncio.wait({turn_task}, timeout=5.0)
                    returned_while_suppressed = (
                        turn_task in done
                        and runtime.started.is_set()
                        and runtime.cancel_requested.is_set()
                        and runtime.cancellation_caught.is_set()
                        and not runtime.finished.is_set()
                    )
                    if turn_task in done:
                        await turn_task
                finally:
                    runtime.release.set()
                    worker_task = runtime.worker_task
                    if worker_task is not None and not worker_task.done():
                        worker_task.cancel()
                        await asyncio.gather(worker_task, return_exceptions=True)
                    if not turn_task.done():
                        await asyncio.wait_for(turn_task, timeout=5.0)
                assert runtime.finished.is_set()
                return returned_while_suppressed

            assert asyncio.run(exercise_timeout())
            saved = app.storage.get_turn(
                int(identity["user_id"]), str(conversation["id"]), str(turn["id"])
            )
            assert saved["status"] == "timed_out"
            assert app.storage.execution_lease(str(turn["execution_id"]))["status"] != "active"
            assert str(turn["execution_id"]) not in app._emitters
        finally:
            browser.close()


def test_internal_provider_proxy_uses_db_model_and_closes_on_bad_capability(settings):
    providers = FakeProviders()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    with TestClient(application, client=("127.0.0.1", 51001)) as owner_client:
        owner = _add_signed_in_user(application, 50003)
        browser = _browser_client(application, owner)
        try:
            context, conversation, turn, _lease, raw_capability = _conversation_and_running_turn(
                browser, owner
            )
            execution_id = str(turn["execution_id"])
            body = {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "Summarize this saved page."}],
                "stream": True,
            }
            headers = {
                "Authorization": f"Bearer {raw_capability}",
                "session-id": "ses_native_session_fixture_01",
                "user-agent": "ordinary-browser-agent",
                "x-opencode-client": "unrelated-client",
            }
            response = owner_client.post(
                f"/api/v1/assistant/internal/provider/{execution_id}/chat/completions",
                headers=headers,
                json=body,
            )
            assert response.status_code == 200, response.text
            assert response.headers["content-type"].startswith("text/event-stream")
            assert b"[DONE]" in response.content
            assert providers.calls[0][0:2] == (MODEL.provider_id, MODEL.model_id)
            assert providers.calls[0][2]["model"] == "assistant-selected"
            assert providers.calls[0][2]["messages"] == body["messages"]
            call_context = providers.call_contexts[0]
            assert call_context["owner_id"] == owner["user_id"]
            assert call_context["app_session_id"] == owner["session_id"]
            assert call_context["native_session_id"] == "ses_native_session_fixture_01"
            assert "native_user_agent" not in call_context
            assert "native_client" not in call_context
            assert callable(call_context["authorization_check"])
            assert call_context["authorization_check"]() is True

            rejected = owner_client.post(
                f"/api/v1/assistant/internal/provider/{execution_id}/chat/completions",
                headers={"Authorization": "Bearer " + "x" * 48},
                json=body,
            )
            assert rejected.status_code == 404
            assert len(providers.calls) == 1

            injection = owner_client.post(
                f"/api/v1/assistant/internal/provider/{execution_id}/chat/completions",
                headers=headers,
                json={**body, "model": "https://attacker.invalid/model"},
            )
            assert injection.status_code == 422
            assert len(providers.calls) == 1
        finally:
            browser.close()


@pytest.mark.parametrize("route_kind", ("chat", "native"), ids=("chat", "native"))
@pytest.mark.parametrize("status_code", (401, 403))
def test_internal_provider_proxy_returns_initial_upstream_auth_status_before_stream(
    settings, route_kind: str, status_code: int
) -> None:
    class Runtime(FakeRuntime):
        def __init__(self) -> None:
            super().__init__()
            self.starts = 0
            self.failures: list[tuple[object, ...]] = []
            self.ends: list[tuple[object, ...]] = []

        def _record_provider_stream_start(self, *_args: object) -> int:
            self.starts += 1
            return 1

        def _record_provider_stream_failure(self, *args: object) -> None:
            self.failures.append(args)

        def _record_provider_stream_end(self, *args: object) -> None:
            self.ends.append(args)

    class NativeProviders(FakeProviders):
        def __init__(self) -> None:
            super().__init__()
            self.closed = False

        async def _failure_stream(self):
            try:
                raise net.PublicHTTPError(
                    "provider_upstream_unavailable",
                    status_code=status_code,
                    content_type_class="json" if status_code == 403 else None,
                    cf_mitigated_class="absent" if status_code == 403 else None,
                )
                yield b"unreachable"
            finally:
                self.closed = True

        async def proxy_native_stream(self, provider_id, model_id, body, **context):
            del provider_id, model_id, body, context
            async for chunk in self._failure_stream():
                yield chunk

        async def proxy_chat_completion(self, provider_id, model_id, body, **context):
            del provider_id, model_id, body, context
            async for chunk in self._failure_stream():
                yield chunk

    runtime = Runtime()
    providers = NativeProviders()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=runtime,
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    with TestClient(application, client=("127.0.0.1", 51078)) as machine:
        owner = _add_signed_in_user(application, 50078)
        browser = _browser_client(application, owner)
        try:
            _context, _conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, owner
            )
            path = (
                f"/api/v1/assistant/internal/provider/{turn['execution_id']}/v1/responses"
                if route_kind == "native"
                else f"/api/v1/assistant/internal/provider/{turn['execution_id']}/chat/completions"
            )
            response = machine.post(
                path,
                headers={
                    "Authorization": f"Bearer {capability}",
                    "session-id": "ses_initial_auth_status_fixture_01",
                },
                json=(
                    {
                        "model": "assistant-selected",
                        "stream": True,
                        "messages": [{"role": "user", "content": "synthetic"}],
                    }
                    if route_kind == "chat"
                    else {"model": "assistant-selected", "stream": True, "input": "synthetic"}
                ),
            )
            assert response.status_code == status_code
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["content-type"].startswith("application/json")
            assert response.json() == {
                "error": {
                    "code": "provider_unavailable",
                    "message": "The selected model provider is unavailable.",
                }
            }
            assert "provider_upstream_unavailable" not in response.text
            assert "synthetic-private" not in response.text
            assert providers.closed
            assert runtime.starts == 1
            assert len(runtime.failures) == 1
            assert len(runtime.ends) == 1
        finally:
            browser.close()


def test_internal_provider_proxy_replays_first_chunk_once_and_records_one_timing_row(settings):
    class Runtime(FakeRuntime):
        def __init__(self) -> None:
            super().__init__()
            self.starts = 0
            self.first_chunks = 0
            self.yields: list[int] = []
            self.failures: list[tuple[object, ...]] = []
            self.ends: list[tuple[object, ...]] = []

        def _record_provider_stream_start(self, *_args: object) -> int:
            self.starts += 1
            return 1

        def _record_provider_first_sanitized_chunk(self, *_args: object) -> None:
            self.first_chunks += 1

        def _record_provider_sanitized_yield(
            self, _execution_id: str, _owner_id: int, _ordinal: int, size: int
        ) -> None:
            self.yields.append(size)

        def _record_provider_stream_failure(self, *args: object) -> None:
            self.failures.append(args)

        def _record_provider_stream_end(self, *args: object) -> None:
            self.ends.append(args)

    class NativeProviders(FakeProviders):
        def __init__(self) -> None:
            super().__init__()
            self.yielded: list[bytes] = []
            self.closed = False

        async def proxy_chat_completion(self, provider_id, model_id, body, **context):
            del provider_id, model_id, body, context
            try:
                for chunk in (b"data: first\n\n", b"data: second\n\n"):
                    self.yielded.append(chunk)
                    yield chunk
            finally:
                self.closed = True

    runtime = Runtime()
    providers = NativeProviders()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=runtime,
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    with TestClient(application, client=("127.0.0.1", 51079)) as machine:
        owner = _add_signed_in_user(application, 50079)
        browser = _browser_client(application, owner)
        try:
            _context, _conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, owner
            )
            response = machine.post(
                f"/api/v1/assistant/internal/provider/{turn['execution_id']}/chat/completions",
                headers={
                    "Authorization": f"Bearer {capability}",
                    "session-id": "ses_first_chunk_replay_fixture_01",
                },
                json={
                    "model": "assistant-selected",
                    "stream": True,
                    "messages": [{"role": "user", "content": "synthetic"}],
                },
            )
            assert response.status_code == 200
            assert response.content == b"data: first\n\ndata: second\n\n"
            assert providers.yielded == [b"data: first\n\n", b"data: second\n\n"]
            assert providers.closed
            assert runtime.starts == 1
            assert runtime.first_chunks == 2
            assert runtime.yields == [len(b"data: first\n\n"), len(b"data: second\n\n")]
            assert runtime.failures == []
            assert len(runtime.ends) == 1
            assert runtime.ends[0][-2:] == ("ended", "clean_eof")
        finally:
            browser.close()


def test_internal_provider_proxy_keeps_midstream_403_interrupted(settings):
    class Runtime(FakeRuntime):
        def __init__(self) -> None:
            super().__init__()
            self.failures: list[tuple[object, ...]] = []
            self.ends: list[tuple[object, ...]] = []

        def _record_provider_stream_start(self, *_args: object) -> int:
            return 1

        def _record_provider_stream_failure(self, *args: object) -> None:
            self.failures.append(args)

        def _record_provider_stream_end(self, *args: object) -> None:
            self.ends.append(args)

    class NativeProviders(FakeProviders):
        def __init__(self) -> None:
            super().__init__()
            self.closed = False

        async def proxy_chat_completion(self, provider_id, model_id, body, **context):
            del provider_id, model_id, body, context
            try:
                yield b"data: partial\n\n"
                raise net.PublicHTTPError(
                    "provider_upstream_unavailable",
                    status_code=403,
                    content_type_class="json",
                    cf_mitigated_class="absent",
                )
            finally:
                self.closed = True

    runtime = Runtime()
    providers = NativeProviders()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=runtime,
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    with TestClient(
        application, client=("127.0.0.1", 51082), raise_server_exceptions=False
    ) as machine:
        owner = _add_signed_in_user(application, 50082)
        browser = _browser_client(application, owner)
        try:
            _context, _conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, owner
            )
            response = machine.post(
                f"/api/v1/assistant/internal/provider/{turn['execution_id']}/chat/completions",
                headers={
                    "Authorization": f"Bearer {capability}",
                    "session-id": "ses_midstream_403_fixture_01",
                },
                json={
                    "model": "assistant-selected",
                    "stream": True,
                    "messages": [{"role": "user", "content": "synthetic"}],
                },
            )
            assert response.status_code == 200
            assert response.content == b"data: partial\n\n"
            assert "provider_upstream_unavailable" not in response.text
            assert providers.closed
            assert len(runtime.failures) == 1
            assert runtime.failures[0][-3] == 403
            assert len(runtime.ends) == 1
            assert runtime.ends[0][-2:] == ("failed", "safe_protocol_error")
        finally:
            browser.close()


def test_internal_provider_proxy_rechecks_revoked_session_after_prefetch(settings):
    class Runtime(FakeRuntime):
        def __init__(self) -> None:
            super().__init__()
            self.application = None
            self.owner_token_hash = ""
            self.revoked = False

        def _record_provider_stream_start(self, *_args: object) -> int:
            return 1

        def _record_provider_first_sanitized_chunk(self, *_args: object) -> None:
            self.application.state.repository.auth_revoke_session(
                self.owner_token_hash, NOW.isoformat()
            )
            self.revoked = True

        def _record_provider_sanitized_yield(self, *_args: object) -> None:
            return None

        def _record_provider_stream_end(self, *_args: object) -> None:
            return None

    class NativeProviders(FakeProviders):
        def __init__(self) -> None:
            super().__init__()
            self.closed = False

        async def proxy_chat_completion(self, provider_id, model_id, body, **context):
            del provider_id, model_id, body, context
            try:
                yield b"data: must-not-escape\n\n"
            finally:
                self.closed = True

    runtime = Runtime()
    providers = NativeProviders()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=runtime,
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    runtime.application = application
    with TestClient(application, client=("127.0.0.1", 51080)) as machine:
        owner = _add_signed_in_user(application, 50080)
        runtime.owner_token_hash = str(owner["token_hash"])
        browser = _browser_client(application, owner)
        try:
            _context, _conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, owner
            )
            response = machine.post(
                f"/api/v1/assistant/internal/provider/{turn['execution_id']}/chat/completions",
                headers={
                    "Authorization": f"Bearer {capability}",
                    "session-id": "ses_revoked_during_prefetch_fixture_01",
                },
                json={
                    "model": "assistant-selected",
                    "stream": True,
                    "messages": [{"role": "user", "content": "synthetic"}],
                },
            )
            assert response.status_code == 404
            assert "must-not-escape" not in response.text
            assert runtime.revoked
            assert providers.closed
        finally:
            browser.close()


def test_provider_proxy_response_closes_iterator_when_send_is_cancelled():
    async def exercise() -> None:
        class Upstream:
            def __init__(self) -> None:
                self.closed = asyncio.Event()
                self.yielded = False

            def __aiter__(self):
                return self

            async def __anext__(self) -> bytes:
                if self.yielded:
                    await asyncio.Future()
                self.yielded = True
                return b"data: first\n\n"

            async def aclose(self) -> None:
                self.closed.set()

        upstream = Upstream()
        response = assistant_api._ProviderProxyStreamingResponse(
            upstream,
            authorization_check=lambda: True,
            denied=assistant_api.JSONResponse(status_code=404, content={"error": "denied"}),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store"},
        )
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/synthetic",
            "raw_path": b"/synthetic",
            "query_string": b"",
            "headers": [],
            "server": ("test", 80),
            "client": ("test", 123),
        }

        async def receive():
            await asyncio.Future()

        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await response(scope, receive, send)
        assert upstream.closed.is_set()

    asyncio.run(exercise())


def test_provider_proxy_response_cancels_pending_handshake_on_asgi23_disconnect():
    async def exercise() -> None:
        class Upstream:
            def __init__(self) -> None:
                self.started = asyncio.Event()
                self.cancelled = asyncio.Event()
                self.closed = asyncio.Event()

            def __aiter__(self):
                return self

            async def __anext__(self) -> bytes:
                self.started.set()
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    self.cancelled.set()
                    raise

            async def aclose(self) -> None:
                self.closed.set()

        upstream = Upstream()
        response = assistant_api._ProviderProxyStreamingResponse(
            upstream,
            authorization_check=lambda: True,
            denied=assistant_api.JSONResponse(status_code=404, content={"error": "denied"}),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store"},
        )
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/synthetic",
            "raw_path": b"/synthetic",
            "query_string": b"",
            "headers": [],
            "server": ("test", 80),
            "client": ("test", 123),
        }
        messages: list[dict[str, object]] = []

        async def receive():
            await upstream.started.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            messages.append(message)

        await response(scope, receive, send)
        await asyncio.wait_for(upstream.closed.wait(), timeout=1.5)
        assert upstream.cancelled.is_set()
        assert messages == []

    asyncio.run(exercise())


@pytest.mark.parametrize("failure_kind", ("empty_eof", "timeout", "invalid_chunk"))
def test_internal_provider_proxy_preserves_initial_non_auth_failures_safely(
    settings, monkeypatch: pytest.MonkeyPatch, failure_kind: str
):
    class Runtime(FakeRuntime):
        def __init__(self) -> None:
            super().__init__()
            self.failures: list[tuple[object, ...]] = []
            self.ends: list[tuple[object, ...]] = []

        def _record_provider_stream_start(self, *_args: object) -> int:
            return 1

        def _record_provider_stream_failure(self, *args: object) -> None:
            self.failures.append(args)

        def _record_provider_stream_end(self, *args: object) -> None:
            self.ends.append(args)

    class NativeProviders(FakeProviders):
        def __init__(self) -> None:
            super().__init__()
            self.closed = threading.Event()

        async def proxy_chat_completion(self, provider_id, model_id, body, **context):
            del provider_id, model_id, body, context
            try:
                if failure_kind == "timeout":
                    await asyncio.Future()
                elif failure_kind == "invalid_chunk":
                    yield "not bytes"
                else:
                    if False:
                        yield b"unreachable"
            finally:
                self.closed.set()

    if failure_kind == "timeout":
        monkeypatch.setattr(assistant_api, "_PROXY_STREAM_TIMEOUT_SECONDS", 0.01)
    runtime = Runtime()
    providers = NativeProviders()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=runtime,
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    with TestClient(
        application,
        client=("127.0.0.1", 51081),
        raise_server_exceptions=False,
    ) as machine:
        owner = _add_signed_in_user(application, 50081)
        browser = _browser_client(application, owner)
        try:
            _context, _conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, owner
            )
            response = machine.post(
                f"/api/v1/assistant/internal/provider/{turn['execution_id']}/chat/completions",
                headers={
                    "Authorization": f"Bearer {capability}",
                    "session-id": "ses_initial_non_auth_failure_fixture_01",
                },
                json={
                    "model": "assistant-selected",
                    "stream": True,
                    "messages": [{"role": "user", "content": "synthetic"}],
                },
            )
            assert response.status_code == 200
            assert response.content == b""
            assert "not bytes" not in response.text
            # A timeout may cancel an in-flight native read; its existing deferred-close
            # callback owns cleanup once that read has actually returned.
            if failure_kind != "timeout":
                assert providers.closed.wait(timeout=1.0)
            assert len(runtime.ends) == 1
            if failure_kind == "empty_eof":
                assert runtime.failures == []
                assert runtime.ends[0][-2:] == ("ended", "clean_eof")
            else:
                assert len(runtime.failures) == 1
                expected_end = (
                    "failed",
                    "proxy_timeout" if failure_kind == "timeout" else "safe_protocol_error",
                )
                assert runtime.ends[0][-2:] == expected_end
        finally:
            browser.close()


def test_internal_provider_proxy_forwards_only_valid_native_zen_identity(
    settings, monkeypatch: pytest.MonkeyPatch
):
    providers = FakeProviders()
    zen_model = _catalog_zen_test_policy()
    runtime = FakeRuntime()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=runtime,
        assistant_catalog=FakeCatalog(zen_model),
        assistant_providers=providers,
    )
    user_agent = "opencode/stable/2.0.7/opencode"
    with TestClient(application, client=("127.0.0.1", 51070)) as owner_client:
        owner = _add_signed_in_user(application, 50070)
        browser = _browser_client(application, owner)
        try:
            _context, _conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, owner, model_id=zen_model.model_id
            )
            execution_id = turn["execution_id"]
            runtime.native_provider_sessions[execution_id] = (
                NATIVE_SESSION_FIXTURE,
                NATIVE_PROJECT_FIXTURE,
            )
            body = {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "Synthetic native request."}],
                "stream": True,
            }
            headers = {
                "Authorization": f"Bearer {capability}",
                "session-id": NATIVE_SESSION_FIXTURE,
                "user-agent": user_agent,
                "x-opencode-client": "opencode",
                "x-opencode-session": NATIVE_SESSION_FIXTURE,
                "x-opencode-project": NATIVE_PROJECT_FIXTURE,
                "x-opencode-request": "private-request-metadata",
                "x-opencode-parent-session-id": "private-parent-metadata",
                "x-session-affinity": NATIVE_SESSION_FIXTURE,
                "x-session-id": NATIVE_SESSION_FIXTURE,
            }
            response = owner_client.post(
                f"/api/v1/assistant/internal/provider/{execution_id}/chat/completions",
                headers=headers,
                json=body,
            )
            assert response.status_code == 200, response.text
            assert len(providers.calls) == 1
            context = providers.call_contexts[0]
            assert context["native_user_agent"] == user_agent
            assert context["native_client"] == "opencode"
            assert context["native_opencode_session"] == NATIVE_SESSION_FIXTURE
            assert context["native_opencode_project"] == NATIVE_PROJECT_FIXTURE
            assert context["native_session_affinity"] == NATIVE_SESSION_FIXTURE
            assert context["native_session_id_alias"] == NATIVE_SESSION_FIXTURE
            assert not {
                "x-opencode-request",
                "x-opencode-parent-session-id",
                "session-id",
            }.intersection(context)
            authorization_check = context["authorization_check"]
            assert callable(authorization_check)
            assert authorization_check() is True

            for field, value in (
                ("x-opencode-session", None),
                ("x-opencode-project", "../private"),
                ("x-opencode-session", "ses_0123456789abABCDEFGHIJKLMA"),
                ("x-session-affinity", "ses_0123456789abABCDEFGHIJKLMA"),
                ("x-session-id", "ses_0123456789abABCDEFGHIJKLMA"),
                ("session-id", "ses_0123456789abABCDEFGHIJKLMA"),
            ):
                altered = dict(headers)
                if value is None:
                    altered.pop(field)
                else:
                    altered[field] = value
                rejected_identity = owner_client.post(
                    f"/api/v1/assistant/internal/provider/{execution_id}/chat/completions",
                    headers=altered,
                    json=body,
                )
                assert rejected_identity.status_code == 422
                assert len(providers.calls) == 1

            duplicate_project = owner_client.post(
                f"/api/v1/assistant/internal/provider/{execution_id}/chat/completions",
                headers=[
                    ("Authorization", f"Bearer {capability}"),
                    ("session-id", NATIVE_SESSION_FIXTURE),
                    ("User-Agent", user_agent),
                    ("x-opencode-client", "opencode"),
                    ("x-opencode-session", NATIVE_SESSION_FIXTURE),
                    ("x-opencode-project", NATIVE_PROJECT_FIXTURE),
                    ("x-opencode-project", NATIVE_PROJECT_FIXTURE),
                ],
                json=body,
            )
            assert duplicate_project.status_code == 422
            assert len(providers.calls) == 1

            runtime.native_provider_sessions.pop(execution_id)
            other_execution_id = "a" * 32
            runtime.native_provider_sessions[other_execution_id] = (
                NATIVE_SESSION_FIXTURE,
                NATIVE_PROJECT_FIXTURE,
            )
            cross_execution = owner_client.post(
                f"/api/v1/assistant/internal/provider/{execution_id}/chat/completions",
                headers=headers,
                json=body,
            )
            assert cross_execution.status_code == 404
            assert len(providers.calls) == 1
            runtime.native_provider_sessions.pop(other_execution_id)
            assert authorization_check() is False
            runtime.native_provider_sessions[execution_id] = (
                NATIVE_SESSION_FIXTURE,
                NATIVE_PROJECT_FIXTURE,
            )

            metadata_reads = 0

            def removed_during_authorization(_execution_id: str):
                nonlocal metadata_reads
                metadata_reads += 1
                return (
                    (NATIVE_SESSION_FIXTURE, NATIVE_PROJECT_FIXTURE)
                    if metadata_reads == 1
                    else None
                )

            runtime.native_provider_metadata = removed_during_authorization
            disappeared_before_dispatch = owner_client.post(
                f"/api/v1/assistant/internal/provider/{execution_id}/chat/completions",
                headers=headers,
                json=body,
            )
            assert disappeared_before_dispatch.status_code == 404
            assert metadata_reads >= 2
            assert len(providers.calls) == 1
            del runtime.native_provider_metadata

            duplicate = owner_client.post(
                f"/api/v1/assistant/internal/provider/{execution_id}/chat/completions",
                headers=[
                    ("Authorization", f"Bearer {capability}"),
                    ("session-id", NATIVE_SESSION_FIXTURE),
                    ("User-Agent", user_agent),
                    ("user-agent", user_agent),
                    ("x-opencode-client", "opencode"),
                    ("x-opencode-session", NATIVE_SESSION_FIXTURE),
                    ("x-opencode-project", NATIVE_PROJECT_FIXTURE),
                ],
                json=body,
            )
            assert duplicate.status_code == 422
            assert len(providers.calls) == 1

            monkeypatch.setattr(
                application.state.assistant,
                "_execution_current",
                lambda *_arguments: False,
            )
            revoked = owner_client.post(
                f"/api/v1/assistant/internal/provider/{execution_id}/chat/completions",
                headers={
                    "Authorization": f"Bearer {capability}",
                    "session-id": NATIVE_SESSION_FIXTURE,
                    "user-agent": user_agent,
                    "x-opencode-client": "opencode",
                    "x-opencode-session": NATIVE_SESSION_FIXTURE,
                    "x-opencode-project": NATIVE_PROJECT_FIXTURE,
                },
                json=body,
            )
            assert revoked.status_code == 404
            assert len(providers.calls) == 1
        finally:
            browser.close()


def test_native_zen_identity_parser_allows_absence_and_rejects_duplicate_fields():
    expected = {
        "expected_session": NATIVE_SESSION_FIXTURE,
        "expected_project": NATIVE_PROJECT_FIXTURE,
    }
    assert (
        assistant_api._native_zen_request_identity(
            Request({"type": "http", "headers": []}), **expected
        )
        is None
    )
    assert assistant_api._native_zen_request_identity(
        Request(
            {
                "type": "http",
                "headers": [
                    (b"user-agent", b"opencode/stable/2.0.7/opencode"),
                    (b"x-opencode-session", NATIVE_SESSION_FIXTURE.encode()),
                    (b"x-opencode-project", NATIVE_PROJECT_FIXTURE.encode()),
                    (b"x-session-affinity", NATIVE_SESSION_FIXTURE.encode()),
                    (b"x-session-id", NATIVE_SESSION_FIXTURE.encode()),
                ],
            }
        ),
        **expected,
    ) == {
        "user-agent": "opencode/stable/2.0.7/opencode",
        "x-opencode-session": NATIVE_SESSION_FIXTURE,
        "x-opencode-project": NATIVE_PROJECT_FIXTURE,
        "x-session-affinity": NATIVE_SESSION_FIXTURE,
        "x-session-id": NATIVE_SESSION_FIXTURE,
    }
    assert (
        assistant_api._native_zen_request_identity(
            Request(
                {
                    "type": "http",
                    "headers": [
                        (b"x-opencode-client", b"opencode"),
                        (b"x-opencode-session", NATIVE_SESSION_FIXTURE.encode()),
                        (b"x-opencode-project", NATIVE_PROJECT_FIXTURE.encode()),
                    ],
                }
            ),
            **expected,
        )
        is None
    )
    assert (
        assistant_api._native_zen_request_identity(
            Request(
                {
                    "type": "http",
                    "headers": [
                        (b"user-agent", b"opencode/stable/2.0.7/opencode"),
                        (b"user-agent", b"opencode/stable/2.0.7/opencode"),
                        (b"x-opencode-session", NATIVE_SESSION_FIXTURE.encode()),
                        (b"x-opencode-project", NATIVE_PROJECT_FIXTURE.encode()),
                    ],
                }
            ),
            **expected,
        )
        is None
    )
    assert (
        assistant_api._native_zen_request_identity(
            Request(
                {
                    "type": "http",
                    "headers": [
                        (b"user-agent", b"opencode/st\xffble/2.0.7/opencode"),
                        (b"x-opencode-session", NATIVE_SESSION_FIXTURE.encode()),
                        (b"x-opencode-project", NATIVE_PROJECT_FIXTURE.encode()),
                    ],
                }
            ),
            **expected,
        )
        is None
    )
    assert (
        assistant_api._native_zen_request_identity(
            Request(
                {
                    "type": "http",
                    "headers": [
                        (b"x-opencode-client", b"opencode"),
                        (b"x-opencode-client", b"opencode"),
                        (b"x-opencode-session", NATIVE_SESSION_FIXTURE.encode()),
                        (b"x-opencode-project", NATIVE_PROJECT_FIXTURE.encode()),
                    ],
                }
            ),
            **expected,
        )
        is None
    )
    assert (
        assistant_api._native_zen_request_identity(
            Request(
                {
                    "type": "http",
                    "headers": [
                        (b"x-opencode-session", NATIVE_SESSION_FIXTURE.encode()),
                        (b"x-opencode-project", b"../private"),
                    ],
                }
            ),
            **expected,
        )
        is None
    )


@pytest.mark.parametrize(
    ("user_agent", "client"),
    (
        ("ordinary-browser-agent", "opencode"),
        ("opencode/stable/2.0.7", "opencode"),
        ("opencode/" + "x" * 280 + "/2.0.7/opencode", "opencode"),
        ("opencode/stable/2.0.7/opencode", "another-client"),
        (None, "opencode"),
    ),
    ids=(
        "non-native-agent",
        "wrong-component-count",
        "oversize",
        "client-mismatch",
        "client-without-user-agent",
    ),
)
def test_internal_provider_proxy_rejects_malformed_native_zen_identity_before_egress(
    settings, user_agent: str | None, client: str
):
    providers = FakeProviders()
    zen_model = _catalog_zen_test_policy()
    runtime = FakeRuntime()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=runtime,
        assistant_catalog=FakeCatalog(zen_model),
        assistant_providers=providers,
    )
    with TestClient(application, client=("127.0.0.1", 51071)) as owner_client:
        owner = _add_signed_in_user(application, 50071)
        browser = _browser_client(application, owner)
        try:
            _context, _conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, owner, model_id=zen_model.model_id
            )
            runtime.native_provider_sessions[str(turn["execution_id"])] = (
                NATIVE_SESSION_FIXTURE,
                NATIVE_PROJECT_FIXTURE,
            )
            headers = {
                "Authorization": f"Bearer {capability}",
                "session-id": NATIVE_SESSION_FIXTURE,
                "x-opencode-session": NATIVE_SESSION_FIXTURE,
                "x-opencode-project": NATIVE_PROJECT_FIXTURE,
                "x-opencode-client": client,
            }
            if user_agent is not None:
                headers["user-agent"] = user_agent
            response = owner_client.post(
                f"/api/v1/assistant/internal/provider/{turn['execution_id']}/chat/completions",
                headers=headers,
                json={
                    "model": "assistant-selected",
                    "messages": [{"role": "user", "content": "Synthetic request."}],
                    "stream": True,
                },
            )
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "invalid_provider_request"
            assert providers.calls == []
        finally:
            browser.close()


@pytest.mark.parametrize("native", (False, True), ids=("chat", "native"))
def test_internal_provider_route_rechecks_authorization_after_body_read(
    settings,
    monkeypatch: pytest.MonkeyPatch,
    native: bool,
) -> None:
    """The post-body lease check blocks manager dispatch when its state turns stale."""

    class NativeProviders(FakeProviders):
        def __init__(self) -> None:
            super().__init__()
            self.native_calls: list[dict[str, object]] = []

        async def proxy_native_stream(self, provider_id, model_id, body, **context):
            self.native_calls.append({"provider_id": provider_id, "model_id": model_id, **context})
            yield b"data: [DONE]\n\n"

    providers = NativeProviders()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    with TestClient(application, client=("127.0.0.1", 51046)) as owner_client:
        owner = _add_signed_in_user(application, 50051)
        browser = _browser_client(application, owner)
        try:
            _context, _conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, owner
            )
            execution_id = str(turn["execution_id"])
            original_current = application.state.assistant._execution_current
            checks = 0

            def revoke_after_first_check(*arguments: object) -> bool:
                nonlocal checks
                checks += 1
                if checks == 1:
                    return original_current(*arguments)
                return False

            monkeypatch.setattr(
                application.state.assistant,
                "_execution_current",
                revoke_after_first_check,
            )
            headers = {
                "Authorization": f"Bearer {capability}",
                "session-id": "ses_delayed_body_authorization_01",
            }
            if native:
                path = f"/api/v1/assistant/internal/provider/{execution_id}/v1/responses"
                response = owner_client.post(
                    path,
                    headers={**headers, "content-type": "application/json"},
                    content=b'{"model":"assistant-selected","stream":true}',
                )
                assert providers.native_calls == []
            else:
                path = f"/api/v1/assistant/internal/provider/{execution_id}/chat/completions"
                response = owner_client.post(
                    path,
                    headers=headers,
                    json={
                        "model": "assistant-selected",
                        "messages": [{"role": "user", "content": "synthetic"}],
                        "stream": True,
                    },
                )
                assert providers.calls == []

            assert checks >= 2
            assert response.status_code == 404
        finally:
            browser.close()


@pytest.mark.parametrize("native", (False, True), ids=("chat", "native"))
@pytest.mark.parametrize(
    "authorization_change", ("session_revoked", "role_demoted", "consent_revoked")
)
def test_internal_provider_authorization_callback_rechecks_live_state_once(
    settings, monkeypatch: pytest.MonkeyPatch, native: bool, authorization_change: str
) -> None:
    """Provider callbacks use one live check and reject real authorization changes."""

    github_id = 50052
    role = "member"
    app_settings = _auth_settings(settings)
    if authorization_change == "role_demoted":
        app_settings = replace(
            app_settings,
            assistant_rollout_mode="owner_canary",
            assistant_canary_github_ids=(github_id,),
        )
        role = "admin"

    class NativeProviders(FakeProviders):
        async def proxy_native_stream(self, provider_id, model_id, body, **context):
            self.calls.append((provider_id, model_id, body))
            self.call_contexts.append(context)
            yield b"data: [DONE]\n\n"

    providers = NativeProviders()
    application = create_app(
        app_settings,
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    with TestClient(application, client=("127.0.0.1", 51047)) as owner_client:
        owner = _add_signed_in_user(application, github_id, role=role)
        browser = _browser_client(application, owner)
        try:
            _context, _conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, owner
            )
            execution_id = str(turn["execution_id"])
            assistant = application.state.assistant
            other_owner = _add_signed_in_user(application, 50053)

            validation_count = 0
            original_validation = assistant.validate_execution_session

            def counted_validation(lease: dict[str, object]) -> bool:
                nonlocal validation_count
                validation_count += 1
                return original_validation(lease)

            monkeypatch.setattr(assistant, "validate_execution_session", counted_validation)
            headers = {
                "Authorization": f"Bearer {capability}",
                "session-id": "ses_provider_authorization_fixture_01",
            }
            if native:
                response = owner_client.post(
                    f"/api/v1/assistant/internal/provider/{execution_id}/v1/responses",
                    headers={**headers, "content-type": "application/json"},
                    content=b'{"model":"assistant-selected","stream":true}',
                )
            else:
                response = owner_client.post(
                    f"/api/v1/assistant/internal/provider/{execution_id}/chat/completions",
                    headers=headers,
                    json={
                        "model": "assistant-selected",
                        "messages": [{"role": "user", "content": "synthetic"}],
                        "stream": True,
                    },
                )
            assert response.status_code == 200, response.text

            callback = providers.call_contexts[-1]["authorization_check"]
            assert callable(callback)
            checks_before = validation_count
            assert callback()
            assert validation_count == checks_before + 1
            assert not assistant._execution_current(
                int(other_owner["user_id"]),
                execution_id,
                MODEL.model_id,
                MODEL.policy_version,
            )

            if authorization_change == "session_revoked":
                application.state.repository.auth_revoke_session(
                    str(owner["token_hash"]), NOW.isoformat()
                )
            elif authorization_change == "role_demoted":
                application.state.repository.auth_update_user(
                    int(owner["user_id"]), {"role": "member"}
                )
            else:
                assistant.storage.create_consent(
                    int(owner["user_id"]),
                    model_id=MODEL.model_id,
                    policy_version=MODEL.policy_version,
                    accepted_terms=False,
                    data_collection_opt_in=False,
                    recorded_at=NOW + timedelta(seconds=1),
                )

            checks_before = validation_count
            assert not callback()
            assert validation_count == checks_before + 1
        finally:
            browser.close()


def test_internal_provider_proxy_accepts_native_websearch_ingress_fixture(settings):
    providers = FakeProviders()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    with TestClient(application, client=("127.0.0.1", 51025)) as owner_client:
        owner = _add_signed_in_user(application, 50032)
        browser = _browser_client(application, owner)
        try:
            _context, _conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, owner
            )
            execution_id = str(turn["execution_id"])
            declaration = _native_websearch_declaration()
            body = {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "Search current information."}],
                "stream": True,
                "store": False,
                "stream_options": {"include_usage": True},
                "tools": [declaration],
            }
            response = owner_client.post(
                f"/api/v1/assistant/internal/provider/{execution_id}/chat/completions",
                headers={
                    "Authorization": f"Bearer {capability}",
                    "session-id": "ses_native_search_fixture_01",
                },
                json=body,
            )
            assert response.status_code == 200, response.text
            assert len(providers.calls) == 1
            assert providers.calls[0][2]["tools"] == [declaration]
            assert providers.calls[0][2]["stream_options"] == {"include_usage": True}

            widened = {
                **declaration,
                "function": {
                    **declaration["function"],
                    "parameters": {
                        **declaration["function"]["parameters"],
                        "additionalProperties": True,
                    },
                },
            }
            rejected = owner_client.post(
                f"/api/v1/assistant/internal/provider/{execution_id}/chat/completions",
                headers={
                    "Authorization": f"Bearer {capability}",
                    "session-id": "ses_native_search_fixture_01",
                },
                json={**body, "tools": [widened]},
            )
            assert rejected.status_code == 422
            assert len(providers.calls) == 1
        finally:
            browser.close()


def test_internal_vendor_provider_routes_bind_exact_path_query_lease_and_bound_json(settings):
    class NativeProviders(FakeProviders):
        def __init__(self):
            super().__init__()
            self.native_calls = []

        async def proxy_native_stream(
            self,
            provider_id,
            model_id,
            body,
            *,
            path_model_id,
            query,
            app_tools,
            **context,
        ):
            self.native_calls.append(
                (
                    provider_id,
                    model_id,
                    dict(body),
                    path_model_id,
                    query,
                    list(app_tools),
                    context,
                )
            )
            yield b'data: {"type":"message_stop"}\n\n'

    providers = NativeProviders()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=providers,
    )
    with TestClient(application, client=("127.0.0.1", 51033)) as machine:
        owner = _add_signed_in_user(application, 50041)
        browser = _browser_client(application, owner)
        try:
            _context, _conversation, turn, _lease, capability = _conversation_and_running_turn(
                browser, owner
            )
            execution_id = str(turn["execution_id"])
            headers = {
                "authorization": f"Bearer {capability}",
                "content-type": "application/json",
                "session-id": "ses_native_vendor_fixture_01",
            }
            body = {"model": "assistant-selected", "stream": True, "input": "synthetic"}
            route_cases = (
                (
                    f"/api/v1/assistant/internal/provider/{execution_id}/v1/responses",
                    None,
                    (),
                ),
                (
                    f"/api/v1/assistant/internal/provider/{execution_id}/v1/messages?beta=true",
                    None,
                    (("beta", "true"),),
                ),
                (
                    f"/api/v1/assistant/internal/provider/{execution_id}/v1/models/assistant-selected:streamGenerateContent?alt=sse",
                    "assistant-selected",
                    (("alt", "sse"),),
                ),
            )
            for url, _path_model_id, _query in route_cases:
                response = machine.post(url, headers=headers, json=body)
                assert response.status_code == 200, response.text
                assert response.headers["cache-control"] == "no-store"
                assert response.text.startswith("data: ")
            assert len(providers.native_calls) == 3
            for call, (_url, path_model_id, query) in zip(
                providers.native_calls, route_cases, strict=True
            ):
                (
                    provider_id,
                    model_id,
                    forwarded,
                    actual_path,
                    actual_query,
                    app_tools,
                    context,
                ) = call
                assert provider_id == MODEL.provider_id
                assert model_id == MODEL.model_id
                assert forwarded == body
                assert actual_path == path_model_id
                assert actual_query == query
                assert app_tools == AssistantToolGateway.list_tools()
                assert context["owner_id"] == owner["user_id"]
                assert context["app_session_id"] == owner["session_id"]
                assert context["native_session_id"] == "ses_native_vendor_fixture_01"
                assert callable(context["authorization_check"])
                assert context["authorization_check"]() is True

            large_body = {**body, "input": "x" * 20_000}
            for url, _path_model_id, _query in route_cases:
                response = machine.post(url, headers=headers, json=large_body)
                assert response.status_code == 200, response.text
            assert len(providers.native_calls) == 6
            assert [call[2] for call in providers.native_calls[3:]] == [large_body] * 3

            large_body_with_unapproved_query = machine.post(
                f"/api/v1/assistant/internal/provider/{execution_id}/v1/responses?store=true",
                headers=headers,
                json=large_body,
            )
            assert large_body_with_unapproved_query.status_code == 413
            assert len(providers.native_calls) == 6

            for rejected_url in (
                f"/api/v1/assistant/internal/provider/{execution_id}/v1/responses?store=true",
                f"/api/v1/assistant/internal/provider/{execution_id}/v1/messages?beta=true&beta=true",
                f"/api/v1/assistant/internal/provider/{execution_id}/v1/models/other-model:streamGenerateContent?alt=sse",
            ):
                rejected = machine.post(rejected_url, headers=headers, json=body)
                assert rejected.status_code == 404
            for forbidden_headers in (
                {"origin": "http://127.0.0.1:51033"},
                {"referer": "http://127.0.0.1:51033/"},
                {"cookie": "signal_ledger_session=synthetic"},
                {"sec-fetch-site": "same-origin"},
                {"x-csrf-token": "synthetic"},
            ):
                rejected = machine.post(
                    f"/api/v1/assistant/internal/provider/{execution_id}/v1/responses",
                    headers={**headers, **forbidden_headers},
                    json=body,
                )
                assert rejected.status_code in {403, 404}
            assert len(providers.native_calls) == 6

            duplicate_json = machine.post(
                f"/api/v1/assistant/internal/provider/{execution_id}/v1/responses",
                headers=headers,
                content=b'{"model":"assistant-selected","model":"forged","input":"x"}',
            )
            assert duplicate_json.status_code == 422
            oversized = machine.post(
                f"/api/v1/assistant/internal/provider/{execution_id}/v1/responses",
                headers=headers,
                content=b"{" + b" " * _PROXY_MAX_NATIVE_JSON_BYTES,
            )
            assert oversized.status_code == 413
            bad_capability = machine.post(
                f"/api/v1/assistant/internal/provider/{execution_id}/v1/responses",
                headers={**headers, "authorization": "Bearer " + "z" * 48},
                json=body,
            )
            assert bad_capability.status_code == 404
            assert len(providers.native_calls) == 6
        finally:
            browser.close()


def test_delete_conversation_recovers_quota_without_growing_database(settings, monkeypatch):
    """Deletion remains available above the assistant write cap and inserts still fail closed."""

    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51024)):
        identity = _add_signed_in_user(application, 50031)
        browser = _browser_client(application, identity)
        try:
            context_response = browser.get(
                "/api/v1/assistant/context", params={"route": "/overview"}
            )
            assert context_response.status_code == 200, context_response.text
            context = context_response.json()["context"]
            created = browser.post(
                "/api/v1/assistant/conversations",
                json={"context": context},
                headers={"x-csrf-token": str(identity["csrf"])},
            )
            assert created.status_code == 201, created.text
            conversation = created.json()["conversation"]["conversation"]
            conversation_id = str(conversation["id"])

            with application.state.repository.connect() as connection:
                allocated_before = assistant_storage.AssistantStorage._database_bytes(connection)
            # A tiny test cap models an unrelated application table already pushing the shared
            # database above the assistant write bound without allocating a 48 MiB fixture.
            monkeypatch.setattr(assistant_storage, "ASSISTANT_DATABASE_LIMIT", 1)
            assert allocated_before > assistant_storage.ASSISTANT_DATABASE_LIMIT
            deleted = browser.request(
                "DELETE",
                f"/api/v1/assistant/conversations/{conversation_id}",
                headers={"x-csrf-token": str(identity["csrf"])},
                json={
                    "expected_revision": int(conversation["revision"]),
                    "confirmation_phrase": conversation["delete_confirmation_phrase"],
                },
            )
            assert deleted.status_code == 200, deleted.text
            with application.state.repository.connect() as connection:
                allocated_after = assistant_storage.AssistantStorage._database_bytes(connection)
            assert allocated_after <= allocated_before

            refused_insert = browser.post(
                "/api/v1/assistant/conversations",
                json={"context": context},
                headers={"x-csrf-token": str(identity["csrf"])},
            )
            assert refused_insert.status_code == 413
            assert refused_insert.json()["error"]["code"] == "assistant_quota_exceeded"
        finally:
            browser.close()


def test_delete_preflights_confirmation_and_keeps_transcript_until_cache_clear(settings):
    class ControlledPurgeRuntime(FakeRuntime):
        def __init__(self):
            self.cancelled: list[str] = []
            self.purged: list[str] = []
            self.allow_purge = False

        async def cancel_execution(self, execution_id):
            self.cancelled.append(execution_id)

        async def clear_conversation_cache(self, conversation_id):
            self.purged.append(conversation_id)
            return self.allow_purge

    runtime = ControlledPurgeRuntime()
    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=runtime,
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51026)):
        owner = _add_signed_in_user(application, 50033)
        other_owner = _add_signed_in_user(application, 50034)
        browser = _browser_client(application, owner)
        other_browser = _browser_client(application, other_owner)
        try:
            _context, conversation, target_turn, _target_lease, _capability = (
                _conversation_and_running_turn(browser, owner)
            )
            _other_context, other_conversation, _other_turn, other_lease, _other_capability = (
                _conversation_and_running_turn(other_browser, other_owner)
            )
            conversation_id = str(conversation["id"])
            headers = {"x-csrf-token": str(owner["csrf"])}
            path = f"/api/v1/assistant/conversations/{conversation_id}"
            phrase = f"DELETE {conversation_id[-8:]}"
            current_revision = int(browser.get(path).json()["conversation"]["revision"])

            stale_revision = browser.request(
                "DELETE",
                path,
                headers=headers,
                json={
                    "expected_revision": current_revision + 1,
                    "confirmation_phrase": phrase,
                },
            )
            wrong_phrase = browser.request(
                "DELETE",
                path,
                headers=headers,
                json={
                    "expected_revision": current_revision,
                    "confirmation_phrase": "DELETE wrong",
                },
            )
            assert stale_revision.status_code == 409
            assert wrong_phrase.status_code == 409
            assert runtime.cancelled == []
            assert runtime.purged == []
            assert (
                application.state.assistant.storage.execution_lease(
                    str(target_turn["execution_id"])
                )["status"]
                == "active"
            )
            assert (
                application.state.assistant.storage.execution_lease(
                    str(other_lease["execution_id"])
                )["status"]
                == "active"
            )

            refused = browser.request(
                "DELETE",
                path,
                headers=headers,
                json={"expected_revision": current_revision, "confirmation_phrase": phrase},
            )
            assert refused.status_code == 503
            assert refused.json()["error"]["code"] == "assistant_cache_clear_pending"
            assert runtime.cancelled == [str(target_turn["execution_id"])]
            assert runtime.purged == [conversation_id]
            retained = browser.get(path)
            assert retained.status_code == 200
            assert retained.json()["conversation"]["id"] == conversation_id
            retained_revision = int(retained.json()["conversation"]["revision"])
            assert (
                application.state.assistant.storage.execution_lease(
                    str(other_lease["execution_id"])
                )["status"]
                == "active"
            )

            runtime.allow_purge = True
            deleted = browser.request(
                "DELETE",
                path,
                headers=headers,
                json={"expected_revision": retained_revision, "confirmation_phrase": phrase},
            )
            assert deleted.status_code == 200, deleted.text
            assert deleted.json()["canonical_content_removed"] is True
            assert runtime.purged == [conversation_id, conversation_id]
            assert (
                application.state.assistant.storage.execution_lease(
                    str(other_lease["execution_id"])
                )["status"]
                == "active"
            )
            assert (
                application.state.assistant.storage.get_conversation(
                    int(other_owner["user_id"]), str(other_conversation["id"])
                )["conversation"]["id"]
                == other_conversation["id"]
            )
        finally:
            browser.close()
            other_browser.close()


def test_long_conversation_pages_keep_turn_context_and_recent_pending_actions(settings):
    """Every bounded transcript page retains its turn and page one shows recent activity."""

    application = create_app(
        _auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=FakeRuntime(),
        assistant_catalog=FakeCatalog(),
        assistant_providers=FakeProviders(),
    )
    with TestClient(application, client=("127.0.0.1", 51025)):
        identity = _add_signed_in_user(application, 50032)
        browser = _browser_client(application, identity)
        try:
            context_response = browser.get(
                "/api/v1/assistant/context", params={"route": "/overview"}
            )
            context = context_response.json()["context"]
            created = browser.post(
                "/api/v1/assistant/conversations",
                json={"context": context},
                headers={"x-csrf-token": str(identity["csrf"])},
            )
            assert created.status_code == 201, created.text
            conversation = created.json()["conversation"]["conversation"]
            conversation_id = str(conversation["id"])
            user_id = int(identity["user_id"])
            app = application.state.assistant
            app.storage.create_consent(
                user_id,
                model_id=MODEL.model_id,
                policy_version=MODEL.policy_version,
                accepted_terms=True,
                data_collection_opt_in=False,
                recorded_at=NOW,
            )

            context_json = json.dumps(context, separators=(",", ":"))
            context_version = str(context["context_version"])
            expires_text = (NOW + timedelta(hours=1)).isoformat()
            ids: list[tuple[str, str, str]] = []
            with application.state.repository.connect() as connection:
                for index in range(105):
                    turn_id = secrets.token_hex(18)
                    message_id = secrets.token_hex(18)
                    action_id = secrets.token_hex(18)
                    timestamp = (NOW + timedelta(seconds=index)).isoformat()
                    phrase = f"CONFIRM {action_id[-8:]}"
                    connection.execute(
                        """INSERT INTO assistant_turns
                        (id, conversation_id, user_id, status, model_id, policy_version,
                         context_json, context_version, created_at, completed_at)
                        VALUES (?, ?, ?, 'completed', ?, ?, ?, ?, ?, ?)""",
                        (
                            turn_id,
                            conversation_id,
                            user_id,
                            MODEL.model_id,
                            MODEL.policy_version,
                            context_json,
                            context_version,
                            timestamp,
                            timestamp,
                        ),
                    )
                    connection.execute(
                        """INSERT INTO assistant_messages
                        (id, conversation_id, turn_id, user_id, sequence, role, content, created_at)
                        VALUES (?, ?, ?, ?, ?, 'user', ?, ?)""",
                        (
                            message_id,
                            conversation_id,
                            turn_id,
                            user_id,
                            index + 1,
                            f"Saved question {index + 1}",
                            timestamp,
                        ),
                    )
                    connection.execute(
                        """INSERT INTO assistant_events
                        (conversation_id, turn_id, user_id, sequence, event_type,
                         payload_json, created_at)
                        VALUES (?, ?, ?, 1, 'tool', ?, ?)""",
                        (
                            conversation_id,
                            turn_id,
                            user_id,
                            json.dumps(
                                {
                                    "name": "workspace.summary",
                                    "status": "completed",
                                    "call_id": f"call-{index + 1}",
                                }
                            ),
                            timestamp,
                        ),
                    )
                    connection.execute(
                        """INSERT INTO assistant_proposed_actions
                        (id, conversation_id, turn_id, user_id, session_id, context_version,
                         action_type, payload_json, action_version, confirmation_phrase_hash,
                         status, expires_at, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, 'theme.set', ?, 1, ?, 'pending', ?, ?)""",
                        (
                            action_id,
                            conversation_id,
                            turn_id,
                            user_id,
                            str(identity["session_id"]),
                            context_version,
                            '{"theme":"dark"}',
                            _sha(phrase),
                            expires_text,
                            timestamp,
                        ),
                    )
                    ids.append((turn_id, message_id, action_id))
                connection.commit()

            first_page = browser.get(f"/api/v1/assistant/conversations/{conversation_id}")
            assert first_page.status_code == 200, first_page.text
            detail = first_page.json()
            assert detail["messages"]["total"] == 105
            assert len(detail["messages"]["items"]) == 50
            assert detail["turns"]
            assert {turn["id"] for turn in detail["turns"]} >= {
                message["turn_id"] for message in detail["messages"]["items"]
            }
            assert detail["action_pagination"] == {"page": 1, "page_size": 100, "total": 105}
            assert len(detail["actions"]) == 100
            assert any(action["action_id"] == ids[-1][2] for action in detail["actions"])
            latest_action = next(
                action for action in detail["actions"] if action["action_id"] == ids[-1][2]
            )
            assert latest_action["availability"] == "confirmable"
            assert latest_action["proposal"]["confirmation_phrase"] == f"CONFIRM {ids[-1][2][-8:]}"
            assert detail["events"] == {
                "items": detail["events"]["items"],
                "page": 1,
                "page_size": 100,
                "total": 105,
            }
            assert detail["event_pagination"] == {"page": 1, "page_size": 100, "total": 105}
            assert detail["events"]["items"][-1]["data"]["call_id"] == "call-105"

            older = browser.get(
                f"/api/v1/assistant/conversations/{conversation_id}",
                params={
                    "message_page": 3,
                    "message_page_size": 50,
                    "action_page": 2,
                    "action_page_size": 100,
                    "event_page": 2,
                    "event_page_size": 100,
                },
            )
            assert older.status_code == 200, older.text
            old_detail = older.json()
            assert old_detail["messages"]["page"] == 3
            assert {turn["id"] for turn in old_detail["turns"]} >= {
                message["turn_id"] for message in old_detail["messages"]["items"]
            }
            assert old_detail["action_pagination"] == {"page": 2, "page_size": 100, "total": 105}
            assert len(old_detail["actions"]) == 5
            assert old_detail["events"]["page"] == 2
            assert old_detail["events"]["total"] == 105
            assert old_detail["events"]["items"][-1]["data"]["call_id"] == "call-5"
        finally:
            browser.close()
