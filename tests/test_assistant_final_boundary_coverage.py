"""Close assistant provider, stream, and worker failure-boundary coverage gaps."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from stock_probs.api import create_app
from stock_probs.assistant import api as assistant_api
from stock_probs.assistant import providers as provider_module
from stock_probs.assistant import runtime as runtime_module
from stock_probs.assistant import supervisor_client
from stock_probs.assistant.model_catalog import AssistantModelCatalog
from stock_probs.assistant.providers import (
    AssistantProviderManager,
    CredentialRejected,
    ProviderUnavailable,
    _validated_native_provider_body,
)
from stock_probs.assistant.runtime import (
    OpenCodeV2Runtime,
    _summarize_native_failure_payload,
)
from stock_probs.assistant.schemas import AssistantModelPolicy, AssistantTurnContext
from stock_probs.assistant.service import AssistantUnavailable
from stock_probs.assistant.tools import AssistantToolGateway
from stock_probs.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from stock_probs.config import Settings
from stock_probs.provider import FixtureProvider

_HTTP_MODEL = AssistantModelPolicy(
    model_id="fixture/model-v1",
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
_NATIVE_OPENCODE_VERSION = json.loads(
    (
        Path(__file__).resolve().parents[1] / "tools/opencode-v2-security-patch/manifest.json"
    ).read_text(encoding="utf-8")
)["opencode"]["version"]
_NATIVE_ZEN_USER_AGENT = f"opencode/stable/{_NATIVE_OPENCODE_VERSION}/opencode"
_NATIVE_ZEN_CLIENT = "opencode"
_NATIVE_ZEN_SESSION = "ses_0123456789abABCDEFGHIJKLMN"
_NATIVE_ZEN_PROJECT = "global"


class _HTTPModelCatalog:
    """Project one test-only model into the authenticated assistant service."""

    def list_models(self) -> list[dict[str, object]]:
        return [
            {
                "model_id": _HTTP_MODEL.model_id,
                "provider_id": _HTTP_MODEL.provider_id,
                "native_provider_id": _HTTP_MODEL.provider_id,
                "display_name": _HTTP_MODEL.display_name,
                "available": True,
                "free": True,
                "training": False,
                "terms_url": _HTTP_MODEL.terms_url,
                "terms_reviewed_at": _HTTP_MODEL.terms_reviewed_at,
                "policy_version": _HTTP_MODEL.policy_version,
                "disclosure": _HTTP_MODEL.disclosure,
                "data_collection_allowed": False,
                "data_collection_default": False,
                "privacy_policy_version": _HTTP_MODEL.policy_version,
                "privacy_disclosure": _HTTP_MODEL.disclosure,
                "billing_class": "free",
                "billing_policy_version": _HTTP_MODEL.policy_version,
                "cost_disclosure": "Free test fixture model.",
                "enabled": True,
                "usable": True,
                "revision": 1,
            }
        ]


class _HTTPRuntime:
    """Satisfy only the app lifespan seams needed by the in-memory API test."""

    async def start(self) -> None:
        return None

    def status(self) -> dict[str, str | None]:
        return {"status": "ready", "message": None}

    async def close(self) -> None:
        return None

    async def clear_conversation_cache(self, _conversation_id: str) -> bool:
        return True


class _HTTPProviders:
    """Record exact API proxy arguments and emit a complete synthetic SSE response."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object], dict[str, object]]] = []

    async def proxy_chat_completion(
        self,
        provider_id: str,
        model_id: str,
        body: dict[str, object],
        **context: object,
    ) -> AsyncIterator[bytes]:
        self.calls.append((provider_id, model_id, body, context))
        yield b'data: {"choices":[{"delta":{"content":"fixture"},"finish_reason":"stop"}]}\n\n'
        yield b"data: [DONE]\n\n"


def _http_test_app(settings: Settings, now: datetime) -> tuple[object, _HTTPProviders]:
    """Build a disposable auth-mode app with synthetic runtime and provider seams."""

    configured = replace(
        settings,
        environment="test",
        auth_mode="github",
        auth_session_secret="synthetic-auth-session-secret-for-assistant-test-000000",  # noqa: S106
        auth_public_origin="http://testserver",
        auth_session_idle_seconds=86_400,
        github_client_id="synthetic-client",
        github_client_secret="synthetic-oauth-secret",  # noqa: S106
        github_redirect_uri="http://testserver/api/v1/auth/github/callback",
        assistant_enabled=True,
        assistant_rollout_mode="invited",
    )
    providers = _HTTPProviders()
    app = create_app(
        configured,
        FixtureProvider(),
        lambda: now,
        assistant_runtime=_HTTPRuntime(),
        assistant_catalog=_HTTPModelCatalog(),
        assistant_providers=providers,
    )
    return app, providers


