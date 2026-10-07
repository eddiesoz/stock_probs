"""Exercise provider OAuth refresh through the manager's public flows."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs

import pytest

from stock_probs.assistant import providers
from stock_probs.assistant.model_catalog import AssistantModelCatalog
from stock_probs.assistant.providers import (
    AssistantProviderManager,
    CredentialRejected,
    ProviderUnavailable,
)

_NOW = 1_800_000_000
_TARGET_OWNER = 71
_OTHER_OWNER = 72
_APP_TOOLS: list[dict[str, object]] = [
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
_CHATGPT_BODY: dict[str, object] = {
    "model": "assistant-selected",
    "input": [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "synthetic provider test"}],
        }
    ],
    "instructions": "Use only the approved local tools.",
    "stream": True,
    "store": False,
}
_COMPLETED_FRAME = b'event: response.completed\ndata: {"type":"response.completed"}\n\n'
_AuthorizationCheck = Callable[[], bool | Awaitable[bool]]


class _HTTPResponse:
    """Represent only the bounded status and bytes returned by the fake transport."""

    def __init__(self, status_code: int, payload: object | bytes) -> None:
        self.status_code = status_code
        self.content = (
            payload
            if isinstance(payload, bytes)
            else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )


def _manager(tmp_path: Path) -> tuple[AssistantProviderManager, AssistantModelCatalog]:
    """Construct the real manager against the checked-in provider policy and a disposable vault."""

    catalog = AssistantModelCatalog(clock=lambda: 5.0)
    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="v" * 64),
        catalog=catalog,
        vault_dir=tmp_path / "assistant-vault",
        clock=lambda: 5.0,
    )
    return manager, catalog


def _freeze_provider_clock(monkeypatch: pytest.MonkeyPatch, now: int = _NOW) -> None:
    """Freeze only providers.py's wall clock so no process-global clock is changed."""

    monkeypatch.setattr(providers, "time", SimpleNamespace(time=lambda: now))


def _seed_chatgpt_credential(
    manager: AssistantProviderManager,
    owner_id: int,
    *,
    access: str,
    refresh: str,
    expires: int,
    account_id: str,
    method_id: str = "chatgpt-headless",
) -> None:
    manager._write_oauth_credential(
        "openai",
        method_id,
        owner_id,
        {
            "type": "oauth",
            "methodID": method_id,
            "access": access,
            "refresh": refresh,
            "expires": expires,
            "metadata": {"accountID": account_id},
        },
    )


def _seed_opencode_credential(
    manager: AssistantProviderManager,
    owner_id: int,
    *,
    access: str,
    refresh: str,
    expires: int,
    org_id: str,
    org_name: str,
) -> None:
    manager._write_oauth_credential(
        "opencode",
        "device",
        owner_id,
        {
            "type": "oauth",
            "methodID": "device",
            "access": access,
            "refresh": refresh,
            "expires": expires,
            "metadata": {
                "server": "https://opencode.ai/console",
                "accountID": f"synthetic-account-{owner_id}",
                "orgID": org_id,
                "orgName": org_name,
            },
        },
    )


def _chatgpt_model_id(catalog: AssistantModelCatalog) -> str:
    """Select a currently reviewed account model from the checked-in application catalog."""

    model = next(item for item in catalog.list_models() if item.provider_id == "openai-chatgpt")
    return model.model_id


def _enable_chatgpt_model(manager: AssistantProviderManager, model_id: str, owner_id: int) -> None:
    state = manager.model_policy_state(model_id, owner_id=owner_id)
    enabled = manager.update_model_policy(
        model_id,
        enabled=True,
        acknowledged_privacy_policy_version=str(state["privacy_policy_version"]),
        acknowledged_billing_policy_version=str(state["billing_policy_version"]),
        expected_revision=int(state["revision"]),
        owner_id=owner_id,
    )
    assert enabled["usable"] is True


