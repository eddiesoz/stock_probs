"""Exercise provider policy and authorization boundaries through manager APIs."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest

from stock_probs.assistant import providers
from stock_probs.assistant.model_catalog import AssistantModel, AssistantModelCatalog
from stock_probs.assistant.native_provider_adapters import resolve_native_adapter
from stock_probs.assistant.providers import (
    AssistantProviderManager,
    CredentialRejected,
    ProviderUnavailable,
)
from stock_probs.assistant.tools import AssistantToolGateway

_UPSTREAM_KEY = "synthetic-policy-boundary-upstream-key"
_CONSOLE_ACCESS_PREFIX = "synthetic-policy-boundary-console-access-"
_APP_TOOLS = AssistantToolGateway.list_tools()


def _native_body(
    provider_id: str,
) -> tuple[dict[str, object], str | None, tuple[tuple[str, str], ...]]:
    """Build one minimal request from each catalog-supported native protocol."""

    if provider_id == "openai":
        return (
            {"model": "assistant-selected", "input": "fixture", "stream": True, "store": False},
            None,
            (),
        )
    if provider_id == "anthropic":
        return (
            {
                "model": "assistant-selected",
                "max_tokens": 64,
                "messages": [{"role": "user", "content": "fixture"}],
                "stream": True,
            },
            None,
            (("beta", "true"),),
        )
    if provider_id == "google":
        return (
            {"contents": [{"role": "user", "parts": [{"text": "fixture"}]}]},
            "assistant-selected",
            (("alt", "sse"),),
        )
    raise AssertionError(f"unexpected native catalog provider: {provider_id}")


def _native_tool_declaration(provider_id: str) -> list[dict[str, object]]:
    """Return a bounded but unreviewed native function declaration for one wire format."""

    if provider_id == "openai":
        return [
            {
                "type": "function",
                "name": "unreviewed_function",
                "parameters": {"type": "object", "properties": {}},
            }
        ]
    if provider_id == "anthropic":
        return [
            {
                "name": "unreviewed_function",
                "description": "Not declared by the application.",
                "input_schema": {"type": "object", "properties": {}},
            }
        ]
    if provider_id == "google":
        return [
            {
                "functionDeclarations": [
                    {
                        "name": "unreviewed_function",
                        "description": "Not declared by the application.",
                        "parameters": {"type": "OBJECT", "properties": {}},
                    }
                ]
            }
        ]
    raise AssertionError(f"unexpected native catalog provider: {provider_id}")


def _secret_echo(provider_id: str) -> bytes:
    """Return one complete native SSE frame that echoes the app-side credential."""

    if provider_id == "openai":
        payload = {"type": "response.output_text.delta", "delta": _UPSTREAM_KEY}
        return f"data: {json.dumps(payload)}\n\n".encode()
    if provider_id == "anthropic":
        payload = {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": _UPSTREAM_KEY},
        }
        return f"event: content_block_delta\ndata: {json.dumps(payload)}\n\n".encode()
    if provider_id == "google":
        payload = {"candidates": [{"content": {"parts": [{"text": _UPSTREAM_KEY}]}}]}
        return f"data: {json.dumps(payload)}\n\n".encode()
    raise AssertionError(f"unexpected native catalog provider: {provider_id}")


def _native_manager(tmp_path: Path, provider_id: str) -> tuple[AssistantProviderManager, str]:
    """Build a real manager using the maintained catalog model type and synthetic inventory."""

    model_id = f"{provider_id}/assistant-policy-boundary-fixture"
    model = AssistantModel(
        model_id=model_id,
        provider_id=provider_id,
        display_name="Synthetic provider policy fixture",
        available=True,
        free=False,
        training=True,
        terms_url="https://terms.example.test/policy",
        terms_reviewed_at="2026-10-05",
        policy_version="synthetic-policy-v1",
        disclosure="Synthetic provider policy fixture.",
        data_collection_allowed=True,
        data_collection_default=False,
        native_provider_id=provider_id,
    )
    catalog = AssistantModelCatalog()
    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="p" * 64),
        catalog=catalog,
        vault_dir=tmp_path / "assistant-vault",
    )
    manager.set_credential(provider_id, _UPSTREAM_KEY)
    catalog.set_native_models((model,))
    return manager, model_id


def _console_payload(endpoint: str = "https://model.example.test/v1") -> dict[str, object]:
    """Return one closed OpenAI Console model row with a synthetic endpoint."""

    return {
        "providers": {
            "reviewed-provider": {
                "canonical": "openai",
                "models": {
                    "fixture-config-model": {
                        "modelID": "vendor/assistant-policy-boundary-fixture",
                        "name": "Synthetic policy-boundary model",
                        "settings": {"baseURL": endpoint},
                    }
                },
            }
        }
    }


def _console_manager(tmp_path: Path, owner_ids: tuple[int, ...]) -> AssistantProviderManager:
    """Create owner-isolated synthetic Console credentials and one app-side API key."""

    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="c" * 64),
        vault_dir=tmp_path / "assistant-vault",
    )
    manager.set_credential("openai", _UPSTREAM_KEY)
    for owner_id in owner_ids:
        manager._write_oauth_credential(
            "opencode",
            "device",
            owner_id,
            {
                "type": "oauth",
                "methodID": "device",
                "access": f"{_CONSOLE_ACCESS_PREFIX}{owner_id}",
                "refresh": f"synthetic-policy-boundary-console-refresh-{owner_id}",
                "expires": int(time.time() * 1000) + 3_600_000,
                "metadata": {
                    "server": "https://opencode.ai/console",
                    "accountID": f"synthetic-account-{owner_id}",
                },
            },
        )
    return manager


def _install_console_transport(
    monkeypatch: pytest.MonkeyPatch,
    payload_for_owner: Mapping[int, Mapping[str, object]],
) -> tuple[list[int], list[dict[str, object]]]:
    """Route fake config reads by synthetic owner token and collect fixed-host calls."""

    owner_by_access = {
        f"{_CONSOLE_ACCESS_PREFIX}{owner_id}": owner_id for owner_id in payload_for_owner
    }
    requested_owners: list[int] = []
    requests: list[dict[str, object]] = []

    async def fake_request(url: str, *, headers: object, **options: object) -> SimpleNamespace:
        assert url == "https://opencode.ai/console/api/v2/config"
        normalized = dict(headers) if isinstance(headers, Mapping) else {}
        authorization = normalized.get("authorization")
        assert isinstance(authorization, str)
        access = authorization.removeprefix("Bearer ")
        owner_id = owner_by_access[access]
        requested_owners.append(owner_id)
        requests.append({"url": url, "owner_id": owner_id, "options": options})
        return SimpleNamespace(
            status_code=200,
            content=json.dumps(payload_for_owner[owner_id]).encode("utf-8"),
        )

    monkeypatch.setattr(providers, "request_public_https", fake_request)
    return requested_owners, requests


async def _review_and_enable_console_model(
    manager: AssistantProviderManager,
    owner_id: int,
    authorization_check: object,
) -> tuple[str, dict[str, object]]:
    """Complete the manager's inventory, review, and policy CAS using fixture disclosures."""

    inventory = await manager.ensure_opencode_model_inventory(
        owner_id=owner_id,
        authorization_check=authorization_check,
        force=True,
    )
    assert len(inventory) == 1
    row = inventory[0]
    model_id = str(row["model_id"])
    review = await manager.review_opencode_model(
        model_id,
        owner_id=owner_id,
        expected_revision=0,
        terms_url="https://terms.example.test/policy",
        privacy_disclosure="Synthetic administrator privacy assertion; unverified.",
        billing_disclosure="Synthetic administrator billing assertion; unverified.",
        billing_class="paid",
        training_policy="no_training",
        confidential_data_policy="allowed",
        endpoint_policy_reviewed=True,
        expected_config_fingerprint=str(row["config_fingerprint"]),
        authorization_check=authorization_check,
    )
    enabled = manager.update_model_policy(
        model_id,
        owner_id=owner_id,
        enabled=True,
        acknowledged_privacy_policy_version=str(review["privacy_policy_version"]),
        acknowledged_billing_policy_version=str(review["billing_policy_version"]),
        expected_revision=0,
    )
    assert enabled["usable"] is True
    return model_id, review