def _add_http_test_user(app: object, now: datetime) -> dict[str, object]:
    """Insert a disposable authenticated owner session without real factor material."""

    repository = app.state.repository
    owner_id = secrets.randbelow(1_000_000_000) + 1
    created = repository.auth_create_user(
        {
            "github_id": owner_id,
            "github_login": f"boundary-{owner_id}",
            "display_name": "Boundary Test User",
            "role": "member",
            "status": "active",
            "created_at": now,
        }
    )
    user_id = int(created["id"])
    expires = now + timedelta(hours=23)
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    session_id = secrets.token_hex(16)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    csrf_hash = hashlib.sha256(csrf.encode()).hexdigest()
    with repository.connect() as connection:
        cursor = connection.execute(
            """INSERT INTO totp_factors
            (user_id, secret_ciphertext, created_at, confirmed_at,
             last_accepted_step, updated_at)
            VALUES (?, ?, ?, ?, -1, ?)""",
            (
                user_id,
                "test-only-factor-ciphertext",
                now.isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        factor_id = int(cursor.lastrowid)
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
                csrf_hash,
                now.isoformat(),
                now.isoformat(),
                expires.isoformat(),
                expires.isoformat(),
                now.isoformat(),
                factor_id,
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


def _http_running_turn(
    browser: TestClient, app: object, identity: Mapping[str, object], now: datetime
) -> tuple[dict[str, object], str, str]:
    """Create one consented owner turn using the app's real disposable SQLite storage."""

    context_response = browser.get("/api/v1/assistant/context", params={"route": "/overview"})
    assert context_response.status_code == 200, context_response.text
    context = context_response.json()["context"]
    created = browser.post(
        "/api/v1/assistant/conversations",
        json={"title": "Boundary test", "context": context},
        headers={"x-csrf-token": str(identity["csrf"])},
    )
    assert created.status_code == 201, created.text
    conversation = created.json()["conversation"]["conversation"]
    assistant = app.state.assistant
    policy = assistant.policy(_HTTP_MODEL.model_id)
    assistant.storage.create_consent(
        int(identity["user_id"]),
        model_id=_HTTP_MODEL.model_id,
        policy_version=policy.policy_version,
        accepted_terms=True,
        data_collection_opt_in=False,
        recorded_at=now,
    )
    capability = secrets.token_urlsafe(32)
    turn = assistant.storage.create_turn(
        int(identity["user_id"]),
        str(conversation["id"]),
        prompt="Review my current workspace safely.",
        model_id=_HTTP_MODEL.model_id,
        policy_version=policy.policy_version,
        context=context,
        context_version=str(context["context_version"]),
        session_id=str(identity["session_id"]),
        session_token_hash=str(identity["token_hash"]),
        capability=capability,
        now=now,
        expires_at=now + timedelta(seconds=120),
    )
    assistant.storage.set_turn_status(
        int(identity["user_id"]),
        str(conversation["id"]),
        str(turn["id"]),
        status="running",
        now=now,
    )
    return turn, capability, str(conversation["id"])


def _manager(
    tmp_path: Path,
    *,
    catalog: AssistantModelCatalog | None = None,
    runtime: object | None = None,
) -> AssistantProviderManager:
    """Construct the real provider manager over a disposable encrypted vault."""

    return AssistantProviderManager(
        cast(Settings, SimpleNamespace(data_dir=tmp_path, auth_session_secret="v" * 64)),
        catalog=catalog,
        vault_dir=tmp_path / "assistant-vault",
        runtime=runtime,
        clock=lambda: 5.0,
    )


def _zen_manager(tmp_path: Path) -> tuple[AssistantProviderManager, str]:
    """Use a model selected from the maintained Zen review catalog."""

    catalog = AssistantModelCatalog(clock=lambda: 5.0)
    zen_policy = cast(Mapping[str, object], catalog._policy["zen"])
    reviewed_models = cast(Mapping[str, Mapping[str, object]], zen_policy["reviewed_models"])
    model_suffix = next(
        model_id
        for model_id, policy in sorted(reviewed_models.items())
        if policy.get("available") is True
        and policy.get("free") is True
        and policy.get("training") is False
        and policy.get("data_collection_allowed") is False
        and policy.get("data_collection_default") is False
        and policy.get("route") == "openai-compatible"
    )
    model = catalog._parse_zen_rows([{"id": model_suffix}])[0]
    manager = _manager(tmp_path, catalog=catalog)
    catalog.set_native_models((model,))
    return manager, model.model_id


def _native_zen_identity_kwargs() -> dict[str, str]:
    """Return syntactically valid synthetic native identity for direct proxy tests."""

    return {
        "native_user_agent": _NATIVE_ZEN_USER_AGENT,
        "native_client": _NATIVE_ZEN_CLIENT,
        "native_opencode_session": _NATIVE_ZEN_SESSION,
        "native_opencode_project": _NATIVE_ZEN_PROJECT,
        "native_session_affinity": _NATIVE_ZEN_SESSION,
        "native_session_id_alias": _NATIVE_ZEN_SESSION,
    }


def _workspace_tool() -> dict[str, object]:
    """Return the narrow app-owned workspace tool used by synthetic stream tests."""

    return next(
        tool
        for tool in AssistantToolGateway.list_tools()
        if tool.get("name") == "workspace.summary"
    )


def _custom_proxy_manager(tmp_path: Path) -> tuple[AssistantProviderManager, str]:
    """Build a reviewed custom adapter from its real policy parser and local catalog."""

    catalog = AssistantModelCatalog(clock=lambda: 5.0)
    manager = _manager(tmp_path, catalog=catalog)
    manager.configure_custom_endpoint(
        base_url="https://provider.example.test/v1",
        terms_url="https://terms.example.test/policy",
        privacy_disclosure="Administrator-provided privacy statement; unverified.",
        billing_disclosure="Administrator-provided billing statement; unverified.",
        billing_class="unknown",
        endpoint_policy_reviewed=True,
        credential="synthetic-secret-for-stream-redaction",
    )
    models = manager._parse_provider_model_rows("custom", [{"id": "boundary-model"}])
    catalog.set_native_models(models)
    return manager, models[0].model_id


class _OAuthDiscoveryRuntime:
    """Return exactly the native integration snapshot chosen by one test."""

    def __init__(self, result: object = None, failure: Exception | None = None) -> None:
        self.result = result
        self.failure = failure

    async def list_native_integrations(self) -> object:
        """Return the fixed fixture or raise its private synthetic failure."""

        if self.failure is not None:
            raise self.failure
        return self.result


@pytest.mark.parametrize(
    "snapshot",
    (
        None,
        {"integration_id": "openai", "methods": "not-a-list"},
        {"integration_id": "../openai", "methods": []},
        {"integration_id": "openai", "methods": [None] * 33},
        [None] * 513,
    ),
)
def test_native_oauth_discovery_rejects_malformed_snapshots_without_projecting_methods(
    tmp_path: Path, snapshot: object
) -> None:
    """Malformed native discovery fails closed before it can widen OAuth method choices."""

    manager = _manager(tmp_path, runtime=_OAuthDiscoveryRuntime(snapshot))

    with pytest.raises(ProviderUnavailable, match="oauth_unavailable") as rejected:
        asyncio.run(manager.list_native_oauth_methods())

    assert rejected.value.code == "oauth_unavailable"


def test_native_oauth_discovery_discards_unknown_and_non_oauth_methods(tmp_path: Path) -> None:
    """Only a discovered fixed OAuth method is exposed to the app-owned chooser."""

    manager = _manager(
        tmp_path,
        runtime=_OAuthDiscoveryRuntime(
            [
                {
                    "integration_id": "openai",
                    "methods": [
                        None,
                        {"method_id": "chatgpt-headless", "kind": "password"},
                        {"method_id": "shell", "kind": "oauth"},
                        {"method_id": "chatgpt-headless", "kind": "oauth"},
                    ],
                }
            ]
        ),
    )

    methods = asyncio.run(manager.list_native_oauth_methods())

    assert [(row["integration_id"], row["method_id"]) for row in methods] == [
        ("openai", "chatgpt-headless")
    ]
    assert methods[0]["model_access_supported"] is True


def test_native_oauth_discovery_sanitizes_runtime_failure(tmp_path: Path) -> None:
    """A private worker diagnostic is replaced by the closed OAuth error code."""

    manager = _manager(
        tmp_path,
        runtime=_OAuthDiscoveryRuntime(failure=RuntimeError("private worker diagnostic")),
    )

    with pytest.raises(ProviderUnavailable, match="oauth_unavailable") as rejected:
        asyncio.run(manager.list_native_oauth_methods())

    assert "private worker diagnostic" not in str(rejected.value)


class _SyncRuntime:
    """Fail only the requested provider clear so rollback behavior stays deterministic."""

    fail_clear = False

    def sync_provider_configuration(
        self, provider_id: str, definition: Mapping[str, object], state: Mapping[str, object]
    ) -> None:
        del definition
        if provider_id == "openai" and not state and self.fail_clear:
            raise RuntimeError("private sync detail")


def test_provider_clear_restores_encrypted_credential_when_runtime_sync_fails(
    tmp_path: Path,
) -> None:
    """A failed runtime sync restores provider state and the app-side credential."""

    runtime = _SyncRuntime()
    manager = _manager(tmp_path, runtime=runtime)
    manager._write_credential("openai", "synthetic-key-that-must-stay-in-the-vault")
    credential_path = manager._credential_path("openai")
    runtime.fail_clear = True

    with pytest.raises(ProviderUnavailable, match="provider_clear_failed") as rejected:
        manager.clear_credential("openai")

    assert rejected.value.code == "provider_clear_failed"
    assert credential_path.is_file()
    assert manager.credential_for_runtime("openai") == "synthetic-key-that-must-stay-in-the-vault"
    assert "synthetic-key-that-must-stay-in-the-vault" not in credential_path.read_text()


@pytest.mark.parametrize(
    ("status_code", "error_type", "error_code"),
    (
        (401, CredentialRejected, "credential_rejected"),
        (403, CredentialRejected, "credential_rejected"),
        (429, ProviderUnavailable, "provider_unavailable"),
        (503, ProviderUnavailable, "provider_unavailable"),
    ),
)
def test_provider_validation_maps_upstream_status_to_safe_local_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    error_type: type[Exception],
    error_code: str,
) -> None:
    """Validation distinguishes rejected credentials while hiding upstream response text."""

    manager = _manager(tmp_path)
    manager.configure_custom_endpoint(
        base_url="https://provider.example.test/v1",
        terms_url="https://terms.example.test/policy",
        privacy_disclosure="Administrator-provided privacy statement; unverified.",
        billing_disclosure="Administrator-provided billing statement; unverified.",
        billing_class="unknown",
        endpoint_policy_reviewed=True,
        credential="synthetic-validation-key",
    )
    requests: list[tuple[str, dict[str, object]]] = []

    async def respond(url: str, **kwargs: object) -> SimpleNamespace:
        requests.append((url, cast(dict[str, object], kwargs)))
        return SimpleNamespace(status_code=status_code, content=b"private upstream response")

    monkeypatch.setattr(provider_module, "request_public_https", respond)

    with pytest.raises(error_type) as rejected:
        asyncio.run(manager.validate("custom"))

    assert rejected.value.code == error_code
    assert "private upstream response" not in str(rejected.value)
    assert len(requests) == 1
    assert requests[0][0].startswith("https://")
    assert requests[0][1]["timeout_seconds"] == 6.5
    assert requests[0][1]["headers"]["authorization"] == "Bearer synthetic-validation-key"


def test_custom_provider_validation_publishes_only_valid_inventory_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful model response publishes opaque valid IDs and drops malformed rows."""

    catalog = AssistantModelCatalog(clock=lambda: 5.0)
    manager = _manager(tmp_path, catalog=catalog)
    manager.configure_custom_endpoint(
        base_url="https://provider.example.test/v1",
        terms_url="https://terms.example.test/policy",
        privacy_disclosure="Administrator-provided privacy statement; unverified.",
        billing_disclosure="Administrator-provided billing statement; unverified.",
        billing_class="unknown",
        endpoint_policy_reviewed=True,
        credential="synthetic-inventory-key",
    )
    requests: list[tuple[str, dict[str, object]]] = []

    async def respond(url: str, **kwargs: object) -> SimpleNamespace:
        requests.append((url, cast(dict[str, object], kwargs)))
        return SimpleNamespace(
            status_code=200,
            content=json.dumps(
                {
                    "data": [
                        {"id": "model-1", "displayName": "Reviewed Candidate"},
                        {"id": "bad id", "displayName": "Drop this row"},
                        {"id": "model-2", "displayName": "invalid\nname"},
                        {"id": "model-1", "displayName": "Duplicate"},
                        None,
                    ]
                }
            ).encode(),
        )

    monkeypatch.setattr(provider_module, "request_public_https", respond)

    result = asyncio.run(manager.validate("custom"))

    assert result.connection_status == "connected"
    assert result.credential_configured is True
    assert [model.model_id for model in catalog.list_models() if model.provider_id == "custom"] == [
        "custom/model-1",
        "custom/model-2",
    ]
    assert catalog.get_model("custom/model-1").display_name == "Reviewed Candidate"
    assert requests[0][0] == "https://provider.example.test/v1/models"
    assert requests[0][1]["timeout_seconds"] == 6.5
    assert requests[0][1]["max_response_bytes"] > 0


@pytest.mark.parametrize(
    ("provider_id", "body", "error_code"),
    (
        (
            "opencode-zen",
            {
                "model": "other-model",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
            "model_unavailable",
        ),
        (
            "opencode-zen",
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
                "store": True,
            },
            "model_unavailable",
        ),
        (
            "opencode-zen",
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
                "stream_options": {"include_usage": False},
            },
            "provider_request_invalid",
        ),
        (
            "opencode-zen",
            {"model": "assistant-selected", "messages": [], "stream": True},
            "provider_request_invalid",
        ),
        (
            "opencode-zen",
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
                "tool_choice": "undeclared-tool",
            },
            "provider_request_invalid",
        ),
        (
            "anthropic",
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
            "provider_adapter_unsupported",
        ),
    ),
)
def test_chat_proxy_rejects_unreviewed_request_shapes_before_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
    body: dict[str, object],
    error_code: str,
) -> None:
    """Malformed aliases, storage flags, tool choices, and protocols never reach egress."""

    manager, model_id = _zen_manager(tmp_path)
    egress: list[str] = []

    async def no_network(*args: object, **kwargs: object) -> AsyncIterator[bytes]:
        del kwargs
        egress.append(str(args[0]))
        yield b"unreachable"

    monkeypatch.setattr(provider_module, "stream_public_https", no_network)
    native_identity = _native_zen_identity_kwargs() if provider_id == "opencode-zen" else {}

    with pytest.raises(ProviderUnavailable) as rejected:
        manager.proxy_chat_completion(
            provider_id,
            model_id,
            body,
            **native_identity,
            app_tools=[
                {
                    "name": "workspace.summary",
                    "description": "Read a bounded workspace summary.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additionalProperties": False,
                    },
                }
            ],
            authorization_check=lambda: True,
        )

    assert rejected.value.code == error_code
    assert egress == []


def test_chat_proxy_emits_only_complete_normalized_provider_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The compatible stream closes at a valid terminal marker and strips provider metadata."""

    manager, model_id = _zen_manager(tmp_path)
    captured: dict[str, object] = {}

    async def stream(
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> AsyncIterator[bytes]:
        captured.update(
            {
                "url": url,
                "headers": dict(headers),
                "body": json.loads(body),
                "timeout_seconds": timeout_seconds,
                "max_response_bytes": max_response_bytes,
            }
        )
        yield (
            b'data: {"choices":[{"index":0,"delta":{"role":"assistant",'
            b'"content":"bounded answer"},"finish_reason":null}],"secret":"drop"}\r\n'
        )
        yield b"\r\n"
        yield b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
        yield b"data: [DONE]"

    monkeypatch.setattr(provider_module, "stream_public_https", stream)
    app_tools = [
        {
            "name": "workspace.summary",
            "description": "Read a bounded workspace summary.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        }
    ]

    async def exercise() -> list[bytes]:
        upstream = manager.proxy_chat_completion(
            "opencode-zen",
            model_id,
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "Summarize safely."}],
                "stream": True,
                "stream_options": {"include_usage": True},
                "max_tokens": 64,
            },
            **_native_zen_identity_kwargs(),
            app_tools=app_tools,
            authorization_check=lambda: True,
        )
        return [chunk async for chunk in upstream]

    chunks = asyncio.run(exercise())

    assert b"".join(chunks) == (
        b'data: {"choices":[{"index":0,"delta":{"role":"assistant",'
        b'"content":"bounded answer"}}]}\n\n'
        b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
        b"data: [DONE]\n\n"
    )
    assert captured["url"] == "https://opencode.ai/zen/v1/chat/completions"
    assert captured["headers"]["accept"] == "text/event-stream"
    assert captured["headers"]["authorization"] == "Bearer public"
    assert captured["body"]["model"] == model_id.removeprefix("opencode-zen/")
    assert captured["body"]["store"] is False
    assert captured["body"]["stream_options"] == {"include_usage": True}


def test_chat_proxy_preserves_a_complete_declared_tool_call_across_sse_fragments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A split tool name and argument are accepted only when the declared call completes."""

    manager, model_id = _zen_manager(tmp_path)
    tool = _workspace_tool()
    app_tools = [tool]
    upstream_tools = [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["inputSchema"],
            },
        }
    ]

    async def stream(*_args: object, **_kwargs: object) -> AsyncIterator[bytes]:
        yield (
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_123",'
            b'"type":"function","function":{"name":"workspace.","arguments":"{"}}]},'
            b'"finish_reason":null}]}'
        )
        yield b'\n\ndata: {"choices":[{"delta":{"tool_calls":[{"index":0,'
        yield (b'"function":{"name":"summary","arguments":"}"}}]},"finish_reason":"tool_calls"}]}')
        yield b"\n\ndata: [DONE]\n\n"

    monkeypatch.setattr(provider_module, "stream_public_https", stream)

    async def exercise() -> list[bytes]:
        upstream = manager.proxy_chat_completion(
            "opencode-zen",
            model_id,
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "Summarize safely."}],
                "stream": True,
                "tools": upstream_tools,
                "tool_choice": "auto",
            },
            **_native_zen_identity_kwargs(),
            app_tools=app_tools,
            authorization_check=lambda: True,
        )
        return [chunk async for chunk in upstream]

    chunks = asyncio.run(exercise())
    combined = b"".join(chunks)

    assert b'"name":"workspace."' in combined
    assert b'"name":"summary","arguments":"}"' in combined
    assert combined.endswith(b"data: [DONE]\n\n")


def test_chat_proxy_validates_and_forwards_a_matched_app_tool_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a declared call and its matching result cross the app proxy boundary."""

    manager, model_id = _zen_manager(tmp_path)
    tool = _workspace_tool()
    captured: dict[str, object] = {}

    async def stream(_url: str, *, body: bytes, **_kwargs: object) -> AsyncIterator[bytes]:
        captured["body"] = json.loads(body)
        yield b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        yield b"data: [DONE]\n\n"

    monkeypatch.setattr(provider_module, "stream_public_https", stream)

    async def exercise() -> list[bytes]:
        upstream = manager.proxy_chat_completion(
            "opencode-zen",
            model_id,
            {
                "model": "assistant-selected",
                "messages": [
                    {"role": "user", "content": "Summarize my workspace."},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {"name": "workspace.summary", "arguments": "{}"},
                            }
                        ],
                    },
                    {"role": "tool", "tool_call_id": "call_123", "content": "Safe summary."},
                ],
                "stream": True,
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "workspace.summary",
                            "description": tool["description"],
                            "parameters": tool["inputSchema"],
                        },
                    }
                ],
            },
            **_native_zen_identity_kwargs(),
            app_tools=[tool],
            authorization_check=lambda: True,
        )
        return [chunk async for chunk in upstream]

    chunks = asyncio.run(exercise())

    assert chunks[-1] == b"data: [DONE]\n\n"
    assert captured["body"]["messages"][-1] == {
        "role": "tool",
        "tool_call_id": "call_123",
        "content": "Safe summary.",
    }
    assert captured["body"]["messages"][1]["tool_calls"][0]["function"]["name"] == (
        "workspace.summary"
    )


