"""Verify the provider bridge preserves only the app's bounded native wire contract."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import replace
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from stock_probs.assistant import model_catalog, providers
from stock_probs.assistant.api import _native_websearch_declaration
from stock_probs.assistant.model_catalog import (
    AssistantModelCatalog,
    ModelCatalogAuthorizationError,
)
from stock_probs.assistant.native_provider_adapters import (
    NATIVE_WEBFETCH_DESCRIPTION_SHA256,
    native_output_token_budget,
    native_webfetch_schema,
)
from stock_probs.assistant.providers import (
    AssistantProviderManager,
    CredentialRejected,
    ProviderUnavailable,
)
from stock_probs.assistant.tools import AssistantToolGateway

_TEST_MODEL_ID = "openai/" + secrets.token_hex(8)
_NATIVE_SESSION_FIXTURE = "ses_0123456789abABCDEFGHIJKLMN"
_NATIVE_PROJECT_FIXTURE = "global"


def _native_zen_context() -> dict[str, str]:
    """Return synthetic values for the native session/project metadata contract."""

    return {
        "native_opencode_session": _NATIVE_SESSION_FIXTURE,
        "native_opencode_project": _NATIVE_PROJECT_FIXTURE,
    }


def _reviewed_zen_model_ids() -> tuple[str, str]:
    """Read the maintained catalog's first listed eligible free/no-training model."""

    catalog = json.loads(
        files("stock_probs.assistant")
        .joinpath("assistant_catalog.json")
        .read_text(encoding="utf-8")
    )
    zen = catalog["zen"]
    reviewed = zen["reviewed_models"]
    model_suffix = next(
        model_id
        for model_id, policy in reviewed.items()
        if policy.get("available") is True
        and policy.get("free") is True
        and policy.get("training") is False
        and policy.get("data_collection_allowed") is False
        and policy.get("data_collection_default") is False
        and policy.get("route") == "openai-compatible"
    )
    return f"{zen['provider_id']}/{model_suffix}", model_suffix


def _zen_exclusion_fixtures() -> tuple[tuple[str, str], ...]:
    """Return exact excluded native IDs and meanings from the maintained catalog fixture."""

    catalog = json.loads(
        files("stock_probs.assistant")
        .joinpath("assistant_catalog.json")
        .read_text(encoding="utf-8")
    )
    exclusions = catalog["zen"]["excluded_models"]
    return tuple(sorted((str(model_id), str(reason)) for model_id, reason in exclusions.items()))


class _Catalog:
    def get_model(self, model_id: str) -> object | None:
        if model_id != _TEST_MODEL_ID:
            return None
        return SimpleNamespace(provider_id="openai", available=True)


def _chat_compat_manager(settings: object, vault_dir: Path) -> AssistantProviderManager:
    """Exercise the retained OpenAI-compatible parser with a synthetic adapter row."""

    manager = AssistantProviderManager(settings, catalog=_Catalog(), vault_dir=vault_dir)
    manager._definitions["openai"]["protocol"] = "openai-compatible-chat"
    return manager


def _native_gateway_proxy_manager(
    tmp_path: Path, provider_id: str
) -> tuple[AssistantProviderManager, str]:
    """Build a synthetic compatible provider row for the native gateway contract."""

    model_id = f"{provider_id}/synthetic-model"
    model = SimpleNamespace(model_id=model_id, provider_id=provider_id, available=True)

    class Catalog:
        def get_model(self, candidate_id: str) -> SimpleNamespace | None:
            return model if candidate_id == model_id else None

    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="t" * 64),
        catalog=Catalog(),
        vault_dir=tmp_path / "assistant-vault",
    )
    if provider_id == "openai":
        manager._definitions[provider_id]["protocol"] = "openai-compatible-chat"
    if provider_id != "opencode-zen":
        manager.set_credential(provider_id, "synthetic-provider-key")
    return manager, model_id


def _message_fixture() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return one app-declared function and a complete assistant/MCP continuation pair."""

    tools: list[dict[str, object]] = [
        {
            "type": "function",
            "function": {
                "name": "signal-ledger_workspace_summary",
                "description": "Read a bounded workspace summary.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
            },
        }
    ]
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "Use the local workspace tool."},
        {"role": "user", "content": "Summarize my workspace."},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_123",
                    "type": "function",
                    "function": {
                        "name": "signal-ledger_workspace_summary",
                        "arguments": "{}",
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_123", "content": "{}"},
    ]
    return tools, messages


def _native_webfetch_declaration() -> dict[str, object]:
    """Return the pinned native fetch declaration used by the compatible gateway tests."""

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


def _native_compatible_declarations(
    app_tools: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Project the current gateway tools plus OpenCode's two pinned builtins."""

    declarations: list[dict[str, object]] = []
    for tool in app_tools:
        name = "signal-ledger_" + str(tool["name"]).replace(".", "_")
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
    declarations.extend((_native_websearch_declaration(), _native_webfetch_declaration()))
    return declarations


def test_provider_proxy_preserves_valid_native_tool_continuation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Forward only app-validated assistant tool calls and their matching MCP results."""

    settings = SimpleNamespace(
        data_dir=tmp_path,
        auth_session_secret="t" * 64,
    )
    manager = _chat_compat_manager(settings, tmp_path / "assistant-vault")
    manager.set_credential("openai", "synthetic-provider-key")
    tools, messages = _message_fixture()
    captured: dict[str, object] = {}

    async def fake_stream(
        url: str,
        *,
        headers: object,
        body: bytes,
        timeout_seconds: float,
        max_response_bytes: int,
    ):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json.loads(body)
        captured["timeout_seconds"] = timeout_seconds
        captured["max_response_bytes"] = max_response_bytes
        yield (
            b'data: {"choices":[{"index":0,"delta":{"content":"done"},"finish_reason":"stop"}]}\n\n'
        )
        yield b"data: [DONE]\n\n"

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)

    async def exercise() -> list[bytes]:
        stream = manager.proxy_chat_completion(
            "openai",
            _TEST_MODEL_ID,
            {
                "model": "assistant-selected",
                "messages": messages,
                "stream": True,
                "tools": tools,
                "tool_choice": "auto",
            },
            authorization_check=lambda: True,
        )
        return [chunk async for chunk in stream]

    chunks = asyncio.run(exercise())

    assert chunks == [
        b'data: {"choices":[{"index":0,"delta":{"content":"done"},"finish_reason":"stop"}]}\n\n',
        b"data: [DONE]\n\n",
    ]
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    request = captured["body"]
    assert isinstance(request, dict)
    assert request["messages"] == messages
    assert request["tools"] == tools
    assert request["tool_choice"] == "auto"
    assert request["model"] == _TEST_MODEL_ID.removeprefix("openai/")
    assert request["store"] is False
    assert request["max_tokens"] == native_output_token_budget()


def test_openai_compatible_proxy_rejects_unbounded_output_counts(tmp_path: Path) -> None:
    manager = _chat_compat_manager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="t" * 64),
        tmp_path / "assistant-vault",
    )
    budget = native_output_token_budget()
    request = {
        "model": "assistant-selected",
        "messages": [{"role": "user", "content": "synthetic"}],
        "stream": True,
    }
    for invalid_count in (True, 0, budget + 1, str(budget)):
        with pytest.raises(ProviderUnavailable, match="provider_request_invalid"):
            manager.proxy_chat_completion(
                "openai", _TEST_MODEL_ID, {**request, "max_tokens": invalid_count}
            )


@pytest.mark.parametrize("provider_id", ("opencode-zen", "openai"))
def test_native_gateway_thirteen_tools_dispatch_and_validate_webfetch_continuation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider_id: str
) -> None:
    """Dispatch the real eleven-tool gateway plus both pinned native builtins."""

    manager, model_id = _native_gateway_proxy_manager(tmp_path, provider_id)
    app_tools = AssistantToolGateway.list_tools()
    declarations = _native_compatible_declarations(app_tools)
    assert len(app_tools) == 11
    assert len(declarations) == 13

    arguments = json.dumps(
        {
            "url": "https://example.test/research/article",
            "format": "markdown",
            "timeout": 30.5,
        },
        separators=(",", ":"),
    )
    search_arguments = json.dumps({"query": "current market conditions"}, separators=(",", ":"))
    messages: list[dict[str, object]] = [
        {"role": "user", "content": "Read this public article."},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_fetch",
                    "type": "function",
                    "function": {"name": "webfetch", "arguments": arguments},
                },
                {
                    "id": "call_search",
                    "type": "function",
                    "function": {"name": "websearch", "arguments": search_arguments},
                },
            ],
        },
        {"role": "tool", "tool_call_id": "call_fetch", "content": "Article text."},
        {"role": "tool", "tool_call_id": "call_search", "content": "Search results."},
    ]
    captured: dict[str, object] = {}

    async def fake_stream(
        url: str,
        *,
        headers: object,
        body: bytes,
        timeout_seconds: float,
        max_response_bytes: int,
    ):
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
            b'data: {"choices":[{"index":0,"delta":{"content":"Done."},'
            b'"finish_reason":"stop"}]}\n\n'
        )
        yield b"data: [DONE]\n\n"

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)

    async def exercise() -> list[bytes]:
        stream = manager.proxy_chat_completion(
            provider_id,
            model_id,
            {
                "model": "assistant-selected",
                "messages": messages,
                "stream": True,
                "tools": declarations,
                "tool_choice": "auto",
            },
            app_tools=app_tools,
            **(_native_zen_context() if provider_id == "opencode-zen" else {}),
            authorization_check=lambda: True,
        )
        return [frame async for frame in stream]

    assert asyncio.run(exercise())[-1] == b"data: [DONE]\n\n"
    request = captured["body"]
    assert isinstance(request, dict)
    assert captured["url"].endswith("/chat/completions")
    assert len(request["tools"]) == 13
    assert request["tools"] == declarations
    assert request["messages"] == messages
    assert request["tool_choice"] == "auto"
    assert request["max_tokens"] == native_output_token_budget()


def test_zen_proxy_uses_native_public_bearer_without_changing_other_auth_headers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Send OpenCode's fixed public marker only for Zen through the real proxy requester."""

    zen_model_id, _suffix = _reviewed_zen_model_ids()
    zen_manager = _policy_manager(
        tmp_path / "zen", _policy_model(zen_model_id, provider_id="opencode-zen")
    )
    openai_manager, openai_model_id = _native_gateway_proxy_manager(tmp_path / "openai", "openai")
    calls: list[dict[str, object]] = []

    async def fake_stream(
        url: str,
        *,
        headers: object,
        body: bytes,
        timeout_seconds: float,
        max_response_bytes: int,
    ):
        calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "body": json.loads(body),
                "timeout_seconds": timeout_seconds,
                "max_response_bytes": max_response_bytes,
            }
        )
        yield b'data: {"choices":[{"index":0,"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\n'
        yield b"data: [DONE]\n\n"

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)
    messages = [{"role": "user", "content": "Synthetic header regression."}]
    zen_tools = AssistantToolGateway.list_tools()

    async def consume(manager: AssistantProviderManager, provider_id: str, model_id: str) -> None:
        stream = manager.proxy_chat_completion(
            provider_id,
            model_id,
            {"model": "assistant-selected", "messages": messages, "stream": True},
            app_tools=zen_tools if provider_id == "opencode-zen" else None,
            **(_native_zen_context() if provider_id == "opencode-zen" else {}),
            authorization_check=lambda: True,
        )
        _ = [chunk async for chunk in stream]

    asyncio.run(consume(zen_manager, "opencode-zen", zen_model_id))
    asyncio.run(consume(openai_manager, "openai", openai_model_id))

    assert len(calls) == 2
    zen_request, openai_request = calls
    assert zen_request["url"] == "https://opencode.ai/zen/v1/chat/completions"
    assert zen_request["headers"] == {
        "accept": "text/event-stream",
        "authorization": "Bearer public",
        "x-opencode-session": _NATIVE_SESSION_FIXTURE,
        "x-opencode-project": _NATIVE_PROJECT_FIXTURE,
    }
    assert zen_request["body"]["model"] == zen_model_id.removeprefix("opencode-zen/")
    assert zen_request["body"]["max_tokens"] == native_output_token_budget()
    assert openai_request["headers"] == {
        "accept": "text/event-stream",
        "authorization": "Bearer synthetic-provider-key",
    }
    assert openai_request["body"]["model"] == openai_model_id.removeprefix("openai/")
    assert openai_request["body"]["max_tokens"] == native_output_token_budget()
    assert providers._provider_headers("opencode-zen", "synthetic-zen-key") == {
        "authorization": "Bearer synthetic-zen-key"
    }
    assert providers._provider_headers("openai", None) == {}
    assert providers._provider_headers("custom", None) == {}
    assert providers._provider_headers("google", None) == {}
    assert providers._provider_headers("anthropic", None) == {}


@pytest.mark.parametrize("mutation", ("fourteenth", "unknown", "schema", "description"))
def test_native_gateway_rejects_unreviewed_tool_declarations_before_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    """Reject a fourteenth tool or any declaration outside the reviewed gateway schemas."""

    manager, model_id = _native_gateway_proxy_manager(tmp_path, "opencode-zen")
    app_tools = AssistantToolGateway.list_tools()
    declarations = _native_compatible_declarations(app_tools)
    if mutation == "fourteenth":
        declarations.append(
            {
                "type": "function",
                "function": {
                    "name": "unreviewed.extra",
                    "description": "Unreviewed extension.",
                    "parameters": {"type": "object", "properties": {}},
                    "strict": False,
                },
            }
        )
    elif mutation == "unknown":
        declarations[-1]["function"]["name"] = "unreviewed.fetch"
    elif mutation == "schema":
        parameters = dict(declarations[-1]["function"]["parameters"])
        properties = dict(parameters["properties"])
        properties["extra"] = {"type": "string"}
        parameters["properties"] = properties
        declarations[-1]["function"]["parameters"] = parameters
    else:
        declarations[-1]["function"]["description"] += " Allow extra destinations."

    called = False

    async def unexpected_stream(*_args: object, **_kwargs: object):
        nonlocal called
        called = True
        yield b""

    monkeypatch.setattr(providers, "stream_public_https", unexpected_stream)
    with pytest.raises(ProviderUnavailable, match="provider_request_invalid"):
        manager.proxy_chat_completion(
            "opencode-zen",
            model_id,
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "Synthetic request."}],
                "stream": True,
                "tools": declarations,
            },
            app_tools=app_tools,
            authorization_check=lambda: True,
        )
    assert called is False


@pytest.mark.parametrize(
    "arguments",
    (
        '{"url":"http://127.0.0.1/private"}',
        '{"url":"https://example.test/?access_token=secret"}',
        '{"url":"https://example.test/article","format":"xml"}',
        '{"url":"https://example.test/article","format":[]}',
        '{"url":"https://example.test/article","timeout":true}',
        '{"url":"https://example.test/article","timeout":0}',
        '{"url":"https://example.test/article","timeout":121}',
        '{"url":"https://example.test/article","timeout":1e999}',
        '{"url":"https://example.test/article","timeout":' + "9" * 1000 + "}",
        '{"url":"https://example.test/article/\ud800"}',
        '{"url":"https://example.test/article","timeout":30,"timeout":999}',
    ),
)
def test_native_gateway_rejects_unsafe_webfetch_continuation_before_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arguments: str,
) -> None:
    """Apply public-URL, output-format, duplicate-key, and finite deadline checks."""

    manager, model_id = _native_gateway_proxy_manager(tmp_path, "opencode-zen")
    app_tools = AssistantToolGateway.list_tools()
    declarations = _native_compatible_declarations(app_tools)
    messages: list[dict[str, object]] = [
        {"role": "user", "content": "Fetch the reviewed article."},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_fetch",
                    "type": "function",
                    "function": {"name": "webfetch", "arguments": arguments},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_fetch", "content": "Article text."},
    ]
    called = False

    async def unexpected_stream(*_args: object, **_kwargs: object):
        nonlocal called
        called = True
        yield b""

    monkeypatch.setattr(providers, "stream_public_https", unexpected_stream)
    with pytest.raises(ProviderUnavailable, match="provider_request_invalid"):
        manager.proxy_chat_completion(
            "opencode-zen",
            model_id,
            {
                "model": "assistant-selected",
                "messages": messages,
                "stream": True,
                "tools": declarations,
            },
            app_tools=app_tools,
            authorization_check=lambda: True,
        )
    assert called is False


@pytest.mark.parametrize(
    "arguments",
    (
        '{"query":"  current events"}',
        '{"query":"current events ","extra":true}',
        '{"query":"' + "x" * 1001 + '"}',
        json.dumps({"query": "current\ud800events"}),
    ),
)
def test_native_gateway_rejects_unsafe_websearch_continuation_before_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arguments: str,
) -> None:
    """Keep native search arguments exact, trimmed, UTF-8 bounded, and control-safe."""

    manager, model_id = _native_gateway_proxy_manager(tmp_path, "opencode-zen")
    app_tools = AssistantToolGateway.list_tools()
    declarations = _native_compatible_declarations(app_tools)
    messages: list[dict[str, object]] = [
        {"role": "user", "content": "Search for current information."},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_search",
                    "type": "function",
                    "function": {"name": "websearch", "arguments": arguments},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_search", "content": "Results."},
    ]
    called = False

    async def unexpected_stream(*_args: object, **_kwargs: object):
        nonlocal called
        called = True
        yield b""

    monkeypatch.setattr(providers, "stream_public_https", unexpected_stream)
    with pytest.raises(ProviderUnavailable, match="provider_request_invalid"):
        manager.proxy_chat_completion(
            "opencode-zen",
            model_id,
            {
                "model": "assistant-selected",
                "messages": messages,
                "stream": True,
                "tools": declarations,
            },
            app_tools=app_tools,
            authorization_check=lambda: True,
        )
    assert called is False


def test_provider_proxy_normalizes_observed_native_v2_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Accept only V2's exact no-store, usage, and non-strict function metadata."""

    settings = SimpleNamespace(data_dir=tmp_path, auth_session_secret="t" * 64)
    manager = _chat_compat_manager(settings, tmp_path / "assistant-vault")
    manager.set_credential("openai", "synthetic-provider-key")
    tools, messages = _message_fixture()
    tools[0]["function"]["strict"] = False
    captured: dict[str, object] = {}

    async def fake_stream(
        _url: str,
        *,
        headers: object,
        body: bytes,
        timeout_seconds: float,
        max_response_bytes: int,
    ):
        del headers, timeout_seconds, max_response_bytes
        captured["body"] = json.loads(body)
        yield (b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n')
        yield b"data: [DONE]\n\n"

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)

    async def exercise(body: dict[str, object]) -> None:
        stream = manager.proxy_chat_completion(
            "openai", _TEST_MODEL_ID, body, authorization_check=lambda: True
        )
        _ = [chunk async for chunk in stream]

    asyncio.run(
        exercise(
            {
                "model": "assistant-selected",
                "messages": messages,
                "stream": True,
                "tools": tools,
                "tool_choice": "auto",
                "store": False,
                "stream_options": {"include_usage": True},
            }
        )
    )
    request = captured["body"]
    assert isinstance(request, dict)
    assert request["store"] is False
    assert request["stream_options"] == {"include_usage": True}
    assert request["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "signal-ledger_workspace_summary",
                "description": "Read a bounded workspace summary.",
                "parameters": tools[0]["function"]["parameters"],
            },
        }
    ]

    for field_value in (
        {"store": True},
        {"stream_options": {"include_usage": False}},
        {"stream_options": {"include_usage": True, "other": False}},
    ):
        with pytest.raises(ProviderUnavailable):
            asyncio.run(
                exercise(
                    {
                        "model": "assistant-selected",
                        "messages": messages,
                        "stream": True,
                        "tools": tools,
                        **field_value,
                    }
                )
            )