async def _collect(stream: AsyncIterator[bytes]) -> list[bytes]:
    """Consume a manager stream while retaining exactly what reached the caller."""

    return [chunk async for chunk in stream]


@pytest.mark.parametrize(
    ("changed_field", "changed_value", "stale_ack_error"),
    (
        (
            "privacy_disclosure",
            "Updated synthetic privacy assertion.",
            "privacy_policy_ack_required",
        ),
        (
            "billing_disclosure",
            "Updated synthetic billing assertion.",
            "billing_policy_ack_required",
        ),
    ),
)
def test_console_policy_revision_invalidates_approval_before_native_upstream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed_field: str,
    changed_value: str,
    stale_ack_error: str,
) -> None:
    """Revised owner privacy or billing terms require new consent before model dispatch."""

    owner_id = 73
    manager = _console_manager(tmp_path, (owner_id,))
    requested_owners, _requests = _install_console_transport(
        monkeypatch, {owner_id: _console_payload()}
    )
    stream_calls: list[str] = []

    async def fake_stream(url: str, **_options: object) -> AsyncIterator[bytes]:
        stream_calls.append(url)
        yield b"data: [DONE]\n\n"

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)

    async def exercise() -> None:
        def authorize() -> bool:
            return True

        model_id, original_review = await _review_and_enable_console_model(
            manager, owner_id, authorize
        )
        changed_values = {
            "terms_url": "https://terms.example.test/policy",
            "privacy_disclosure": "Synthetic administrator privacy assertion; unverified.",
            "billing_disclosure": "Synthetic administrator billing assertion; unverified.",
            "billing_class": "paid",
            "training_policy": "no_training",
            "confidential_data_policy": "allowed",
            "endpoint_policy_reviewed": True,
        }
        changed_values[changed_field] = changed_value
        changed_review = await manager.review_opencode_model(
            model_id,
            owner_id=owner_id,
            expected_revision=1,
            expected_config_fingerprint=str(
                manager._opencode_public_inventory(owner_id)[0]["config_fingerprint"]
            ),
            authorization_check=authorize,
            **changed_values,
        )
        state = manager.model_policy_state(model_id, owner_id=owner_id)
        assert changed_review["review_revision"] == 2
        assert changed_review["privacy_policy_version"] != original_review[
            "privacy_policy_version"
        ] or (changed_review["billing_policy_version"] != original_review["billing_policy_version"])
        assert state["enabled"] is True
        assert state["usable"] is False
        assert state["availability_reason"] == "policy_acknowledgement_required"

        metadata_before_denials = manager._read_metadata()
        review_before_denials = manager._read_opencode_reviews(owner_id)
        requests_before_denials = len(requested_owners)
        with pytest.raises(ProviderUnavailable) as stale_ack:
            manager.update_model_policy(
                model_id,
                owner_id=owner_id,
                enabled=True,
                acknowledged_privacy_policy_version=str(original_review["privacy_policy_version"]),
                acknowledged_billing_policy_version=str(original_review["billing_policy_version"]),
                expected_revision=1,
            )
        assert stale_ack.value.code == stale_ack_error

        body = {
            "model": "assistant-selected",
            "input": "synthetic prompt",
            "stream": True,
            "store": False,
        }
        with pytest.raises(ProviderUnavailable, match="model_unavailable"):
            manager.proxy_native_stream(
                "opencode-console",
                model_id,
                body,
                path_model_id=None,
                query=(),
                app_tools=_APP_TOOLS,
                owner_id=owner_id,
                app_session_id="synthetic-policy-boundary-session",
                authorization_check=authorize,
            )

        assert len(requested_owners) == requests_before_denials
        assert stream_calls == []
        assert manager._read_metadata() == metadata_before_denials
        assert manager._read_opencode_reviews(owner_id) == review_before_denials

    asyncio.run(exercise())