@pytest.mark.parametrize(
    "messages",
    (
        [{"role": "tool", "tool_call_id": "call_404", "content": "orphan result"}],
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {"name": "workspace.summary", "arguments": "{}"},
                    }
                ],
            }
        ],
        [
            {"role": "user", "content": "Start."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {"name": "workspace.summary", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_123", "content": "\x00bad"},
        ],
    ),
)
def test_chat_proxy_rejects_orphan_pending_and_binary_tool_histories_without_egress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    messages: list[dict[str, object]],
) -> None:
    """An orphan, unresolved, or control-character tool result cannot reach a provider."""

    manager, model_id = _zen_manager(tmp_path)
    egress: list[bool] = []

    async def no_network(*_args: object, **_kwargs: object) -> AsyncIterator[bytes]:
        egress.append(True)
        yield b"unreachable"

    monkeypatch.setattr(provider_module, "stream_public_https", no_network)

    with pytest.raises(ProviderUnavailable) as rejected:
        manager.proxy_chat_completion(
            "opencode-zen",
            model_id,
            {"model": "assistant-selected", "messages": messages, "stream": True},
            **_native_zen_identity_kwargs(),
            app_tools=[_workspace_tool()],
            authorization_check=lambda: True,
        )

    assert rejected.value.code == "provider_request_invalid"
    assert egress == []


def test_native_protocol_adapters_preserve_valid_tool_roundtrips_and_drop_cache_hint() -> None:
    """Reviewed tool schemas and matched results stay within each native vendor contract."""

    tool = _workspace_tool()
    tools = [tool]
    responses_allowed = provider_module._native_application_tools(
        tools, protocol="openai-responses"
    )
    responses_tool = responses_allowed["workspace.summary"][1]
    assert responses_tool is not None
    responses = _validated_native_provider_body(
        "openai-responses",
        {
            "model": "assistant-selected",
            "input": [
                {"type": "message", "role": "user", "content": "Summarize safely."},
                {
                    "type": "function_call",
                    "call_id": "call_123",
                    "name": "workspace.summary",
                    "arguments": "{}",
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_123",
                    "output": "Safe aggregate.",
                },
            ],
            "stream": True,
            "store": False,
            "prompt_cache_key": "discard-this-provider-cache-hint",
            "include": ["reasoning.encrypted_content"],
            "max_output_tokens": 256,
            "tools": [
                {
                    "type": "function",
                    "name": "workspace.summary",
                    "description": tool["description"],
                    "parameters": responses_tool,
                    "strict": False,
                }
            ],
            "tool_choice": {"type": "function", "name": "workspace.summary"},
        },
        model_alias="assistant-selected",
        upstream_model_id="native-model-id",
        app_tools=tools,
    )
    assert responses["model"] == "native-model-id"
    assert "prompt_cache_key" not in responses
    assert responses["input"][1]["name"] == "workspace.summary"

    anthropic_allowed = provider_module._native_application_tools(
        tools, protocol="anthropic-messages"
    )
    anthropic_schema = anthropic_allowed["workspace.summary"][1]
    assert anthropic_schema is not None
    anthropic = _validated_native_provider_body(
        "anthropic-messages",
        {
            "model": "assistant-selected",
            "max_tokens": 128,
            "stream": True,
            "system": [{"type": "text", "text": "Honor the app-owned tool schema."}],
            "messages": [
                {"role": "user", "content": "Summarize safely."},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "I will read a small summary."},
                        {
                            "type": "tool_use",
                            "id": "toolu_123",
                            "name": "workspace.summary",
                            "input": {},
                        },
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_123",
                            "content": [{"type": "text", "text": "Safe aggregate."}],
                            "is_error": False,
                        }
                    ],
                },
            ],
            "tools": [
                {
                    "name": "workspace.summary",
                    "description": tool["description"],
                    "input_schema": anthropic_schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": "workspace.summary"},
            "temperature": 0.2,
            "top_p": 0.9,
            "top_k": 4,
            "stop_sequences": ["<END>"],
        },
        model_alias="assistant-selected",
        upstream_model_id="native-model-id",
        app_tools=tools,
    )
    assert anthropic["model"] == "native-model-id"
    assert anthropic["messages"][1]["content"][1]["type"] == "tool_use"

    google_allowed = provider_module._native_application_tools(
        tools, protocol="google-generative-language"
    )
    google_schema = google_allowed["workspace.summary"][1]
    google = _validated_native_provider_body(
        "google-generative-language",
        {
            "contents": [
                {"role": "user", "parts": [{"text": "Summarize safely."}]},
                {
                    "role": "model",
                    "parts": [
                        {
                            "functionCall": {
                                "name": "workspace.summary",
                                "args": {},
                            }
                        }
                    ],
                },
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": "workspace.summary",
                                "response": {"content": "Safe aggregate."},
                            }
                        }
                    ],
                },
            ],
            "systemInstruction": {"parts": [{"text": "Use the approved schema."}]},
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "workspace.summary",
                            "description": tool["description"],
                            "parameters": google_schema,
                        }
                    ]
                }
            ],
            "toolConfig": {
                "functionCallingConfig": {
                    "mode": "ANY",
                    "allowedFunctionNames": ["workspace.summary"],
                }
            },
            "generationConfig": {
                "temperature": 0.2,
                "topP": 0.9,
                "topK": 4,
                "maxOutputTokens": 256,
                "stopSequences": ["<END>"],
                "responseMimeType": "text/plain",
            },
        },
        model_alias="assistant-selected",
        upstream_model_id="native-model-id",
        app_tools=tools,
    )
    assert google["contents"][1]["parts"][0]["functionCall"]["name"] == "workspace.summary"


@pytest.mark.parametrize(
    ("protocol", "body"),
    (
        (
            "openai-responses",
            {
                "model": "assistant-selected",
                "input": [{"type": "message", "role": "user", "content": "x"}],
                "stream": True,
                "store": False,
                "tools": [
                    {
                        "type": "function",
                        "name": "workspace.summary",
                        "description": "forged schema description",
                        "parameters": {},
                    }
                ],
            },
        ),
        (
            "anthropic-messages",
            {
                "model": "assistant-selected",
                "max_tokens": 64,
                "messages": [{"role": "tool", "content": "forged role"}],
                "stream": True,
            },
        ),
        (
            "google-generative-language",
            {
                "contents": [
                    {
                        "role": "model",
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "workspace.summary",
                                    "args": {},
                                }
                            }
                        ],
                    }
                ]
            },
        ),
        (
            "openai-compatible-chat",
            {
                "model": "assistant-selected",
                "messages": [{"role": "tool", "tool_call_id": "call_404", "content": "orphan"}],
                "stream": True,
            },
        ),
    ),
)
def test_native_protocol_adapters_reject_forged_tool_and_unmatched_history_shapes(
    protocol: str, body: dict[str, object]
) -> None:
    """Vendor-native protocol schemas reject forged declarations and unmatched tool output."""

    with pytest.raises(ProviderUnavailable, match="provider_request_invalid"):
        _validated_native_provider_body(
            protocol,
            body,
            model_alias="assistant-selected",
            upstream_model_id="native-model-id",
            app_tools=[_workspace_tool()],
        )


@pytest.mark.parametrize(
    ("arguments", "expected"),
    (
        ({"url": "https://public.example.test/article"}, True),
        (
            {
                "url": "https://public.example.test/article",
                "format": "markdown",
                "timeout": 1.5,
            },
            True,
        ),
        ({"url": "file:///private/secret"}, False),
        ({"url": "https://public.example.test/article", "format": "raw"}, False),
        ({"url": "https://public.example.test/article", "timeout": True}, False),
        ({"url": "https://public.example.test/article", "timeout": float("inf")}, False),
        ({"url": "https://public.example.test/article", "header": "forged"}, False),
        ({"url": "https://public.example.test/\ud800"}, False),
    ),
)
def test_native_webfetch_arguments_allow_only_exact_bounded_public_request(
    arguments: dict[str, object], expected: bool
) -> None:
    """Native fetch arguments keep exact public URLs, formats, and finite timeout types."""

    assert assistant_api._native_webfetch_arguments_valid(arguments) is expected


def test_provider_json_normalizer_rejects_duplicate_member_names() -> None:
    """Duplicate JSON keys cannot create two interpretations of provider tool arguments."""

    assert (
        provider_module._parse_json_object('{"url":"https://example.test","url":"file:///x"}')
        is None
    )
    assert provider_module._utf8_length("lone surrogate: \ud800") is None


@pytest.mark.parametrize(
    ("protocol", "body", "expected_code"),
    (
        (
            "openai-responses",
            {
                "model": "assistant-selected",
                "input": [{"type": "message", "role": "user", "content": "x"}],
                "stream": True,
                "store": False,
                "include": ["reasoning.private"],
            },
            "provider_request_invalid",
        ),
        (
            "openai-responses",
            {
                "model": "assistant-selected",
                "input": [{"type": "message", "role": "user", "content": "x"}],
                "stream": True,
                "store": False,
                "instructions": "x" * 65_537,
            },
            "provider_request_invalid",
        ),
        (
            "openai-responses",
            {
                "model": "assistant-selected",
                "input": [{"type": "message", "role": "user", "content": "x"}],
                "stream": True,
                "store": False,
                "truncation": "force",
            },
            "provider_request_invalid",
        ),
        (
            "openai-responses",
            {
                "model": "assistant-selected",
                "input": [{"type": "message", "role": "user", "content": "x"}],
                "stream": True,
                "store": False,
                "parallel_tool_calls": 1,
            },
            "provider_request_invalid",
        ),
        (
            "anthropic-messages",
            {
                "model": "assistant-selected",
                "max_tokens": 64,
                "messages": [{"role": "user", "content": "x"}],
                "stream": True,
                "system": [],
            },
            "provider_request_invalid",
        ),
        (
            "anthropic-messages",
            {
                "model": "assistant-selected",
                "max_tokens": 64,
                "messages": [{"role": "user", "content": "x"}],
                "stream": True,
                "stop_sequences": ["sequence"] * 9,
            },
            "provider_request_invalid",
        ),
        (
            "google-generative-language",
            {
                "contents": [{"role": "user", "parts": [{"text": "x"}]}],
                "systemInstruction": {},
            },
            "provider_request_invalid",
        ),
        (
            "openai-compatible-chat",
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "x"}],
                "stream": True,
                "stream_options": {"include_usage": False},
            },
            "provider_request_invalid",
        ),
        (
            "openai-compatible-chat",
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "x"}],
                "stream": True,
                "tool_choice": "unregistered-tool",
            },
            "provider_request_invalid",
        ),
        (
            "openai-compatible-chat",
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "x"}],
                "stream": True,
                "max_tokens": True,
            },
            "provider_request_invalid",
        ),
        (
            "openai-responses",
            {
                "model": "assistant-selected",
                "input": [{"type": "message", "role": "user", "content": "x"}],
                "stream": True,
                "store": False,
                "large": "x" * 262_145,
            },
            "provider_request_invalid",
        ),
    ),
)
def test_native_provider_body_rejects_invalid_optionals_and_oversized_inputs(
    protocol: str, body: dict[str, object], expected_code: str
) -> None:
    """Optional vendor controls and large requests stay within reviewed native contracts."""

    with pytest.raises(ProviderUnavailable) as rejected:
        _validated_native_provider_body(
            protocol,
            body,
            model_alias="assistant-selected",
            upstream_model_id="native-model-id",
            app_tools=[_workspace_tool()],
        )

    assert rejected.value.code == expected_code