@pytest.mark.parametrize("hostile_name", ("execute", "session.delete", "file.read"))
def test_provider_proxy_rejects_undeclared_fragmented_native_tool_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hostile_name: str
) -> None:
    """Reject native function calls outside the exact app declaration set at their terminal."""

    settings = SimpleNamespace(data_dir=tmp_path, auth_session_secret="t" * 64)
    manager = _chat_compat_manager(settings, tmp_path / "assistant-vault")
    manager.set_credential("openai", "synthetic-provider-key")
    tools, messages = _message_fixture()
    first, second = (
        hostile_name[: max(1, len(hostile_name) // 2)],
        hostile_name[max(1, len(hostile_name) // 2) :],
    )
    frames = [
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_bad",
                                "type": "function",
                                "function": {"name": first},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {"tool_calls": [{"index": 0, "function": {"name": second}}]},
                    "finish_reason": "tool_calls",
                }
            ]
        },
    ]
    raw = b"".join(b"data: " + json.dumps(frame).encode() + b"\n\n" for frame in frames)
    raw += b"data: [DONE]\n\n"

    async def fake_stream(
        *_args: object,
        **_kwargs: object,
    ):
        yield raw

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)
    yielded: list[bytes] = []

    async def exercise() -> None:
        stream = manager.proxy_chat_completion(
            "openai",
            _TEST_MODEL_ID,
            {"model": "assistant-selected", "messages": messages, "stream": True, "tools": tools},
            authorization_check=lambda: True,
        )
        async for frame in stream:
            yielded.append(frame)

    with pytest.raises(ProviderUnavailable, match="provider_response_invalid"):
        asyncio.run(exercise())
    assert not any(b'"finish_reason":"tool_calls"' in frame for frame in yielded)
    assert not any(b"[DONE]" in frame for frame in yielded)


def test_provider_proxy_allows_a_declared_tool_with_fragmented_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Handle valid native function-name fragments and forward the authorized terminal."""

    settings = SimpleNamespace(data_dir=tmp_path, auth_session_secret="t" * 64)
    manager = _chat_compat_manager(settings, tmp_path / "assistant-vault")
    manager.set_credential("openai", "synthetic-provider-key")
    tools, messages = _message_fixture()
    declared_name = tools[0]["function"]["name"]
    split = len(declared_name) // 2
    frames = [
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_valid",
                                "type": "function",
                                "function": {"name": declared_name[:split]},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {
                                    "name": declared_name[split:],
                                    "arguments": "{}",
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
    ]
    raw = b"".join(b"data: " + json.dumps(frame).encode() + b"\n\n" for frame in frames)
    raw += b"data: [DONE]\n\n"

    async def fake_stream(*_args: object, **_kwargs: object):
        yield raw

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)

    async def exercise() -> list[bytes]:
        stream = manager.proxy_chat_completion(
            "openai",
            _TEST_MODEL_ID,
            {"model": "assistant-selected", "messages": messages, "stream": True, "tools": tools},
            authorization_check=lambda: True,
        )
        return [frame async for frame in stream]

    output = asyncio.run(exercise())
    assert output[-1] == b"data: [DONE]\n\n"
    assert any(b'"finish_reason":"tool_calls"' in frame for frame in output)


def test_provider_proxy_splits_large_valid_sse_frames_to_app_chunk_bound(tmp_path, monkeypatch):
    """Keep provider frames below the app bridge's 32 KiB yielded-chunk ceiling."""

    settings = SimpleNamespace(data_dir=tmp_path, auth_session_secret="t" * 64)
    manager = _chat_compat_manager(settings, tmp_path / "assistant-vault")
    manager.set_credential("openai", "synthetic-provider-key")
    tools, messages = _message_fixture()
    arguments = "{" + (" " * 16_382) + "}"
    payload = {
        "choices": [
            {
                "index": 0,
                "delta": {
                    "content": "x" * 16_384,
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_large",
                            "type": "function",
                            "function": {
                                "name": tools[0]["function"]["name"],
                                "arguments": arguments,
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    raw = b"data: " + json.dumps(payload, separators=(",", ":")).encode() + b"\n\n"
    raw += b"data: [DONE]\n\n"

    async def fake_stream(*_args: object, **_kwargs: object):
        yield raw

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)

    async def exercise() -> list[bytes]:
        stream = manager.proxy_chat_completion(
            "openai",
            _TEST_MODEL_ID,
            {"model": "assistant-selected", "messages": messages, "stream": True, "tools": tools},
            authorization_check=lambda: True,
        )
        return [chunk async for chunk in stream]

    chunks = asyncio.run(exercise())
    assert len(chunks) > 2
    assert all(0 < len(chunk) <= 32 * 1024 for chunk in chunks)
    reassembled = b"".join(chunks)
    data_frame, done_frame = reassembled.split(b"\n\n", 1)
    assert done_frame == b"data: [DONE]\n\n"
    forwarded = json.loads(data_frame.removeprefix(b"data: "))
    delta = forwarded["choices"][0]["delta"]
    assert len(delta["content"]) == 16_384
    assert delta["tool_calls"][0]["function"]["arguments"] == arguments


def test_provider_proxy_rejects_overlimit_provider_tool_arguments(tmp_path, monkeypatch):
    """Splitting frames does not loosen the native function-argument bound."""

    settings = SimpleNamespace(data_dir=tmp_path, auth_session_secret="t" * 64)
    manager = _chat_compat_manager(settings, tmp_path / "assistant-vault")
    manager.set_credential("openai", "synthetic-provider-key")
    tools, messages = _message_fixture()
    payload = {
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_large",
                            "type": "function",
                            "function": {
                                "name": tools[0]["function"]["name"],
                                "arguments": "{" + (" " * 16_383) + "}",
                            },
                        }
                    ]
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    raw = b"data: " + json.dumps(payload, separators=(",", ":")).encode() + b"\n\n"
    raw += b"data: [DONE]\n\n"

    async def fake_stream(*_args: object, **_kwargs: object):
        yield raw

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)

    async def exercise() -> None:
        stream = manager.proxy_chat_completion(
            "openai",
            _TEST_MODEL_ID,
            {"model": "assistant-selected", "messages": messages, "stream": True, "tools": tools},
            authorization_check=lambda: True,
        )
        async for _chunk in stream:
            pass

    with pytest.raises(ProviderUnavailable, match="provider_response_invalid"):
        asyncio.run(exercise())


@pytest.mark.parametrize(
    ("finish_reason", "include_done", "expected_code"),
    (
        (None, True, "provider_response_invalid"),
        ("stop", False, "provider_response_invalid"),
        ("length", True, "provider_response_incomplete"),
        ("content_filter", True, "provider_response_incomplete"),
    ),
)
def test_provider_proxy_requires_complete_text_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    finish_reason: str | None,
    include_done: bool,
    expected_code: str,
) -> None:
    """Do not turn partial text, truncation, or early EOF into a completed answer."""

    settings = SimpleNamespace(data_dir=tmp_path, auth_session_secret="t" * 64)
    manager = _chat_compat_manager(settings, tmp_path / "assistant-vault")
    manager.set_credential("openai", "synthetic-provider-key")
    tools, messages = _message_fixture()
    choice: dict[str, object] = {
        "index": 0,
        "delta": {"content": "partial answer"},
        "finish_reason": finish_reason,
    }
    raw = b"data: " + json.dumps({"choices": [choice]}).encode() + b"\n\n"
    if include_done:
        raw += b"data: [DONE]\n\n"

    async def fake_stream(*_args: object, **_kwargs: object):
        yield raw

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)

    async def exercise() -> list[bytes]:
        stream = manager.proxy_chat_completion(
            "openai",
            _TEST_MODEL_ID,
            {"model": "assistant-selected", "messages": messages, "stream": True, "tools": tools},
            authorization_check=lambda: True,
        )
        return [chunk async for chunk in stream]

    with pytest.raises(ProviderUnavailable, match=expected_code):
        asyncio.run(exercise())


@pytest.mark.parametrize(
    "mutation",
    (
        lambda messages: messages.pop(),
        lambda messages: messages[-1].update(tool_call_id="call_other"),
        lambda messages: messages[2]["tool_calls"][0]["function"].update(name="not_declared"),
        lambda messages: messages[2]["tool_calls"][0]["function"].update(arguments="[]"),
    ),
)
def test_provider_proxy_rejects_incomplete_or_unregistered_tool_continuations(
    tmp_path: Path,
    mutation: Callable[[list[dict[str, object]]], object],
) -> None:
    """Reject continuation frames outside the call IDs and schemas approved by the app."""

    settings = SimpleNamespace(
        data_dir=tmp_path,
        auth_session_secret="t" * 64,
    )
    manager = _chat_compat_manager(settings, tmp_path / "assistant-vault")
    tools, messages = _message_fixture()
    mutation(messages)
    with pytest.raises(ProviderUnavailable, match="provider_request_invalid"):
        manager.proxy_chat_completion(
            "openai",
            _TEST_MODEL_ID,
            {
                "model": "assistant-selected",
                "messages": messages,
                "stream": True,
                "tools": tools,
            },
            authorization_check=lambda: True,
        )


class _PolicyCatalog:
    def __init__(self, *models: SimpleNamespace) -> None:
        self.models = {model.model_id: model for model in models}

    def get_model(self, model_id: str) -> object | None:
        return self.models.get(model_id)


def _policy_model(
    model_id: str,
    *,
    provider_id: str = "opencode-zen",
    free: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        model_id=model_id,
        provider_id=provider_id,
        native_provider_id=("assistant-proxy" if provider_id == "opencode-zen" else provider_id),
        display_name=model_id,
        available=True,
        free=free,
        training=False,
        terms_url="https://example.test/terms",
        terms_reviewed_at="2026-10-04",
        policy_version="review-v1",
        privacy_policy_version="privacy-v1",
        billing_policy_version="billing-v1",
        disclosure="Reviewed provider terms.",
        privacy_disclosure="Privacy disclosure.",
        billing_class="free" if free else "paid",
        cost_disclosure="No charge." if free else "Explicit cost acknowledgement required.",
        data_collection_allowed=False,
        data_collection_default=False,
    )


def _policy_manager(tmp_path: Path, *models: SimpleNamespace) -> AssistantProviderManager:
    return AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="t" * 64),
        catalog=_PolicyCatalog(*models),
        vault_dir=tmp_path / "assistant-vault",
    )


def _configure_custom_endpoint(
    manager: AssistantProviderManager,
    base_url: str = "https://model.example/v1",
    *,
    terms_url: str = "https://terms.example/policy",
    privacy_disclosure: str = "Administrator-provided privacy statement; unverified.",
    billing_disclosure: str = "Administrator-provided billing statement; unverified.",
    billing_class: str = "paid",
    credential: str | None = None,
) -> object:
    """Save the full administrator-reviewed custom provider tuple used by tests."""

    return manager.configure_custom_endpoint(
        base_url=base_url,
        terms_url=terms_url,
        privacy_disclosure=privacy_disclosure,
        billing_disclosure=billing_disclosure,
        billing_class=billing_class,
        endpoint_policy_reviewed=True,
        credential=credential,
    )


def test_model_policy_seeds_only_reviewed_free_no_training_zen_model(tmp_path: Path) -> None:
    """Expose explicit provider capabilities and seed only the safe Zen row as enabled."""

    zen_model_id, _ = _reviewed_zen_model_ids()
    zen = _policy_model(zen_model_id)
    manager = _policy_manager(tmp_path, zen)
    state = manager.model_policy_state(zen.model_id)

    assert state["enabled"] is True
    assert state["usable"] is True
    assert state["revision"] == 1
    assert state["acknowledged_privacy_policy_version"] == "privacy-v1"
    assert state["acknowledged_billing_policy_version"] == "billing-v1"
    assert str(state["policy_version"]).startswith("ap1-")
    assert len(str(state["policy_version"])) == 68

    rows = {row.provider_id: row.public_dict() for row in manager.list_providers()}
    assert rows["opencode-zen"]["credential_supported"] is False
    assert rows["opencode-zen"]["endpoint_editable"] is False
    assert rows["opencode-zen"]["validation_requires_credential"] is False
    assert rows["openai"]["credential_supported"] is True
    assert rows["openai"]["validation_requires_credential"] is True
    assert rows["custom"]["endpoint_editable"] is True
    assert rows["custom"]["validation_requires_credential"] is False
    assert rows["anthropic"]["adapter_supported"] is True
    assert rows["anthropic"]["protocol"] == "anthropic-messages"


def test_zen_catalog_uses_the_closed_native_compatible_provider_alias() -> None:
    """Keep the app catalog ID distinct from OpenCode's fixed native package ID."""

    _model_id, suffix = _reviewed_zen_model_ids()
    rows = AssistantModelCatalog()._parse_zen_rows([{"id": suffix}])

    assert len(rows) == 1
    assert rows[0].provider_id == "opencode-zen"
    assert rows[0].native_provider_id == "assistant-proxy"


def test_every_reviewed_free_no_training_zen_model_uses_current_policy_versions(
    tmp_path: Path,
) -> None:
    """Keep each eligible catalog model on current policy versions and explicit consent."""

    policy = json.loads(
        files("stock_probs.assistant")
        .joinpath("assistant_catalog.json")
        .read_text(encoding="utf-8")
    )["zen"]
    reviewed = policy["reviewed_models"]
    eligible_ids = tuple(
        model_id
        for model_id, model_policy in reviewed.items()
        if model_policy.get("available") is True
        and model_policy.get("free") is True
        and model_policy.get("training") is False
        and model_policy.get("data_collection_allowed") is False
        and model_policy.get("data_collection_default") is False
        and model_policy.get("route") == "openai-compatible"
    )
    assert len(eligible_ids) >= 2
    catalog = AssistantModelCatalog()

    rows = catalog._parse_zen_rows([{"id": model_id} for model_id in eligible_ids])

    assert {model.model_id for model in rows} == {
        f"{policy['provider_id']}/{model_id}" for model_id in eligible_ids
    }
    for index, model in enumerate(rows):
        model_policy = reviewed[model.model_id.removeprefix(f"{policy['provider_id']}/")]
        assert model.display_name == model_policy["display_name"]
        assert model.available is True
        assert model.free is True
        assert model.training is False
        assert model.data_collection_allowed is False
        assert model.data_collection_default is False
        assert model.privacy_policy_version == policy["privacy_policy_version"]
        assert model.billing_policy_version == policy["billing_policy_version"]
        assert model.policy_version == policy["policy_version"]
        assert model.terms_reviewed_at == policy["terms_reviewed_at"]
        assert model.terms_url == policy["terms_url"]
        assert model.disclosure == model_policy["disclosure"]
        assert "zero-retention" in model.disclosure
        assert "training" in model.disclosure
        if "cost_disclosure" in model_policy:
            assert model.cost_disclosure == model_policy["cost_disclosure"]
        combined_disclosure = model.disclosure + str(model.cost_disclosure)
        assert "availability" in combined_disclosure
        assert "paid fallback" in combined_disclosure
        assert "automatic top-up" in combined_disclosure
        assert model.billing_class == "free"
        assert model.native_provider_id == "assistant-proxy"

        manager = _policy_manager(tmp_path / str(index), model)
        state = manager.model_policy_state(model.model_id)
        expected_revision = int(state["revision"])
        with pytest.raises(ProviderUnavailable, match="privacy_policy_ack_required"):
            manager.update_model_policy(
                model.model_id,
                enabled=True,
                acknowledged_privacy_policy_version=None,
                acknowledged_billing_policy_version=model.billing_policy_version,
                expected_revision=expected_revision,
            )
        with pytest.raises(ProviderUnavailable, match="billing_policy_ack_required"):
            manager.update_model_policy(
                model.model_id,
                enabled=True,
                acknowledged_privacy_policy_version=model.privacy_policy_version,
                acknowledged_billing_policy_version=None,
                expected_revision=expected_revision,
            )


def test_zen_longcat_disclosure_uses_current_hosting_regions() -> None:
    """Keep the LongCat privacy disclosure aligned with the maintained Zen policy."""

    policy = json.loads(
        files("stock_probs.assistant")
        .joinpath("assistant_catalog.json")
        .read_text(encoding="utf-8")
    )["zen"]
    longcat_policies = [
        model_policy
        for model_policy in policy["reviewed_models"].values()
        if str(model_policy.get("display_name", "")).startswith("LongCat ")
    ]

    assert len(longcat_policies) == 1
    assert "hosted in the US and EU" in str(longcat_policies[0]["disclosure"])


@pytest.mark.parametrize("native_model_id", [item for item, _reason in _zen_exclusion_fixtures()])
def test_zen_catalog_exclusions_override_a_forged_reviewed_allow_row(
    native_model_id: str,
) -> None:
    """Keep maintained hard exclusions authoritative if a future row is misclassified."""

    catalog = AssistantModelCatalog()
    catalog._policy["zen"]["reviewed_models"][native_model_id] = {
        "display_name": "Synthetic reviewed label",
        "free": True,
        "training": False,
        "data_collection_allowed": False,
        "data_collection_default": False,
        "available": True,
        "route": "openai-compatible",
        "disclosure": "Synthetic catalog row for a policy precedence regression.",
    }

    assert catalog._parse_zen_rows([{"id": native_model_id}]) == ()


def test_zen_native_descriptor_matches_catalog_provider_alias(tmp_path: Path) -> None:
    """Resolve only a usable reviewed Zen model to its exact fixed V2 provider package."""

    model_id, _suffix = _reviewed_zen_model_ids()
    model = _policy_model(model_id)
    manager = _policy_manager(tmp_path, model)

    descriptor = manager.native_execution_descriptor(model_id)

    assert descriptor.adapter_id == "openai-compatible-chat"
    assert descriptor.native_provider_id == model.native_provider_id == "assistant-proxy"
    assert descriptor.package_id == "@opencode/ai/providers/openai-compatible"


