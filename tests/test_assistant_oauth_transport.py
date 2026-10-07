from __future__ import annotations

import asyncio
import json
from functools import wraps
from urllib.parse import parse_qs

import pytest

from stock_probs.assistant.net import PublicHTTPResponse
from stock_probs.assistant.oauth_transport import OAuthTransport, OAuthTransportError


def _async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


def _response(value: object, status: int = 200) -> PublicHTTPResponse:
    return PublicHTTPResponse(
        status,
        {"content-type": "application/json"},
        json.dumps(value, separators=(",", ":")).encode(),
    )


@_async_test
async def test_oauth_registry_binds_capability_method_owner_and_expiry():
    now = 1_800_000_000.0
    transport = OAuthTransport(clock=lambda: now)
    cap = await transport.register(
        "a" * 32,
        "openai",
        "chatgpt-headless",
        7,
        "b" * 32,
        now + 300,
        session_token_hash="c" * 64,
    )
    assert len(cap) == 32
    binding = await transport.authorize("a" * 32, cap, "openai.device_poll")
    with pytest.raises(OAuthTransportError) as duplicate_in_flight:
        await transport.authorize("a" * 32, cap, "openai.device_start")
    assert duplicate_in_flight.value.code == "oauth_attempt_not_found"
    await transport.release(binding)
    next_binding = await transport.authorize("a" * 32, cap, "openai.device_start")
    await transport.release(next_binding)

    with pytest.raises(OAuthTransportError) as wrong_cap:
        await transport.authorize("a" * 32, "d" * 32, "openai.device_start")
    assert wrong_cap.value.code == "oauth_attempt_not_found"
    with pytest.raises(OAuthTransportError) as wrong_method:
        await transport.authorize("a" * 32, cap, "opencode.device_start")
    assert wrong_method.value.code == "oauth_attempt_not_found"

    await transport.revoke("a" * 32)
    with pytest.raises(OAuthTransportError):
        await transport.authorize("a" * 32, cap, "openai.device_start")

    cap = await transport.register(
        "e" * 32,
        "opencode",
        "device",
        7,
        "b" * 32,
        now + 30,
        session_token_hash="c" * 64,
    )
    now += 31
    with pytest.raises(OAuthTransportError):
        await transport.authorize("e" * 32, cap, "opencode.device_start")

    cap = await transport.register(
        "1" * 32,
        "opencode",
        "device",
        7,
        "b" * 32,
        now + 30,
        session_token_hash="c" * 64,
    )
    user_binding = await transport.authorize("1" * 32, cap, "opencode.user")
    with pytest.raises(OAuthTransportError) as parallel_org_lookup:
        await transport.authorize("1" * 32, cap, "opencode.orgs")
    assert parallel_org_lookup.value.code == "oauth_attempt_not_found"
    await transport.release(user_binding)
    org_binding = await transport.authorize("1" * 32, cap, "opencode.orgs")
    await transport.release(org_binding)