def test_native_compatible_body_drops_tool_field_when_no_tool_is_declared() -> None:
    """An app with no registered native tools forwards no caller-supplied tool declaration."""

    body = _validated_native_provider_body(
        "openai-compatible-chat",
        {
            "model": "assistant-selected",
            "messages": [{"role": "user", "content": "x"}],
            "stream": True,
        },
        model_alias="assistant-selected",
        upstream_model_id="native-model-id",
        app_tools=[_workspace_tool()],
    )

    assert body["model"] == "native-model-id"
    assert body["store"] is False
    assert "tools" not in body


@pytest.mark.parametrize(
    ("finish_reason", "function_name", "arguments", "expected_code"),
    (
        ("tool_calls", "workspace.unknown", "{}", "provider_response_invalid"),
        ("length", "workspace.summary", "{}", "provider_response_incomplete"),
    ),
)
def test_chat_proxy_rejects_undeclared_or_truncated_tool_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    finish_reason: str,
    function_name: str,
    arguments: str,
    expected_code: str,
) -> None:
    """The provider cannot name an undeclared app tool or return a truncated action."""

    manager, model_id = _zen_manager(tmp_path)
    app_tool = _workspace_tool()
    raw = json.dumps(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_123",
                                "type": "function",
                                "function": {"name": function_name, "arguments": arguments},
                            }
                        ]
                    },
                    "finish_reason": finish_reason,
                }
            ]
        },
        separators=(",", ":"),
    ).encode()

    async def stream(*_args: object, **_kwargs: object) -> AsyncIterator[bytes]:
        yield b"data: " + raw + b"\n\ndata: [DONE]\n\n"

    monkeypatch.setattr(provider_module, "stream_public_https", stream)

    async def exercise() -> list[bytes]:
        upstream = manager.proxy_chat_completion(
            "opencode-zen",
            model_id,
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "Use the tool if needed."}],
                "stream": True,
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "workspace.summary",
                            "description": app_tool["description"],
                            "parameters": app_tool["inputSchema"],
                        },
                    }
                ],
            },
            **_native_zen_identity_kwargs(),
            app_tools=[app_tool],
            authorization_check=lambda: True,
        )
        return [chunk async for chunk in upstream]

    with pytest.raises(ProviderUnavailable) as rejected:
        asyncio.run(exercise())

    assert rejected.value.code == expected_code


def test_custom_provider_stream_rejects_secret_spanning_two_sse_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Secret fragments split across valid events are detected before either is released."""

    manager, model_id = _custom_proxy_manager(tmp_path)
    captured_headers: list[dict[str, str]] = []

    async def stream(
        _url: str,
        *,
        headers: Mapping[str, str],
        **_kwargs: object,
    ) -> AsyncIterator[bytes]:
        captured_headers.append(dict(headers))
        yield (
            b'data: {"choices":[{"delta":{"content":"synthetic-secret-for-"},'
            b'"finish_reason":null}]}\n\n'
        )
        yield (
            b'data: {"choices":[{"delta":{"content":"stream-redaction"},'
            b'"finish_reason":"stop"}]}\n\n'
        )
        yield b"data: [DONE]\n\n"

    monkeypatch.setattr(provider_module, "stream_public_https", stream)

    async def exercise() -> list[bytes]:
        upstream = manager.proxy_chat_completion(
            "custom",
            model_id,
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "Return a short answer."}],
                "stream": True,
            },
            app_tools=[_workspace_tool()],
            authorization_check=lambda: True,
        )
        return [chunk async for chunk in upstream]

    with pytest.raises(ProviderUnavailable, match="provider_response_secret_rejected"):
        asyncio.run(exercise())

    assert captured_headers == [
        {
            "accept": "text/event-stream",
            "authorization": "Bearer synthetic-secret-for-stream-redaction",
        }
    ]


@pytest.mark.parametrize(
    ("frame", "expected_code"),
    (
        (b"data: \xff\n\n", "provider_response_invalid"),
        (
            b'data: {"choices":[{"index":0,"delta":{"content":"partial"},'
            b'"finish_reason":null}]}\n\n',
            "provider_response_invalid",
        ),
    ),
)
def test_chat_proxy_rejects_invalid_encoding_and_truncated_provider_streams(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    frame: bytes,
    expected_code: str,
) -> None:
    """Invalid UTF-8 and missing terminal markers remain interrupted provider responses."""

    manager, model_id = _zen_manager(tmp_path)

    async def stream(*_args: object, **_kwargs: object) -> AsyncIterator[bytes]:
        yield frame

    monkeypatch.setattr(provider_module, "stream_public_https", stream)

    async def exercise() -> list[bytes]:
        upstream = manager.proxy_chat_completion(
            "opencode-zen",
            model_id,
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "Boundary fixture."}],
                "stream": True,
            },
            **_native_zen_identity_kwargs(),
            app_tools=[
                {
                    "name": "workspace.summary",
                    "description": "Read a bounded workspace summary.",
                    "inputSchema": {"type": "object", "properties": {}},
                }
            ],
            authorization_check=lambda: True,
        )
        return [chunk async for chunk in upstream]

    with pytest.raises(ProviderUnavailable) as rejected:
        asyncio.run(exercise())

    assert rejected.value.code == expected_code


def test_chat_proxy_stops_when_total_sanitized_output_exceeds_the_response_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated individually valid frames cannot exceed the aggregate stream output bound."""

    manager, model_id = _zen_manager(tmp_path)
    content = "x" * 16_000
    frame = (
        b'data: {"choices":[{"index":0,"delta":{"content":"'
        + content.encode()
        + b'"},"finish_reason":null}]}\n\n'
    )

    async def stream(*_args: object, **_kwargs: object) -> AsyncIterator[bytes]:
        for _ in range(70):
            yield frame

    monkeypatch.setattr(provider_module, "stream_public_https", stream)

    async def exercise() -> int:
        upstream = manager.proxy_chat_completion(
            "opencode-zen",
            model_id,
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "bounded fixture"}],
                "stream": True,
            },
            **_native_zen_identity_kwargs(),
            app_tools=[
                {
                    "name": "workspace.summary",
                    "description": "Read a bounded workspace summary.",
                    "inputSchema": {"type": "object", "properties": {}},
                }
            ],
            authorization_check=lambda: True,
        )
        emitted = 0
        async for chunk in upstream:
            emitted += len(chunk)
        return emitted

    with pytest.raises(ProviderUnavailable, match="provider_response_too_large"):
        asyncio.run(exercise())


class _SnapshotRuntime(OpenCodeV2Runtime):
    """Supply one parsed worker response to the real snapshot consumer."""

    def __init__(self) -> None:
        super().__init__(
            cast(Settings, SimpleNamespace(assistant_enabled=True)),
            providers=object(),
            catalog=object(),
        )
        self.snapshot_response = httpx.Response(200, json={"data": []})

    async def _request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        del method, path, kwargs
        return self.snapshot_response


def _consume_snapshot(
    runtime: _SnapshotRuntime, outcome: dict[str, object]
) -> list[dict[str, object]]:
    """Consume one snapshot and collect only events that passed native checks."""

    events: list[dict[str, object]] = []

    async def emit(event: dict[str, object]) -> None:
        events.append(event)

    asyncio.run(
        runtime._consume_message_snapshot(
            "sesBoundary123",
            cast(AssistantTurnContext, object()),
            emit,
            outcome,
        )
    )
    return events


def test_runtime_snapshot_emits_text_and_consumes_one_approved_webfetch() -> None:
    """Flat native snapshots project text and sources only after matching approval."""

    runtime = _SnapshotRuntime()
    url = "https://public.example.test/article"
    runtime.snapshot_response = httpx.Response(
        200,
        json={
            "data": [
                {
                    "id": "message-1",
                    "type": "assistant",
                    "finish": "stop",
                    "parts": [
                        {"id": "text-1", "type": "text", "text": "Reviewed answer."},
                        {
                            "id": "fetch-1",
                            "type": "tool",
                            "name": "webfetch",
                            "state": {
                                "status": "completed",
                                "input": {"url": url},
                                "metadata": {"finalUrl": url},
                            },
                        },
                    ],
                }
            ]
        },
    )
    outcome: dict[str, object] = {"approved_fetch_urls": {url: 2}}

    events = _consume_snapshot(runtime, outcome)

    assert [event["type"] for event in events] == ["token", "tool", "source"]
    assert events[0]["data"] == {"text": "Reviewed answer."}
    assert events[2]["data"]["url"] == url
    assert outcome["terminal_finish"] == "stop"
    assert outcome["approved_fetch_urls"] == {url: 1}


@pytest.mark.parametrize(
    ("row", "initial_outcome", "expected_event_types"),
    (
        (
            {
                "info": {"id": "message-foreign", "role": "assistant"},
                "sessionID": "sesAnotherOwner123",
                "parts": [{"id": "text-1", "type": "text", "text": "must not leak"}],
            },
            {},
            (),
        ),
        (
            {
                "info": {"id": "message-rewind", "role": "assistant"},
                "parts": [{"id": "text-1", "type": "text", "text": "shorter"}],
            },
            {"text_parts": {"message-rewind:text-1": "already emitted answer"}},
            (),
        ),
        (
            {
                "info": {"id": "message-unapproved", "role": "assistant"},
                "parts": [
                    {
                        "id": "fetch-1",
                        "type": "tool",
                        "name": "webfetch",
                        "state": {
                            "status": "completed",
                            "input": {"url": "https://public.example.test/article"},
                            "metadata": {"finalUrl": "https://public.example.test/article"},
                        },
                    }
                ],
            },
            {},
            ("tool",),
        ),
        (
            {
                "info": {"id": "message-bad-tool", "role": "assistant"},
                "parts": [{"id": "tool-1", "type": "tool", "name": "../exec"}],
            },
            {},
            (),
        ),
    ),
)
def test_runtime_snapshot_stops_on_foreign_or_unapproved_native_state(
    row: dict[str, object],
    initial_outcome: dict[str, object],
    expected_event_types: tuple[str, ...],
) -> None:
    """Foreign session IDs, regressed text, invalid tools, and unapproved fetches fail closed."""

    runtime = _SnapshotRuntime()
    runtime.snapshot_response = httpx.Response(200, json={"data": [row]})
    outcome = dict(initial_outcome)

    events = _consume_snapshot(runtime, outcome)

    assert outcome.get("status") == "failed"
    assert tuple(event["type"] for event in events) == expected_event_types
    assert all(event.get("type") != "source" for event in events)
    assert all("must not leak" not in repr(event) for event in events)


def test_runtime_snapshot_rejects_non_success_or_malformed_worker_envelopes() -> None:
    """A missing or malformed native message envelope becomes one fixed runtime failure."""

    runtime = _SnapshotRuntime()
    runtime.snapshot_response = httpx.Response(503, json={"error": "private upstream detail"})
    with pytest.raises(RuntimeError, match="session_messages_unavailable"):
        _consume_snapshot(runtime, {})

    runtime.snapshot_response = httpx.Response(200, json={"data": "not-a-message-list"})
    with pytest.raises(RuntimeError, match="session_messages_unavailable"):
        _consume_snapshot(runtime, {})


def test_runtime_snapshot_emits_utf8_bounded_text_from_nested_assistant_message() -> None:
    """Nested V2 message roles retain text while long UTF-8 answers split at safe bounds."""

    runtime = _SnapshotRuntime()
    text = "🙂" * 3_000
    runtime.snapshot_response = httpx.Response(
        200,
        json={
            "data": [
                {
                    "info": {
                        "id": "message-nested",
                        "message": {"role": "assistant"},
                        "finish": "stop",
                    },
                    "parts": [{"id": "long-text", "type": "text", "text": text}],
                }
            ]
        },
    )

    events = _consume_snapshot(runtime, {})
    fragments = [event["data"]["text"] for event in events]

    assert all(event["type"] == "token" for event in events)
    assert "".join(fragments) == text
    assert all(len(fragment.encode("utf-8")) <= 8_192 for fragment in fragments)


def test_runtime_snapshot_limits_distinct_native_tools_and_keeps_only_bounded_events() -> None:
    """The ninth distinct native tool ends projection after the eight-item event budget."""

    runtime = _SnapshotRuntime()
    runtime.snapshot_response = httpx.Response(
        200,
        json={
            "data": [
                {
                    "info": {"id": "message-many-tools", "type": "assistant"},
                    "parts": [
                        {"id": f"tool-{index}", "type": "tool", "name": "workspace.summary"}
                        for index in range(9)
                    ],
                }
            ]
        },
    )
    outcome: dict[str, object] = {}

    events = _consume_snapshot(runtime, outcome)

    assert outcome["status"] == "failed"
    assert len(events) == 8
    assert all(event["type"] == "tool" for event in events)