def test_model_policy_cas_requires_exact_paid_privacy_and_billing_ack(tmp_path: Path) -> None:
    """Paid model enablement requires reviewed versions and advances one CAS revision."""

    model_id = "openai/reviewed-paid-model"
    model = _policy_model(model_id, provider_id="openai", free=False)
    manager = _policy_manager(tmp_path, model)

    with pytest.raises(ProviderUnavailable, match="billing_policy_ack_required"):
        manager.update_model_policy(
            model_id,
            enabled=True,
            acknowledged_privacy_policy_version="privacy-v1",
            acknowledged_billing_policy_version=None,
            expected_revision=0,
        )

    accepted = manager.update_model_policy(
        model_id,
        enabled=True,
        acknowledged_privacy_policy_version="privacy-v1",
        acknowledged_billing_policy_version="billing-v1",
        expected_revision=0,
    )
    assert accepted["enabled"] is True
    assert accepted["usable"] is False  # No validated provider/model connection exists.
    assert accepted["revision"] == 1
    assert accepted["acknowledged_billing_policy_version"] == "billing-v1"

    with pytest.raises(ProviderUnavailable, match="model_policy_conflict"):
        manager.update_model_policy(
            model_id,
            enabled=False,
            acknowledged_privacy_policy_version=None,
            acknowledged_billing_policy_version=None,
            expected_revision=0,
        )


@pytest.mark.parametrize("changed_field", ("privacy_policy_version", "billing_policy_version"))
def test_model_consent_generation_changes_when_either_policy_version_changes(
    tmp_path: Path, changed_field: str
) -> None:
    """Old catalog-backed consent becomes stale and accepts current reviewed versions."""

    model_id, suffix = _reviewed_zen_model_ids()
    model = AssistantModelCatalog()._parse_zen_rows([{"id": suffix}])[0]
    previous_model = replace(
        model,
        **{changed_field: f"previous-{getattr(model, changed_field)}"},
    )
    policy_catalog = _PolicyCatalog(previous_model)
    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="t" * 64),
        catalog=policy_catalog,
        vault_dir=tmp_path / "assistant-vault",
    )
    before = manager.model_policy_state(model_id)
    assert before["enabled"] is True
    assert before["usable"] is True
    assert before["acknowledged_privacy_policy_version"] == previous_model.privacy_policy_version
    assert before["acknowledged_billing_policy_version"] == previous_model.billing_policy_version

    policy_catalog.models[model_id] = model
    after = manager.model_policy_state(model_id)

    assert before["policy_version"] != after["policy_version"]
    assert after["acknowledged_privacy_policy_version"] == previous_model.privacy_policy_version
    assert after["acknowledged_billing_policy_version"] == previous_model.billing_policy_version
    assert after["usable"] is False
    assert after["availability_reason"] == "policy_acknowledgement_required"
    stale_ack_error = (
        "privacy_policy_ack_required"
        if changed_field == "privacy_policy_version"
        else "billing_policy_ack_required"
    )
    with pytest.raises(ProviderUnavailable, match=stale_ack_error):
        manager.update_model_policy(
            model_id,
            enabled=True,
            acknowledged_privacy_policy_version=str(previous_model.privacy_policy_version),
            acknowledged_billing_policy_version=str(previous_model.billing_policy_version),
            expected_revision=1,
        )

    accepted = manager.update_model_policy(
        model_id,
        enabled=True,
        acknowledged_privacy_policy_version=str(after["privacy_policy_version"]),
        acknowledged_billing_policy_version=str(after["billing_policy_version"]),
        expected_revision=1,
    )
    assert accepted["usable"] is True
    assert accepted["policy_version"] != after["policy_version"]


def test_custom_endpoint_change_invalidates_approval_and_consent_generation(
    tmp_path: Path,
) -> None:
    """Changing endpoint terms changes identity and blocks the prior model approval."""

    model_id = "custom/reviewed-model"
    model = _policy_model(model_id, provider_id="custom", free=False)
    manager = _policy_manager(tmp_path, model)
    _configure_custom_endpoint(manager, "https://model-a.example/v1")

    before = manager.model_policy_state(model_id)
    approved = manager.update_model_policy(
        model_id,
        enabled=True,
        acknowledged_privacy_policy_version="privacy-v1",
        acknowledged_billing_policy_version="billing-v1",
        expected_revision=0,
    )
    assert approved["enabled"] is True
    assert approved["endpoint_identity_sha256"] == before["current_endpoint_identity_sha256"]

    _configure_custom_endpoint(
        manager,
        "https://model-b.example/v1",
        privacy_disclosure="Changed administrator-provided privacy statement; unverified.",
    )
    changed = manager.model_policy_state(model_id)
    assert changed["usable"] is False
    assert changed["availability_reason"] == "provider_endpoint_changed"
    assert changed["endpoint_identity_sha256"] != changed["current_endpoint_identity_sha256"]
    assert changed["current_endpoint_identity_sha256"] != before["current_endpoint_identity_sha256"]
    assert changed["policy_version"] != before["policy_version"]
    assert before["current_endpoint_identity_sha256"] != changed["current_endpoint_identity_sha256"]


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    (
        ({"endpoint_policy_reviewed": False}, "custom_policy_review_required"),
        ({"billing_class": "free-ish"}, "custom_policy_review_required"),
        ({"base_url": "http://model.example/v1"}, "invalid_provider_endpoint"),
        ({"base_url": "https://127.0.0.1/v1"}, "private_provider_endpoint_rejected"),
        ({"base_url": "https://224.0.0.1/v1"}, "private_provider_endpoint_rejected"),
        ({"base_url": "https://[ff02::1]/v1"}, "private_provider_endpoint_rejected"),
        ({"base_url": "https://model.example:8443/v1"}, "invalid_provider_endpoint"),
        ({"base_url": "https://user@model.example/v1"}, "invalid_provider_endpoint"),
        ({"base_url": "https://model.example/v1?token=marker"}, "invalid_provider_endpoint"),
        ({"terms_url": "https://terms.example:444/policy"}, "custom_policy_review_required"),
        ({"privacy_disclosure": ""}, "custom_policy_review_required"),
        ({"privacy_disclosure": "x" * 2001}, "custom_policy_review_required"),
        ({"billing_disclosure": "statement\x00marker"}, "custom_policy_review_required"),
        ({"billing_disclosure": "\ud800"}, "custom_policy_review_required"),
    ),
)
def test_custom_endpoint_requires_complete_safe_review_tuple(
    tmp_path: Path, overrides: dict[str, object], error_code: str
) -> None:
    """Reject arbitrary endpoints and malformed administrator statements before saving."""

    manager = _policy_manager(tmp_path)
    values: dict[str, object] = {
        "base_url": "https://model.example/v1",
        "terms_url": "https://terms.example/policy",
        "privacy_disclosure": "Administrator-provided privacy statement; unverified.",
        "billing_disclosure": "Administrator-provided billing statement; unverified.",
        "billing_class": "unknown",
        "endpoint_policy_reviewed": True,
    }
    values.update(overrides)

    with pytest.raises(ProviderUnavailable, match=error_code):
        manager.configure_custom_endpoint(**values)

    assert not (tmp_path / "assistant-vault" / "providers.json").exists()


def test_custom_endpoint_policy_discovery_keeps_unknown_claims_unverified_and_key_app_side(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Discover a reviewed custom model without claiming an unknown billing class is free."""

    now = 10.0
    manager, catalog = _configured_provider_manager(tmp_path, lambda: now)
    _configure_custom_endpoint(
        manager,
        "https://models.example/v1",
        billing_class="unknown",
        credential="synthetic-custom-key",
    )
    requests: list[tuple[str, dict[str, str], int]] = []

    async def fake_request(
        url: str,
        *,
        headers: object,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> SimpleNamespace:
        requests.append((url, dict(headers), max_response_bytes))
        assert timeout_seconds <= 6.5
        return SimpleNamespace(status_code=200, content=b'{"data":[{"id":"fixture-model"}]}')

    monkeypatch.setattr(providers, "request_public_https", fake_request)
    models = asyncio.run(manager.ensure_model_inventory())
    model = next(item for item in models if item.model_id == "custom/fixture-model")

    assert requests == [
        (
            "https://models.example/v1/models",
            {"authorization": "Bearer synthetic-custom-key"},
            providers._MAX_VALIDATE_BYTES,
        )
    ]
    assert model.billing_class == "unknown"
    assert model.free is False
    assert model.training is True
    assert model.data_collection_allowed is True
    assert model.terms_url == "https://terms.example/policy"

    state = manager.model_policy_state(model.model_id)
    assert state["enabled"] is False
    approved = manager.update_model_policy(
        model.model_id,
        enabled=True,
        acknowledged_privacy_policy_version=str(state["privacy_policy_version"]),
        acknowledged_billing_policy_version=str(state["billing_policy_version"]),
        expected_revision=0,
    )
    assert approved["enabled"] is True
    assert approved["usable"] is True
    assert approved["free"] is False
    assert approved["billing_class"] == "unknown"
    assert approved["privacy_disclosure"].startswith("Administrator-provided")
    assert approved["cost_disclosure"].startswith("Administrator-provided")

    custom = next(row for row in manager.list_providers() if row.provider_id == "custom")
    public_state = json.dumps({"provider": custom.public_dict(), "model": approved}, sort_keys=True)
    assert custom.selected_endpoint_policy_reviewed is True
    assert custom.selected_terms_url == "https://terms.example/policy"
    assert custom.selected_billing_class == "unknown"
    assert custom.credential_configured is True
    assert "synthetic-custom-key" not in public_state


def test_custom_endpoint_canonicalizes_default_tls_port_and_idna_host(tmp_path: Path) -> None:
    """Store a canonical ASCII host and omit the default HTTPS port from policy identity."""

    manager = _policy_manager(tmp_path)
    row = _configure_custom_endpoint(manager, "https://bücher.example:443/v1/")

    assert row.selected_base_url == "https://xn--bcher-kva.example/v1"


def test_custom_endpoint_key_is_retained_for_same_endpoint_and_cleared_on_endpoint_change(
    tmp_path: Path,
) -> None:
    """Do not forward a previously supplied key to a newly selected custom host."""

    manager = _policy_manager(tmp_path)
    first = _configure_custom_endpoint(
        manager,
        "https://first.example/v1",
        credential="synthetic-custom-key",
    )
    assert first.credential_configured is True
    assert manager._read_credential("custom") == "synthetic-custom-key"

    same_endpoint = _configure_custom_endpoint(
        manager,
        "https://first.example/v1",
        privacy_disclosure="Updated admin statement; unverified.",
    )
    assert same_endpoint.credential_configured is True
    assert manager._read_credential("custom") == "synthetic-custom-key"

    changed_endpoint = _configure_custom_endpoint(
        manager,
        "https://second.example/v1",
        privacy_disclosure="Updated admin statement; unverified.",
    )
    assert changed_endpoint.selected_base_url == "https://second.example/v1"
    assert changed_endpoint.credential_configured is False
    assert manager._read_credential("custom") is None
    assert "synthetic-custom-key" not in manager._config_path.read_text(encoding="utf-8")


def test_legacy_custom_endpoint_and_generic_update_stay_closed(tmp_path: Path) -> None:
    """Require the dedicated full-review operation instead of endpoint-only mutation."""

    manager = _policy_manager(tmp_path)
    with pytest.raises(ProviderUnavailable, match="custom_policy_review_required"):
        manager.set_custom_endpoint("custom", "https://model.example/v1")
    with pytest.raises(ProviderUnavailable, match="custom_policy_review_required"):
        manager.update_provider("custom", base_url="https://model.example/v1")


def test_model_policy_cannot_enable_custom_model_without_reviewed_terms(tmp_path: Path) -> None:
    """An arbitrary custom endpoint cannot become approved with missing policy disclosures."""

    model_id = "custom/unreviewed-model"
    model = _policy_model(model_id, provider_id="custom", free=False)
    model.privacy_policy_version = None
    manager = _policy_manager(tmp_path, model)
    _configure_custom_endpoint(manager)

    with pytest.raises(ProviderUnavailable, match="model_policy_review_required"):
        manager.update_model_policy(
            model_id,
            enabled=True,
            acknowledged_privacy_policy_version="review-v1",
            acknowledged_billing_policy_version="review-v1",
            expected_revision=0,
        )


@pytest.mark.parametrize(
    "terms_url",
    (
        "https://127.0.0.1/terms",
        "https://user@terms.example/policy",
        "https://terms.example:444/policy",
        "https://terms.example/policy\n",
    ),
)
def test_model_policy_rejects_unsafe_or_noncanonical_terms_url(
    tmp_path: Path, terms_url: str
) -> None:
    """Terms acknowledgement binds only to a public canonical HTTPS document URL."""

    model_id = "custom/model-with-bad-terms"
    model = _policy_model(model_id, provider_id="custom", free=False)
    model.terms_url = terms_url
    manager = _policy_manager(tmp_path, model)
    _configure_custom_endpoint(manager)

    with pytest.raises(ProviderUnavailable, match="model_policy_review_required"):
        manager.update_model_policy(
            model_id,
            enabled=True,
            acknowledged_privacy_policy_version="privacy-v1",
            acknowledged_billing_policy_version="billing-v1",
            expected_revision=0,
        )


def test_model_inventory_refreshes_on_demand_and_single_flights_concurrent_reads() -> None:
    """Normal model discovery populates an empty startup cache without admin validation."""

    calls = 0
    _, model_suffix = _reviewed_zen_model_ids()

    async def requester(_url: str):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return SimpleNamespace(
            status_code=200,
            content=json.dumps({"data": [{"id": model_suffix}]}).encode(),
        )

    catalog = AssistantModelCatalog(requester=requester, clock=lambda: 10.0)
    assert catalog.list_models() == ()

    async def exercise():
        return await asyncio.gather(
            catalog.ensure_fresh(),
            catalog.ensure_fresh(),
            catalog.ensure_fresh(),
        )

    results = asyncio.run(exercise())
    assert calls == 1
    assert all(len(rows) == 1 for rows in results)
    assert results[0][0].model_id == _reviewed_zen_model_ids()[0]


def test_model_inventory_refreshes_before_remaining_turn_lifetime_expires() -> None:
    """A model selected near TTL expiry receives a fresh full turn window."""

    now = 10.0
    calls = 0
    _, model_suffix = _reviewed_zen_model_ids()

    async def requester(_url: str):
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            status_code=200,
            content=json.dumps({"data": [{"id": model_suffix}]}).encode(),
        )

    catalog = AssistantModelCatalog(requester=requester, clock=lambda: now)
    asyncio.run(catalog.ensure_fresh())
    now += 179.0
    still_fresh = asyncio.run(catalog.ensure_fresh(minimum_validity_seconds=120.0))
    assert len(still_fresh) == 1
    assert calls == 1

    now += 2.0
    refreshed = asyncio.run(catalog.ensure_fresh(minimum_validity_seconds=120.0))
    assert len(refreshed) == 1
    assert calls == 2


def test_model_inventory_failure_is_suppressed_then_recovers_on_later_demand() -> None:
    """A failed startup fetch is unavailable briefly, then a normal read can recover."""

    now = 10.0
    calls = 0
    _, model_suffix = _reviewed_zen_model_ids()

    async def requester(_url: str):
        nonlocal calls
        calls += 1
        status = 503 if calls == 1 else 200
        content = b"{}" if status == 503 else json.dumps({"data": [{"id": model_suffix}]}).encode()
        return SimpleNamespace(status_code=status, content=content)

    catalog = AssistantModelCatalog(requester=requester, clock=lambda: now)
    assert asyncio.run(catalog.ensure_fresh()) == ()
    assert asyncio.run(catalog.ensure_fresh()) == ()
    assert calls == 1

    now += 5.1
    recovered = asyncio.run(catalog.ensure_fresh())
    assert calls == 2
    assert len(recovered) == 1


@pytest.mark.parametrize(
    ("models_url", "expected_headers"),
    [
        (
            "https://opencode.ai/zen/v1/models",
            {"authorization": "Bearer public"},
        ),
        (
            "https://inventory.example.test/v1/models",
            {},
        ),
        (
            "https://opencode.ai/zen/v1/models/",
            {},
        ),
    ],
)
def test_zen_catalog_public_marker_is_fixed_endpoint_only_and_request_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
    models_url: str,
    expected_headers: dict[str, str],
) -> None:
    """Use the native public marker only for the exact fixed Zen inventory URL."""

    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_request(url: str, **kwargs: object) -> SimpleNamespace:
        calls.append((url, dict(kwargs)))
        return SimpleNamespace(status_code=200, content=b'{"data":[]}')

    monkeypatch.setattr(model_catalog, "request_public_https", fake_request)
    catalog = AssistantModelCatalog(clock=lambda: 10.0)
    catalog._policy["zen"]["models_url"] = models_url

    assert asyncio.run(catalog.refresh()) == ()
    assert len(calls) == 1
    assert calls[0][0] == models_url
    options = calls[0][1]
    assert options["headers"] == expected_headers
    assert options["timeout_seconds"] == 6.5
    assert options["max_response_bytes"] == model_catalog._MAX_CATALOG_BYTES
    assert "authorization_check" not in options


def test_zen_catalog_public_marker_keeps_live_authorization_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A revoked catalog refresh cannot apply its held response or lose its callback."""

    _model_id, model_suffix = _reviewed_zen_model_ids()
    response_started = asyncio.Event()
    release_response = asyncio.Event()
    authorization = {"allowed": True}
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_request(url: str, **kwargs: object) -> SimpleNamespace:
        calls.append((url, dict(kwargs)))
        if "authorization_check" in kwargs:
            response_started.set()
            await release_response.wait()
            content = b'{"data":[]}'
        else:
            content = json.dumps({"data": [{"id": model_suffix}]}).encode()
        return SimpleNamespace(status_code=200, content=content)

    async def authorization_check() -> bool:
        return authorization["allowed"] is True

    monkeypatch.setattr(model_catalog, "request_public_https", fake_request)
    catalog = AssistantModelCatalog(clock=lambda: 10.0)
    initial_models = asyncio.run(catalog.refresh())
    assert len(initial_models) == 1
    cached_state = (catalog._models, catalog._loaded_at, catalog._retry_at)

    async def revoke_held_refresh() -> None:
        refresh = asyncio.create_task(catalog.refresh(authorization_check=authorization_check))
        await asyncio.wait_for(response_started.wait(), timeout=1)
        authorization["allowed"] = False
        release_response.set()
        with pytest.raises(ModelCatalogAuthorizationError):
            await refresh

    asyncio.run(revoke_held_refresh())

    fixed_url = "https://opencode.ai/zen/v1/models"
    assert len(calls) == 2
    assert all(url == fixed_url for url, _options in calls)
    assert all(options["headers"] == {"authorization": "Bearer public"} for _, options in calls)
    assert calls[1][1]["authorization_check"] is authorization_check
    assert calls[1][1]["timeout_seconds"] == 6.5
    assert calls[1][1]["max_response_bytes"] == model_catalog._MAX_CATALOG_BYTES
    assert (catalog._models, catalog._loaded_at, catalog._retry_at) == cached_state


def _configured_provider_manager(
    tmp_path: Path, clock: Callable[[], float]
) -> tuple[AssistantProviderManager, AssistantModelCatalog]:
    """Build a real catalog/manager pair with empty Zen data and a synthetic clock."""

    async def zen_requester(_url: str):
        return SimpleNamespace(status_code=200, content=b'{"data":[]}')

    settings = SimpleNamespace(data_dir=tmp_path, auth_session_secret="t" * 64)
    catalog = AssistantModelCatalog(requester=zen_requester, clock=clock)
    manager = AssistantProviderManager(
        settings,
        catalog,
        vault_dir=tmp_path / "assistant-vault",
        clock=clock,
    )
    return manager, catalog


@pytest.mark.parametrize(("native_model_id", "reason"), _zen_exclusion_fixtures())
@pytest.mark.parametrize(
    "endpoint",
    [
        "HTTPS://OPENCODE.AI:443/%7Aen/v1/",
        "https://opencode.ai/unused/%2e%2e/zen/v1",
        "https://opencode.ai/zen/%76%31/",
    ],
)
def test_custom_inventory_excludes_catalog_native_ids_at_canonical_zen_endpoint(
    tmp_path: Path, native_model_id: str, reason: str, endpoint: str
) -> None:
    """Do not let a custom endpoint review override the catalog's exact Zen exclusions."""

    manager, _catalog = _configured_provider_manager(tmp_path, lambda: 10.0)
    _configure_custom_endpoint(
        manager,
        base_url=endpoint,
        billing_class="free",
    )

    assert manager._known_model_exclusion_reason("custom", endpoint, native_model_id) == reason
    assert manager._parse_provider_model_rows("custom", [{"id": native_model_id}]) == ()


def test_excluded_id_on_ambiguous_zen_host_path_fails_closed(tmp_path: Path) -> None:
    """Do not infer that another path on Zen's host has unrelated model identity."""

    native_model_id = _zen_exclusion_fixtures()[0][0]
    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="a" * 64),
        vault_dir=tmp_path / "assistant-vault",
    )

    with pytest.raises(ProviderUnavailable, match="model_policy_unavailable"):
        manager._known_model_exclusion_reason(
            "custom", "HTTPS://OPENCODE.AI:443/unrelated/path", native_model_id
        )