def test_console_proxy_rechecks_revoked_live_authorization_before_refresh_or_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A revoked session cannot trigger a new Console config read or model stream."""

    owner_id = 81
    other_owner_id = 82
    manager = _console_manager(tmp_path, (owner_id, other_owner_id))
    requested_owners, _requests = _install_console_transport(
        monkeypatch,
        {
            owner_id: _console_payload(),
            other_owner_id: _console_payload(),
        },
    )
    stream_calls: list[str] = []

    async def fake_stream(url: str, **_options: object) -> AsyncIterator[bytes]:
        stream_calls.append(url)
        yield b"data: [DONE]\n\n"

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)

    async def exercise() -> None:
        authorization = {"active": True}

        def authorize() -> bool:
            return authorization["active"]

        model_id, _review = await _review_and_enable_console_model(manager, owner_id, authorize)
        other_model_id, _other_review = await _review_and_enable_console_model(
            manager, other_owner_id, lambda: True
        )
        assert model_id != other_model_id

        owner_credential_path = manager._oauth_credential_path("opencode", owner_id, "device")
        other_credential_path = manager._oauth_credential_path("opencode", other_owner_id, "device")
        owner_credential_before = owner_credential_path.read_bytes()
        other_credential_before = other_credential_path.read_bytes()
        other_review_before = manager._opencode_review_path(other_owner_id).read_bytes()
        other_policy_before = manager.model_policy_state(other_model_id, owner_id=other_owner_id)
        metadata_before = manager._read_metadata()
        requests_before = len(requested_owners)
        requested_owners.clear()

        body = {
            "model": "assistant-selected",
            "input": "synthetic prompt",
            "stream": True,
            "store": False,
        }
        stream = manager.proxy_native_stream(
            "opencode-console",
            model_id,
            body,
            path_model_id=None,
            query=(),
            app_tools=_APP_TOOLS,
            owner_id=owner_id,
            app_session_id="synthetic-policy-boundary-revoked-session",
            authorization_check=authorize,
        )
        authorization["active"] = False
        with pytest.raises(CredentialRejected, match="oauth_authorization_required") as rejected:
            await _collect(stream)

        assert rejected.value.code == "oauth_authorization_required"
        assert requested_owners == []
        assert stream_calls == []
        assert manager._read_metadata() == metadata_before
        assert owner_credential_path.read_bytes() == owner_credential_before
        assert other_credential_path.read_bytes() == other_credential_before
        assert manager._opencode_review_path(other_owner_id).read_bytes() == other_review_before
        assert (
            manager.model_policy_state(other_model_id, owner_id=other_owner_id)
            == other_policy_before
        )
        assert len(requested_owners) == 0
        assert requests_before > 0

    asyncio.run(exercise())


def test_console_proxy_rejects_other_owners_model_before_any_egress_or_state_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid owner's model identifier cannot be replayed in another owner's session."""

    owner_id = 91
    other_owner_id = 92
    manager = _console_manager(tmp_path, (owner_id, other_owner_id))
    requested_owners, _requests = _install_console_transport(
        monkeypatch,
        {
            owner_id: _console_payload(),
            other_owner_id: _console_payload(),
        },
    )
    stream_calls: list[str] = []

    async def fake_stream(url: str, **_options: object) -> AsyncIterator[bytes]:
        stream_calls.append(url)
        yield b"data: [DONE]\n\n"

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)

    async def exercise() -> None:
        owner_model_id, _owner_review = await _review_and_enable_console_model(
            manager, owner_id, lambda: True
        )
        other_model_id, _other_review = await _review_and_enable_console_model(
            manager, other_owner_id, lambda: True
        )
        assert owner_model_id != other_model_id
        before_metadata = manager._read_metadata()
        before_other_review = manager._read_opencode_reviews(other_owner_id)
        before_other_policy = manager.model_policy_state(other_model_id, owner_id=other_owner_id)
        before_other_vault = manager._oauth_credential_path(
            "opencode", other_owner_id, "device"
        ).read_bytes()
        requested_owners.clear()

        with pytest.raises(ProviderUnavailable, match="model_unavailable") as rejected:
            manager.proxy_native_stream(
                "opencode-console",
                owner_model_id,
                {
                    "model": "assistant-selected",
                    "input": "synthetic prompt",
                    "stream": True,
                    "store": False,
                },
                path_model_id=None,
                query=(),
                app_tools=_APP_TOOLS,
                owner_id=other_owner_id,
                app_session_id="synthetic-policy-boundary-other-owner-session",
                authorization_check=lambda: True,
            )

        assert rejected.value.code == "model_unavailable"
        assert requested_owners == []
        assert stream_calls == []
        assert manager._read_metadata() == before_metadata
        assert manager._read_opencode_reviews(other_owner_id) == before_other_review
        assert (
            manager.model_policy_state(other_model_id, owner_id=other_owner_id)
            == before_other_policy
        )
        assert manager._oauth_credential_path(
            "opencode", other_owner_id, "device"
        ).read_bytes() == (before_other_vault)

    asyncio.run(exercise())