def test_runtime_snapshot_projects_only_safe_native_search_heading_links() -> None:
    """Native search prose can add bounded HTTPS links, while secret query links are omitted."""

    runtime = _SnapshotRuntime()
    runtime.snapshot_response = httpx.Response(
        200,
        json={
            "data": [
                {
                    "info": {"id": "message-search", "type": "assistant"},
                    "parts": [
                        {
                            "id": "search-1",
                            "type": "tool",
                            "name": "websearch",
                            "state": {
                                "status": "completed",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": (
                                            "## [Result](https://EXAMPLE.test/story)\n\n"
                                            "## [Secret](https://example.test/a?token=hidden)\n"
                                        ),
                                    }
                                ],
                            },
                        }
                    ],
                }
            ]
        },
    )

    events = _consume_snapshot(runtime, {})
    sources = [event["data"] for event in events if event["type"] == "source"]

    assert len(sources) == 1
    assert sources[0]["url"] == "https://example.test/story"
    assert "hidden" not in repr(sources)


@pytest.mark.parametrize(
    ("payload", "expected_status"),
    (
        ({"data": [None]}, "invalid_response"),
        ({"data": [{"sessionID": "sesForeignSession123"}]}, "invalid_scope"),
        ({"data": [None] * 4_097}, "too_many_messages"),
    ),
)
def test_failure_summary_rejects_malformed_foreign_and_oversized_snapshots(
    payload: dict[str, object], expected_status: str
) -> None:
    """Failure diagnostics report only a closed status for invalid or excessive worker data."""

    summary = _summarize_native_failure_payload(
        payload,
        session_id="d" * 32,
        approved_fetch_urls={},
    )

    assert summary["snapshot_status"] == expected_status
    assert "private" not in repr(summary)


def test_failure_snapshot_collapses_nested_errors_and_fetch_state_to_closed_labels() -> None:
    """Terminal worker details reduce to bounded categories, counts, and approval status."""

    payload = {
        "data": [
            {
                "info": {
                    "id": "message-error",
                    "role": "assistant",
                    "finish": "unexpected-private-finish",
                    "error": {
                        "name": "TypeError",
                        "message": "private diagnostic must not survive",
                    },
                },
                "parts": [
                    {
                        "id": "fetch-error",
                        "type": "tool",
                        "name": "webfetch",
                        "time": {"ran": 1_000, "completed": 1_400},
                        "state": {
                            "status": "error",
                            "code": "EAI_AGAIN",
                            "message": "DNS lookup timed out at private-host.invalid",
                            "input": {"url": "https://private.example.test/a", "timeout": 9},
                        },
                    },
                    {
                        "id": "fetch-unapproved",
                        "type": "tool",
                        "name": "webfetch",
                        "state": {
                            "status": "completed",
                            "input": {"url": "https://public.example.test/article"},
                            "metadata": {"finalUrl": "https://public.example.test/article"},
                        },
                    },
                    {
                        "id": "fetch-invalid",
                        "type": "tool",
                        "name": "webfetch",
                        "state": {
                            "status": "completed",
                            "input": {"url": "file:///private/path"},
                            "metadata": {"finalUrl": "file:///private/path"},
                        },
                    },
                    {
                        "id": "fetch-unapproved-2",
                        "type": "tool",
                        "name": "webfetch",
                        "state": {
                            "status": "completed",
                            "input": {"url": "https://another.example.test/article"},
                            "metadata": {"finalUrl": "https://another.example.test/article"},
                        },
                    },
                    {
                        "id": "tool-other",
                        "type": "tool",
                        "name": "workspace.summary",
                        "state": {"status": "failed", "statusCode": 503},
                    },
                ],
            },
            {"info": {"id": "user-message", "role": "user"}, "content": []},
        ]
    }

    summary = _summarize_native_failure_payload(
        payload,
        session_id="sesBoundary123",
        approved_fetch_urls={"https://public.example.test/article": 1},
    )

    assert summary["snapshot_status"] == "read"
    assert summary["assistant_finish"] == "other"
    assert summary["assistant_failure_categories"] == "native_defect"
    assert summary["assistant_error_count"] == 1
    assert summary["webfetch_state"] == "completed,error"
    assert summary["webfetch_failure_categories"] == "dns"
    assert summary["webfetch_timeout_stage"] == "dns_lookup_timeout"
    assert summary["webfetch_timeout_seconds_max"] == "9"
    assert summary["webfetch_tool_elapsed_ms_max"] == 400
    assert summary["webfetch_completion_categories"] == (
        "approval_missing,approved_destination_present,request_invalid"
    )
    assert summary["native_failure_categories"] == "dns,http"
    assert summary["native_tool_error_count"] == 2
    assert "private diagnostic" not in repr(summary)
    assert "private.example.test" not in repr(summary)
    assert "file:///private/path" not in repr(summary)


class _ProxyChunks:
    """Yield synthetic upstream frames and record deterministic iterator cleanup."""

    def __init__(self, chunks: list[object], failure: Exception | None = None) -> None:
        self.chunks = list(chunks)
        self.failure = failure
        self.closed = False

    def __aiter__(self) -> _ProxyChunks:
        return self

    async def __anext__(self) -> bytes:
        if self.chunks:
            return cast(bytes, self.chunks.pop(0))
        if self.failure is not None:
            raise self.failure
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("chunks", "failure", "current"),
    (
        ([b"first frame"], RuntimeError("private provider URL"), True),
        (["not-bytes"], None, True),
        ([b"x" * (32 * 1024 + 1)], None, True),
        ([b"frame after revocation"], None, False),
    ),
)
def test_provider_http_stream_fails_closed_and_closes_its_iterator(
    chunks: list[object], failure: Exception | None, current: bool
) -> None:
    """Provider stream failure, malformed chunks, and revoked turns never become clean EOF."""

    upstream = _ProxyChunks(chunks, failure)
    emitted: list[bytes] = []

    async def consume() -> None:
        async for chunk in assistant_api._provider_proxy_chunks(upstream, lambda: current):
            emitted.append(chunk)

    with pytest.raises(AssistantUnavailable) as rejected:
        asyncio.run(consume())

    assert rejected.value.code == "provider_unavailable"
    assert "private provider URL" not in str(rejected.value)
    assert upstream.closed is True
    assert emitted == ([b"first frame"] if failure is not None else [])


def test_provider_http_stream_enforces_aggregate_output_limit_and_closes_iterator() -> None:
    """Many bounded frames still stop once a single response crosses its total budget."""

    upstream = _ProxyChunks([b"x" * (32 * 1024)] * 33)
    emitted: list[bytes] = []

    async def consume() -> None:
        async for chunk in assistant_api._provider_proxy_chunks(upstream, lambda: True):
            emitted.append(chunk)

    with pytest.raises(AssistantUnavailable) as rejected:
        asyncio.run(consume())

    assert rejected.value.code == "provider_unavailable"
    assert sum(map(len, emitted)) == 1_048_576
    assert upstream.closed is True


def test_internal_provider_api_binds_proxy_to_durable_owner_turn_and_session(
    settings: Settings,
) -> None:
    """The private proxy checks the bearer lease, request contract, and live owner session."""

    now = datetime.now(UTC).replace(microsecond=0)
    app, providers = _http_test_app(settings, now)
    with TestClient(app, client=("127.0.0.1", 51_109)) as client:
        identity = _add_http_test_user(app, now)
        client.cookies.set(SESSION_COOKIE_NAME, str(identity["token"]), path="/")
        client.cookies.set(CSRF_COOKIE_NAME, str(identity["csrf"]), path="/")
        turn, capability, _conversation_id = _http_running_turn(client, app, identity, now)
        execution_id = str(turn["execution_id"])
        path = f"/api/v1/assistant/internal/provider/{execution_id}/chat/completions"
        headers = {
            "authorization": f"Bearer {capability}",
            "session-id": "sesBoundaryNative123",
            "content-type": "application/json",
        }
        body = {
            "model": "assistant-selected",
            "messages": [{"role": "user", "content": "Summarize this safely."}],
            "stream": True,
        }

        client.cookies.clear()
        wrong_capability = client.post(
            path,
            headers={**headers, "authorization": "Bearer " + "x" * 48},
            json=body,
        )
        malformed_json = client.post(
            path,
            headers={**headers, "content-type": "application/json"},
            content=b"{not-json",
        )
        invalid_contract = client.post(path, headers=headers, json={**body, "model": "forged"})
        complete = client.post(path, headers=headers, json=body)

        assert wrong_capability.status_code == 404
        assert malformed_json.status_code == 400
        assert invalid_contract.status_code == 422
        assert complete.status_code == 200, complete.text
        assert complete.headers["cache-control"] == "no-store"
        assert complete.headers["x-accel-buffering"] == "no"
        assert b'"content":"fixture"' in complete.content
        assert complete.content.endswith(b"data: [DONE]\n\n")
        assert len(providers.calls) == 1
        provider_id, model_id, forwarded, context = providers.calls[0]
        assert (provider_id, model_id) == (_HTTP_MODEL.provider_id, _HTTP_MODEL.model_id)
        assert forwarded["model"] == "assistant-selected"
        assert context["owner_id"] == identity["user_id"]
        assert context["app_session_id"] == identity["session_id"]
        assert context["native_session_id"] == "sesBoundaryNative123"
        assert context["authorization_check"]() is True

        with app.state.repository.connect() as connection:
            connection.execute(
                "UPDATE sessions SET revoked_at = ? WHERE token_hash = ?",
                (now.isoformat(), identity["token_hash"]),
            )
            connection.commit()
        assert context["authorization_check"]() is False


def test_internal_native_provider_api_bounds_body_and_maps_unavailable_proxy(
    settings: Settings,
) -> None:
    """The vendor-native loopback route bounds JSON before invoking the provider manager."""

    now = datetime.now(UTC).replace(microsecond=0)
    app, providers = _http_test_app(settings, now)
    proxy_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    mode = "stream"

    def proxy_native_stream(*args: object, **kwargs: object) -> object:
        proxy_calls.append((args, cast(dict[str, object], kwargs)))
        if mode == "bad-contract":
            raise ProviderUnavailable("provider_request_invalid")
        if mode == "unavailable":
            return object()

        async def chunks() -> AsyncIterator[bytes]:
            yield b"event: response.completed\ndata: {}\n\n"

        return chunks()

    providers.proxy_native_stream = proxy_native_stream  # type: ignore[attr-defined]
    with TestClient(app, client=("127.0.0.1", 51_109)) as client:
        identity = _add_http_test_user(app, now)
        client.cookies.set(SESSION_COOKIE_NAME, str(identity["token"]), path="/")
        client.cookies.set(CSRF_COOKIE_NAME, str(identity["csrf"]), path="/")
        turn, capability, _conversation_id = _http_running_turn(client, app, identity, now)
        client.cookies.clear()
        execution_id = str(turn["execution_id"])
        path = f"/api/v1/assistant/internal/provider/{execution_id}/v1/responses"
        headers = {
            "authorization": f"Bearer {capability}",
            "session-id": "sesBoundaryNative123",
            "content-type": "application/json",
        }
        duplicate_json = client.post(
            path,
            headers=headers,
            content=b'{"model":"assistant-selected","model":"forged"}',
        )
        assert duplicate_json.status_code == 422
        assert proxy_calls == []

        valid = client.post(
            path,
            headers=headers,
            json={"model": "assistant-selected", "input": []},
        )
        assert valid.status_code == 200, valid.text
        assert valid.headers["cache-control"] == "no-store"
        assert valid.content == b"event: response.completed\ndata: {}\n\n"
        assert len(proxy_calls) == 1
        assert proxy_calls[0][0][:3] == (
            _HTTP_MODEL.provider_id,
            _HTTP_MODEL.model_id,
            {
                "model": "assistant-selected",
                "input": [],
            },
        )
        assert proxy_calls[0][1]["owner_id"] == identity["user_id"]
        assert proxy_calls[0][1]["app_session_id"] == identity["session_id"]
        assert proxy_calls[0][1]["native_session_id"] == "sesBoundaryNative123"

        mode = "bad-contract"
        invalid = client.post(
            path,
            headers=headers,
            json={"model": "assistant-selected", "input": []},
        )
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "invalid_provider_request"

        mode = "unavailable"
        unavailable = client.post(
            path,
            headers=headers,
            json={"model": "assistant-selected", "input": []},
        )
        assert unavailable.status_code == 503
        assert unavailable.json()["error"]["code"] == "provider_unavailable"

        oversized = client.post(
            path,
            headers=headers,
            content=b'{"input":"' + b"x" * 262_144 + b'"}',
        )
        assert oversized.status_code == 413