def test_custom_endpoint_allows_same_catalog_id_on_unrelated_host(tmp_path: Path) -> None:
    """Scope exclusions to the Zen provider or endpoint instead of banning IDs globally."""

    native_model_id = _zen_exclusion_fixtures()[0][0]
    manager, _catalog = _configured_provider_manager(tmp_path, lambda: 10.0)
    _configure_custom_endpoint(
        manager,
        base_url="https://opencode.ai.example.test/zen/v1",
        billing_class="free",
    )

    rows = manager._parse_provider_model_rows("custom", [{"id": native_model_id}])

    assert len(rows) == 1
    assert rows[0].model_id == f"custom/{native_model_id}"
    assert rows[0].available is True
    assert (
        manager._known_model_exclusion_reason(
            "custom", "https://opencode.ai.example.test/zen/v1", native_model_id
        )
        is None
    )


@pytest.mark.parametrize(
    "native_model_id", [model_id for model_id, _reason in _zen_exclusion_fixtures()]
)
def test_custom_selection_and_turn_reject_forged_excluded_model_before_key_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    native_model_id: str,
) -> None:
    """Fail closed for stale catalog rows before loading an upstream key or making a request."""

    model_id = f"custom/{native_model_id}"
    model = SimpleNamespace(model_id=model_id, provider_id="custom", available=True)

    class Catalog:
        def get_model(self, candidate_id: str) -> SimpleNamespace | None:
            return model if candidate_id == model_id else None

    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="c" * 64),
        catalog=Catalog(),
        vault_dir=tmp_path / "assistant-vault",
    )
    _configure_custom_endpoint(
        manager,
        base_url="https://opencode.ai/zen/v1",
        billing_class="free",
        credential="synthetic-custom-key",
    )
    credential_reads: list[str] = []
    provider_calls: list[str] = []

    def read_credential(provider_id: str) -> str | None:
        credential_reads.append(provider_id)
        return "synthetic-custom-key"

    async def fake_stream(url: str, **_kwargs: object):
        provider_calls.append(url)
        yield b""

    monkeypatch.setattr(manager, "_read_credential", read_credential)
    monkeypatch.setattr(providers, "stream_public_https", fake_stream)

    with pytest.raises(ProviderUnavailable, match="model_unavailable"):
        manager._validated_model("custom", model_id)
    with pytest.raises(ProviderUnavailable, match="model_unavailable"):
        manager.model_policy_state(model_id)
    with pytest.raises(ProviderUnavailable, match="model_unavailable"):
        manager.proxy_chat_completion(
            "custom",
            model_id,
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "synthetic"}],
                "stream": True,
            },
            authorization_check=lambda: True,
        )

    assert credential_reads == []
    assert provider_calls == []


def test_configured_provider_models_are_live_discovered_and_admin_disabled_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Join exact model IDs to fixed reviewed terms after bounded authenticated discovery."""

    now = 10.0
    calls: list[tuple[str, dict[str, str], float, int]] = []
    manager, catalog = _configured_provider_manager(tmp_path, lambda: now)
    manager.set_credential("openai", "synthetic-provider-key")

    async def fake_request(
        url: str,
        *,
        headers: object,
        timeout_seconds: float,
        max_response_bytes: int,
    ):
        calls.append((url, dict(headers), timeout_seconds, max_response_bytes))
        return SimpleNamespace(
            status_code=200,
            content=json.dumps(
                {
                    "data": [
                        {"id": "synthetic-text-model"},
                        {"id": "synthetic-text-model"},
                        {"id": "contains spaces"},
                        {"name": "missing-id"},
                    ]
                }
            ).encode(),
        )

    monkeypatch.setattr(providers, "request_public_https", fake_request)

    async def refresh_concurrently():
        return await asyncio.gather(
            manager.ensure_model_inventory(),
            manager.ensure_model_inventory(),
            manager.ensure_model_inventory(),
        )

    results = asyncio.run(refresh_concurrently())
    model_id = "openai/synthetic-text-model"
    assert len(calls) == 1
    assert calls[0][0] == "https://api.openai.com/v1/models"
    assert calls[0][1] == {"authorization": "Bearer synthetic-provider-key"}
    assert calls[0][2] <= 6.5
    assert calls[0][3] == providers._MAX_VALIDATE_BYTES
    assert all(any(row.model_id == model_id for row in rows) for rows in results)
    model = catalog.get_model(model_id)
    assert model is not None
    assert model.available is True
    assert model.free is False
    assert model.training is False
    assert model.data_collection_allowed is False
    assert model.billing_class == "paid"

    state = manager.model_policy_state(model_id)
    assert state["enabled"] is False
    assert state["usable"] is False
    assert state["revision"] == 0
    accepted = manager.update_model_policy(
        model_id,
        enabled=True,
        acknowledged_privacy_policy_version=str(state["privacy_policy_version"]),
        acknowledged_billing_policy_version=str(state["billing_policy_version"]),
        expected_revision=0,
    )
    assert accepted["enabled"] is True
    assert accepted["usable"] is True
    assert accepted["revision"] == 1
    openai_provider = next(row for row in manager.list_providers() if row.provider_id == "openai")
    assert openai_provider.connection_status == "connected"
    public_provider = openai_provider.public_dict()
    assert "synthetic-provider-key" not in json.dumps(
        {"provider": public_provider, "model_policy": accepted}, sort_keys=True
    )


def test_configured_provider_model_discovery_expires_and_failure_suppresses_then_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed provider refresh removes stale models and later demand can restore them."""

    now = 10.0
    calls = 0
    manager, catalog = _configured_provider_manager(tmp_path, lambda: now)
    manager.set_credential("google", "synthetic-google-key")

    async def fake_request(
        _url: str,
        *,
        headers: object,
        timeout_seconds: float,
        max_response_bytes: int,
    ):
        nonlocal calls
        assert dict(headers) == {"x-goog-api-key": "synthetic-google-key"}
        assert timeout_seconds <= 6.5
        assert max_response_bytes == providers._MAX_VALIDATE_BYTES
        calls += 1
        if calls == 2:
            return SimpleNamespace(status_code=503, content=b"not retained")
        return SimpleNamespace(
            status_code=200,
            content=(
                b'{"models":[{"name":"models/synthetic-google-model",'
                b'"displayName":"Synthetic Google model",'
                b'"supportedGenerationMethods":["generateContent"]}]}'
            ),
        )

    monkeypatch.setattr(providers, "request_public_https", fake_request)
    asyncio.run(manager.ensure_model_inventory())
    model_id = "google/synthetic-google-model"
    model = catalog.get_model(model_id)
    assert model is not None
    assert model.training is True
    assert model.data_collection_allowed is True
    assert model.data_collection_default is False
    assert model.free is False
    first_state = manager.model_policy_state(model_id)
    assert first_state["enabled"] is False
    assert first_state["usable"] is False
    assert first_state["revision"] == 0

    now += 301.0
    asyncio.run(manager.ensure_model_inventory())
    assert calls == 2
    assert catalog.get_model(model_id) is None
    google_provider = next(row for row in manager.list_providers() if row.provider_id == "google")
    assert google_provider.connection_status == "unavailable"
    asyncio.run(manager.ensure_model_inventory())
    assert calls == 2  # The failed refresh is briefly suppressed.

    now += 5.1
    asyncio.run(manager.ensure_model_inventory())
    assert calls == 3
    recovered = catalog.get_model(model_id)
    assert recovered is not None
    assert recovered.available is True
    assert manager.model_policy_state(model_id)["enabled"] is False


def test_provider_model_id_cannot_be_selected_under_a_different_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A discovered provider model remains bound to its exact provider ID."""

    manager, _catalog = _configured_provider_manager(tmp_path, lambda: 10.0)
    manager.set_credential("openai", "synthetic-provider-key")

    async def fake_request(*_args: object, **_kwargs: object):
        return SimpleNamespace(status_code=200, content=b'{"data":[{"id":"model-a"}]}')

    monkeypatch.setattr(providers, "request_public_https", fake_request)
    asyncio.run(manager.validate("openai"))
    with pytest.raises(ProviderUnavailable, match="model_unavailable"):
        manager.update_provider("google", model_id="openai/model-a")


def test_provider_model_discovery_rejects_auth_failure_without_leaking_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An upstream auth rejection removes that API inventory without hiding other routes."""

    manager, catalog = _configured_provider_manager(tmp_path, lambda: 10.0)
    manager.set_credential("openai", "synthetic-provider-key")

    async def fake_request(*_args: object, **_kwargs: object):
        return SimpleNamespace(status_code=401, content=b"provider response omitted")

    monkeypatch.setattr(providers, "request_public_https", fake_request)
    with pytest.raises(CredentialRejected, match="credential_rejected"):
        asyncio.run(manager.validate("openai"))

    assert not any(item.provider_id == "openai" for item in catalog.list_models())
    public_provider = next(
        item.public_dict() for item in manager.list_providers() if item.provider_id == "openai"
    )
    assert public_provider["connection_status"] == "validation_failed"
    assert "synthetic-provider-key" not in json.dumps(public_provider, sort_keys=True)


def test_provider_validation_revocation_after_response_preserves_inventory_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A revoked admin validation cannot clear or replace the prior provider inventory."""

    manager, _catalog = _configured_provider_manager(tmp_path, lambda: 10.0)
    manager.set_credential("openai", "synthetic-provider-key")
    existing = (object(),)
    manager._provider_models["openai"] = existing
    manager._provider_inventory_loaded_at["openai"] = 8.0
    manager._provider_inventory_status["openai"] = "connected"
    manager._provider_inventory_retry_at["openai"] = 3.0
    cache_before = (
        manager._provider_models["openai"],
        manager._provider_inventory_loaded_at["openai"],
        manager._provider_inventory_status["openai"],
        manager._provider_inventory_retry_at["openai"],
    )
    response_started = asyncio.Event()
    release_response = asyncio.Event()
    authorization = {"allowed": True}

    async def held_request(
        _url: str,
        *,
        headers: object,
        timeout_seconds: float,
        max_response_bytes: int,
        authorization_check: object,
    ) -> SimpleNamespace:
        assert dict(headers) == {"authorization": "Bearer synthetic-provider-key"}
        assert timeout_seconds <= 6.5
        assert max_response_bytes == providers._MAX_VALIDATE_BYTES
        assert callable(authorization_check)
        response_started.set()
        await release_response.wait()
        return SimpleNamespace(status_code=200, content=b'{"data":[{"id":"new-model"}]}')

    monkeypatch.setattr(providers, "request_public_https", held_request)

    async def authorization_check() -> bool:
        return authorization["allowed"] is True

    async def exercise() -> None:
        validation = asyncio.create_task(
            manager.validate("openai", authorization_check=authorization_check)
        )
        await asyncio.wait_for(response_started.wait(), timeout=1)
        authorization["allowed"] = False
        release_response.set()
        with pytest.raises(CredentialRejected, match="oauth_authorization_required"):
            await validation

    asyncio.run(exercise())
    cache_after = (
        manager._provider_models["openai"],
        manager._provider_inventory_loaded_at["openai"],
        manager._provider_inventory_status["openai"],
        manager._provider_inventory_retry_at["openai"],
    )
    assert cache_after == cache_before


def test_zen_validation_revocation_after_response_preserves_catalog_cache(
    tmp_path: Path,
) -> None:
    """A revoked admin validation cannot replace or clear the shared Zen catalog cache."""

    model_suffix = _reviewed_zen_model_ids()[1]
    response_started = asyncio.Event()
    release_response = asyncio.Event()
    authorization = {"allowed": True}
    calls = 0

    async def requester(_url: str) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        if calls > 1:
            response_started.set()
            await release_response.wait()
        return SimpleNamespace(
            status_code=200,
            content=json.dumps({"data": [{"id": model_suffix}]}).encode(),
        )

    catalog = AssistantModelCatalog(requester=requester, clock=lambda: 10.0)
    original_models = asyncio.run(catalog.refresh())
    settings = SimpleNamespace(data_dir=tmp_path, auth_session_secret="t" * 64)
    manager = AssistantProviderManager(
        settings,
        catalog,
        vault_dir=tmp_path / "assistant-vault",
        clock=lambda: 10.0,
    )
    cache_before = (catalog._models, catalog._loaded_at, catalog._retry_at)

    async def authorization_check() -> bool:
        return authorization["allowed"] is True

    async def exercise() -> None:
        validation = asyncio.create_task(
            manager.validate("opencode-zen", authorization_check=authorization_check)
        )
        await asyncio.wait_for(response_started.wait(), timeout=1)
        authorization["allowed"] = False
        release_response.set()
        with pytest.raises(CredentialRejected, match="oauth_authorization_required"):
            await validation

    asyncio.run(exercise())

    assert original_models == catalog._models
    assert (catalog._models, catalog._loaded_at, catalog._retry_at) == cache_before
    assert calls == 2


@pytest.mark.parametrize("boundary", ("provider_inventory", "zen_catalog"))
def test_provider_validation_revocation_while_waiting_for_refresh_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    """A revoked validation queued behind refresh single-flight cannot fetch or change cache."""

    authorization = {"allowed": True}
    calls: list[str] = []
    manager, catalog = _configured_provider_manager(tmp_path, lambda: 10.0)
    cache_before: tuple[object, ...] | None = None

    if boundary == "provider_inventory":
        manager.set_credential("openai", "synthetic-lock-provider-key")
        existing_models = (object(),)
        manager._provider_models["openai"] = existing_models
        manager._provider_inventory_loaded_at["openai"] = 8.0
        manager._provider_inventory_status["openai"] = "connected"
        manager._provider_inventory_retry_at["openai"] = 3.0
        cache_before = (
            manager._provider_models["openai"],
            manager._provider_inventory_loaded_at["openai"],
            manager._provider_inventory_status["openai"],
            manager._provider_inventory_retry_at["openai"],
        )
        lock = manager._inventory_lock
        provider_id = "openai"

        async def fake_request(_url: str, **_kwargs: object) -> SimpleNamespace:
            calls.append("provider request")
            return SimpleNamespace(status_code=200, content=b'{"data":[]}')

        monkeypatch.setattr(providers, "request_public_https", fake_request)
    else:
        model_suffix = _reviewed_zen_model_ids()[1]

        async def requester(_url: str) -> SimpleNamespace:
            calls.append("catalog request")
            return SimpleNamespace(
                status_code=200,
                content=json.dumps({"data": [{"id": model_suffix}]}).encode(),
            )

        catalog = AssistantModelCatalog(requester=requester, clock=lambda: 10.0)
        manager = AssistantProviderManager(
            SimpleNamespace(data_dir=tmp_path, auth_session_secret="t" * 64),
            catalog,
            vault_dir=tmp_path / "assistant-vault",
            clock=lambda: 10.0,
        )
        lock = catalog._refresh_lock
        provider_id = "opencode-zen"

    async def authorization_check() -> bool:
        return authorization["allowed"] is True

    async def wait_until_queued() -> None:
        for _ in range(1000):
            waiters = getattr(lock, "_waiters", None)
            if waiters:
                return
            await asyncio.sleep(0)
        raise AssertionError("validation did not queue behind the held refresh lock")

    async def exercise() -> None:
        nonlocal cache_before
        if boundary == "zen_catalog":
            await catalog.refresh()
            cache_before = (catalog._models, catalog._loaded_at, catalog._retry_at)
            assert len(calls) == 1

        await lock.acquire()
        validation = asyncio.create_task(
            manager.validate(provider_id, authorization_check=authorization_check)
        )
        await asyncio.wait_for(wait_until_queued(), timeout=1)
        authorization["allowed"] = False
        lock.release()
        with pytest.raises(CredentialRejected, match="oauth_authorization_required"):
            await validation

    asyncio.run(exercise())
    assert calls == ([] if boundary == "provider_inventory" else ["catalog request"])
    assert cache_before is not None
    if boundary == "provider_inventory":
        assert (
            manager._provider_models["openai"],
            manager._provider_inventory_loaded_at["openai"],
            manager._provider_inventory_status["openai"],
            manager._provider_inventory_retry_at["openai"],
        ) == cache_before
    else:
        assert (catalog._models, catalog._loaded_at, catalog._retry_at) == cache_before


@pytest.mark.parametrize(
    ("provider_id", "adapter_request", "expected_url", "expected_headers", "expected_model"),
    [
        (
            "openai",
            {
                "body": {
                    "model": "assistant-selected",
                    "input": [
                        {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "synthetic"}],
                        }
                    ],
                    "instructions": "Use the approved local functions.",
                    "stream": True,
                    "store": False,
                },
                "path_model_id": None,
                "query": (),
            },
            "https://api.openai.com/v1/responses",
            {"accept": "text/event-stream", "Authorization": "Bearer synthetic-key"},
            "gpt-test",
        ),
        (
            "anthropic",
            {
                "body": {
                    "model": "assistant-selected",
                    "max_tokens": 512,
                    "messages": [{"role": "user", "content": "synthetic"}],
                    "system": "Use the approved local functions.",
                    "stream": True,
                },
                "path_model_id": None,
                "query": (("beta", "true"),),
            },
            "https://api.anthropic.com/v1/messages",
            {
                "accept": "text/event-stream",
                "x-api-key": "synthetic-key",
                "anthropic-version": "2023-06-01",
            },
            "claude-test",
        ),
        (
            "google",
            {
                "body": {"contents": [{"role": "user", "parts": [{"text": "synthetic"}]}]},
                "path_model_id": "assistant-selected",
                "query": (("alt", "sse"),),
            },
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:streamGenerateContent?alt=sse",
            {"accept": "text/event-stream", "x-goog-api-key": "synthetic-key"},
            None,
        ),
    ],
)
def test_native_protocol_proxy_preserves_vendor_wire_and_keeps_key_app_side(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
    adapter_request: dict[str, object],
    expected_url: str,
    expected_headers: dict[str, str],
    expected_model: str | None,
) -> None:
    """Keep each native schema distinct while replacing only the server-side model alias."""

    model_suffix = {
        "openai": "gpt-test",
        "anthropic": "claude-test",
        "google": "gemini-test",
    }[provider_id]
    model_id = f"{provider_id}/{model_suffix}"
    model = SimpleNamespace(model_id=model_id, provider_id=provider_id, available=True)

    class Catalog:
        def get_model(self, candidate_id: str) -> SimpleNamespace | None:
            return model if candidate_id == model_id else None

    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="t" * 64),
        catalog=Catalog(),
        vault_dir=tmp_path / "assistant-vault",
    )
    manager.set_credential(provider_id, "synthetic-key")
    captured: dict[str, object] = {}

    async def fake_stream(
        url: str,
        *,
        headers: object,
        body: bytes,
        timeout_seconds: float,
        max_response_bytes: int,
    ):
        captured.update(
            {
                "url": url,
                "headers": dict(headers),
                "body": json.loads(body),
                "timeout_seconds": timeout_seconds,
                "max_response_bytes": max_response_bytes,
            }
        )
        yield b'event: response.completed\ndata: {"type":"response.completed"}\n\n'

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)

    async def exercise() -> list[bytes]:
        stream = manager.proxy_native_stream(
            provider_id,
            model_id,
            adapter_request["body"],
            path_model_id=adapter_request["path_model_id"],
            query=adapter_request["query"],
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
        return [chunk async for chunk in stream]

    chunks = asyncio.run(exercise())

    assert chunks == [b'event: response.completed\ndata: {"type":"response.completed"}\n\n']
    assert captured["url"] == expected_url
    assert captured["headers"] == expected_headers
    assert captured["timeout_seconds"] == 120.0
    assert captured["max_response_bytes"] == 1_048_576
    forwarded = captured["body"]
    assert isinstance(forwarded, dict)
    if expected_model is not None:
        assert forwarded["model"] == expected_model
    else:
        assert "model" not in forwarded
    assert "synthetic-key" not in json.dumps(forwarded, sort_keys=True)


@pytest.mark.parametrize(
    ("provider_id", "body", "path_model_id", "query"),
    [
        (
            "openai",
            {"model": "attacker-model", "input": "synthetic", "stream": True, "store": False},
            None,
            (),
        ),
        (
            "anthropic",
            {"model": "assistant-selected", "max_tokens": 512, "messages": [], "stream": True},
            None,
            (("beta", "true"), ("api_key", "injected")),
        ),
        (
            "google",
            {"contents": [{"role": "user", "parts": [{"text": "x"}]}]},
            "models/attacker-model",
            (("alt", "sse"),),
        ),
    ],
)
def test_native_protocol_proxy_rejects_unknown_model_path_or_query_before_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
    body: dict[str, object],
    path_model_id: str | None,
    query: tuple[tuple[str, str], ...],
) -> None:
    """Do not let native path, query, or body choose another model or endpoint."""

    model_id = f"{provider_id}/reviewed-model"
    model = SimpleNamespace(model_id=model_id, provider_id=provider_id, available=True)

    class Catalog:
        def get_model(self, candidate_id: str) -> SimpleNamespace | None:
            return model if candidate_id == model_id else None

    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="t" * 64),
        catalog=Catalog(),
        vault_dir=tmp_path / "assistant-vault",
    )
    called = False

    async def unexpected_stream(*_args: object, **_kwargs: object):
        nonlocal called
        called = True
        yield b""

    monkeypatch.setattr(providers, "stream_public_https", unexpected_stream)
    tools = [{"name": "workspace.summary", "description": "safe", "inputSchema": {}}]
    with pytest.raises(ProviderUnavailable, match="provider_request_invalid"):
        manager.proxy_native_stream(
            provider_id,
            model_id,
            body,
            path_model_id=path_model_id,
            query=query,
            app_tools=tools,
            authorization_check=lambda: True,
        )
    assert called is False


def test_native_protocol_proxy_withholds_secret_echo_split_across_sse_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never release a text-delta prefix before a later SSE event completes the vault key."""

    model_id = "openai/gpt-test"
    model = SimpleNamespace(model_id=model_id, provider_id="openai", available=True)

    class Catalog:
        def get_model(self, candidate_id: str) -> SimpleNamespace | None:
            return model if candidate_id == model_id else None

    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="t" * 64),
        catalog=Catalog(),
        vault_dir=tmp_path / "assistant-vault",
    )
    manager.set_credential("openai", "synthetic-provider-secret")

    first = b'data: {"type":"response.output_text.delta","delta":"synthetic-provider-"}\n\n'
    second = b'data: {"type":"response.output_text.delta","delta":"secret"}\n\n'
    complete_stream = first + second
    chunks: list[bytes] = []

    async def fake_stream(*_args: object, **_kwargs: object):
        for chunk in chunks:
            yield chunk

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)

    async def exercise() -> list[bytes]:
        stream = manager.proxy_native_stream(
            "openai",
            model_id,
            {
                "model": "assistant-selected",
                "input": "synthetic",
                "stream": True,
                "store": False,
            },
            path_model_id=None,
            query=(),
            app_tools=[{"name": "workspace.summary", "description": "safe", "inputSchema": {}}],
            authorization_check=lambda: True,
        )
        return [chunk async for chunk in stream]

    for split in range(len(complete_stream) + 1):
        chunks[:] = [part for part in (complete_stream[:split], complete_stream[split:]) if part]
        released: list[bytes] = []
        with pytest.raises(ProviderUnavailable, match="provider_response_secret_rejected"):
            released.extend(asyncio.run(exercise()))
        assert released == []