def test_console_inventory_omits_private_endpoint_and_unreviewed_adapter_per_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discard unsafe owner-configured endpoints and dynamic packages from manager inventory."""

    owner_id = 101
    other_owner_id = 102
    manager = _console_manager(tmp_path, (owner_id, other_owner_id))
    safe_payload = _console_payload()
    hostile_payload = {
        "providers": {
            "safe-row": safe_payload["providers"]["reviewed-provider"],
            "private-endpoint-row": {
                "canonical": "anthropic",
                "models": {
                    "private-fixture": {
                        "modelID": "vendor/private-fixture",
                        "settings": {"baseURL": "https://127.0.0.1/v1"},
                    }
                },
            },
            "dynamic-adapter-row": {
                "package": "npm:unreviewed/native-adapter",
                "models": {"dynamic-fixture": {"modelID": "vendor/dynamic-fixture"}},
            },
        }
    }
    _requested_owners, requests = _install_console_transport(
        monkeypatch,
        {owner_id: safe_payload, other_owner_id: hostile_payload},
    )
    stream_calls: list[str] = []

    async def unexpected_stream(url: str, **_options: object) -> AsyncIterator[bytes]:
        stream_calls.append(url)
        yield b""

    monkeypatch.setattr(providers, "stream_public_https", unexpected_stream)

    async def exercise() -> None:
        safe_rows = await manager.ensure_opencode_model_inventory(
            owner_id=owner_id, authorization_check=lambda: True, force=True
        )
        safe_summary = manager.opencode_inventory_summary(owner_id=owner_id)
        safe_model_id = str(safe_rows[0]["model_id"])
        safe_policy_before = manager.model_policy_state(safe_model_id, owner_id=owner_id)
        safe_vault_before = manager._oauth_credential_path(
            "opencode", owner_id, "device"
        ).read_bytes()

        rejected_rows = await manager.ensure_opencode_model_inventory(
            owner_id=other_owner_id, authorization_check=lambda: True, force=True
        )

        assert len(safe_rows) == 1
        assert safe_summary == {"model_count": 1, "unsupported_model_count": 0}
        assert len(rejected_rows) == 1
        assert manager.opencode_inventory_summary(owner_id=other_owner_id) == {
            "model_count": 1,
            "unsupported_model_count": 2,
        }
        public_hostile_state = json.dumps(rejected_rows, sort_keys=True)
        assert "127.0.0.1" not in public_hostile_state
        assert "unreviewed/native-adapter" not in public_hostile_state
        assert (
            manager.get_opencode_model(safe_model_id, owner_id=owner_id).model_id == safe_model_id
        )
        assert manager.model_policy_state(safe_model_id, owner_id=owner_id) == safe_policy_before
        assert manager._oauth_credential_path("opencode", owner_id, "device").read_bytes() == (
            safe_vault_before
        )
        assert all(
            request["url"] == "https://opencode.ai/console/api/v2/config" for request in requests
        )
        assert stream_calls == []

    asyncio.run(exercise())


@pytest.mark.parametrize("provider_id", ("openai", "anthropic", "google"))
def test_catalog_native_proxy_rejects_unreviewed_request_and_tool_before_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
) -> None:
    """Reject provider-selected endpoint fields and undeclared tools in every native schema."""

    manager, model_id = _native_manager(tmp_path, provider_id)
    body, path_model_id, query = _native_body(provider_id)
    upstream_calls: list[str] = []

    async def unexpected_stream(url: str, **_options: object) -> AsyncIterator[bytes]:
        upstream_calls.append(url)
        yield b"data: {}\n\n"

    monkeypatch.setattr(providers, "stream_public_https", unexpected_stream)
    metadata_before = manager._read_metadata()
    credential_path = manager._credential_path(provider_id)
    credential_before = credential_path.read_bytes()

    invalid_request = dict(body)
    invalid_request["endpoint"] = "https://attacker.example.test/"
    with pytest.raises(ProviderUnavailable, match="provider_request_invalid"):
        manager.proxy_native_stream(
            provider_id,
            model_id,
            invalid_request,
            path_model_id=path_model_id,
            query=query,
            app_tools=_APP_TOOLS,
            authorization_check=lambda: True,
        )

    invalid_tools = dict(body)
    invalid_tools["tools"] = _native_tool_declaration(provider_id)
    with pytest.raises(ProviderUnavailable, match="provider_request_invalid"):
        manager.proxy_native_stream(
            provider_id,
            model_id,
            invalid_tools,
            path_model_id=path_model_id,
            query=query,
            app_tools=_APP_TOOLS,
            authorization_check=lambda: True,
        )

    assert upstream_calls == []
    assert manager._read_metadata() == metadata_before
    assert credential_path.read_bytes() == credential_before
    assert manager._read_credential(provider_id) == _UPSTREAM_KEY


@pytest.mark.parametrize("provider_id", ("openai", "anthropic", "google"))
def test_catalog_native_proxy_withholds_echoed_vault_key_for_each_vendor_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
) -> None:
    """Keep an echoed provider credential out of caller-visible SSE for each catalog adapter."""

    manager, model_id = _native_manager(tmp_path, provider_id)
    body, path_model_id, query = _native_body(provider_id)
    adapter_id = {
        "openai": "openai-responses",
        "anthropic": "anthropic-messages",
        "google": "google-generative-language",
    }[provider_id]
    descriptor = resolve_native_adapter(adapter_id, provider_id)
    upstream_requests: list[tuple[str, dict[str, str], bytes]] = []

    async def fake_stream(
        url: str,
        *,
        headers: object,
        body: bytes,
        **_options: object,
    ) -> AsyncIterator[bytes]:
        upstream_requests.append((url, dict(headers), body))
        yield _secret_echo(provider_id)

    monkeypatch.setattr(providers, "stream_public_https", fake_stream)

    async def exercise() -> list[bytes]:
        stream = manager.proxy_native_stream(
            provider_id,
            model_id,
            body,
            path_model_id=path_model_id,
            query=query,
            app_tools=_APP_TOOLS,
            authorization_check=lambda: True,
        )
        return await _collect(stream)

    released: list[bytes] = []

    async def capture() -> None:
        released.extend(await exercise())

    with pytest.raises(ProviderUnavailable, match="provider_response_secret_rejected") as rejected:
        asyncio.run(capture())

    assert rejected.value.code == "provider_response_secret_rejected"
    assert released == []
    assert len(upstream_requests) == 1
    url, headers, encoded_body = upstream_requests[0]
    assert url.startswith("https://")
    expected_credential = (
        f"Bearer {_UPSTREAM_KEY}" if descriptor.upstream_auth_scheme == "bearer" else _UPSTREAM_KEY
    )
    normalized_headers = {name.lower(): value for name, value in headers.items()}
    assert normalized_headers[descriptor.upstream_auth_header.lower()] == expected_credential
    assert _UPSTREAM_KEY.encode() not in encoded_body
    assert manager._read_credential(provider_id) == _UPSTREAM_KEY