def test_public_event_stream_validates_cursors_and_closes_failed_turn_without_completion(
    settings: Settings,
) -> None:
    """Owner SSE replay rejects cursor ambiguity and supplies a terminal completion frame."""

    now = datetime.now(UTC).replace(microsecond=0)
    app, _providers = _http_test_app(settings, now)
    with TestClient(app, client=("127.0.0.1", 51_109)) as client:
        identity = _add_http_test_user(app, now)
        client.cookies.set(SESSION_COOKIE_NAME, str(identity["token"]), path="/")
        client.cookies.set(CSRF_COOKIE_NAME, str(identity["csrf"]), path="/")
        turn, _capability, conversation_id = _http_running_turn(client, app, identity, now)
        turn_id = str(turn["id"])
        path = f"/api/v1/assistant/conversations/{conversation_id}/turns/{turn_id}/events"

        malformed = client.get(path, headers={"last-event-id": "1.5"})
        conflict = client.get(path, params={"after": 1}, headers={"last-event-id": "0"})
        ahead = client.get(path, params={"after": 2})
        assert malformed.status_code == 422
        assert malformed.json()["error"]["code"] == "invalid_event_cursor"
        assert conflict.status_code == 422
        assert conflict.json()["error"]["code"] == "conflicting_event_cursor"
        assert ahead.status_code == 409
        assert ahead.json()["error"]["code"] == "event_cursor_ahead"

        app.state.assistant.storage.append_event(
            int(identity["user_id"]),
            conversation_id,
            turn_id,
            event_type="token",
            data={"text": "A saved test answer."},
            now=now,
        )
        app.state.assistant.storage.set_turn_status(
            int(identity["user_id"]),
            conversation_id,
            turn_id,
            status="failed",
            now=now,
        )
        replay = client.get(path)

        assert replay.status_code == 200
        assert replay.headers["cache-control"] == "no-store"
        assert 'event: token\ndata: {"text":"A saved test answer."}' in replay.text
        assert 'event: complete\ndata: {"status": "failed"}' in replay.text


class _FakeReader:
    """Expose one bounded supervisor response frame to its client."""

    def __init__(self, frame: bytes) -> None:
        self.frame = frame

    async def readuntil(self, separator: bytes) -> bytes:
        assert separator == b"\n"
        return self.frame

    async def read(self, amount: int) -> bytes:
        assert amount == 1
        return b""