def test_secret_guard_detects_json_escaped_key_split_across_events() -> None:
    """Decode JSON strings before checking a key split across separately valid events."""

    provider_key = "synthetic\\provider-secret"
    first = (
        "data: "
        + json.dumps({"type": "response.output_text.delta", "delta": "synthetic\\"})
        + "\n\n"
    ).encode()
    second = (
        "data: "
        + json.dumps({"type": "response.output_text.delta", "delta": "provider-secret"})
        + "\n\n"
    ).encode()
    guard = providers._SecretStreamGuard(provider_key, protocol="openai-responses")

    assert guard.push(first) == ()
    with pytest.raises(ProviderUnavailable, match="provider_response_secret_rejected"):
        guard.push(second)


@pytest.mark.parametrize(
    ("protocol", "frames"),
    [
        (
            "openai-responses",
            [
                {
                    "type": "response.output_text.delta",
                    "item_id": "item-text",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": "synthetic-provider-",
                },
                {
                    "type": "response.reasoning_summary_text.delta",
                    "item_id": "item-reasoning",
                    "output_index": 1,
                    "summary_index": 0,
                    "delta": "unrelated-channel-filler-that-is-longer-than-the-key",
                },
                {
                    "type": "response.output_text.delta",
                    "item_id": "item-text",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": "secret",
                },
            ],
        ),
        (
            "openai-compatible-chat",
            [
                {"choices": [{"index": 0, "delta": {"content": "synthetic-provider-"}}]},
                {
                    "choices": [
                        {
                            "index": 1,
                            "delta": {"content": "unrelated-channel-filler-longer-than-the-key"},
                        }
                    ]
                },
                {"choices": [{"index": 0, "delta": {"content": "secret"}}]},
            ],
        ),
        (
            "anthropic-messages",
            [
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "synthetic-provider-"},
                },
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {
                        "type": "text_delta",
                        "text": "unrelated-channel-filler-longer-than-the-key",
                    },
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "secret"},
                },
            ],
        ),
        (
            "google-generative-language",
            [
                {
                    "candidates": [
                        {
                            "index": 0,
                            "content": {"parts": [{"text": "synthetic-provider-"}]},
                        }
                    ]
                },
                {
                    "candidates": [
                        {
                            "index": 1,
                            "content": {
                                "parts": [{"text": "unrelated-channel-filler-longer-than-the-key"}]
                            },
                        }
                    ]
                },
                {"candidates": [{"index": 0, "content": {"parts": [{"text": "secret"}]}}]},
            ],
        ),
    ],
)
def test_secret_guard_keeps_independent_protocol_channels_separate(
    protocol: str, frames: list[dict[str, object]]
) -> None:
    """Do not let long text on a different output/choice/block/candidate release a key prefix."""

    guard = providers._SecretStreamGuard("synthetic-provider-secret", protocol=protocol)
    for payload in frames[:-1]:
        frame = f"data: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()
        assert guard.push(frame) == ()
    final_frame = f"data: {json.dumps(frames[-1], separators=(',', ':'))}\n\n".encode()

    with pytest.raises(ProviderUnavailable, match="provider_response_secret_rejected"):
        guard.push(final_frame)


def test_chat_tool_argument_channel_survives_later_deltas_without_optional_call_id() -> None:
    """Use stable choice/tool indices when later native deltas omit their first-frame ID."""

    guard = providers._SecretStreamGuard(
        "synthetic-provider-secret", protocol="openai-compatible-chat"
    )
    first = (
        b'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,'
        b'"id":"call-fixed","function":{"arguments":"synthetic-provider-"}}]}}]}\n\n'
    )
    unrelated = (
        b'data: {"choices":[{"index":1,"delta":{"content":"ordinary filler '
        b'longer than the credential prefix"}}]}\n\n'
    )
    continuation = (
        b'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,'
        b'"function":{"arguments":"secret"}}]}}]}\n\n'
    )

    assert guard.push(first) == ()
    assert guard.push(unrelated) == ()
    with pytest.raises(ProviderUnavailable, match="provider_response_secret_rejected"):
        guard.push(continuation)


def test_secret_guard_does_not_wait_for_unrelated_short_completed_channel() -> None:
    """A short reasoning channel must not keep a long normal answer over the frame cap."""

    guard = providers._SecretStreamGuard("synthetic-provider-secret", protocol="openai-responses")
    reasoning = (
        b'data: {"type":"response.reasoning_summary_text.delta",'
        b'"output_index":0,"summary_index":0,"delta":"Brief."}\n\n'
    )
    assert guard.push(reasoning) == (reasoning,)

    for index in range(300):
        frame = (
            "data: "
            + json.dumps(
                {
                    "type": "response.output_text.delta",
                    "output_index": 1,
                    "content_index": 0,
                    "delta": f"ordinary-answer-fragment-{index:03d}",
                },
                separators=(",", ":"),
            )
            + "\n\n"
        ).encode()
        assert guard.push(frame) == (frame,)
    assert guard.finish() == ()


@pytest.mark.parametrize("provider_id", ("opencode-zen", "custom"))
def test_optional_credential_provider_stream_does_not_require_a_synthetic_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider_id: str
) -> None:
    """Keyless approved routes still validate and stream without inventing a key."""

    if provider_id == "opencode-zen":
        model_id, _model_suffix = _reviewed_zen_model_ids()
        catalog_provider = provider_id
    else:
        model_id = "custom/synthetic-model"
        catalog_provider = "custom"

    class OptionalCredentialCatalog:
        def get_model(self, candidate_id: str) -> SimpleNamespace | None:
            if candidate_id != model_id:
                return None
            return SimpleNamespace(
                model_id=model_id,
                provider_id=catalog_provider,
                available=True,
            )

    settings = SimpleNamespace(data_dir=tmp_path, auth_session_secret="t" * 64)
    manager = AssistantProviderManager(
        settings,
        catalog=OptionalCredentialCatalog(),
        vault_dir=tmp_path / f"{provider_id}-vault",
    )
    if provider_id == "custom":
        manager.configure_custom_endpoint(
            base_url="https://provider.example/v1",
            terms_url="https://provider.example/terms",
            privacy_disclosure="Administrator-provided privacy terms; details are unknown.",
            billing_disclosure="Administrator-provided billing terms; details are unknown.",
            billing_class="unknown",
            endpoint_policy_reviewed=True,
        )

    captured: dict[str, object] = {}

    async def fake_stream(
        url: str,
        *,
        headers: object,
        body: bytes,
        timeout_seconds: float,
        max_response_bytes: int,
    ):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json.loads(body)
        captured["timeout_seconds"] = timeout_seconds
        captured["max_response_bytes"] = max_response_bytes
        yield (
            b'data: {"choices":[{"index":0,"delta":{"content":"synthetic answer"},'
            b'"finish_reason":"stop"}]}\n\n'
        )
        yield b"data: [DONE]\n\n"

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)

    async def exercise() -> list[bytes]:
        stream = manager.proxy_chat_completion(
            provider_id,
            model_id,
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "synthetic prompt"}],
                "stream": True,
            },
            app_tools=(
                AssistantToolGateway.list_tools() if provider_id == "opencode-zen" else None
            ),
            **(_native_zen_context() if provider_id == "opencode-zen" else {}),
            authorization_check=lambda: True,
        )
        return [frame async for frame in stream]

    chunks = asyncio.run(exercise())

    assert chunks == [
        b'data: {"choices":[{"index":0,"delta":{"content":"synthetic answer"},'
        b'"finish_reason":"stop"}]}\n\n',
        b"data: [DONE]\n\n",
    ]
    expected_headers = {"accept": "text/event-stream"}
    if provider_id == "opencode-zen":
        expected_headers["authorization"] = "Bearer public"
        expected_headers.update(
            {
                "x-opencode-session": _NATIVE_SESSION_FIXTURE,
                "x-opencode-project": _NATIVE_PROJECT_FIXTURE,
            }
        )
    assert captured["headers"] == expected_headers
    assert captured["body"]["model"] == model_id.removeprefix(f"{provider_id}/")
    assert captured["url"].endswith("/chat/completions")


def test_zen_proxy_forwards_only_valid_native_identity_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_id, _model_suffix = _reviewed_zen_model_ids()

    class ZenCatalog:
        def get_model(self, candidate_id: str) -> SimpleNamespace | None:
            if candidate_id != model_id:
                return None
            return SimpleNamespace(
                model_id=model_id,
                provider_id="opencode-zen",
                available=True,
            )

    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="t" * 64),
        catalog=ZenCatalog(),
        vault_dir=tmp_path / "zen-identity-vault",
    )
    captured: dict[str, object] = {}

    async def fake_stream(
        _url: str,
        *,
        headers: object,
        body: bytes,
        timeout_seconds: float,
        max_response_bytes: int,
    ):
        captured["headers"] = dict(headers)
        captured["body"] = json.loads(body)
        del timeout_seconds, max_response_bytes
        yield (
            b'data: {"choices":[{"index":0,"delta":{"content":"synthetic"},'
            b'"finish_reason":"stop"}]}'
            b"\n\n"
        )
        yield b"data: [DONE]\n\n"

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)

    async def exercise() -> list[bytes]:
        stream = manager.proxy_chat_completion(
            "opencode-zen",
            model_id,
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "synthetic prompt"}],
                "stream": True,
            },
            app_session_id="private-app-session",
            native_session_id="ses_private_native_session",
            native_user_agent="opencode/stable/2.0.7/opencode",
            native_client="opencode",
            native_opencode_session=_NATIVE_SESSION_FIXTURE,
            native_opencode_project=_NATIVE_PROJECT_FIXTURE,
            native_session_affinity=_NATIVE_SESSION_FIXTURE,
            native_session_id_alias=_NATIVE_SESSION_FIXTURE,
            app_tools=AssistantToolGateway.list_tools(),
            authorization_check=lambda: True,
        )
        return [chunk async for chunk in stream]

    assert asyncio.run(exercise())[-1] == b"data: [DONE]\n\n"
    expected_headers = {
        "accept": "text/event-stream",
        "authorization": "Bearer public",
        "user-agent": "opencode/stable/2.0.7/opencode",
        "x-opencode-client": "opencode",
        "x-opencode-session": _NATIVE_SESSION_FIXTURE,
        "x-opencode-project": _NATIVE_PROJECT_FIXTURE,
        "x-session-affinity": _NATIVE_SESSION_FIXTURE,
        "x-session-id": _NATIVE_SESSION_FIXTURE,
    }
    assert captured["headers"] == expected_headers
    assert captured["body"]["model"] == model_id.removeprefix("opencode-zen/")


@pytest.mark.parametrize(
    ("user_agent", "client"),
    (
        ("opencode/stable/2.0.7/opencode\r\nInjected: value", "opencode"),
        ("opencode/" + "x" * 280 + "/2.0.7/opencode", "opencode"),
        ("opencode/stable/2.0.7/opencode", "different-client"),
        (None, "opencode"),
    ),
    ids=("crlf", "oversize", "client-mismatch", "client-without-user-agent"),
)
def test_zen_proxy_rejects_malformed_native_identity_before_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    user_agent: str | None,
    client: str,
) -> None:
    model_id, _model_suffix = _reviewed_zen_model_ids()

    class ZenCatalog:
        def get_model(self, candidate_id: str) -> SimpleNamespace | None:
            if candidate_id != model_id:
                return None
            return SimpleNamespace(model_id=model_id, provider_id="opencode-zen", available=True)

    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="u" * 64),
        catalog=ZenCatalog(),
        vault_dir=tmp_path / "zen-invalid-identity-vault",
    )
    transport_calls: list[bool] = []

    async def unexpected_stream(*_args: object, **_kwargs: object):
        transport_calls.append(True)
        yield b"data: [DONE]\n\n"

    monkeypatch.setattr(providers, "stream_public_https", unexpected_stream)
    with pytest.raises(ProviderUnavailable, match="provider_request_invalid"):
        manager.proxy_chat_completion(
            "opencode-zen",
            model_id,
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "synthetic prompt"}],
                "stream": True,
            },
            native_user_agent=user_agent,
            native_client=client,
            **_native_zen_context(),
            app_tools=AssistantToolGateway.list_tools(),
            authorization_check=lambda: True,
        )
    assert transport_calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("native_opencode_session", "ses_not_a_native_id"),
        ("native_opencode_project", "/run/assistant/worker-locations/private"),
        ("native_opencode_project", "bad\nproject"),
        ("native_opencode_project", "p" * 129),
        ("native_opencode_project", "caf\N{LATIN SMALL LETTER E WITH ACUTE}"),
        ("native_session_affinity", "ses_0123456789abABCDEFGHIJKLMA"),
        ("native_session_id_alias", "ses_0123456789abABCDEFGHIJKLMA"),
    ),
    ids=(
        "session-shape",
        "project-path",
        "project-control",
        "project-size",
        "project-ascii",
        "affinity-mismatch",
        "session-alias-mismatch",
    ),
)
def test_zen_proxy_rejects_malformed_native_session_metadata_before_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    model_id, _model_suffix = _reviewed_zen_model_ids()

    class ZenCatalog:
        def get_model(self, candidate_id: str) -> SimpleNamespace | None:
            if candidate_id != model_id:
                return None
            return SimpleNamespace(model_id=model_id, provider_id="opencode-zen", available=True)

    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="w" * 64),
        catalog=ZenCatalog(),
        vault_dir=tmp_path / "zen-invalid-session-metadata-vault",
    )
    transport_calls: list[bool] = []

    async def unexpected_stream(*_args: object, **_kwargs: object):
        transport_calls.append(True)
        yield b"data: [DONE]\n\n"

    monkeypatch.setattr(providers, "stream_public_https", unexpected_stream)
    context = {
        "native_user_agent": "opencode/stable/2.0.7/opencode",
        "native_client": "opencode",
        **_native_zen_context(),
        "native_session_affinity": _NATIVE_SESSION_FIXTURE,
        "native_session_id_alias": _NATIVE_SESSION_FIXTURE,
    }
    context[field] = value
    with pytest.raises(ProviderUnavailable, match="provider_request_invalid"):
        manager.proxy_chat_completion(
            "opencode-zen",
            model_id,
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "synthetic"}],
                "stream": True,
            },
            app_tools=AssistantToolGateway.list_tools(),
            authorization_check=lambda: True,
            **context,
        )
    assert transport_calls == []