@_async_test
async def test_oauth_transport_uses_only_fixed_protocol_destinations_and_fields():
    calls: list[tuple[str, str, dict[str, str], bytes]] = []
    responses = [
        _response(
            {
                "device_auth_id": "device-1",
                "user_code": "WXYZ-1234",
                "interval": "5",
                "verification_uri": "https://auth.openai.com/codex/device",
            }
        ),
        _response({}, 403),
        _response({"authorization_code": "auth-code", "code_verifier": "verifier"}),
        _response(
            {
                "id_token": "id-token",
                "access_token": "access",
                "refresh_token": "refresh",
                "token_type": "Bearer",
                "scope": "openid profile",
            }
        ),
        _response(
            {
                "device_code": "device-2",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://opencode.ai/console/device",
                "verification_uri_complete": (
                    "/console/device?client_id=opencode-cli&user_code=ABCD-EFGH"
                ),
                "expires_in": 600,
                "interval": 5,
            }
        ),
        _response({"error": "authorization_pending"}, 400),
        _response(
            {
                "access_token": "op-access",
                "refresh_token": "op-refresh",
                "expires_in": 3600,
                "token_type": "Bearer",
            }
        ),
        _response({"id": "user-1", "email": "user@example.net"}),
        _response([{"id": "org-1", "name": "Research", "description": "Ignored metadata"}]),
    ]

    async def fake_request(url: str, *, method: str, headers, body=b"", **_options):
        calls.append((url, method, dict(headers), body))
        return responses.pop(0)

    transport = OAuthTransport(request=fake_request)
    assert await transport.perform("openai.device_start", {}) == {
        "device_auth_id": "device-1",
        "user_code": "WXYZ-1234",
        "interval": "5",
    }
    assert await transport.perform(
        "openai.device_poll", {"device_auth_id": "device-1", "user_code": "WXYZ-1234"}
    ) == {"status": "pending"}
    assert await transport.perform(
        "openai.device_poll", {"device_auth_id": "device-1", "user_code": "WXYZ-1234"}
    ) == {
        "status": "authorized",
        "authorization_code": "auth-code",
        "code_verifier": "verifier",
    }
    assert await transport.perform(
        "openai.token_exchange",
        {
            "code": "auth-code",
            "redirect_uri": "http://localhost:1455/auth/callback",
            "code_verifier": "verifier",
        },
    ) == {"id_token": "id-token", "access_token": "access", "refresh_token": "refresh"}
    assert await transport.perform("opencode.device_start", {}) == {
        "device_code": "device-2",
        "user_code": "ABCD-EFGH",
        "verification_uri_complete": "https://opencode.ai/console/device?client_id=opencode-cli&user_code=ABCD-EFGH",
        "expires_in": 600,
        "interval": 5,
    }
    assert await transport.perform("opencode.device_poll", {"device_code": "device-2"}) == {
        "error": "authorization_pending"
    }
    assert await transport.perform("opencode.device_poll", {"device_code": "device-2"}) == {
        "access_token": "op-access",
        "refresh_token": "op-refresh",
        "expires_in": 3600,
    }
    assert await transport.perform("opencode.user", {"access_token": "op-access"}) == {
        "id": "user-1",
        "email": "user@example.net",
    }
    assert await transport.perform("opencode.orgs", {"access_token": "op-access"}) == [
        {"id": "org-1", "name": "Research"}
    ]
    assert responses == []
    assert [call[0] for call in calls] == [
        "https://auth.openai.com/api/accounts/deviceauth/usercode",
        "https://auth.openai.com/api/accounts/deviceauth/token",
        "https://auth.openai.com/api/accounts/deviceauth/token",
        "https://auth.openai.com/oauth/token",
        "https://opencode.ai/console/auth/device/code",
        "https://opencode.ai/console/auth/device/token",
        "https://opencode.ai/console/auth/device/token",
        "https://opencode.ai/console/api/user",
        "https://opencode.ai/console/api/orgs",
    ]
    assert calls[0][2] == {"content-type": "application/json"}
    assert json.loads(calls[0][3]) == {"client_id": "app_EMoamEEZ73f0CkXaXp7hrann"}
    assert parse_qs(calls[3][3].decode()) == {
        "grant_type": ["authorization_code"],
        "code": ["auth-code"],
        "redirect_uri": ["http://localhost:1455/auth/callback"],
        "client_id": ["app_EMoamEEZ73f0CkXaXp7hrann"],
        "code_verifier": ["verifier"],
    }
    assert calls[7][2] == {"authorization": "Bearer op-access"}
    assert calls[8][2] == {"authorization": "Bearer op-access"}