class _FakeWriter:
    """Capture the local supervisor request and prove client cleanup happened."""

    def __init__(self) -> None:
        self.closed = False
        self.request = b""

    def get_extra_info(self, name: str) -> object:
        assert name == "socket"
        return object()

    def write(self, value: bytes) -> None:
        self.request += value

    async def drain(self) -> None:
        return None

    def write_eof(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


def test_supervisor_client_rejects_oversized_requests_before_socket_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller cannot force the fixed local control socket to accept an oversized frame."""

    def socket_must_not_be_checked() -> None:
        raise AssertionError("oversized payload must be rejected before socket access")

    monkeypatch.setattr(supervisor_client, "_validate_socket_path", socket_must_not_be_checked)
    payload = {"padding": "x" * supervisor_client.REQUEST_LIMIT}

    with pytest.raises(supervisor_client.SupervisorClientError, match="request_too_large"):
        asyncio.run(supervisor_client.SupervisorClient()._request(payload))


def test_supervisor_client_sanitizes_unknown_error_codes_and_closes_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unrecognized supervisor text is not relayed to the app or retained in the socket."""

    writer = _FakeWriter()
    reader = _FakeReader(b'{"ok":false,"error":"credential=private-value"}\n')

    async def open_connection(*args: object, **kwargs: object) -> tuple[_FakeReader, _FakeWriter]:
        del args, kwargs
        return reader, writer

    monkeypatch.setattr(supervisor_client, "_validate_socket_path", lambda: None)
    monkeypatch.setattr(
        supervisor_client, "_peer_uid", lambda _peer: supervisor_client.SOCKET_OWNER_UID
    )
    monkeypatch.setattr(supervisor_client.asyncio, "open_unix_connection", open_connection)

    with pytest.raises(supervisor_client.SupervisorClientError) as rejected:
        asyncio.run(supervisor_client.SupervisorClient()._request({"op": "status"}))

    assert rejected.value.code == "request_rejected"
    assert "private-value" not in str(rejected.value)
    assert writer.closed is True
    assert b'"op":"status"' in writer.request


def test_supervisor_status_accepts_fixed_worker_identity_and_only_true_guard_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful local status projects the fixed URL and capability without extra fields."""

    response = {
        "ok": True,
        "status": "ready",
        "api_url": supervisor_client.WORKER_API_URL,
        "api_password": "A" * 32,
        "observation_uncertain": False,
        "webfetch_guard_ready": True,
        "private": "drop me",
    }
    writer = _FakeWriter()
    reader = _FakeReader(json.dumps(response, separators=(",", ":")).encode() + b"\n")

    async def open_connection(*_args: object, **_kwargs: object) -> tuple[_FakeReader, _FakeWriter]:
        return reader, writer

    monkeypatch.setattr(supervisor_client, "_validate_socket_path", lambda: None)
    monkeypatch.setattr(
        supervisor_client, "_peer_uid", lambda _peer: supervisor_client.SOCKET_OWNER_UID
    )
    monkeypatch.setattr(supervisor_client.asyncio, "open_unix_connection", open_connection)

    result = asyncio.run(supervisor_client.SupervisorClient().status())

    assert result == {
        "ok": True,
        "status": "ready",
        "api_url": supervisor_client.WORKER_API_URL,
        "api_password": "A" * 32,
        "webfetch_guard_ready": True,
        "observation_uncertain": False,
    }
    assert writer.closed is True


def test_supervisor_peer_identity_rejects_missing_or_unreadable_credentials() -> None:
    """The supervisor IPC client requires kernel peer credentials and maps read failures."""

    with pytest.raises(
        supervisor_client.SupervisorClientError, match="peer_credentials_unavailable"
    ):
        supervisor_client._peer_uid(object())

    class _BrokenPeer:
        def getsockopt(self, *_args: int) -> bytes:
            raise OSError("private socket detail")

    with pytest.raises(
        supervisor_client.SupervisorClientError, match="peer_credentials_unavailable"
    ):
        supervisor_client._peer_uid(_BrokenPeer())


def _write_expiring_opencode_credential(
    manager: AssistantProviderManager, owner_id: int, *, expires: int
) -> Path:
    """Install a synthetic owner-bound Console credential and return its encrypted path."""

    manager._write_oauth_credential(
        "opencode",
        "device",
        owner_id,
        {
            "type": "oauth",
            "methodID": "device",
            "access": "synthetic-expiring-access",
            "refresh": "synthetic-expiring-refresh",
            "expires": expires,
            "metadata": {
                "server": "https://opencode.ai/console",
                "accountID": f"synthetic-account-{owner_id}",
                "orgID": "synthetic-old-org",
                "orgName": "Old organization label",
            },
        },
    )
    return manager._oauth_credential_path("opencode", owner_id, "device")


def test_opencode_refresh_rotates_only_the_authorized_owner_vault_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fixed synthetic refresh response is validated before encrypted owner storage."""

    now = 1_800_000_000
    monkeypatch.setattr(provider_module, "time", SimpleNamespace(time=lambda: now))
    manager = _manager(tmp_path)
    target_path = _write_expiring_opencode_credential(manager, 71, expires=(now - 1) * 1000)
    other_path = _write_expiring_opencode_credential(manager, 72, expires=(now + 3600) * 1000)
    other_ciphertext = other_path.read_bytes()
    requests: list[tuple[str, dict[str, object]]] = []

    class _Response:
        status_code = 200
        content = json.dumps(
            {
                "access_token": "synthetic-refreshed-access",
                "refresh_token": "synthetic-refreshed-refresh",
                "expires_in": 3600,
                "org_id": "synthetic-new-org",
            },
            separators=(",", ":"),
        ).encode()

    async def refresh(url: str, **kwargs: object) -> _Response:
        requests.append((url, dict(kwargs)))
        return _Response()

    monkeypatch.setattr(provider_module, "request_public_https", refresh)
    checks = 0

    def authorize() -> bool:
        nonlocal checks
        checks += 1
        return True

    current = manager._owned_opencode_credential(71)
    assert current is not None
    updated = asyncio.run(manager._refresh_opencode_credential_if_needed(71, current, authorize))

    assert checks == 3
    assert requests[0][0] == "https://opencode.ai/console/auth/device/token"
    assert requests[0][1]["method"] == "POST"
    assert json.loads(bytes(requests[0][1]["body"])) == {
        "grant_type": "refresh_token",
        "refresh_token": "synthetic-expiring-refresh",
        "client_id": provider_module._OPENCODE_CLIENT_ID,
    }
    assert updated["access"] == "synthetic-refreshed-access"
    assert updated["metadata"] == {
        "server": "https://opencode.ai/console",
        "accountID": "synthetic-account-71",
        "orgID": "synthetic-new-org",
        "orgName": "synthetic-new-org",
    }
    assert b"synthetic-refreshed-access" not in target_path.read_bytes()
    persisted = manager._read_oauth_credential("opencode", "device", 71)
    assert persisted == updated
    assert other_path.read_bytes() == other_ciphertext


def test_opencode_refresh_does_not_replace_vault_after_session_revocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session revoked during refresh egress cannot persist rotated bearer material."""

    now = 1_800_000_000
    monkeypatch.setattr(provider_module, "time", SimpleNamespace(time=lambda: now))
    manager = _manager(tmp_path)
    target_path = _write_expiring_opencode_credential(manager, 71, expires=(now - 1) * 1000)
    original = target_path.read_bytes()
    authorized = True
    requests: list[str] = []

    class _Response:
        status_code = 200
        content = (
            b'{"access_token":"synthetic-new-access",'
            b'"refresh_token":"synthetic-new-refresh","expires_in":3600}'
        )

    async def refresh(url: str, **_kwargs: object) -> _Response:
        nonlocal authorized
        requests.append(url)
        authorized = False
        return _Response()

    monkeypatch.setattr(provider_module, "request_public_https", refresh)
    current = manager._owned_opencode_credential(71)
    assert current is not None

    with pytest.raises(CredentialRejected, match="oauth_authorization_required"):
        asyncio.run(manager._refresh_opencode_credential_if_needed(71, current, lambda: authorized))

    assert requests == ["https://opencode.ai/console/auth/device/token"]
    assert target_path.read_bytes() == original
    assert manager._read_oauth_credential("opencode", "device", 71)["refresh"] == (
        "synthetic-expiring-refresh"
    )


@pytest.mark.parametrize(
    ("status_code", "error_type", "error_code"),
    (
        (401, CredentialRejected, "oauth_connection_required"),
        (429, ProviderUnavailable, "oauth_refresh_unavailable"),
    ),
)
def test_opencode_refresh_maps_remote_status_without_disclosing_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    error_type: type[Exception],
    error_code: str,
) -> None:
    """Rejected and transient refresh statuses keep the old encrypted credential intact."""

    now = 1_800_000_000
    monkeypatch.setattr(provider_module, "time", SimpleNamespace(time=lambda: now))
    manager = _manager(tmp_path)
    path = _write_expiring_opencode_credential(manager, 71, expires=(now - 1) * 1000)
    old = path.read_bytes()

    class _Response:
        def __init__(self) -> None:
            self.status_code = status_code
            self.content = b"private synthetic upstream response"

    async def respond(_url: str, **_kwargs: object) -> _Response:
        return _Response()

    monkeypatch.setattr(provider_module, "request_public_https", respond)
    current = manager._owned_opencode_credential(71)
    assert current is not None

    with pytest.raises(error_type) as rejected:
        asyncio.run(manager._refresh_opencode_credential_if_needed(71, current, lambda: True))

    assert rejected.value.code == error_code
    assert "private synthetic upstream response" not in str(rejected.value)
    assert path.read_bytes() == old


@pytest.mark.parametrize(
    ("status_code", "payload", "expected"),
    (
        (503, {"data": []}, "http_error"),
        (200, {"data": "not-an-array"}, "invalid_response"),
    ),
)
def test_runtime_terminal_snapshot_sanitizes_http_and_payload_failures(
    status_code: int, payload: object, expected: str
) -> None:
    """Worker failure snapshots retain a closed failure label instead of response details."""

    runtime = _SnapshotRuntime()
    runtime.snapshot_response = httpx.Response(status_code, json=payload)
    result = asyncio.run(
        runtime._read_native_terminal_failure_snapshot(
            "sesBoundary123",
            started=time.monotonic(),
            approved_fetch_urls={},
        )
    )

    assert result["snapshot_status"] == expected
    assert "private" not in repr(result)


@pytest.mark.parametrize(
    "failure", (TimeoutError("private timeout"), RuntimeError("private error"))
)
def test_runtime_terminal_snapshot_collapses_transport_exceptions(failure: Exception) -> None:
    """Timeout and unexpected worker read failures become distinct closed states."""

    runtime = _SnapshotRuntime()

    async def fail(_method: str, _path: str, **_kwargs: object) -> httpx.Response:
        raise failure

    runtime._request = fail  # type: ignore[method-assign]
    result = asyncio.run(
        runtime._read_native_terminal_failure_snapshot(
            "sesBoundary123",
            started=time.monotonic(),
            approved_fetch_urls={},
        )
    )

    assert result["snapshot_status"] == (
        "timeout" if isinstance(failure, TimeoutError) else "unavailable"
    )
    assert "private" not in repr(result)


def test_runtime_terminal_snapshot_skips_network_after_turn_deadline() -> None:
    """A terminal diagnostic at the hard turn deadline performs no worker request."""

    runtime = _SnapshotRuntime()

    async def forbidden(*_args: object, **_kwargs: object) -> httpx.Response:
        raise AssertionError("expired turns must skip native snapshot I/O")

    runtime._request = forbidden  # type: ignore[method-assign]
    result = asyncio.run(
        runtime._read_native_terminal_failure_snapshot(
            "sesBoundary123",
            started=0.0,
            approved_fetch_urls={},
        )
    )

    assert result["snapshot_status"] == "skipped_deadline"


def test_runtime_wait_reports_terminal_failure_and_rejects_unresolved_state() -> None:
    """The worker wait endpoint distinguishes terminal failure from an incomplete response."""

    runtime = _SnapshotRuntime()
    runtime.snapshot_response = httpx.Response(200, json={"data": {"status": "failed"}})
    assert asyncio.run(runtime._wait_until_idle("sesBoundary123", 2.0)) is False
    runtime.snapshot_response = httpx.Response(200, json={"data": {"status": "busy"}})
    with pytest.raises(RuntimeError, match="session_wait_incomplete"):
        asyncio.run(runtime._wait_until_idle("sesBoundary123", 2.0))
    runtime.snapshot_response = httpx.Response(204)
    assert asyncio.run(runtime._wait_until_idle("sesBoundary123", 2.0)) is True


def test_runtime_permission_reply_failure_rolls_back_one_time_fetch_approval() -> None:
    """A failed native reply cannot leave an exact fetch URL approved for later reuse."""

    url = "https://public.example.test/article"
    requests: list[tuple[str, str, dict[str, object]]] = []

    async def approve(
        _context: AssistantTurnContext, requested_url: str, _emit: object
    ) -> str | None:
        return requested_url

    class _PermissionRuntime(OpenCodeV2Runtime):
        def __init__(self) -> None:
            super().__init__(
                cast(Settings, SimpleNamespace(assistant_enabled=True)),
                providers=object(),
                catalog=object(),
                webfetch_approval=approve,
            )

        async def _request(
            self,
            method: str,
            path: str,
            **kwargs: object,
        ) -> httpx.Response:
            requests.append((method, path, cast(dict[str, object], kwargs)))
            if method == "GET" and path.endswith("/message"):
                return httpx.Response(200, json={"data": []})
            if method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            None,
                            {"id": "invalid id", "sessionID": "sesBoundary123"},
                            {"id": "perm-foreign", "sessionID": "sesForeign123"},
                            {
                                "id": "perm-fetch-1",
                                "sessionID": "sesBoundary123",
                                "action": "webfetch",
                                "resources": [url],
                            },
                        ]
                    },
                )
            return httpx.Response(503, json={"error": "private supervisor detail"})

    runtime = _PermissionRuntime()
    outcome: dict[str, object] = {"approved_fetch_urls": {}}

    async def emit(_event: dict[str, object]) -> None:
        return None

    with pytest.raises(RuntimeError, match="permission_reply_failed"):
        asyncio.run(
            runtime._poll_permissions(
                "sesBoundary123",
                cast(AssistantTurnContext, object()),
                emit,
                asyncio.Event(),
                outcome,
                time.monotonic(),
            )
        )

    permission_requests = [
        request
        for request in requests
        if request[0:2] == ("GET", "/api/session/sesBoundary123/permission")
    ]
    reply_requests = [
        request
        for request in requests
        if request[0:2] == ("POST", "/api/session/sesBoundary123/permission/perm-fetch-1/reply")
    ]
    assert len(permission_requests) == 1
    assert len(reply_requests) == 1
    assert reply_requests[0][2]["json"] == {"decision": "once"}
    assert outcome["approved_fetch_urls"] == {}


def _turn_context(execution_id: str = "a" * 32) -> AssistantTurnContext:
    """Build one safe context for runtime preflight rejection cases."""

    return AssistantTurnContext(
        user_id=71,
        app_id="signal-ledger",
        conversation_id="b" * 36,
        turn_id="c" * 36,
        execution_id=execution_id,
        capability="d" * 48,
        model_id=_HTTP_MODEL.model_id,
        policy_version=_HTTP_MODEL.policy_version,
        context_version="e" * 64,
        page_context={"route": "/overview"},
        history=(),
    )


def test_runtime_turn_preflight_rejects_worker_inventory_model_and_policy_failures() -> None:
    """Runtime preflight stops safely before location creation on every failed dependency."""

    class _Catalog:
        def __init__(self, result: object = (_HTTP_MODEL,), failure: bool = False) -> None:
            self.result = result
            self.failure = failure

        async def ensure_fresh(self, **_kwargs: object) -> object:
            if self.failure:
                raise RuntimeError("private catalog diagnostic")
            return self.result

    class _Providers:
        def __init__(self, state: object = {"usable": True}, failure: bool = False) -> None:
            self.state = state
            self.failure = failure

        def model_policy_state(self, *_args: object, **_kwargs: object) -> object:
            if self.failure:
                raise RuntimeError("private policy diagnostic")
            return self.state

    class _PreflightRuntime(OpenCodeV2Runtime):
        def __init__(self, catalog: object, providers: object, *, ready: bool = True) -> None:
            super().__init__(
                cast(Settings, SimpleNamespace(assistant_enabled=True)),
                providers=providers,
                catalog=catalog,
            )
            self.ready = ready
            self.locations_started = 0

        async def start(self, *, preserve_ready: bool = False) -> object:
            del preserve_ready
            self._status = SimpleNamespace(status="ready" if self.ready else "unavailable")
            self._client = object() if self.ready else None
            self._enabled = self.ready
            return self._status

        def _model_for_turn(self, _context: AssistantTurnContext) -> object:
            return _HTTP_MODEL

        def _native_adapter_for_model(self, _model_id: str, *, owner_id: int) -> object:
            del owner_id
            return object()

        async def _prepare_location(self, *_args: object) -> str:
            self.locations_started += 1
            raise AssertionError("preflight rejection must happen before location creation")

    async def emit(_event: Mapping[str, object]) -> None:
        return None

    async def run(
        *,
        catalog: object,
        providers: object,
        ready: bool = True,
        adapter_failure: bool = False,
        locked: bool = False,
        execution_id: str = "a" * 32,
        prompt: str = "A safe test prompt.",
    ) -> tuple[object, int]:
        runtime = _PreflightRuntime(catalog, providers, ready=ready)
        if adapter_failure:

            def reject_adapter(*_args: object, **_kwargs: object) -> object:
                raise runtime_module._AssistantRuntimeFailure(
                    "native_adapter_invalid", "model_discovery"
                )

            runtime._native_adapter_for_model = reject_adapter  # type: ignore[method-assign]
        if locked:
            lock = asyncio.Lock()
            await lock.acquire()
            runtime._locks[execution_id] = lock
        result = await runtime._run_turn_impl(
            context=_turn_context(execution_id), prompt=prompt, emit=emit
        )
        return result, runtime.locations_started

    cases = (
        (run(catalog=_Catalog(failure=True), providers=_Providers()), "provider_unavailable"),
        (run(catalog=_Catalog(result=()), providers=_Providers()), "provider_unavailable"),
        (
            run(catalog=_Catalog(), providers=_Providers(failure=True)),
            "provider_unavailable",
        ),
        (
            run(catalog=_Catalog(), providers=_Providers(state={"usable": False})),
            "provider_unavailable",
        ),
        (
            run(
                catalog=_Catalog(),
                providers=_Providers(),
                adapter_failure=True,
            ),
            "provider_unavailable",
        ),
        (run(catalog=_Catalog(), providers=_Providers(), ready=False), "worker_unavailable"),
        (run(catalog=_Catalog(), providers=_Providers(), locked=True), "provider_unavailable"),
        (
            run(
                catalog=_Catalog(),
                providers=_Providers(),
                execution_id="invalid-execution",
            ),
            "provider_unavailable",
        ),
        (run(catalog=_Catalog(), providers=_Providers(), prompt=" \n"), "provider_unavailable"),
    )

    async def exercise() -> list[tuple[object, int]]:
        return await asyncio.gather(*[case[0] for case in cases])

    results = asyncio.run(exercise())

    for (result, locations_started), (_pending, expected_error) in zip(results, cases, strict=True):
        assert result.status == "failed"
        assert result.error_code == expected_error
        assert locations_started == 0


def test_oauth_method_and_connection_projections_reject_unadvertised_capabilities() -> None:
    """The API exposes only fixed OAuth capabilities and omits manager-private fields."""

    browser = {
        "integration_id": "openai",
        "method_id": "chatgpt-browser",
        "label": "ChatGPT browser sign-in",
        "mode": "browser",
        "connection_status": "available",
        "connection_supported": True,
        "model_access_supported": True,
        "availability_reason": None,
        "authorization_url": "https://auth.openai.com/oauth/authorize",
        "private_token": "must-not-cross-the-response-boundary",
    }
    projected_browser = assistant_api._oauth_method_response(browser)
    assert projected_browser == {
        "integration_id": "openai",
        "method_id": "chatgpt-browser",
        "label": "ChatGPT browser sign-in",
        "mode": "browser",
        "connection_status": "available",
        "connection_supported": True,
        "model_access_supported": True,
        "availability_reason": None,
    }
    device = {
        **browser,
        "integration_id": "opencode",
        "method_id": "device",
        "label": "OpenCode device sign-in",
        "mode": "device",
        "model_access_supported": False,
        "availability_reason": "oauth_proxy_pending",
    }
    assert assistant_api._oauth_method_response(device)["model_access_supported"] is False
    headless = {**browser, "method_id": "chatgpt-headless", "mode": "device"}
    assert assistant_api._oauth_method_response(headless)["mode"] == "device"
    for invalid in (
        {**browser, "label": "\u200bhidden label"},
        {**browser, "connection_status": "Connected!"},
        {**browser, "connection_supported": 1},
        {**browser, "model_access_supported": False},
        {**device, "availability_reason": "provider returned private error"},
    ):
        assert assistant_api._oauth_method_response(invalid) is None

    connection = {
        "integration_id": "openai",
        "method_id": "chatgpt-browser",
        "status": "connected",
        "model_access_supported": True,
        "availability_reason": None,
        "credential": "must-not-cross-the-response-boundary",
    }
    assert assistant_api._oauth_connection_response(connection) == {
        "integration_id": "openai",
        "method_id": "chatgpt-browser",
        "status": "connected",
        "model_access_supported": True,
        "availability_reason": None,
    }
    opencode_connection = {
        **connection,
        "integration_id": "opencode",
        "method_id": "device",
        "model_access_supported": False,
        "availability_reason": "oauth_proxy_pending",
    }
    assert assistant_api._oauth_connection_response(opencode_connection) is not None
    for invalid in (
        {**connection, "status": "pending"},
        {**connection, "method_id": "unexpected"},
        {**connection, "model_access_supported": False},
        {**opencode_connection, "availability_reason": None},
    ):
        assert assistant_api._oauth_connection_response(invalid) is None


def test_opencode_review_projection_requires_public_urls_and_closed_metadata() -> None:
    """Reviewed Console rows retain only public endpoints and recognized metadata."""

    for candidate in (
        "https://api.example.org/v1",
        "https://8.8.8.8/v1",
    ):
        assert assistant_api._opencode_public_url(candidate) == candidate
    for candidate in (
        "http://api.example.org/v1",
        "https://127.0.0.1/v1",
        "https://localhost/v1",
        "https://user:pass@api.example.org/v1",
        "https://api.example.org:8443/v1",
        "https://api.example.org/v1#token",
        "https://api.example.org\\@evil.test/v1",
        "https://api.example.org/v1\x7f",
        "not a URL",
    ):
        assert assistant_api._opencode_public_url(candidate) is None

    row = {
        "model_id": "opencode-console/" + "a" * 64,
        "provider_id": "opencode-console",
        "display_name": "Reviewed fixture model",
        "native_model_id": "fixture/model-v1",
        "adapter_id": "openai-responses",
        "protocol": "openai-responses",
        "package_id": "@opencode/ai/providers/openai",
        "endpoint": "https://api.example.org/v1",
        "config_fingerprint": "b" * 64,
        "available": True,
        "enabled": False,
        "reviewed": True,
        "usable": False,
        "revision": 2,
        "review_revision": 1,
        "billing_class": "free",
        "training_policy": "no_training",
        "confidential_data_policy": "allowed",
        "terms_url": "https://example.org/terms",
        "privacy_disclosure": "Synthetic no-training review.",
        "billing_disclosure": None,
        "privacy_policy_version": "policy-1",
        "billing_policy_version": None,
        "availability_reason": "not_enabled",
        "native_settings": {"api_key": "must-not-cross-the-response-boundary"},
    }
    projected = assistant_api._opencode_model_review_response(row)
    assert projected is not None
    assert projected["model_id"] == row["model_id"]
    assert projected["terms_url"] == row["terms_url"]
    assert "native_settings" not in projected

    for invalid in (
        {**row, "endpoint": "http://api.example.org/v1"},
        {**row, "terms_url": "https://127.0.0.1/terms"},
        {**row, "config_fingerprint": "g" * 64},
        {**row, "package_id": "@opencode/ai/providers/unknown"},
        {**row, "revision": True},
        {**row, "availability_reason": "not enabled"},
        {**row, "display_name": "hidden\u200bname"},
    ):
        assert assistant_api._opencode_model_review_response(invalid) is None


def test_native_oauth_discovery_intersects_fixed_ui_methods_and_fails_closed(
    settings: Settings, tmp_path: Path
) -> None:
    """The provider manager keeps native discovery inside its reviewed method catalog."""

    class _Runtime:
        def __init__(self, integrations: object) -> None:
            self.integrations = integrations

        async def list_native_integrations(self) -> object:
            if isinstance(self.integrations, Exception):
                raise self.integrations
            return self.integrations

    manager = AssistantProviderManager(settings, vault_dir=tmp_path, runtime=_Runtime([]))
    manager.attach_oauth_transport(lambda *_args, **_kwargs: None, lambda *_args: None)
    with pytest.raises(TypeError, match="must be callable"):
        manager.attach_oauth_transport(None, None)  # type: ignore[arg-type]

    async def discover(integrations: object) -> tuple[dict[str, object], ...]:
        manager.runtime = _Runtime(integrations)
        return await manager.list_native_oauth_methods()

    rows = asyncio.run(
        discover(
            [
                {
                    "integration_id": "openai",
                    "methods": [
                        {"method_id": "chatgpt-browser", "kind": "oauth"},
                        {"method_id": "chatgpt-headless", "kind": "oauth"},
                        {"method_id": "unsupported", "kind": "oauth"},
                        {"method_id": "chatgpt-browser", "kind": "api"},
                    ],
                },
                {
                    "integration_id": "opencode",
                    "methods": [{"method_id": "device", "kind": "oauth"}],
                },
                {
                    "integration_id": "attacker",
                    "methods": [{"method_id": "device", "kind": "oauth"}],
                },
            ]
        )
    )
    assert [(row["integration_id"], row["method_id"]) for row in rows] == [
        ("openai", "chatgpt-browser"),
        ("openai", "chatgpt-headless"),
        ("opencode", "device"),
    ]
    assert rows[-1]["model_access_supported"] is False
    assert rows[-1]["availability_reason"] == "oauth_proxy_pending"

    malformed = (
        RuntimeError("private runtime diagnostic"),
        {"not": "a list"},
        [{"integration_id": "Bad_ID", "methods": []}],
        [{"integration_id": "openai", "methods": "not a list"}],
        [{"integration_id": "openai", "methods": [{}] * 33}],
        [None],
    )
    for value in malformed:
        with pytest.raises(ProviderUnavailable, match="oauth_unavailable"):
            asyncio.run(discover(value))


def test_native_provider_request_rejects_malformed_histories_and_unreviewed_options() -> None:
    """The app-to-provider bridge accepts only bounded, declared request semantics."""

    validate = assistant_api._validated_provider_request
    base = {
        "model": "assistant-selected",
        "messages": [{"role": "user", "content": "A bounded prompt."}],
        "stream": True,
    }
    normalized = validate(
        {
            **base,
            "temperature": 1,
            "max_tokens": 32,
            "stream_options": {"include_usage": True},
            "tool_choice": "none",
        },
        [],
    )
    assert normalized is not None
    assert normalized["store"] is False
    assert normalized["temperature"] == 1.0
    assert normalized["stream_options"] == {"include_usage": True}

    app_tool = {
        "name": "inspect",
        "description": "Inspect one local item.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    }
    tool_decl = {
        "type": "function",
        "function": {
            "name": "inspect",
            "description": app_tool["description"],
            "parameters": app_tool["inputSchema"],
            "strict": False,
        },
    }
    alias_decl = {
        **tool_decl,
        "function": {**tool_decl["function"], "name": "signal-ledger_inspect"},
    }
    assert validate({**base, "tools": [tool_decl]}, [app_tool])["tools"] == [tool_decl]
    assert validate({**base, "tools": [tool_decl, alias_decl]}, [app_tool]) is None
    assert validate({**base, "tools": [{"type": "function"}]}, [app_tool]) is None
    assert (
        validate({**base, "tools": [{"type": "function", "function": "inspect"}]}, [app_tool])
        is None
    )
    assert validate({**base, "tools": [tool_decl], "tool_choice": "missing"}, [app_tool]) is None

    invalid_values: tuple[object, ...] = (
        None,
        {**base, "messages": []},
        {**base, "messages": [None]},
        {**base, "messages": [{"role": "admin", "content": "x"}]},
        {**base, "messages": [{"role": "user", "content": "\ud800"}]},
        {**base, "messages": [{"role": "user", "content": "x" * 65_537}]},
        {**base, "temperature": True},
        {**base, "temperature": float("nan")},
        {**base, "temperature": 2.1},
        {**base, "max_tokens": True},
        {**base, "max_tokens": 4097},
        {**base, "stream_options": {"include_usage": False}},
        {**base, "tools": "not a list"},
        {
            **base,
            "tools": [tool_decl],
            "messages": [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "inspect", "arguments": "{}"},
                        }
                    ],
                }
            ],
        },
    )
    for value in invalid_values:
        assert validate(value, [app_tool]) is None

    unfinished_call = {
        **base,
        "tools": [tool_decl],
        "messages": [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "inspect", "arguments": "{}"},
                    }
                ],
            },
            {"role": "user", "content": "interrupted history"},
        ],
    }
    assert validate(unfinished_call, [app_tool]) is None


def test_native_oauth_status_projects_only_terminal_and_owner_bound_states() -> None:
    """OAuth status maps native transport outcomes to a closed app-side state machine."""

    runtime = OpenCodeV2Runtime(
        cast(Settings, SimpleNamespace(assistant_enabled=True)),
        providers=SimpleNamespace(),
        catalog=SimpleNamespace(),
    )
    runtime._require_ready_worker = lambda: None  # type: ignore[method-assign]
    released: list[str] = []

    async def release(attempt_id: str) -> None:
        released.append(attempt_id)

    runtime._release_oauth_hold = release  # type: ignore[method-assign]
    requests: list[tuple[str, str]] = []
    next_response: object = None

    async def request(method: str, path: str, **_kwargs: object) -> object:
        requests.append((method, path))
        if isinstance(next_response, Exception):
            raise next_response
        return next_response

    runtime._request = request  # type: ignore[method-assign]

    def add_attempt(status: str = "pending", expires_at: float | None = None) -> str:
        attempt_id = secrets.token_hex(16)
        runtime._oauth_attempts[attempt_id] = runtime_module._NativeOAuthAttempt(
            attempt_id=attempt_id,
            native_attempt_id="native-attempt-1",
            integration_id="openai",
            method_id="chatgpt-headless",
            owner_id=71,
            session_id="d" * 32,
            expires_at=time.time() + 300 if expires_at is None else expires_at,
            url="https://auth.openai.com/codex/device",
            instructions="Use the displayed synthetic test code.",
            mode="device",
            status=status,
        )
        return attempt_id

    async def get(attempt_id: str, *, owner_id: int = 71, session_id: str = "d" * 32):
        return await runtime.native_oauth_status(
            "openai", attempt_id, owner_id=owner_id, session_id=session_id
        )

    async def exercise() -> None:
        nonlocal next_response
        assert await get("a" * 32) == "cancelled"
        with pytest.raises(RuntimeError, match="native_oauth_attempt_unavailable"):
            await runtime.native_oauth_status(
                None,
                "a" * 32,
                owner_id=71,
                session_id="d" * 32,  # type: ignore[arg-type]
            )

        handoff = add_attempt("handoff_ready")
        assert await get(handoff) == "handoff_ready"
        starting = add_attempt("starting")
        assert await get(starting) == "pending"
        terminal = add_attempt("cancelled")
        assert await get(terminal) == "cancelled"
        foreign = add_attempt()
        with pytest.raises(RuntimeError, match="native_oauth_attempt_unavailable"):
            await get(foreign, session_id="e" * 32)
        with pytest.raises(RuntimeError, match="native_oauth_attempt_unavailable"):
            await get(foreign, owner_id=72)

        expired = add_attempt(expires_at=time.time() - 1)
        assert await get(expired) == "expired"
        assert expired not in runtime._oauth_attempts
        assert expired in released

        timeout_attempt = add_attempt()
        request_faults: tuple[object, ...] = (
            TimeoutError("private timeout"),
            httpx.TimeoutException("private transport timeout"),
        )
        for fault in request_faults:
            next_response = fault
            assert await get(timeout_attempt) == "pending"

        removed = add_attempt()
        next_response = httpx.Response(404, json={"message": "private body"})
        assert await get(removed) == "cancelled"
        assert removed not in runtime._oauth_attempts
        assert removed in released

        next_response = httpx.Response(503, json={"message": "private body"})
        assert await get(add_attempt()) == "pending"
        next_response = httpx.Response(400, json={"message": "private body"})
        with pytest.raises(RuntimeError, match="native_oauth_status_failed"):
            await get(add_attempt())
        next_response = httpx.Response(200, json={"data": {"status": "complete"}})
        completed = add_attempt()
        assert await get(completed) == "handoff_ready"
        assert runtime._oauth_attempts[completed].status == "handoff_ready"
        next_response = httpx.Response(200, json={"data": {"status": "failed"}})
        denied = add_attempt()
        assert await get(denied) == "denied"
        assert denied not in runtime._oauth_attempts
        next_response = httpx.Response(200, json={"data": {"status": "unknown"}})
        with pytest.raises(RuntimeError, match="native_oauth_status_invalid"):
            await get(add_attempt())

    asyncio.run(exercise())