async def _collect_chatgpt_stream(
    manager: AssistantProviderManager,
    model_id: str,
    *,
    owner_id: int,
    authorization_check: _AuthorizationCheck,
) -> list[bytes]:
    stream = manager.proxy_native_stream(
        "openai-chatgpt",
        model_id,
        _CHATGPT_BODY,
        path_model_id=None,
        query=(),
        app_tools=_APP_TOOLS,
        owner_id=owner_id,
        app_session_id=f"app-session-{owner_id}",
        native_session_id="ses-provider-release-gap",
        authorization_check=authorization_check,
    )
    return [chunk async for chunk in stream]


def _token_response(
    *,
    access: str = "synthetic-rotated-access",
    refresh: str = "synthetic-rotated-refresh",
    expires_in: object = 3600,
) -> dict[str, object]:
    """Return a bounded token body with allowed provider metadata that must not be persisted."""

    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": expires_in,
        "id_token": "synthetic-unrelated-id-token",
        "token_type": "Bearer",
        "scope": "openid profile offline_access",
    }


@pytest.mark.parametrize("status_code", (401, 403, 500))
def test_chatgpt_refresh_rejects_non_success_http_status_without_vault_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    """Reject a valid-looking token body when the fixed refresh endpoint did not succeed."""

    _freeze_provider_clock(monkeypatch)
    manager, catalog = _manager(tmp_path)
    model_id = _chatgpt_model_id(catalog)
    _seed_chatgpt_credential(
        manager,
        _TARGET_OWNER,
        access="synthetic-old-owner-access",
        refresh="synthetic-old-owner-refresh",
        expires=_NOW * 1000 + 30_000,
        account_id="synthetic-target-account",
    )
    _seed_chatgpt_credential(
        manager,
        _OTHER_OWNER,
        access="synthetic-other-owner-access",
        refresh="synthetic-other-owner-refresh",
        expires=_NOW * 1000 + 3_600_000,
        account_id="synthetic-other-account",
    )
    _enable_chatgpt_model(manager, model_id, _TARGET_OWNER)
    target_path = manager._oauth_credential_path("openai", _TARGET_OWNER, "chatgpt-headless")
    other_path = manager._oauth_credential_path("openai", _OTHER_OWNER, "chatgpt-headless")
    target_ciphertext_before = target_path.read_bytes()
    other_ciphertext_before = other_path.read_bytes()
    requests: list[dict[str, object]] = []
    upstream_calls: list[str] = []

    async def fake_request(
        url: str,
        *,
        method: str,
        headers: Mapping[str, str],
        body: bytes,
        content_type: str,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> _HTTPResponse:
        requests.append(
            {
                "url": url,
                "method": method,
                "headers": dict(headers),
                "body": body,
                "content_type": content_type,
                "timeout_seconds": timeout_seconds,
                "max_response_bytes": max_response_bytes,
            }
        )
        return _HTTPResponse(status_code, _token_response())

    async def unexpected_stream(url: str, **_options: object) -> AsyncIterator[bytes]:
        upstream_calls.append(url)
        yield _COMPLETED_FRAME

    monkeypatch.setattr(providers, "request_public_https", fake_request)
    monkeypatch.setattr(providers, "stream_public_https", unexpected_stream)

    with pytest.raises(
        CredentialRejected if status_code in {401, 403} else ProviderUnavailable,
        match=(
            "oauth_connection_required"
            if status_code in {401, 403}
            else "oauth_refresh_unavailable"
        ),
    ) as rejected:
        asyncio.run(
            _collect_chatgpt_stream(
                manager,
                model_id,
                owner_id=_TARGET_OWNER,
                authorization_check=lambda: True,
            )
        )

    expected_error = (
        "oauth_connection_required" if status_code in {401, 403} else "oauth_refresh_unavailable"
    )
    assert rejected.value.code == expected_error
    assert requests[0]["url"] == "https://auth.openai.com/oauth/token"
    assert requests[0]["method"] == "POST"
    assert requests[0]["headers"] == {"accept": "application/json"}
    assert requests[0]["content_type"] == "application/x-www-form-urlencoded"
    assert requests[0]["timeout_seconds"] == 10.0
    assert requests[0]["max_response_bytes"] == 65_536
    assert parse_qs(bytes(requests[0]["body"]).decode("ascii")) == {
        "grant_type": ["refresh_token"],
        "refresh_token": ["synthetic-old-owner-refresh"],
        "client_id": [providers._CHATGPT_CLIENT_ID],
    }
    assert len(requests) == 1
    assert upstream_calls == []
    assert target_path.read_bytes() == target_ciphertext_before
    assert other_path.read_bytes() == other_ciphertext_before
    assert manager._read_oauth_credential("openai", "chatgpt-headless", _TARGET_OWNER) == {
        "type": "oauth",
        "methodID": "chatgpt-headless",
        "access": "synthetic-old-owner-access",
        "refresh": "synthetic-old-owner-refresh",
        "expires": _NOW * 1000 + 30_000,
        "metadata": {"accountID": "synthetic-target-account"},
    }
    assert manager._read_oauth_credential("openai", "chatgpt-headless", _OTHER_OWNER) == {
        "type": "oauth",
        "methodID": "chatgpt-headless",
        "access": "synthetic-other-owner-access",
        "refresh": "synthetic-other-owner-refresh",
        "expires": _NOW * 1000 + 3_600_000,
        "metadata": {"accountID": "synthetic-other-account"},
    }


def test_chatgpt_refresh_rotates_only_owner_and_omits_unrelated_response_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persist only canonical refreshed token fields and stream with that owner's access token."""

    _freeze_provider_clock(monkeypatch)
    manager, catalog = _manager(tmp_path)
    model_id = _chatgpt_model_id(catalog)
    _seed_chatgpt_credential(
        manager,
        _TARGET_OWNER,
        access="synthetic-old-owner-access",
        refresh="synthetic-old-owner-refresh",
        expires=_NOW * 1000 + 30_000,
        account_id="synthetic-target-account",
    )
    _seed_chatgpt_credential(
        manager,
        _OTHER_OWNER,
        access="synthetic-other-owner-access",
        refresh="synthetic-other-owner-refresh",
        expires=_NOW * 1000 + 3_600_000,
        account_id="synthetic-other-account",
    )
    _enable_chatgpt_model(manager, model_id, _TARGET_OWNER)
    target_path = manager._oauth_credential_path("openai", _TARGET_OWNER, "chatgpt-headless")
    other_path = manager._oauth_credential_path("openai", _OTHER_OWNER, "chatgpt-headless")
    other_ciphertext_before = other_path.read_bytes()
    requests: list[dict[str, object]] = []
    upstream_calls: list[dict[str, object]] = []

    async def fake_request(
        url: str,
        *,
        method: str,
        headers: Mapping[str, str],
        body: bytes,
        content_type: str,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> _HTTPResponse:
        requests.append(
            {
                "url": url,
                "method": method,
                "headers": dict(headers),
                "body": body,
                "content_type": content_type,
                "timeout_seconds": timeout_seconds,
                "max_response_bytes": max_response_bytes,
            }
        )
        return _HTTPResponse(200, _token_response())

    async def fake_stream(
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> AsyncIterator[bytes]:
        upstream_calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "body": json.loads(body),
                "timeout_seconds": timeout_seconds,
                "max_response_bytes": max_response_bytes,
            }
        )
        yield _COMPLETED_FRAME

    monkeypatch.setattr(providers, "request_public_https", fake_request)
    monkeypatch.setattr(providers, "stream_public_https", fake_stream)

    chunks = asyncio.run(
        _collect_chatgpt_stream(
            manager,
            model_id,
            owner_id=_TARGET_OWNER,
            authorization_check=lambda: True,
        )
    )

    assert chunks == [_COMPLETED_FRAME]
    assert requests[0]["url"] == "https://auth.openai.com/oauth/token"
    assert parse_qs(bytes(requests[0]["body"]).decode("ascii"))["refresh_token"] == [
        "synthetic-old-owner-refresh"
    ]
    assert requests[0]["timeout_seconds"] == 10.0
    assert requests[0]["max_response_bytes"] == 65_536
    assert len(requests) == 1
    upstream = upstream_calls[0]
    assert upstream["url"] == providers._CHATGPT_UPSTREAM_URL
    assert upstream["headers"]["authorization"] == "Bearer synthetic-rotated-access"
    assert upstream["headers"]["chatgpt-account-id"] == "synthetic-target-account"
    assert upstream["timeout_seconds"] == 120.0
    assert upstream["max_response_bytes"] == 1_048_576
    assert upstream["body"]["model"] == model_id.partition("/")[2]
    assert upstream["body"]["store"] is False
    assert "synthetic-rotated-access" not in b"".join(chunks).decode("utf-8")
    assert "synthetic-rotated-refresh" not in b"".join(chunks).decode("utf-8")

    target_credential = manager._read_oauth_credential("openai", "chatgpt-headless", _TARGET_OWNER)
    assert target_credential is not None
    assert set(target_credential) == {
        "type",
        "methodID",
        "access",
        "refresh",
        "expires",
        "metadata",
    }
    assert target_credential == {
        "type": "oauth",
        "methodID": "chatgpt-headless",
        "access": "synthetic-rotated-access",
        "refresh": "synthetic-rotated-refresh",
        "expires": _NOW * 1000 + 3_600_000,
        "metadata": {"accountID": "synthetic-target-account"},
    }
    assert target_path.read_bytes() != other_ciphertext_before
    assert b"synthetic-rotated-access" not in target_path.read_bytes()
    assert b"synthetic-rotated-refresh" not in target_path.read_bytes()
    assert other_path.read_bytes() == other_ciphertext_before
    assert manager._read_oauth_credential("openai", "chatgpt-headless", _OTHER_OWNER) == {
        "type": "oauth",
        "methodID": "chatgpt-headless",
        "access": "synthetic-other-owner-access",
        "refresh": "synthetic-other-owner-refresh",
        "expires": _NOW * 1000 + 3_600_000,
        "metadata": {"accountID": "synthetic-other-account"},
    }


def test_chatgpt_refresh_does_not_commit_after_live_authorization_is_revoked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A session revoked during token egress cannot replace its owner credential."""

    _freeze_provider_clock(monkeypatch)
    manager, catalog = _manager(tmp_path)
    model_id = _chatgpt_model_id(catalog)
    _seed_chatgpt_credential(
        manager,
        _TARGET_OWNER,
        access="synthetic-old-owner-access",
        refresh="synthetic-old-owner-refresh",
        expires=_NOW * 1000 + 30_000,
        account_id="synthetic-target-account",
    )
    _enable_chatgpt_model(manager, model_id, _TARGET_OWNER)
    target_path = manager._oauth_credential_path("openai", _TARGET_OWNER, "chatgpt-headless")
    old_ciphertext = target_path.read_bytes()
    authorized = True
    requests: list[str] = []
    upstream_calls: list[str] = []

    async def fake_request(url: str, **_options: object) -> _HTTPResponse:
        nonlocal authorized
        requests.append(url)
        authorized = False
        return _HTTPResponse(200, _token_response())

    async def unexpected_stream(url: str, **_options: object) -> AsyncIterator[bytes]:
        upstream_calls.append(url)
        yield _COMPLETED_FRAME

    monkeypatch.setattr(providers, "request_public_https", fake_request)
    monkeypatch.setattr(providers, "stream_public_https", unexpected_stream)

    with pytest.raises(CredentialRejected, match="oauth_authorization_required") as rejected:
        asyncio.run(
            _collect_chatgpt_stream(
                manager,
                model_id,
                owner_id=_TARGET_OWNER,
                authorization_check=lambda: authorized,
            )
        )

    assert rejected.value.code == "oauth_authorization_required"
    assert requests == ["https://auth.openai.com/oauth/token"]
    assert upstream_calls == []
    assert target_path.read_bytes() == old_ciphertext
    assert manager._read_oauth_credential("openai", "chatgpt-headless", _TARGET_OWNER) == {
        "type": "oauth",
        "methodID": "chatgpt-headless",
        "access": "synthetic-old-owner-access",
        "refresh": "synthetic-old-owner-refresh",
        "expires": _NOW * 1000 + 30_000,
        "metadata": {"accountID": "synthetic-target-account"},
    }


@pytest.mark.parametrize(
    "payload",
    (
        b"not-json",
        {**_token_response(), "expires_in": True},
        {**_token_response(), "expires_in": 0},
        {**_token_response(), "expires_in": 366 * 86_400 + 1},
        {**_token_response(), "access_token": "synthetic\ninvalid"},
    ),
    ids=("invalid-json", "bool-expiry", "zero-expiry", "expiry-over-limit", "control-token"),
)
def test_chatgpt_refresh_invalid_success_payload_preserves_encrypted_credential(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    """Malformed HTTP-success refresh bodies fail without mutating the owner vault."""

    _freeze_provider_clock(monkeypatch)
    manager, catalog = _manager(tmp_path)
    model_id = _chatgpt_model_id(catalog)
    _seed_chatgpt_credential(
        manager,
        _TARGET_OWNER,
        access="synthetic-old-owner-access",
        refresh="synthetic-old-owner-refresh",
        expires=_NOW * 1000 + 30_000,
        account_id="synthetic-target-account",
    )
    _enable_chatgpt_model(manager, model_id, _TARGET_OWNER)
    target_path = manager._oauth_credential_path("openai", _TARGET_OWNER, "chatgpt-headless")
    old_ciphertext = target_path.read_bytes()
    upstream_calls: list[str] = []

    async def fake_request(_url: str, **_options: object) -> _HTTPResponse:
        return _HTTPResponse(200, payload)

    async def unexpected_stream(url: str, **_options: object) -> AsyncIterator[bytes]:
        upstream_calls.append(url)
        yield _COMPLETED_FRAME

    monkeypatch.setattr(providers, "request_public_https", fake_request)
    monkeypatch.setattr(providers, "stream_public_https", unexpected_stream)

    with pytest.raises(ProviderUnavailable, match="oauth_refresh_invalid") as rejected:
        asyncio.run(
            _collect_chatgpt_stream(
                manager,
                model_id,
                owner_id=_TARGET_OWNER,
                authorization_check=lambda: True,
            )
        )

    assert rejected.value.code == "oauth_refresh_invalid"
    assert upstream_calls == []
    assert target_path.read_bytes() == old_ciphertext
    assert manager._read_oauth_credential("openai", "chatgpt-headless", _TARGET_OWNER) == {
        "type": "oauth",
        "methodID": "chatgpt-headless",
        "access": "synthetic-old-owner-access",
        "refresh": "synthetic-old-owner-refresh",
        "expires": _NOW * 1000 + 30_000,
        "metadata": {"accountID": "synthetic-target-account"},
    }


def test_chatgpt_oauth_stream_fails_closed_when_provider_echoes_access_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The OAuth access token receives the same response-secret guard as API credentials."""

    _freeze_provider_clock(monkeypatch)
    manager, catalog = _manager(tmp_path)
    model_id = _chatgpt_model_id(catalog)
    _seed_chatgpt_credential(
        manager,
        _TARGET_OWNER,
        access="synthetic-current-access-token",
        refresh="synthetic-current-refresh-token",
        expires=_NOW * 1000 + 300_000,
        account_id="synthetic-target-account",
    )
    _enable_chatgpt_model(manager, model_id, _TARGET_OWNER)
    refresh_requests: list[str] = []
    released: list[bytes] = []

    async def unexpected_refresh(url: str, **_options: object) -> _HTTPResponse:
        refresh_requests.append(url)
        return _HTTPResponse(500, {})

    async def echo_access_token(url: str, **_options: object) -> AsyncIterator[bytes]:
        assert url == providers._CHATGPT_UPSTREAM_URL
        yield (
            b'data: {"type":"response.output_text.delta",'
            b'"delta":"synthetic-current-access-token"}\n\n'
        )

    monkeypatch.setattr(providers, "request_public_https", unexpected_refresh)
    monkeypatch.setattr(providers, "stream_public_https", echo_access_token)

    async def consume() -> None:
        stream = manager.proxy_native_stream(
            "openai-chatgpt",
            model_id,
            _CHATGPT_BODY,
            path_model_id=None,
            query=(),
            app_tools=_APP_TOOLS,
            owner_id=_TARGET_OWNER,
            app_session_id="app-session-current-token",
            native_session_id="ses-provider-release-gap",
            authorization_check=lambda: True,
        )
        async for chunk in stream:
            released.append(chunk)

    with pytest.raises(ProviderUnavailable, match="provider_response_secret_rejected") as rejected:
        asyncio.run(consume())

    assert rejected.value.code == "provider_response_secret_rejected"
    assert released == []
    assert refresh_requests == []


def test_opencode_inventory_refresh_rotates_only_owner_before_fixed_config_fetch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refresh an expiring Console token before reading its owner-bound configuration."""

    _freeze_provider_clock(monkeypatch)
    manager, _catalog = _manager(tmp_path)
    _seed_opencode_credential(
        manager,
        _TARGET_OWNER,
        access="synthetic-old-console-access",
        refresh="synthetic-old-console-refresh",
        expires=_NOW * 1000 + 30_000,
        org_id="synthetic-old-org",
        org_name="Old organization name",
    )
    _seed_opencode_credential(
        manager,
        _OTHER_OWNER,
        access="synthetic-other-console-access",
        refresh="synthetic-other-console-refresh",
        expires=_NOW * 1000 + 3_600_000,
        org_id="synthetic-other-org",
        org_name="Other organization name",
    )
    target_path = manager._oauth_credential_path("opencode", _TARGET_OWNER, "device")
    other_path = manager._oauth_credential_path("opencode", _OTHER_OWNER, "device")
    other_ciphertext_before = other_path.read_bytes()
    requests: list[dict[str, object]] = []

    async def fake_request(
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout_seconds: float,
        max_response_bytes: int,
        method: str = "GET",
        body: bytes = b"",
        **_options: object,
    ) -> _HTTPResponse:
        requests.append(
            {
                "url": url,
                "headers": dict(headers or {}),
                "timeout_seconds": timeout_seconds,
                "max_response_bytes": max_response_bytes,
                "method": method,
                "body": body,
            }
        )
        if url == providers._OPENCODE_REFRESH_URL:
            return _HTTPResponse(
                200,
                {
                    "access_token": "synthetic-rotated-console-access",
                    "refresh_token": "synthetic-rotated-console-refresh",
                    "expires_in": 3600,
                    "org_id": "synthetic-new-org",
                },
            )
        return _HTTPResponse(200, {"providers": {}})

    monkeypatch.setattr(providers, "request_public_https", fake_request)
    result = asyncio.run(
        manager.ensure_opencode_model_inventory(
            owner_id=_TARGET_OWNER,
            authorization_check=lambda: True,
        )
    )

    assert result == ()
    assert [request["url"] for request in requests] == [
        "https://opencode.ai/console/auth/device/token",
        "https://opencode.ai/console/api/v2/config",
    ]
    assert requests[0]["method"] == "POST"
    assert requests[0]["headers"] == {"accept": "application/json"}
    assert json.loads(bytes(requests[0]["body"])) == {
        "grant_type": "refresh_token",
        "refresh_token": "synthetic-old-console-refresh",
        "client_id": providers._OPENCODE_CLIENT_ID,
    }
    assert requests[0]["timeout_seconds"] == 10.0
    assert requests[0]["max_response_bytes"] == 65_536
    assert requests[1]["headers"] == {
        "authorization": "Bearer synthetic-rotated-console-access",
        "x-org-id": "synthetic-new-org",
    }
    assert requests[1]["timeout_seconds"] < 10.0
    assert requests[1]["max_response_bytes"] > 0
    target_credential = manager._read_oauth_credential("opencode", "device", _TARGET_OWNER)
    assert target_credential is not None
    assert target_credential["access"] == "synthetic-rotated-console-access"
    assert target_credential["refresh"] == "synthetic-rotated-console-refresh"
    assert target_credential["metadata"] == {
        "server": "https://opencode.ai/console",
        "accountID": f"synthetic-account-{_TARGET_OWNER}",
        "orgID": "synthetic-new-org",
        "orgName": "synthetic-new-org",
    }
    assert b"synthetic-rotated-console-access" not in target_path.read_bytes()
    assert b"synthetic-rotated-console-refresh" not in target_path.read_bytes()
    assert other_path.read_bytes() == other_ciphertext_before
    assert manager._read_oauth_credential("opencode", "device", _OTHER_OWNER) == {
        "type": "oauth",
        "methodID": "device",
        "access": "synthetic-other-console-access",
        "refresh": "synthetic-other-console-refresh",
        "expires": _NOW * 1000 + 3_600_000,
        "metadata": {
            "server": "https://opencode.ai/console",
            "accountID": f"synthetic-account-{_OTHER_OWNER}",
            "orgID": "synthetic-other-org",
            "orgName": "Other organization name",
        },
    }


@pytest.mark.parametrize(
    ("status_code", "error_type", "error_code"),
    (
        (401, CredentialRejected, "oauth_connection_required"),
        (403, CredentialRejected, "oauth_connection_required"),
        (429, ProviderUnavailable, "oauth_refresh_unavailable"),
        (500, ProviderUnavailable, "oauth_refresh_unavailable"),
    ),
)
def test_opencode_refresh_non_success_status_preserves_owner_credential(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    error_type: type[Exception],
    error_code: str,
) -> None:
    """Reject every unsuccessful refresh status before parsing or fetching Console config."""

    _freeze_provider_clock(monkeypatch)
    manager, _catalog = _manager(tmp_path)
    _seed_opencode_credential(
        manager,
        _TARGET_OWNER,
        access="synthetic-old-console-access",
        refresh="synthetic-old-console-refresh",
        expires=_NOW * 1000 + 30_000,
        org_id="synthetic-org",
        org_name="Synthetic organization",
    )
    path = manager._oauth_credential_path("opencode", _TARGET_OWNER, "device")
    old_ciphertext = path.read_bytes()
    requests: list[str] = []

    async def fake_request(url: str, **_options: object) -> _HTTPResponse:
        requests.append(url)
        return _HTTPResponse(
            status_code,
            {
                "access_token": "synthetic-rotated-console-access",
                "refresh_token": "synthetic-rotated-console-refresh",
                "expires_in": 3600,
                "org_id": "synthetic-new-org",
            },
        )

    monkeypatch.setattr(providers, "request_public_https", fake_request)

    with pytest.raises(error_type, match=error_code) as rejected:
        asyncio.run(
            manager.ensure_opencode_model_inventory(
                owner_id=_TARGET_OWNER,
                authorization_check=lambda: True,
            )
        )

    assert rejected.value.code == error_code
    assert requests == ["https://opencode.ai/console/auth/device/token"]
    assert path.read_bytes() == old_ciphertext
    assert manager._read_oauth_credential("opencode", "device", _TARGET_OWNER) == {
        "type": "oauth",
        "methodID": "device",
        "access": "synthetic-old-console-access",
        "refresh": "synthetic-old-console-refresh",
        "expires": _NOW * 1000 + 30_000,
        "metadata": {
            "server": "https://opencode.ai/console",
            "accountID": f"synthetic-account-{_TARGET_OWNER}",
            "orgID": "synthetic-org",
            "orgName": "Synthetic organization",
        },
    }


def test_opencode_refresh_does_not_commit_after_live_authorization_is_revoked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revalidate the active app session after refresh egress and before vault replacement."""

    _freeze_provider_clock(monkeypatch)
    manager, _catalog = _manager(tmp_path)
    _seed_opencode_credential(
        manager,
        _TARGET_OWNER,
        access="synthetic-old-console-access",
        refresh="synthetic-old-console-refresh",
        expires=_NOW * 1000 + 30_000,
        org_id="synthetic-org",
        org_name="Synthetic organization",
    )
    path = manager._oauth_credential_path("opencode", _TARGET_OWNER, "device")
    old_ciphertext = path.read_bytes()
    authorized = True
    requests: list[str] = []

    async def fake_request(url: str, **_options: object) -> _HTTPResponse:
        nonlocal authorized
        requests.append(url)
        authorized = False
        return _HTTPResponse(
            200,
            {
                "access_token": "synthetic-rotated-console-access",
                "refresh_token": "synthetic-rotated-console-refresh",
                "expires_in": 3600,
                "org_id": "synthetic-new-org",
            },
        )

    monkeypatch.setattr(providers, "request_public_https", fake_request)

    with pytest.raises(CredentialRejected, match="oauth_authorization_required") as rejected:
        asyncio.run(
            manager.ensure_opencode_model_inventory(
                owner_id=_TARGET_OWNER,
                authorization_check=lambda: authorized,
            )
        )

    assert rejected.value.code == "oauth_authorization_required"
    assert requests == ["https://opencode.ai/console/auth/device/token"]
    assert path.read_bytes() == old_ciphertext
    assert manager._read_oauth_credential("opencode", "device", _TARGET_OWNER) == {
        "type": "oauth",
        "methodID": "device",
        "access": "synthetic-old-console-access",
        "refresh": "synthetic-old-console-refresh",
        "expires": _NOW * 1000 + 30_000,
        "metadata": {
            "server": "https://opencode.ai/console",
            "accountID": f"synthetic-account-{_TARGET_OWNER}",
            "orgID": "synthetic-org",
            "orgName": "Synthetic organization",
        },
    }


def test_opencode_same_owner_concurrent_inventory_refreshes_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Coalesce simultaneous expired-token inventory demand into one refresh and one fetch."""

    _freeze_provider_clock(monkeypatch)
    manager, _catalog = _manager(tmp_path)
    _seed_opencode_credential(
        manager,
        _TARGET_OWNER,
        access="synthetic-old-console-access",
        refresh="synthetic-old-console-refresh",
        expires=_NOW * 1000 + 30_000,
        org_id="synthetic-org",
        org_name="Synthetic organization",
    )
    refresh_started = asyncio.Event()
    allow_refresh_to_finish = asyncio.Event()
    second_call_authenticated = asyncio.Event()
    authorization_checks = 0
    requests: list[str] = []

    def authorization_check() -> bool:
        nonlocal authorization_checks
        authorization_checks += 1
        if authorization_checks == 4:
            second_call_authenticated.set()
        return True

    async def fake_request(url: str, **_options: object) -> _HTTPResponse:
        requests.append(url)
        if url == providers._OPENCODE_REFRESH_URL:
            refresh_started.set()
            await allow_refresh_to_finish.wait()
            return _HTTPResponse(
                200,
                {
                    "access_token": "synthetic-rotated-console-access",
                    "refresh_token": "synthetic-rotated-console-refresh",
                    "expires_in": 3600,
                    "org_id": "synthetic-org",
                },
            )
        return _HTTPResponse(200, {"providers": {}})

    monkeypatch.setattr(providers, "request_public_https", fake_request)

    async def exercise() -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
        first = asyncio.create_task(
            manager.ensure_opencode_model_inventory(
                owner_id=_TARGET_OWNER,
                authorization_check=authorization_check,
            )
        )
        await refresh_started.wait()
        second = asyncio.create_task(
            manager.ensure_opencode_model_inventory(
                owner_id=_TARGET_OWNER,
                authorization_check=authorization_check,
            )
        )
        await second_call_authenticated.wait()
        allow_refresh_to_finish.set()
        return await asyncio.gather(first, second)

    first_result, second_result = asyncio.run(exercise())

    assert first_result == second_result == ()
    assert requests == [providers._OPENCODE_REFRESH_URL, providers._OPENCODE_CONFIG_URL]
    credential = manager._read_oauth_credential("opencode", "device", _TARGET_OWNER)
    assert credential is not None
    assert credential["access"] == "synthetic-rotated-console-access"
    assert credential["refresh"] == "synthetic-rotated-console-refresh"