@pytest.mark.parametrize("provider_id", ("openai", "custom"))
def test_non_zen_proxy_ignores_native_identity_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
) -> None:
    if provider_id == "custom":
        model_id = "custom/synthetic-model"

        class CustomCatalog:
            def get_model(self, candidate_id: str) -> SimpleNamespace | None:
                if candidate_id != model_id:
                    return None
                return SimpleNamespace(
                    model_id=model_id,
                    provider_id="custom",
                    available=True,
                )

        manager = AssistantProviderManager(
            SimpleNamespace(data_dir=tmp_path, auth_session_secret="v" * 64),
            catalog=CustomCatalog(),
            vault_dir=tmp_path / "custom-identity-vault",
        )
    else:
        manager, model_id = _native_gateway_proxy_manager(tmp_path, provider_id)
    if provider_id == "custom":
        manager.configure_custom_endpoint(
            base_url="https://provider.example/v1",
            terms_url="https://provider.example/terms",
            privacy_disclosure="Synthetic privacy terms.",
            billing_disclosure="Synthetic billing terms.",
            billing_class="unknown",
            endpoint_policy_reviewed=True,
        )
    captured: dict[str, object] = {}

    async def fake_stream(
        _url: str,
        *,
        headers: object,
        body: bytes,
        timeout_seconds: float,
        max_response_bytes: int,
    ):
        captured["headers"] = dict(headers)
        del body, timeout_seconds, max_response_bytes
        yield (
            b'data: {"choices":[{"index":0,"delta":{"content":"synthetic"},'
            b'"finish_reason":"stop"}]}'
            b"\n\n"
        )
        yield b"data: [DONE]\n\n"

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)

    async def exercise() -> None:
        stream = manager.proxy_chat_completion(
            provider_id,
            model_id,
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "synthetic prompt"}],
                "stream": True,
            },
            native_user_agent="opencode/stable/2.0.7/opencode",
            native_client="opencode",
            native_opencode_session="malformed-ignored-on-non-zen",
            native_opencode_project="../ignored-on-non-zen",
            native_session_affinity="mismatch-ignored-on-non-zen",
            native_session_id_alias="mismatch-ignored-on-non-zen",
            authorization_check=lambda: True,
        )
        _ = [chunk async for chunk in stream]

    asyncio.run(exercise())
    expected_headers = {"accept": "text/event-stream"}
    if provider_id == "openai":
        expected_headers["authorization"] = "Bearer synthetic-provider-key"
    assert captured["headers"] == expected_headers


def test_legacy_compatible_proxy_withholds_secret_echo_split_across_sse_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Apply the same cross-event app-key guard before legacy Zen-compatible bytes escape."""

    provider_key = "synthetic-provider-secret"
    manager = _chat_compat_manager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="t" * 64),
        tmp_path / "assistant-vault",
    )
    manager.set_credential("openai", provider_key)
    first = (
        b'data: {"choices":[{"index":0,"delta":{"content":"synthetic-provider-"},'
        b'"finish_reason":null}]}\n\n'
    )
    second = (
        b'data: {"choices":[{"index":0,"delta":{"content":"secret"},"finish_reason":null}]}\n\n'
    )
    complete_stream = first + second
    chunks: list[bytes] = []

    async def fake_stream(*_args: object, **_kwargs: object):
        for chunk in chunks:
            yield chunk

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)

    async def exercise() -> list[bytes]:
        stream = manager.proxy_chat_completion(
            "openai",
            _TEST_MODEL_ID,
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "synthetic"}],
                "stream": True,
            },
            authorization_check=lambda: True,
        )
        return [chunk async for chunk in stream]

    for split in range(len(complete_stream) + 1):
        chunks[:] = [part for part in (complete_stream[:split], complete_stream[split:]) if part]
        released: list[bytes] = []
        with pytest.raises(ProviderUnavailable, match="provider_response_secret_rejected"):
            released.extend(asyncio.run(exercise()))
        assert released == []


def test_legacy_compatible_proxy_rejects_unencodable_fixture_text_safely(
    tmp_path: Path,
) -> None:
    """Reject lone surrogates as bounded request errors instead of leaking encoding errors."""

    manager = _chat_compat_manager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="t" * 64),
        tmp_path / "assistant-vault",
    )
    manager.set_credential("openai", "synthetic-provider-key")
    tools, _messages = _message_fixture()
    tools[0]["function"]["description"] = "\ud800"
    with pytest.raises(ProviderUnavailable, match="provider_request_invalid"):
        manager.proxy_chat_completion(
            "openai",
            _TEST_MODEL_ID,
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "synthetic"}],
                "stream": True,
                "tools": tools,
            },
            authorization_check=lambda: True,
        )

    with pytest.raises(ProviderUnavailable, match="provider_request_invalid"):
        manager.proxy_chat_completion(
            "openai",
            _TEST_MODEL_ID,
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "\ud800"}],
                "stream": True,
            },
            authorization_check=lambda: True,
        )


def test_responses_request_without_tools_keeps_initialized_empty_allowlist() -> None:
    """Accept a no-tools request without reading an uninitialized tool-name set."""

    request = providers._validated_native_provider_body(
        "openai-responses",
        {"model": "assistant-selected", "input": "synthetic", "stream": True, "store": False},
        model_alias="assistant-selected",
        upstream_model_id="reviewed/model",
        app_tools=[{"name": "workspace.summary", "description": "safe", "inputSchema": {}}],
    )

    assert request["model"] == "reviewed/model"
    assert "tools" not in request


@pytest.mark.parametrize(
    ("protocol", "body", "token_path"),
    (
        (
            "openai-responses",
            {"model": "assistant-selected", "input": "synthetic", "stream": True, "store": False},
            ("max_output_tokens",),
        ),
        (
            "anthropic-messages",
            {
                "model": "assistant-selected",
                "max_tokens": 128,
                "messages": [{"role": "user", "content": "synthetic"}],
                "stream": True,
            },
            ("max_tokens",),
        ),
        (
            "google-generative-language",
            {"contents": [{"role": "user", "parts": [{"text": "synthetic"}]}]},
            ("generationConfig", "maxOutputTokens"),
        ),
        (
            "openai-compatible-chat",
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "synthetic"}],
                "stream": True,
                "store": False,
            },
            ("max_tokens",),
        ),
    ),
)
def test_native_adapter_output_budget_defaults_and_rejects_overflow(
    protocol: str,
    body: dict[str, object],
    token_path: tuple[str, ...],
) -> None:
    """Each supported wire protocol has a bounded upstream output request."""

    budget = native_output_token_budget()
    app_tools = [{"name": "workspace.summary", "description": "safe", "inputSchema": {}}]

    def normalized(candidate: dict[str, object]) -> dict[str, object]:
        return providers._validated_native_provider_body(
            protocol,
            candidate,
            model_alias="assistant-selected",
            upstream_model_id="reviewed/model",
            app_tools=app_tools,
        )

    request = normalized(
        {**body, "max_tokens": budget} if protocol == "anthropic-messages" else body
    )
    field_value: object = request
    for key in token_path:
        assert isinstance(field_value, dict)
        field_value = field_value[key]
    assert field_value == budget

    invalid_counts = (True, False, 0, budget + 1, str(budget))
    for invalid_count in invalid_counts:
        changed = dict(body)
        if token_path == ("generationConfig", "maxOutputTokens"):
            changed["generationConfig"] = {"maxOutputTokens": invalid_count}
        else:
            changed[token_path[0]] = invalid_count
        with pytest.raises(ProviderUnavailable, match="provider_request_invalid"):
            normalized(changed)


def test_google_native_protocol_cannot_use_legacy_chat_completions(
    tmp_path: Path,
) -> None:
    """Keep the legacy protocol endpoint closed to Gemini's distinct native API."""

    model_id = "google/gemini-test-model"
    model = SimpleNamespace(model_id=model_id, provider_id="google", available=True)

    class GoogleCatalog:
        def get_model(self, candidate_id: str) -> SimpleNamespace | None:
            return model if candidate_id == model_id else None

    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="t" * 64),
        catalog=GoogleCatalog(),
        vault_dir=tmp_path / "assistant-vault",
    )
    with pytest.raises(ProviderUnavailable, match="provider_adapter_unsupported"):
        manager.proxy_chat_completion(
            "google",
            model_id,
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "synthetic"}],
                "stream": True,
            },
            authorization_check=lambda: True,
        )


class _NativeOAuthRuntime:
    """Synthetic native OAuth runtime that keeps all token bytes in the test process."""

    def __init__(
        self,
        *,
        status: str = "pending",
        launch_override: dict[str, object] | None = None,
    ) -> None:
        self.status = status
        self.attempts: dict[str, str] = {}
        self.calls: list[str] = []
        self.capabilities: dict[str, str] = {}
        self.launch_override = launch_override

    async def list_native_integrations(self) -> list[dict[str, object]]:
        return [
            {
                "integration_id": "openai",
                "methods": [
                    {"method_id": "chatgpt-browser", "kind": "oauth"},
                    {"method_id": "chatgpt-headless", "kind": "oauth"},
                    {"method_id": "unreviewed", "kind": "oauth"},
                ],
            },
            {
                "integration_id": "opencode",
                "methods": [{"method_id": "device", "kind": "oauth"}],
            },
        ]

    async def begin_native_oauth(
        self,
        integration_id: str,
        method_id: str,
        *,
        attempt_id: str,
        owner_id: int,
        session_id: str,
        capability: str,
    ) -> dict[str, object]:
        assert owner_id == 17
        assert session_id == "a" * 32
        assert re.fullmatch(r"[0-9a-f]{32}", capability)
        self.calls.append("begin")
        self.attempts[attempt_id] = self.status
        self.capabilities[attempt_id] = capability
        launch: dict[str, object]
        if integration_id == "openai" and method_id == "chatgpt-headless":
            launch = {
                "native_attempt_id": "con_synthetic-native-id",
                "url": "https://auth.openai.com/codex/device",
                "instructions": "Enter code: SYNTHETIC-CODE",
                "mode": "auto",
                "expires_at": time.time() + 300,
            }
        elif integration_id == "openai" and method_id == "chatgpt-browser":
            launch = {
                "native_attempt_id": "con_synthetic-native-id",
                "url": "https://auth.openai.com/oauth/authorize?"
                + urlencode(
                    {
                        "response_type": "code",
                        "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
                        "redirect_uri": "http://localhost:1455/auth/callback",
                        "scope": "openid profile email offline_access",
                        "code_challenge": "C" * 43,
                        "code_challenge_method": "S256",
                        "id_token_add_organizations": "true",
                        "codex_cli_simplified_flow": "true",
                        "state": "S" * 43,
                        "originator": "opencode",
                    }
                ),
                "instructions": (
                    "Complete authorization in your browser. This window will close automatically."
                ),
                "mode": "auto",
                "expires_at": time.time() + 300,
            }
        elif integration_id == "opencode" and method_id == "device":
            launch = {
                "native_attempt_id": "con_synthetic-native-id",
                "url": "https://opencode.ai/console/device?"
                + urlencode(
                    {
                        "user_code": "SYNTHETIC-CODE",
                        "client_id": "opencode-cli",
                    }
                ),
                "instructions": "Enter code: SYNTHETIC-CODE",
                "mode": "auto",
                "expires_at": time.time() + 300,
            }
        else:
            raise AssertionError("unexpected synthetic OAuth method")
        return self.launch_override if self.launch_override is not None else launch

    async def native_oauth_status(
        self,
        integration_id: str,
        attempt_id: str,
        *,
        owner_id: int,
        session_id: str,
    ) -> str:
        assert self.attempts.get(attempt_id) is not None
        assert owner_id == 17
        assert session_id == "a" * 32
        self.calls.append("status")
        return self.attempts[attempt_id]

    async def complete_native_oauth(self, *_args: object, **_kwargs: object) -> None:
        self.calls.append("submit_code")

    async def submit_native_oauth_callback(self, *_args: object, **_kwargs: object) -> None:
        self.calls.append("callback")

    async def take_native_oauth_handoff(
        self, *_args: object, **_kwargs: object
    ) -> dict[str, object]:
        self.calls.append("handoff")
        return {
            "type": "oauth",
            "methodID": "chatgpt-headless",
            "access": "synthetic-oauth-access-token",
            "refresh": "synthetic-oauth-refresh-token",
            "expires": int(time.time() * 1000) + 3_600_000,
            "metadata": {"accountID": "synthetic-account"},
        }

    async def cancel_native_oauth(self, *_args: object, **_kwargs: object) -> None:
        self.calls.append("cancel")


def _oauth_manager(tmp_path: Path, runtime: _NativeOAuthRuntime) -> AssistantProviderManager:
    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="v" * 64),
        vault_dir=tmp_path / "assistant-vault",
        runtime=runtime,
    )
    registrations: dict[str, dict[str, object]] = {}
    revoked: list[str] = []

    def register(
        attempt_id: str,
        integration_id: str,
        method_id: str,
        owner_id: int,
        session_id: str,
        expires_at: float,
        *,
        session_token_hash: str,
    ) -> str:
        assert re.fullmatch(r"[0-9a-f]{64}", session_token_hash)
        capability = secrets.token_hex(16)
        registrations[attempt_id] = {
            "integration_id": integration_id,
            "method_id": method_id,
            "owner_id": owner_id,
            "session_id": session_id,
            "expires_at": expires_at,
            "session_token_hash": session_token_hash,
            "capability": capability,
        }
        return capability

    def revoke(attempt_id: str) -> None:
        revoked.append(attempt_id)

    manager.attach_oauth_transport(register, revoke)
    manager._test_oauth_transport = {"registrations": registrations, "revoked": revoked}
    return manager


def _seed_opencode_console_credential(manager: AssistantProviderManager, owner_id: int) -> None:
    """Seed only encrypted, synthetic owner data for Console inventory tests."""

    manager._write_oauth_credential(
        "opencode",
        "device",
        owner_id,
        {
            "type": "oauth",
            "methodID": "device",
            "access": f"synthetic-access-{owner_id}",
            "refresh": f"synthetic-refresh-{owner_id}",
            "expires": int(time.time() * 1000) + 3_600_000,
            "metadata": {"server": "https://opencode.ai/console", "accountID": f"acct-{owner_id}"},
        },
    )


@pytest.mark.parametrize("operation", ("opencode_inventory", "opencode_refresh", "chatgpt_refresh"))
@pytest.mark.parametrize("phase", ("dns_tls", "response"))
def test_oauth_https_operations_pass_live_authorization_into_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    phase: str,
) -> None:
    """Revalidate the same owner lease inside DNS/TLS and after provider responses."""

    owner_id = 71
    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="q" * 64),
        vault_dir=tmp_path / "assistant-vault",
    )
    if operation.startswith("opencode"):
        _seed_opencode_console_credential(manager, owner_id)
        credential = manager._owned_opencode_credential(owner_id)
        assert credential is not None
        if operation == "opencode_refresh":
            credential["expires"] = int(time.time() * 1000) - 1_000
            manager._write_oauth_credential("opencode", "device", owner_id, credential)
            expected_url = providers._OPENCODE_REFRESH_URL
        else:
            expected_url = providers._OPENCODE_CONFIG_URL
        credential_before = manager._owned_opencode_credential(owner_id)
    else:
        method_id = "chatgpt-headless"
        credential = {
            "type": "oauth",
            "methodID": method_id,
            "access": "synthetic-chatgpt-access",
            "refresh": "synthetic-chatgpt-refresh",
            "expires": int(time.time() * 1000) - 1_000,
            "metadata": {"accountID": "synthetic-chatgpt-account"},
        }
        manager._write_oauth_credential("openai", method_id, owner_id, credential)
        credential_before = manager._read_oauth_credential("openai", method_id, owner_id)
        expected_url = providers._CHATGPT_REFRESH_URL

    authorization = {"allowed": True}
    request_started = asyncio.Event()
    response_held = asyncio.Event()
    release_transport = asyncio.Event()
    request_bytes_written = {"value": False}
    transport_callback_seen = {"value": False}

    async def authorization_check() -> bool:
        return authorization["allowed"] is True

    async def fake_request(url: str, **kwargs: object) -> SimpleNamespace:
        assert url == expected_url
        transport_authorization = kwargs.get("authorization_check")
        if callable(transport_authorization):
            transport_callback_seen["value"] = True

        async def transport_check() -> None:
            assert callable(transport_authorization)
            if await transport_authorization() is not True:
                raise providers.PublicHTTPError("provider_authorization_required")

        request_started.set()
        if phase == "dns_tls":
            await release_transport.wait()
            if callable(transport_authorization):
                await transport_check()
            request_bytes_written["value"] = True
        else:
            if callable(transport_authorization):
                await transport_check()
            request_bytes_written["value"] = True
            response_held.set()
            await release_transport.wait()
            if callable(transport_authorization):
                await transport_check()
        if operation == "opencode_inventory":
            content = json.dumps(_opencode_console_payload()).encode("utf-8")
        else:
            content = json.dumps(
                {
                    "access_token": "synthetic-rotated-access",
                    "refresh_token": "synthetic-rotated-refresh",
                    "expires_in": 3600,
                }
            ).encode("utf-8")
        return SimpleNamespace(status_code=200, content=content)

    monkeypatch.setattr(providers, "request_public_https", fake_request)

    async def perform_request() -> None:
        if operation == "opencode_inventory":
            await manager.ensure_opencode_model_inventory(
                owner_id=owner_id, authorization_check=authorization_check, force=True
            )
        elif operation == "opencode_refresh":
            assert credential_before is not None
            await manager._refresh_opencode_credential_if_needed(
                owner_id, credential_before, authorization_check
            )
        else:
            assert credential_before is not None
            await manager._refresh_chatgpt_credential_if_needed(
                owner_id,
                "chatgpt-headless",
                credential_before,
                authorization_check,
            )

    async def exercise() -> None:
        pending = asyncio.create_task(perform_request())
        await asyncio.wait_for(request_started.wait(), timeout=1)
        if phase == "response":
            await asyncio.wait_for(response_held.wait(), timeout=1)
        authorization["allowed"] = False
        release_transport.set()
        with pytest.raises(CredentialRejected, match="oauth_authorization_required"):
            await pending

    asyncio.run(exercise())
    assert transport_callback_seen["value"] is True
    assert request_bytes_written["value"] is (phase == "response")
    if operation == "opencode_refresh":
        assert manager._owned_opencode_credential(owner_id) == credential_before
    elif operation == "chatgpt_refresh":
        assert manager._read_oauth_credential("openai", "chatgpt-headless", owner_id) == (
            credential_before
        )


