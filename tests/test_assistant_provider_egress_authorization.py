"""Keep provider request egress behind live execution authorization."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from stock_probs.assistant import providers
from stock_probs.assistant.api import _provider_proxy_chunks
from stock_probs.assistant.native_provider_adapters import native_adapter_descriptors
from stock_probs.assistant.providers import (
    AssistantProviderManager,
    CredentialRejected,
)
from stock_probs.assistant.service import AssistantUnavailable

_PROMPT = "synthetic private request for provider authorization regression"
_KEY = "synthetic provider key for authorization regression"
_NATIVE_OPENCODE_VERSION = json.loads(
    (
        Path(__file__).resolve().parents[1] / "tools/opencode-v2-security-patch/manifest.json"
    ).read_text(encoding="utf-8")
)["opencode"]["version"]
_NATIVE_ZEN_CLIENT = "opencode"
_NATIVE_ZEN_SESSION = "ses_0123456789abABCDEFGHIJKLMN"
_NATIVE_ZEN_PROJECT = "global"
_NATIVE_ZEN_USER_AGENT = f"opencode/stable/{_NATIVE_OPENCODE_VERSION}/{_NATIVE_ZEN_CLIENT}"
_APP_TOOLS: list[dict[str, object]] = [
    {
        "name": "workspace.summary",
        "description": "Return a bounded synthetic workspace summary.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    }
]
_CHAT_RESPONSE = (
    b'data: {"choices":[{"index":0,"delta":{"content":"synthetic answer"},'
    b'"finish_reason":"stop"}]}'
    b"\n\ndata: [DONE]\n\n"
)


def _reviewed_zen_model_id() -> str:
    """Select a Zen model ID from the maintained reviewed catalog policy."""

    catalog = json.loads(
        files("stock_probs.assistant")
        .joinpath("assistant_catalog.json")
        .read_text(encoding="utf-8")
    )
    zen = catalog["zen"]
    reviewed = zen["reviewed_models"]
    model_suffix = next(
        model_id
        for model_id, policy in sorted(reviewed.items())
        if policy.get("available") is True
        and policy.get("free") is True
        and policy.get("training") is False
        and policy.get("data_collection_allowed") is False
        and policy.get("data_collection_default") is False
        and policy.get("route") == "openai-compatible"
    )
    return f"{zen['provider_id']}/{model_suffix}"


class _Catalog:
    """Expose one synthetic, provider-bound model through the manager catalog seam."""

    def __init__(self, provider_id: str, model_id: str) -> None:
        self.model = SimpleNamespace(
            provider_id=provider_id,
            model_id=model_id,
            available=True,
        )

    def get_model(self, model_id: str) -> Any | None:
        return self.model if model_id == self.model.model_id else None


def _manager(tmp_path: Path, provider_id: str) -> tuple[AssistantProviderManager, str]:
    """Build one real manager with synthetic credentials and maintained Zen selection."""

    model_id = (
        _reviewed_zen_model_id()
        if provider_id == "opencode-zen"
        else f"{provider_id}/synthetic-egress-model"
    )
    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="e" * 64),
        catalog=_Catalog(provider_id, model_id),
        vault_dir=tmp_path / "assistant-vault",
    )
    if provider_id in {"openai", "anthropic", "google"}:
        manager.set_credential(provider_id, _KEY)
    elif provider_id == "custom":
        manager.configure_custom_endpoint(
            base_url="https://provider.example.test/v1",
            terms_url="https://terms.example.test/policy",
            privacy_disclosure="Synthetic administrator privacy statement; unverified.",
            billing_disclosure="Synthetic administrator billing statement; unverified.",
            billing_class="free",
            endpoint_policy_reviewed=True,
            credential=_KEY,
        )
    return manager, model_id


def _manager_stream(
    manager: AssistantProviderManager,
    provider_id: str,
    model_id: str,
    authorization_check: Callable[[], bool] | None,
) -> AsyncIterator[bytes]:
    """Return the correct fixed native or compatible-chat provider stream."""

    if provider_id in {"openai", "anthropic", "google"}:
        if provider_id == "openai":
            body: dict[str, object] = {
                "model": "assistant-selected",
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": _PROMPT}],
                    }
                ],
                "instructions": "Use only the approved local functions.",
                "stream": True,
                "store": False,
            }
            path_model_id = None
        elif provider_id == "anthropic":
            body = {
                "model": "assistant-selected",
                "max_tokens": 128,
                "messages": [{"role": "user", "content": _PROMPT}],
                "system": "Use only the approved local functions.",
                "stream": True,
            }
            path_model_id = None
        else:
            body = {"contents": [{"role": "user", "parts": [{"text": _PROMPT}]}]}
            path_model_id = "assistant-selected"
        descriptor = next(
            item for item in native_adapter_descriptors() if item.integration_id == provider_id
        )
        return manager.proxy_native_stream(
            provider_id,
            model_id,
            body,
            path_model_id=path_model_id,
            query=descriptor.fixed_query,
            app_tools=_APP_TOOLS,
            owner_id=501,
            app_session_id="synthetic-session-r120",
            authorization_check=authorization_check,
        )
    native_identity = (
        {
            "native_user_agent": _NATIVE_ZEN_USER_AGENT,
            "native_client": _NATIVE_ZEN_CLIENT,
            "native_opencode_session": _NATIVE_ZEN_SESSION,
            "native_opencode_project": _NATIVE_ZEN_PROJECT,
            "native_session_affinity": _NATIVE_ZEN_SESSION,
            "native_session_id_alias": _NATIVE_ZEN_SESSION,
        }
        if provider_id == "opencode-zen"
        else {}
    )
    return manager.proxy_chat_completion(
        provider_id,
        model_id,
        {
            "model": "assistant-selected",
            "messages": [{"role": "user", "content": _PROMPT}],
            "stream": True,
        },
        owner_id=501,
        app_session_id="synthetic-session-r120",
        authorization_check=authorization_check,
        app_tools=_APP_TOOLS if provider_id == "opencode-zen" else None,
        **native_identity,
    )


async def _collect(stream: AsyncIterator[bytes]) -> list[bytes]:
    return [chunk async for chunk in stream]


@pytest.mark.parametrize(
    "provider_id",
    ("openai", "anthropic", "google", "custom", "opencode-zen"),
)
def test_revocation_after_body_and_credential_preparation_blocks_first_provider_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
) -> None:
    """Do not forward a prepared request after session or consent revocation."""

    manager, model_id = _manager(tmp_path, provider_id)
    authorization = {"current": True}
    contacts: list[dict[str, object]] = []

    def authorize() -> bool:
        return authorization["current"] is True

    async def fake_stream(
        url: str,
        *,
        headers: object,
        body: bytes,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> AsyncIterator[bytes]:
        contacts.append({"url": url, "headers": dict(headers), "body": body})
        yield b"data: [DONE]\n\n"

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)
    stream = _manager_stream(manager, provider_id, model_id, authorize)
    authorization["current"] = False

    with pytest.raises(CredentialRejected, match="oauth_authorization_required"):
        asyncio.run(_collect(stream))

    assert contacts == []


@pytest.mark.parametrize(
    "provider_id",
    ("openai", "anthropic", "google", "custom", "opencode-zen"),
)
def test_current_authorization_allows_bounded_provider_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
) -> None:
    """Keep approved native, custom, and Zen protocol requests operational."""

    manager, model_id = _manager(tmp_path, provider_id)
    contacts: list[dict[str, object]] = []

    async def fake_stream(
        url: str,
        *,
        headers: object,
        body: bytes,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> AsyncIterator[bytes]:
        contacts.append(
            {
                "url": url,
                "headers": dict(headers),
                "body": body,
                "timeout_seconds": timeout_seconds,
                "max_response_bytes": max_response_bytes,
            }
        )
        if provider_id in {"custom", "opencode-zen"}:
            yield _CHAT_RESPONSE
        else:
            yield b"data: [DONE]\n\n"

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)
    chunks = asyncio.run(_collect(_manager_stream(manager, provider_id, model_id, lambda: True)))

    assert len(contacts) == 1
    assert contacts[0]["url"].startswith("https://")
    assert contacts[0]["timeout_seconds"] == 120.0
    assert contacts[0]["max_response_bytes"] == 1_048_576
    assert _PROMPT.encode("utf-8") in bytes(contacts[0]["body"])
    raw_headers = contacts[0]["headers"]
    assert isinstance(raw_headers, dict)
    headers = {str(name).lower(): value for name, value in raw_headers.items()}
    if provider_id == "openai":
        assert headers["authorization"] == f"Bearer {_KEY}"
    elif provider_id == "anthropic":
        assert headers["x-api-key"] == _KEY
    elif provider_id == "google":
        assert headers["x-goog-api-key"] == _KEY
    elif provider_id == "custom":
        assert headers["authorization"] == f"Bearer {_KEY}"
    elif provider_id == "opencode-zen":
        assert headers["authorization"] == "Bearer public"
    else:
        assert "authorization" not in headers
    assert chunks


@pytest.mark.parametrize("provider_id", ("custom", "opencode-zen"))
def test_missing_live_authorization_fails_before_compatible_chat_egress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
) -> None:
    """A standalone compatible-chat caller cannot forward without a live check."""

    manager, model_id = _manager(tmp_path, provider_id)
    contacts: list[str] = []

    async def fake_stream(url: str, **_options: object) -> AsyncIterator[bytes]:
        contacts.append(url)
        yield _CHAT_RESPONSE

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)
    stream = _manager_stream(manager, provider_id, model_id, None)

    with pytest.raises(CredentialRejected, match="oauth_authorization_required"):
        asyncio.run(_collect(stream))

    assert contacts == []


@pytest.mark.parametrize("provider_id", ("openai", "anthropic", "google"))
def test_missing_live_authorization_fails_before_native_egress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
) -> None:
    """A standalone native API-key caller cannot forward without a live check."""

    manager, model_id = _manager(tmp_path, provider_id)
    contacts: list[str] = []

    async def fake_stream(url: str, **_options: object) -> AsyncIterator[bytes]:
        contacts.append(url)
        yield b"data: [DONE]\n\n"

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)
    stream = _manager_stream(manager, provider_id, model_id, None)

    with pytest.raises(CredentialRejected, match="oauth_authorization_required"):
        asyncio.run(_collect(stream))

    assert contacts == []


def test_stream_wrapper_checks_authorization_before_requesting_first_upstream_chunk() -> None:
    """Do not pull a lazy provider iterator if the execution stopped before streaming."""

    pulled: list[bool] = []

    async def upstream() -> AsyncIterator[bytes]:
        pulled.append(True)
        yield b"synthetic provider bytes"

    with pytest.raises(AssistantUnavailable, match="provider_unavailable"):
        asyncio.run(_collect(_provider_proxy_chunks(upstream(), lambda: False)))

    assert pulled == []


def test_provider_stream_stops_releasing_chunks_when_authorization_expires(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recheck authorization after upstream reads and before each downstream frame."""

    manager, model_id = _manager(tmp_path, "custom")
    authorization = {"current": True}
    contacts: list[str] = []

    async def fake_stream(url: str, **_options: object) -> AsyncIterator[bytes]:
        contacts.append(url)
        yield (
            b'data: {"choices":[{"index":0,"delta":{"content":"first"},"finish_reason":null}]}\n\n'
        )
        authorization["current"] = False
        yield (
            b'data: {"choices":[{"index":0,"delta":{"content":"second"},"finish_reason":null}]}\n\n'
        )

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)
    stream = _manager_stream(
        manager,
        "custom",
        model_id,
        lambda: authorization["current"],
    )
    received: list[bytes] = []

    async def consume() -> None:
        async for chunk in stream:
            received.append(chunk)

    with pytest.raises(CredentialRejected, match="oauth_authorization_required"):
        asyncio.run(consume())

    assert len(contacts) == 1
    assert b"first" in b"".join(received)
    assert b"second" not in b"".join(received)