@_async_test
async def test_oauth_transport_rejects_widened_inputs_redirect_hosts_and_private_failures():
    calls = 0

    async def fake_request(_url: str, **_options):
        nonlocal calls
        calls += 1
        return _response(
            {
                "device_code": "code",
                "user_code": "user",
                "verification_uri_complete": "/console/device?client_id=evil&user_code=user",
                "expires_in": 600,
                "interval": 5,
            }
        )

    transport = OAuthTransport(request=fake_request)
    with pytest.raises(OAuthTransportError) as widened:
        await transport.perform("openai.device_start", {"url": "https://attacker.example"})
    assert widened.value.code == "oauth_request_invalid"
    assert calls == 0

    with pytest.raises(OAuthTransportError) as redirect:
        await transport.perform("opencode.device_start", {})
    assert redirect.value.code == "oauth_response_invalid"
    assert calls == 1


@_async_test
async def test_opencode_verification_uri_resolves_only_the_fixed_console_path():
    invalid_values = (
        "//attacker.example/console/device?client_id=opencode-cli&user_code=ABCD",
        "/console/other?client_id=opencode-cli&user_code=ABCD",
        "/console/device?client_id=opencode-cli&user_code=ABCD&extra=1",
        "https://opencode.ai/console/device?client_id=opencode-cli&user_code=ABCD#fragment",
    )
    for verification_uri in invalid_values:

        async def fake_request(_url: str, *, _verification_uri: str = verification_uri, **_options):
            return _response(
                {
                    "device_code": "device",
                    "user_code": "ABCD",
                    "verification_uri_complete": _verification_uri,
                    "expires_in": 600,
                    "interval": 5,
                }
            )

        with pytest.raises(OAuthTransportError) as rejected:
            await OAuthTransport(request=fake_request).perform("opencode.device_start", {})
        assert rejected.value.code == "oauth_response_invalid"


@_async_test
async def test_openai_headless_exchange_accepts_only_the_pinned_device_redirect():
    calls: list[tuple[str, bytes]] = []

    async def fake_request(url: str, *, body=b"", **_options):
        calls.append((url, body))
        return _response(
            {
                "id_token": "id-token",
                "access_token": "access",
                "refresh_token": "refresh",
            }
        )

    transport = OAuthTransport(request=fake_request)
    result = await transport.perform(
        "openai.token_exchange",
        {
            "code": "headless-code",
            "redirect_uri": "https://auth.openai.com/deviceauth/callback",
            "code_verifier": "verifier",
        },
    )
    assert result == {"id_token": "id-token", "access_token": "access", "refresh_token": "refresh"}
    assert calls[0][0] == "https://auth.openai.com/oauth/token"
    assert b"redirect_uri=https%3A%2F%2Fauth.openai.com%2Fdeviceauth%2Fcallback" in calls[0][1]

    with pytest.raises(OAuthTransportError) as widened_redirect:
        await transport.perform(
            "openai.token_exchange",
            {
                "code": "headless-code",
                "redirect_uri": "https://auth.openai.com.evil.test/deviceauth/callback",
                "code_verifier": "verifier",
            },
        )
    assert widened_redirect.value.code == "oauth_request_invalid"
    assert len(calls) == 1

    with pytest.raises(OAuthTransportError):
        await transport.perform(
            "openai.token_exchange",
            {
                "code": "code",
                "redirect_uri": "http://localhost:1456/auth/callback",
                "code_verifier": "verifier",
            },
        )
    assert len(calls) == 1


@_async_test
async def test_oauth_transport_rejects_duplicate_json_and_sanitizes_network_errors():
    async def duplicate(_url: str, **_options):
        return PublicHTTPResponse(
            200,
            {"content-type": "application/json"},
            b'{"device_auth_id":"a","device_auth_id":"b"}',
        )

    async def failure(_url: str, **_options):
        raise RuntimeError("synthetic secret must not be exposed")

    for fetch in (duplicate, failure):
        transport = OAuthTransport(request=fetch)
        with pytest.raises(OAuthTransportError) as failed:
            await transport.perform("openai.device_start", {})
        assert failed.value.code in {"oauth_response_invalid", "oauth_provider_unavailable"}
        assert "synthetic secret" not in str(failed.value)