def _opencode_console_payload() -> dict[str, object]:
    return {
        "providers": {
            "reviewed-openai": {
                "canonical": "openai",
                "settings": {"baseURL": "https://api.example.test/v1"},
                "models": {
                    "synthetic-config-model": {
                        "modelID": "vendor/synthetic-model",
                        "name": "Synthetic model",
                        "settings": {"baseURL": "https://model.example.test/v1"},
                        "headers": {"Authorization": "must-not-be-retained"},
                        "body": {"model": "attacker-overlay"},
                        "variants": [{"temperature": 2}],
                    }
                },
            },
            "unreviewed-provider": {
                "package": "npm:attacker/native-provider",
                "models": {"unsafe-model": {"modelID": "unsafe-model"}},
            },
        },
        "websearch": {"providerID": "console-search-must-not-be-used"},
    }


def _opencode_console_payload_for_model(native_model_id: str, endpoint: str) -> dict[str, object]:
    """Build one synthetic compatible Console model with a distinct local alias."""

    return {
        "providers": {
            "reviewed-compatible": {
                "package": "@opencode/ai/providers/openai-compatible",
                "settings": {"baseURL": endpoint},
                "models": {
                    "friendly-local-alias": {
                        "modelID": native_model_id,
                        "name": "Synthetic compatible model",
                    }
                },
            }
        }
    }


def test_opencode_console_review_and_policy_cas_use_separate_revisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep review CAS independent from policy CAS and bind both to a config fingerprint."""

    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="o" * 64),
        vault_dir=tmp_path / "assistant-vault",
    )
    _seed_opencode_console_credential(manager, 17)
    calls: list[tuple[str, dict[str, str]]] = []

    async def fake_request(url: str, *, headers: object, **_kwargs: object):
        calls.append((url, dict(headers)))
        return SimpleNamespace(
            status_code=200,
            content=json.dumps(_opencode_console_payload()).encode("utf-8"),
        )

    monkeypatch.setattr(providers, "request_public_https", fake_request)

    def authorize() -> bool:
        return True

    async def exercise() -> None:
        inventory = await manager.ensure_opencode_model_inventory(
            owner_id=17, authorization_check=authorize, force=True
        )
        assert len(inventory) == 1
        initial = inventory[0]
        assert initial["provider_id"] == "opencode-console"
        assert initial["protocol"] == "openai-responses"
        assert initial["revision"] == 0
        assert initial["review_revision"] == 0
        assert initial["reviewed"] is False
        assert initial["enabled"] is False
        assert initial["usable"] is False
        assert "synthetic-access-17" not in json.dumps(initial)
        assert "must-not-be-retained" not in json.dumps(initial)

        model_id = str(initial["model_id"])
        common_review = {
            "terms_url": "https://terms.example.test/policy",
            "privacy_disclosure": "Administrator-provided privacy statement; unverified.",
            "billing_disclosure": "Administrator-provided billing statement; unverified.",
            "billing_class": "paid",
            "training_policy": "no_training",
            "confidential_data_policy": "allowed",
            "endpoint_policy_reviewed": True,
            "expected_config_fingerprint": str(initial["config_fingerprint"]),
            "authorization_check": authorize,
        }
        reviewed = await manager.review_opencode_model(
            model_id,
            owner_id=17,
            expected_revision=0,
            **common_review,
        )
        assert reviewed["review_revision"] == 1
        assert reviewed["revision"] == 0
        assert reviewed["available"] is True
        assert reviewed["usable"] is False

        enabled = manager.update_model_policy(
            model_id,
            owner_id=17,
            enabled=True,
            acknowledged_privacy_policy_version=str(reviewed["privacy_policy_version"]),
            acknowledged_billing_policy_version=str(reviewed["billing_policy_version"]),
            expected_revision=0,
        )
        assert enabled["revision"] == 1
        assert enabled["review_revision"] == 1
        assert enabled["enabled"] is True
        assert enabled["usable"] is False  # Console token is not an upstream model API key.

        changed = await manager.review_opencode_model(
            model_id,
            owner_id=17,
            expected_revision=1,
            **{
                **common_review,
                "privacy_disclosure": "Revised administrator statement; still unverified.",
            },
        )
        assert changed["review_revision"] == 2
        assert changed["revision"] == 1
        assert changed["usable"] is False

        with pytest.raises(ProviderUnavailable, match="model_policy_conflict"):
            await manager.review_opencode_model(
                model_id,
                owner_id=17,
                expected_revision=1,
                **common_review,
            )

        disabled = manager.update_model_policy(
            model_id,
            owner_id=17,
            enabled=False,
            acknowledged_privacy_policy_version=None,
            acknowledged_billing_policy_version=None,
            expected_revision=1,
        )
        assert disabled["revision"] == 2
        assert disabled["review_revision"] == 2
        assert disabled["enabled"] is False
        assert (
            await manager.clear_opencode_model_review(
                model_id,
                owner_id=17,
                expected_revision=2,
                authorization_check=authorize,
            )
            is True
        )
        cleared = manager._opencode_public_inventory(17)[0]
        assert cleared["reviewed"] is False
        assert cleared["review_revision"] == 3
        assert cleared["revision"] == 0
        assert cleared["available"] is False
        restored = await manager.review_opencode_model(
            model_id,
            owner_id=17,
            expected_revision=3,
            **common_review,
        )
        assert restored["review_revision"] == 4
        assert restored["revision"] == 0
        with pytest.raises(ProviderUnavailable, match="model_policy_conflict"):
            await manager.review_opencode_model(
                model_id,
                owner_id=17,
                expected_revision=2,
                **common_review,
            )

    asyncio.run(exercise())
    assert len(calls) == 7
    assert all(url == "https://opencode.ai/console/api/v2/config" for url, _ in calls)
    assert all(set(headers) == {"authorization"} for _, headers in calls)
    assert all(headers.get("authorization", "").startswith("Bearer ") for _, headers in calls)


def test_opencode_console_model_ids_and_inventories_are_owner_scoped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never expose or resolve one owner's Console models through another owner scope."""

    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="p" * 64),
        vault_dir=tmp_path / "assistant-vault",
    )
    _seed_opencode_console_credential(manager, 21)
    _seed_opencode_console_credential(manager, 22)

    async def fake_request(_url: str, **_kwargs: object):
        return SimpleNamespace(
            status_code=200,
            content=json.dumps(_opencode_console_payload()).encode("utf-8"),
        )

    monkeypatch.setattr(providers, "request_public_https", fake_request)

    async def exercise() -> None:
        owner_a = await manager.ensure_opencode_model_inventory(
            owner_id=21, authorization_check=lambda: True, force=True
        )
        owner_b = await manager.ensure_opencode_model_inventory(
            owner_id=22, authorization_check=lambda: True, force=True
        )
        model_a = str(owner_a[0]["model_id"])
        model_b = str(owner_b[0]["model_id"])
        assert model_a != model_b
        assert manager.get_opencode_model(model_a, owner_id=21).model_id == model_a
        with pytest.raises(ProviderUnavailable, match="model_unavailable"):
            manager.get_opencode_model(model_a, owner_id=22)
        assert manager.opencode_inventory_summary(owner_id=21) == {
            "model_count": 1,
            "unsupported_model_count": 1,
        }

    asyncio.run(exercise())


@pytest.mark.parametrize(("native_model_id", "reason"), _zen_exclusion_fixtures())
@pytest.mark.parametrize(
    "endpoint",
    [
        "HTTPS://OPENCODE.AI:443/%7Aen/v1/",
        "https://opencode.ai/unused/%2e%2e/zen/v1",
        "https://opencode.ai/zen/%76%31/",
    ],
)
def test_opencode_console_inventory_excludes_catalog_native_ids_after_alias_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    native_model_id: str,
    reason: str,
    endpoint: str,
) -> None:
    """Apply the maintained Zen exclusions to upstream IDs, not opaque local aliases."""

    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="x" * 64),
        vault_dir=tmp_path / "assistant-vault",
    )
    _seed_opencode_console_credential(manager, 41)

    async def fake_request(_url: str, **_kwargs: object):
        return SimpleNamespace(
            status_code=200,
            content=json.dumps(
                _opencode_console_payload_for_model(native_model_id, endpoint)
            ).encode("utf-8"),
        )

    monkeypatch.setattr(providers, "request_public_https", fake_request)

    inventory = asyncio.run(
        manager.ensure_opencode_model_inventory(
            owner_id=41, authorization_check=lambda: True, force=True
        )
    )

    assert inventory == ()
    assert manager.opencode_inventory_summary(owner_id=41) == {
        "model_count": 0,
        "unsupported_model_count": 1,
    }
    assert (
        manager._known_model_exclusion_reason("opencode-console", endpoint, native_model_id)
        == reason
    )


def test_opencode_console_allows_review_of_nonexcluded_model_on_zen_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep explicit admin review available for unrelated IDs on the exact Zen route."""

    safe_native_id = "synthetic-compatible-model"
    assert safe_native_id not in dict(_zen_exclusion_fixtures())
    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="y" * 64),
        vault_dir=tmp_path / "assistant-vault",
    )
    _seed_opencode_console_credential(manager, 42)

    async def fake_request(_url: str, **_kwargs: object):
        return SimpleNamespace(
            status_code=200,
            content=json.dumps(
                _opencode_console_payload_for_model(safe_native_id, "https://opencode.ai/zen/v1")
            ).encode("utf-8"),
        )

    monkeypatch.setattr(providers, "request_public_https", fake_request)

    async def exercise() -> dict[str, object]:
        rows = await manager.ensure_opencode_model_inventory(
            owner_id=42, authorization_check=lambda: True, force=True
        )
        assert len(rows) == 1
        initial = rows[0]
        assert initial["available"] is False
        return await manager.review_opencode_model(
            str(initial["model_id"]),
            owner_id=42,
            terms_url="https://terms.example.test/policy",
            privacy_disclosure="Synthetic administrator policy statement.",
            billing_disclosure="Synthetic billing statement.",
            billing_class="free",
            training_policy="no_training",
            confidential_data_policy="allowed",
            endpoint_policy_reviewed=True,
            expected_revision=0,
            expected_config_fingerprint=str(initial["config_fingerprint"]),
            authorization_check=lambda: True,
        )

    reviewed = asyncio.run(exercise())
    assert reviewed["available"] is True
    assert reviewed["native_model_id"] == safe_native_id


@pytest.mark.parametrize(
    "native_model_id", [model_id for model_id, _reason in _zen_exclusion_fixtures()[:1]]
)
def test_opencode_console_same_model_id_on_similarly_named_host_is_not_globally_excluded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    native_model_id: str,
) -> None:
    """Match the exact Zen endpoint, not a host that merely contains its name."""

    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="z" * 64),
        vault_dir=tmp_path / "assistant-vault",
    )
    _seed_opencode_console_credential(manager, 43)

    async def fake_request(_url: str, **_kwargs: object):
        return SimpleNamespace(
            status_code=200,
            content=json.dumps(
                _opencode_console_payload_for_model(
                    native_model_id, "https://opencode.ai.example.test/zen/v1"
                )
            ).encode("utf-8"),
        )

    monkeypatch.setattr(providers, "request_public_https", fake_request)

    inventory = asyncio.run(
        manager.ensure_opencode_model_inventory(
            owner_id=43, authorization_check=lambda: True, force=True
        )
    )

    assert len(inventory) == 1
    assert (
        manager._known_model_exclusion_reason(
            "opencode-console", "https://opencode.ai.example.test/zen/v1", native_model_id
        )
        is None
    )
    assert manager.get_opencode_model(str(inventory[0]["model_id"]), owner_id=43).available is False


@pytest.mark.parametrize(
    "native_model_id", [model_id for model_id, _reason in _zen_exclusion_fixtures()]
)
def test_opencode_console_turn_rejects_stale_approved_record_before_upstream_key_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    native_model_id: str,
) -> None:
    """Recheck the exact upstream ID before accepting stale or forged Console approval."""

    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="v" * 64),
        vault_dir=tmp_path / "assistant-vault",
    )
    owner_id = 44
    model_id = "opencode-console/" + "a" * 64
    manager._opencode_loaded_at[owner_id] = manager._clock()
    manager._opencode_models[owner_id] = (
        SimpleNamespace(
            owner_id=owner_id,
            model=SimpleNamespace(model_id=model_id, available=True),
            endpoint="HTTPS://OPENCODE.AI:443/%7Aen/v1/",
            native_model_id=native_model_id,
        ),
    )
    credential_reads: list[str] = []
    provider_calls: list[str] = []

    def read_credential(provider_id: str) -> str | None:
        credential_reads.append(provider_id)
        return "synthetic-custom-key"

    async def fake_stream(url: str, **_kwargs: object):
        provider_calls.append(url)
        yield b""

    monkeypatch.setattr(manager, "_read_credential", read_credential)
    monkeypatch.setattr(providers, "stream_public_https", fake_stream)

    with pytest.raises(ProviderUnavailable, match="model_unavailable"):
        manager.get_opencode_model(model_id, owner_id=owner_id)
    with pytest.raises(ProviderUnavailable, match="model_unavailable"):
        manager.model_policy_state(model_id, owner_id=owner_id)
    with pytest.raises(ProviderUnavailable, match="model_unavailable"):
        manager.proxy_chat_completion(
            "opencode-console",
            model_id,
            {},
            owner_id=owner_id,
            app_session_id="synthetic-session",
            authorization_check=lambda: True,
            app_tools=[{}],
        )

    assert credential_reads == []
    assert provider_calls == []


def test_opencode_console_turn_horizon_refreshes_near_expiry_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refresh an owner inventory that cannot cover the requested turn horizon."""

    now = [1_000.0]
    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="h" * 64),
        vault_dir=tmp_path / "assistant-vault",
        clock=lambda: now[0],
    )
    _seed_opencode_console_credential(manager, 31)
    requests: list[str] = []

    async def fake_request(url: str, **_kwargs: object):
        requests.append(url)
        return SimpleNamespace(
            status_code=200,
            content=json.dumps(_opencode_console_payload()).encode("utf-8"),
        )

    monkeypatch.setattr(providers, "request_public_https", fake_request)

    async def exercise() -> None:
        first = await manager.ensure_opencode_model_inventory(
            owner_id=31, authorization_check=lambda: True
        )
        initial = first[0]
        reviewed = await manager.review_opencode_model(
            str(initial["model_id"]),
            owner_id=31,
            expected_revision=0,
            terms_url="https://terms.example.test/policy",
            privacy_disclosure="Administrator-provided privacy statement; unverified.",
            billing_disclosure="Administrator-provided billing statement; unverified.",
            billing_class="free",
            training_policy="no_training",
            confidential_data_policy="allowed",
            endpoint_policy_reviewed=True,
            expected_config_fingerprint=str(initial["config_fingerprint"]),
            authorization_check=lambda: True,
        )
        assert reviewed["reviewed"] is True
        requests_before_turn_refresh = len(requests)

        # The cached row has 100 seconds left, which is too short for a 120-second turn.
        now[0] += 200.0
        refreshed = await manager.ensure_opencode_model_inventory(
            owner_id=31,
            authorization_check=lambda: True,
            minimum_validity_seconds=120,
        )
        current = refreshed[0]
        assert len(requests) == requests_before_turn_refresh + 1
        assert current["model_id"] == initial["model_id"]
        assert current["config_fingerprint"] == initial["config_fingerprint"]
        assert current["reviewed"] is True
        assert current["review_revision"] == reviewed["review_revision"]

        with pytest.raises(ProviderUnavailable, match="model_inventory_invalid"):
            await manager.ensure_opencode_model_inventory(
                owner_id=31,
                authorization_check=lambda: True,
                minimum_validity_seconds=120.01,
            )

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("protocol", "expected_url", "query", "native_body", "response", "upstream", "auth_header"),
    [
        (
            "openai-responses",
            "https://model.example.test/v1/responses",
            (),
            {"model": "assistant-selected", "input": "synthetic", "stream": True, "store": False},
            b'data: {"type":"response.output_text.delta","delta":"ok"}\n\n',
            "openai",
            "authorization",
        ),
        (
            "anthropic-messages",
            "https://model.example.test/v1/messages",
            (("beta", "true"),),
            {
                "model": "assistant-selected",
                "max_tokens": 128,
                "messages": [{"role": "user", "content": "synthetic"}],
                "stream": True,
            },
            b'event: message_stop\ndata: {"type":"message_stop"}\n\n',
            "anthropic",
            "x-api-key",
        ),
        (
            "google-generative-language",
            "https://model.example.test/v1/models/vendor%2Fsynthetic-model:streamGenerateContent?alt=sse",
            (("alt", "sse"),),
            {"contents": [{"role": "user", "parts": [{"text": "synthetic"}]}]},
            b'data: {"candidates":[]}\n\n',
            "google",
            "x-goog-api-key",
        ),
        (
            "openai-compatible-chat",
            "https://model.example.test/v1/chat/completions",
            (),
            {
                "model": "assistant-selected",
                "messages": [{"role": "user", "content": "synthetic"}],
                "stream": True,
                "store": False,
            },
            b'data: {"choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
            b"data: [DONE]\n\n",
            "custom",
            "authorization",
        ),
    ],
)
def test_opencode_console_native_adapters_use_fixed_vendor_wire_and_app_vault_keys(
    protocol: str,
    expected_url: str,
    query: tuple[tuple[str, str], ...],
    native_body: dict[str, object],
    response: bytes,
    upstream: str,
    auth_header: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Route Console models through their closed package protocol, never its OAuth token."""

    package = {
        "openai-responses": "@opencode/ai/providers/openai",
        "anthropic-messages": "@opencode/ai/providers/anthropic",
        "google-generative-language": "@opencode/ai/providers/google",
        "openai-compatible-chat": "@opencode/ai/providers/openai-compatible",
    }[protocol]
    canonical = {
        "openai-responses": "openai",
        "anthropic-messages": "anthropic",
        "google-generative-language": "google",
    }.get(protocol)
    endpoint = "https://model.example.test/v1"
    console_payload: dict[str, object] = {
        "providers": {
            "synthetic-provider": {
                **({"canonical": canonical} if canonical else {"package": package}),
                "models": {
                    "synthetic-config-model": {
                        "modelID": "vendor/synthetic-model",
                        "name": "Synthetic model",
                        "settings": {"baseURL": endpoint},
                    }
                },
            }
        }
    }
    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="w" * 64),
        vault_dir=tmp_path / "assistant-vault",
    )
    _seed_opencode_console_credential(manager, 51)
    config_requests: list[dict[str, str]] = []

    async def fake_request(url: str, *, headers: object, **_kwargs: object):
        assert url == "https://opencode.ai/console/api/v2/config"
        config_requests.append(dict(headers))
        return SimpleNamespace(
            status_code=200,
            content=json.dumps(console_payload).encode("utf-8"),
        )

    calls: list[dict[str, object]] = []

    async def fake_stream(
        url: str,
        *,
        headers: object,
        body: bytes,
        **_kwargs: object,
    ):
        calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "body": json.loads(body),
            }
        )
        yield response

    monkeypatch.setattr(providers, "request_public_https", fake_request)
    monkeypatch.setattr(providers, "stream_public_https", fake_stream)
    if upstream == "custom":
        manager.configure_custom_endpoint(
            base_url=endpoint,
            terms_url="https://terms.example.test/policy",
            privacy_disclosure="Administrator-provided privacy statement; unverified.",
            billing_disclosure="Administrator-provided billing statement; unverified.",
            billing_class="paid",
            endpoint_policy_reviewed=True,
            credential="synthetic-upstream-key",
        )
    else:
        manager.set_credential(upstream, "synthetic-upstream-key")

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
        initial = await manager.ensure_opencode_model_inventory(
            owner_id=51, authorization_check=lambda: True
        )
        row = initial[0]
        reviewed = await manager.review_opencode_model(
            str(row["model_id"]),
            owner_id=51,
            expected_revision=0,
            terms_url="https://terms.example.test/policy",
            privacy_disclosure="Administrator-provided privacy statement; unverified.",
            billing_disclosure="Administrator-provided billing statement; unverified.",
            billing_class="paid",
            training_policy="no_training",
            confidential_data_policy="allowed",
            endpoint_policy_reviewed=True,
            expected_config_fingerprint=str(row["config_fingerprint"]),
            authorization_check=lambda: True,
        )
        manager.update_model_policy(
            str(row["model_id"]),
            owner_id=51,
            enabled=True,
            acknowledged_privacy_policy_version=str(reviewed["privacy_policy_version"]),
            acknowledged_billing_policy_version=str(reviewed["billing_policy_version"]),
            expected_revision=0,
        )
        model_id = str(row["model_id"])
        if protocol == "openai-compatible-chat":
            stream = manager.proxy_chat_completion(
                "opencode-console",
                model_id,
                native_body,
                owner_id=51,
                app_session_id="synthetic-session-51",
                authorization_check=lambda: True,
                app_tools=app_tools,
            )
        else:
            stream = manager.proxy_native_stream(
                "opencode-console",
                model_id,
                native_body,
                path_model_id=(
                    "assistant-selected" if protocol == "google-generative-language" else None
                ),
                query=query,
                app_tools=app_tools,
                owner_id=51,
                app_session_id="synthetic-session-51",
                authorization_check=lambda: True,
            )
        return [chunk async for chunk in stream]

    output = asyncio.run(exercise())

    assert output
    assert b"".join(output) == response
    assert len(calls) == 1
    assert calls[0]["url"] == expected_url
    headers = calls[0]["headers"]
    assert isinstance(headers, dict)
    normalized_headers = {str(key).lower(): value for key, value in headers.items()}
    expected_auth = (
        "Bearer synthetic-upstream-key"
        if auth_header == "authorization"
        else "synthetic-upstream-key"
    )
    assert normalized_headers[auth_header] == expected_auth
    assert all("synthetic-access-51" not in str(value) for value in headers.values())
    assert "synthetic-access-51" not in json.dumps(calls[0]["body"])
    forwarded = calls[0]["body"]
    assert isinstance(forwarded, dict)
    expected_forwarded = dict(native_body)
    budget = native_output_token_budget()
    if protocol == "openai-responses":
        expected_forwarded["max_output_tokens"] = budget
    elif protocol == "google-generative-language":
        expected_forwarded["generationConfig"] = {"maxOutputTokens": budget}
    elif protocol == "openai-compatible-chat":
        expected_forwarded["max_tokens"] = budget
    if protocol != "google-generative-language":
        expected_forwarded["model"] = "vendor/synthetic-model"
    assert forwarded == expected_forwarded
    if protocol == "anthropic-messages":
        assert normalized_headers["anthropic-version"] == "2023-06-01"
    assert config_requests
    assert all(set(request) == {"authorization"} for request in config_requests)
    assert all(request["authorization"].startswith("Bearer ") for request in config_requests)


def test_native_oauth_methods_are_flat_fixed_and_discovery_intersected(tmp_path: Path) -> None:
    runtime = _NativeOAuthRuntime()
    manager = _oauth_manager(tmp_path, runtime)

    methods = asyncio.run(manager.list_native_oauth_methods())

    assert [(item["integration_id"], item["method_id"], item["mode"]) for item in methods] == [
        ("openai", "chatgpt-browser", "browser"),
        ("openai", "chatgpt-headless", "device"),
        ("opencode", "device", "device"),
    ]
    assert all(item["connection_supported"] is True for item in methods)
    assert [item["model_access_supported"] for item in methods] == [True, True, False]
    assert [item["availability_reason"] for item in methods] == [
        None,
        None,
        "oauth_proxy_pending",
    ]
    assert all(
        set(item)
        == {
            "integration_id",
            "method_id",
            "label",
            "mode",
            "connection_status",
            "connection_supported",
            "model_access_supported",
            "availability_reason",
        }
        for item in methods
    )


@pytest.mark.parametrize(
    ("integration_id", "method_id"),
    [
        ("openai", "chatgpt-browser"),
        ("openai", "chatgpt-headless"),
        ("opencode", "device"),
    ],
)
def test_native_oauth_launches_match_exact_pinned_method_contract(
    tmp_path: Path, integration_id: str, method_id: str
) -> None:
    manager = _oauth_manager(tmp_path, _NativeOAuthRuntime())

    attempt = asyncio.run(
        manager.begin_native_oauth(
            integration_id,
            method_id,
            owner_id=17,
            session_id="a" * 32,
            session_token_hash="b" * 64,
        )
    )

    assert attempt["status"] == "pending"
    assert attempt["integration_id"] == integration_id
    assert attempt["method_id"] == method_id
    if method_id == "chatgpt-browser":
        assert attempt["authorization_url"].startswith("https://auth.openai.com/oauth/authorize?")
        assert "state" not in attempt["instructions"]
        assert manager._oauth_attempts[str(attempt["attempt_id"])].callback_state == "S" * 43


@pytest.mark.parametrize(
    ("integration", "method", "url"),
    [
        (
            "openai",
            "chatgpt-headless",
            "https://auth.openai.com.evil.test/codex/device",
        ),
        ("openai", "chatgpt-headless", "https://auth.openai.com:444/codex/device"),
        (
            "openai",
            "chatgpt-headless",
            "https://auth.openai.com/codex/device?next=https%3A%2F%2Fevil.test",
        ),
        (
            "opencode",
            "device",
            "https://opencode.ai/console/device?user_code=A&user_code=B&client_id=opencode-cli",
        ),
        (
            "opencode",
            "device",
            "https://opencode.ai/console/device?user_code=A&client_id=other",
        ),
    ],
)
def test_native_oauth_rejects_unreviewed_launch_url_and_revokes_transport(
    tmp_path: Path, integration: str, method: str, url: str
) -> None:
    runtime = _NativeOAuthRuntime()
    # Produce a valid launch for the selected method, then alter only the untrusted URL.
    if method == "chatgpt-headless":
        instructions = "Enter code: SYNTHETIC-CODE"
    else:
        instructions = "Enter code: SYNTHETIC-CODE"
    runtime.launch_override = {
        "native_attempt_id": "con_synthetic-native-id",
        "url": url,
        "instructions": instructions,
        "mode": "auto",
        "expires_at": time.time() + 300,
    }
    manager = _oauth_manager(tmp_path, runtime)

    with pytest.raises(ProviderUnavailable) as rejected:
        asyncio.run(
            manager.begin_native_oauth(
                integration,
                method,
                owner_id=17,
                session_id="a" * 32,
                session_token_hash="b" * 64,
            )
        )

    assert rejected.value.code == "oauth_unavailable"
    assert manager._oauth_attempts == {}
    assert len(manager._test_oauth_transport["revoked"]) == 1
    assert runtime.calls[-1] == "cancel"


def test_native_oauth_browser_callback_is_attempt_state_bound_and_never_fetched(
    tmp_path: Path,
) -> None:
    runtime = _NativeOAuthRuntime()
    manager = _oauth_manager(tmp_path, runtime)
    attempt = asyncio.run(
        manager.begin_native_oauth(
            "openai",
            "chatgpt-browser",
            owner_id=17,
            session_id="a" * 32,
            session_token_hash="b" * 64,
        )
    )
    attempt_id = str(attempt["attempt_id"])
    base = "http://localhost:1455/auth/callback?"

    with pytest.raises(CredentialRejected) as wrong_state:
        asyncio.run(
            manager.submit_native_oauth_callback(
                attempt_id,
                owner_id=17,
                session_id="a" * 32,
                callback_url=base + urlencode({"code": "synthetic", "state": "wrong"}),
            )
        )
    assert wrong_state.value.code == "oauth_callback_invalid"
    assert "callback" not in runtime.calls

    callback_url = base + urlencode({"code": "synthetic", "state": "S" * 43})
    asyncio.run(
        manager.submit_native_oauth_callback(
            attempt_id,
            owner_id=17,
            session_id="a" * 32,
            callback_url=callback_url,
        )
    )
    assert runtime.calls[-2:] == ["callback", "status"]

    for hostile in (
        "http://localhost:1455.evil.test/auth/callback?code=x&state=" + "S" * 43,
        "http://127.0.0.1:1455/auth/callback?code=x&state=" + "S" * 43,
        "http://localhost:1456/auth/callback?code=x&state=" + "S" * 43,
        base + "code=x&code=y&state=" + "S" * 43,
        base + urlencode({"code": "x", "state": "S" * 43, "next": "https://evil.test"}),
    ):
        with pytest.raises(CredentialRejected) as invalid:
            manager._validate_native_oauth_callback(manager._oauth_attempts[attempt_id], hostile)
        assert invalid.value.code == "oauth_callback_invalid"


def test_native_oauth_attempt_is_bound_and_hides_native_attempt_id(tmp_path: Path) -> None:
    runtime = _NativeOAuthRuntime()
    manager = _oauth_manager(tmp_path, runtime)

    attempt = asyncio.run(
        manager.begin_native_oauth(
            "openai",
            "chatgpt-headless",
            owner_id=17,
            session_id="a" * 32,
            session_token_hash="b" * 64,
        )
    )

    assert re.fullmatch(r"[0-9a-f]{32}", attempt["attempt_id"])
    assert attempt["status"] == "pending"
    assert attempt["mode"] == "device"
    assert "native_attempt_id" not in attempt
    assert all("native" not in key for key in attempt)
    registration = manager._test_oauth_transport["registrations"][str(attempt["attempt_id"])]
    assert registration["session_token_hash"] == "b" * 64
    assert runtime.capabilities[str(attempt["attempt_id"])] == registration["capability"]
    assert not hasattr(manager._oauth_attempts[str(attempt["attempt_id"])], "session_token_hash")
    assert "b" * 64 not in repr(manager._oauth_attempts[str(attempt["attempt_id"])])
    assert registration["capability"] not in repr(attempt)
    assert (
        asyncio.run(
            manager.native_oauth_status(
                str(attempt["attempt_id"]), owner_id=17, session_id="a" * 32
            )
        )["status"]
        == "pending"
    )
    with pytest.raises(CredentialRejected) as wrong_session:
        asyncio.run(
            manager.native_oauth_status(
                str(attempt["attempt_id"]), owner_id=17, session_id="b" * 32
            )
        )
    assert wrong_session.value.code == "oauth_attempt_not_found"


def test_native_oauth_handoff_is_encrypted_after_live_authorization(tmp_path: Path) -> None:
    runtime = _NativeOAuthRuntime(status="handoff_ready")
    manager = _oauth_manager(tmp_path, runtime)

    attempt = asyncio.run(
        manager.begin_native_oauth(
            "openai",
            "chatgpt-headless",
            owner_id=17,
            session_id="a" * 32,
            session_token_hash="b" * 64,
        )
    )
    authorization_checks: list[str] = []

    async def authorization_check() -> bool:
        authorization_checks.append("revalidated")
        runtime.calls.append("authorization_check")
        return True

    completed = asyncio.run(
        manager.complete_native_oauth(
            str(attempt["attempt_id"]),
            owner_id=17,
            session_id="a" * 32,
            authorization_check=authorization_check,
        )
    )

    assert completed["status"] == "connected"
    assert completed["authorization_url"] is None
    assert completed["instructions"] is None
    assert authorization_checks == ["revalidated"]
    assert runtime.calls[-2:] == ["handoff", "authorization_check"]
    registration = manager._test_oauth_transport["registrations"][str(attempt["attempt_id"])]
    assert str(attempt["attempt_id"]) in manager._test_oauth_transport["revoked"]
    assert registration["capability"] not in repr(completed)
    credential_path = manager._oauth_credential_path("openai", 17, "chatgpt-headless")
    ciphertext = credential_path.read_bytes()
    assert b"synthetic-oauth-access-token" not in ciphertext
    assert b"synthetic-oauth-refresh-token" not in ciphertext
    stored = manager._read_oauth_credential("openai", "chatgpt-headless", 17)
    assert stored is not None
    assert stored["type"] == "oauth"
    assert stored["methodID"] == "chatgpt-headless"
    assert stored["access"] == "synthetic-oauth-access-token"
    assert stored["refresh"] == "synthetic-oauth-refresh-token"
    assert type(stored["expires"]) is int
    assert stored["metadata"] == {"accountID": "synthetic-account"}


def test_native_oauth_attempt_and_connection_lists_are_owner_scoped_and_secret_free(
    tmp_path: Path,
) -> None:
    runtime = _NativeOAuthRuntime(status="handoff_ready")
    manager = _oauth_manager(tmp_path, runtime)
    attempt = asyncio.run(
        manager.begin_native_oauth(
            "openai",
            "chatgpt-headless",
            owner_id=17,
            session_id="a" * 32,
            session_token_hash="b" * 64,
        )
    )

    same_session = asyncio.run(manager.list_native_oauth_attempts(owner_id=17, session_id="a" * 32))
    other_session = asyncio.run(
        manager.list_native_oauth_attempts(owner_id=17, session_id="c" * 32)
    )
    assert len(same_session) == 1
    assert same_session[0]["attempt_id"] == attempt["attempt_id"]
    assert other_session == ()
    assert all("capability" not in key and "native_attempt" not in key for key in same_session[0])

    async def allow_commit() -> bool:
        return True

    asyncio.run(
        manager.complete_native_oauth(
            str(attempt["attempt_id"]),
            owner_id=17,
            session_id="a" * 32,
            authorization_check=allow_commit,
        )
    )
    connections = asyncio.run(manager.list_native_oauth_connections(owner_id=17))
    assert connections == (
        {
            "integration_id": "openai",
            "method_id": "chatgpt-headless",
            "status": "connected",
            "model_access_supported": True,
            "availability_reason": None,
        },
    )
    serialized = json.dumps(connections)
    assert "synthetic-oauth-access-token" not in serialized
    assert "synthetic-oauth-refresh-token" not in serialized

    async def deny_revoke() -> bool:
        return False

    with pytest.raises(CredentialRejected) as denied:
        asyncio.run(
            manager.clear_native_oauth_connection(
                "openai",
                "chatgpt-headless",
                owner_id=17,
                authorization_check=deny_revoke,
            )
        )
    assert denied.value.code == "oauth_authorization_required"
    credential_path = manager._oauth_credential_path("openai", 17, "chatgpt-headless")
    assert credential_path.exists()

    assert (
        asyncio.run(
            manager.clear_native_oauth_connection(
                "openai",
                "chatgpt-headless",
                owner_id=17,
                authorization_check=allow_commit,
            )
        )
        is True
    )
    assert not credential_path.exists()
    assert asyncio.run(manager.list_native_oauth_connections(owner_id=17)) == ()


def test_native_oauth_handoff_fails_closed_when_admin_was_revoked(tmp_path: Path) -> None:
    runtime = _NativeOAuthRuntime(status="handoff_ready")
    manager = _oauth_manager(tmp_path, runtime)
    attempt = asyncio.run(
        manager.begin_native_oauth(
            "openai",
            "chatgpt-headless",
            owner_id=17,
            session_id="a" * 32,
            session_token_hash="b" * 64,
        )
    )

    async def authorization_check() -> bool:
        return False

    with pytest.raises(CredentialRejected) as revoked:
        asyncio.run(
            manager.complete_native_oauth(
                str(attempt["attempt_id"]),
                owner_id=17,
                session_id="a" * 32,
                authorization_check=authorization_check,
            )
        )

    assert revoked.value.code == "oauth_authorization_required"
    assert not manager._oauth_credential_path("openai", 17, "chatgpt-headless").exists()
    assert manager._oauth_attempts[str(attempt["attempt_id"])].status == "cancelled"
    assert runtime.calls[-1] == "cancel"
    assert str(attempt["attempt_id"]) in manager._test_oauth_transport["revoked"]


def test_native_oauth_cancel_is_session_bound_and_redacts_launch_details(tmp_path: Path) -> None:
    runtime = _NativeOAuthRuntime()
    manager = _oauth_manager(tmp_path, runtime)
    attempt = asyncio.run(
        manager.begin_native_oauth(
            "openai",
            "chatgpt-headless",
            owner_id=17,
            session_id="a" * 32,
            session_token_hash="b" * 64,
        )
    )

    cancelled = asyncio.run(
        manager.cancel_native_oauth(str(attempt["attempt_id"]), owner_id=17, session_id="a" * 32)
    )

    assert cancelled["status"] == "cancelled"
    assert cancelled["authorization_url"] is None
    assert cancelled["instructions"] is None
    assert runtime.calls[-1] == "cancel"
    assert str(attempt["attempt_id"]) in manager._test_oauth_transport["revoked"]
