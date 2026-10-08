"""Fixed, attempt-bound egress for the two reviewed native OAuth integrations."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import re
import secrets
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from stock_probs.assistant.net import (
    PublicHTTPError,
    PublicHTTPResponse,
    RequestAuthorizationCheck,
    request_public_https,
)

_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_TOKEN_HASH = re.compile(r"^[0-9a-f]{64}$")
_ATTEMPT_ID = re.compile(r"^[0-9a-f]{32}$")
_CAPABILITY = re.compile(r"^[0-9a-f]{32}$")
_MAX_ATTEMPTS = 32
_MAX_ATTEMPT_SECONDS = 600.0
_MAX_OPERATIONS_PER_ATTEMPT = 256
_OPERATION_TIMEOUT_SECONDS = 15.0
_MAX_RESPONSE_BYTES = 65_536
_MAX_VALUE_BYTES = 16_384

_OPENAI_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
_OPENCODE_CLIENT_ID = "opencode-cli"
_OPENAI_ROOT = "https://auth.openai.com"
_OPENAI_DEVICE_REDIRECT = "https://auth.openai.com/deviceauth/callback"
_OPENCODE_ROOT = "https://opencode.ai/console"
_OPENCODE_VERIFICATION_BASE = f"{_OPENCODE_ROOT}/"

_ALLOWED_OPERATIONS: dict[tuple[str, str], frozenset[str]] = {
    ("openai", "chatgpt-browser"): frozenset({"openai.token_exchange"}),
    ("openai", "chatgpt-headless"): frozenset(
        {"openai.device_start", "openai.device_poll", "openai.token_exchange"}
    ),
    ("opencode", "device"): frozenset(
        {"opencode.device_start", "opencode.device_poll", "opencode.user", "opencode.orgs"}
    ),
}


class OAuthTransportError(Exception):
    """Closed internal failure categories; never includes provider response text."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(slots=True)
class _AttemptBinding:
    attempt_id: str
    capability_hash: bytes = field(repr=False)
    integration_id: str
    method_id: str
    owner_id: int
    session_id: str
    session_token_hash: str = field(repr=False)
    expires_at: float
    operation_count: int = 0
    in_flight: int = 0


class OAuthTransport:
    """Keep capabilities in app memory and expose only fixed HTTPS operations."""

    def __init__(
        self,
        *,
        request: Callable[..., Awaitable[PublicHTTPResponse]] = request_public_https,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._request = request
        self._clock = clock
        self._attempts: dict[str, _AttemptBinding] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        attempt_id: str,
        integration_id: str,
        method_id: str,
        owner_id: int,
        session_id: str,
        expires_at: float,
        *,
        session_token_hash: str,
    ) -> str:
        """Register one opaque native capability and keep its hashed session binding."""

        now = self._clock()
        if (
            not isinstance(attempt_id, str)
            or _ATTEMPT_ID.fullmatch(attempt_id) is None
            or (integration_id, method_id) not in _ALLOWED_OPERATIONS
            or type(owner_id) is not int
            or owner_id < 1
            or not isinstance(session_id, str)
            or _ATTEMPT_ID.fullmatch(session_id) is None
            or not isinstance(session_token_hash, str)
            or _TOKEN_HASH.fullmatch(session_token_hash) is None
            or type(expires_at) not in {int, float}
            or not math.isfinite(float(expires_at))
            or not now < float(expires_at) <= now + _MAX_ATTEMPT_SECONDS
        ):
            raise OAuthTransportError("oauth_attempt_invalid")
        async with self._lock:
            self._remove_expired(now)
            if attempt_id in self._attempts or len(self._attempts) >= _MAX_ATTEMPTS:
                raise OAuthTransportError("oauth_unavailable")
            capability = secrets.token_hex(16)
            self._attempts[attempt_id] = _AttemptBinding(
                attempt_id=attempt_id,
                capability_hash=hashlib.sha256(capability.encode("ascii")).digest(),
                integration_id=integration_id,
                method_id=method_id,
                owner_id=owner_id,
                session_id=session_id,
                session_token_hash=session_token_hash,
                expires_at=float(expires_at),
            )
            return capability

    async def revoke(self, attempt_id: str) -> None:
        """Forget a capability and its session hash without retaining a tombstone."""

        if isinstance(attempt_id, str) and _ATTEMPT_ID.fullmatch(attempt_id):
            async with self._lock:
                self._attempts.pop(attempt_id, None)

    async def authorize(self, attempt_id: str, capability: str, operation: str) -> _AttemptBinding:
        """Validate capability, method scope, expiry, and bounded request count."""

        if (
            not isinstance(attempt_id, str)
            or _ATTEMPT_ID.fullmatch(attempt_id) is None
            or not isinstance(capability, str)
            or _CAPABILITY.fullmatch(capability) is None
            or not isinstance(operation, str)
        ):
            raise OAuthTransportError("oauth_attempt_not_found")
        async with self._lock:
            self._remove_expired(self._clock())
            binding = self._attempts.get(attempt_id)
            if (
                binding is None
                or not hmac.compare_digest(
                    binding.capability_hash, hashlib.sha256(capability.encode("ascii")).digest()
                )
                or operation
                not in _ALLOWED_OPERATIONS.get(
                    (binding.integration_id, binding.method_id), frozenset()
                )
                or binding.operation_count >= _MAX_OPERATIONS_PER_ATTEMPT
                or binding.in_flight >= 1
            ):
                raise OAuthTransportError("oauth_attempt_not_found")
            binding.operation_count += 1
            binding.in_flight += 1
            return binding

    async def is_current(self, binding: _AttemptBinding) -> bool:
        """Confirm cancellation or expiry did not race a bounded upstream operation."""

        async with self._lock:
            self._remove_expired(self._clock())
            return self._attempts.get(binding.attempt_id) is binding

    async def release(self, binding: _AttemptBinding) -> None:
        async with self._lock:
            current = self._attempts.get(binding.attempt_id)
            if current is binding:
                current.in_flight = max(0, current.in_flight - 1)

    async def perform(
        self,
        operation: str,
        value: Mapping[str, object],
        *,
        authorization_check: RequestAuthorizationCheck,
    ) -> dict[str, object] | list[dict[str, str]]:
        """Execute one source-compatible OAuth operation against a fixed HTTPS destination."""

        if operation == "openai.device_start":
            _exact(value, set())
            response = await self._json_request(
                f"{_OPENAI_ROOT}/api/accounts/deviceauth/usercode",
                {"client_id": _OPENAI_CLIENT_ID},
                authorization_check=authorization_check,
            )
            return _openai_device_start(response)

        if operation == "openai.device_poll":
            _exact(value, {"device_auth_id", "user_code"})
            device_auth_id = _string(value, "device_auth_id", 4096)
            user_code = _string(value, "user_code", 512)
            response = await self._json_request(
                f"{_OPENAI_ROOT}/api/accounts/deviceauth/token",
                {
                    "device_auth_id": device_auth_id,
                    "user_code": user_code,
                },
                accepted_statuses={200, 403, 404},
                authorization_check=authorization_check,
            )
            if response.status_code in {403, 404}:
                return {"status": "pending"}
            result = _object_response(response)
            if not {"authorization_code", "code_verifier"} <= set(result):
                raise OAuthTransportError("oauth_response_invalid")
            return {
                "status": "authorized",
                "authorization_code": _string(result, "authorization_code", 16_384),
                "code_verifier": _string(result, "code_verifier", 16_384),
            }

        if operation == "openai.token_exchange":
            _exact(value, {"code", "redirect_uri", "code_verifier"})
            redirect_uri = _string(value, "redirect_uri", 512)
            if redirect_uri not in {
                "http://localhost:1455/auth/callback",
                "http://localhost:1457/auth/callback",
                _OPENAI_DEVICE_REDIRECT,
            }:
                raise OAuthTransportError("oauth_request_invalid")
            form = urlencode(
                {
                    "grant_type": "authorization_code",
                    "code": _string(value, "code", 4096),
                    "redirect_uri": redirect_uri,
                    "client_id": _OPENAI_CLIENT_ID,
                    "code_verifier": _string(value, "code_verifier", 4096),
                }
            ).encode("ascii")
            response = await self._checked_request(
                f"{_OPENAI_ROOT}/oauth/token",
                method="POST",
                headers={"content-type": "application/x-www-form-urlencoded"},
                body=form,
                timeout_seconds=_OPERATION_TIMEOUT_SECONDS,
                max_response_bytes=_MAX_RESPONSE_BYTES,
                authorization_check=authorization_check,
            )
            return _token_response(response, openai=True)

        if operation == "opencode.device_start":
            _exact(value, set())
            response = await self._json_request(
                f"{_OPENCODE_ROOT}/auth/device/code",
                {"client_id": _OPENCODE_CLIENT_ID, "supports_org_scope": True},
                authorization_check=authorization_check,
            )
            result = _object_response(response)
            verification = _normalized_opencode_verification_uri(
                _string(result, "verification_uri_complete", 2048)
            )
            if verification is None:
                raise OAuthTransportError("oauth_response_invalid")
            return {
                "device_code": _string(result, "device_code", 4096),
                "user_code": _string(result, "user_code", 512),
                "verification_uri_complete": verification,
                "expires_in": _positive_int(result, "expires_in", 3600),
                "interval": _positive_int(result, "interval", 60),
            }

        if operation == "opencode.device_poll":
            _exact(value, {"device_code"})
            device_code = _string(value, "device_code", 4096)
            response = await self._json_request(
                f"{_OPENCODE_ROOT}/auth/device/token",
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": device_code,
                    "client_id": _OPENCODE_CLIENT_ID,
                },
                accepted_statuses={200, 400},
                authorization_check=authorization_check,
            )
            result = _json_value(response.content)
            if not isinstance(result, Mapping):
                raise OAuthTransportError("oauth_response_invalid")
            if response.status_code == 400:
                error = result.get("error")
                if error not in {"authorization_pending", "slow_down"}:
                    raise OAuthTransportError("oauth_provider_unavailable")
                return {"error": error}
            return _opencode_token_response(result)

        if operation == "opencode.user":
            _exact(value, {"access_token"})
            response = await self._checked_request(
                f"{_OPENCODE_ROOT}/api/user",
                method="GET",
                headers={"authorization": "Bearer " + _string(value, "access_token", 16_384)},
                timeout_seconds=_OPERATION_TIMEOUT_SECONDS,
                max_response_bytes=_MAX_RESPONSE_BYTES,
                authorization_check=authorization_check,
            )
            result = _object_response(response)
            if response.status_code != 200:
                raise OAuthTransportError("oauth_provider_unavailable")
            return {"id": _string(result, "id", 1024), "email": _string(result, "email", 1024)}

        if operation == "opencode.orgs":
            _exact(value, {"access_token"})
            response = await self._checked_request(
                f"{_OPENCODE_ROOT}/api/orgs",
                method="GET",
                headers={"authorization": "Bearer " + _string(value, "access_token", 16_384)},
                timeout_seconds=_OPERATION_TIMEOUT_SECONDS,
                max_response_bytes=_MAX_RESPONSE_BYTES,
                authorization_check=authorization_check,
            )
            if response.status_code != 200:
                raise OAuthTransportError("oauth_provider_unavailable")
            parsed = _json_value(response.content)
            if not isinstance(parsed, list) or len(parsed) > 128:
                raise OAuthTransportError("oauth_response_invalid")
            result: list[dict[str, str]] = []
            for row in parsed:
                if not isinstance(row, Mapping):
                    raise OAuthTransportError("oauth_response_invalid")
                result.append({"id": _string(row, "id", 1024), "name": _string(row, "name", 1024)})
            return result

        raise OAuthTransportError("oauth_operation_invalid")

    async def _json_request(
        self,
        url: str,
        payload: Mapping[str, object],
        *,
        authorization_check: RequestAuthorizationCheck,
        accepted_statuses: set[int] | None = None,
    ) -> PublicHTTPResponse:
        body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        response = await self._checked_request(
            url,
            method="POST",
            headers={"content-type": "application/json"},
            body=body,
            timeout_seconds=_OPERATION_TIMEOUT_SECONDS,
            max_response_bytes=_MAX_RESPONSE_BYTES,
            authorization_check=authorization_check,
        )
        if response.status_code not in (accepted_statuses or {200}):
            raise OAuthTransportError("oauth_provider_unavailable")
        return response

    async def _checked_request(
        self,
        url: str,
        *,
        authorization_check: RequestAuthorizationCheck,
        **options: object,
    ) -> PublicHTTPResponse:
        """Hide transport exceptions while allowing task cancellation to propagate."""

        if not callable(authorization_check):
            raise OAuthTransportError("oauth_authorization_required")
        try:
            response = await self._request(url, authorization_check=authorization_check, **options)
        except PublicHTTPError as exc:
            if exc.code in {
                "provider_authorization_required",
                "provider_authorization_timeout",
            }:
                raise OAuthTransportError("oauth_authorization_required") from None
            raise OAuthTransportError("oauth_provider_unavailable") from exc
        except Exception as exc:
            raise OAuthTransportError("oauth_provider_unavailable") from exc
        if not isinstance(response, PublicHTTPResponse):
            raise OAuthTransportError("oauth_response_invalid")
        return response

    def _remove_expired(self, now: float) -> None:
        for attempt_id, binding in tuple(self._attempts.items()):
            if binding.expires_at <= now:
                del self._attempts[attempt_id]


def _exact(value: Mapping[str, object], names: set[str]) -> None:
    if set(value) != names:
        raise OAuthTransportError("oauth_request_invalid")


def _string(value: Mapping[str, object], name: str, max_bytes: int) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise OAuthTransportError("oauth_request_invalid")
    try:
        encoded_length = len(item.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise OAuthTransportError("oauth_request_invalid") from exc
    if encoded_length > min(max_bytes, _MAX_VALUE_BYTES) or any(
        ord(character) < 0x20 or ord(character) == 0x7F for character in item
    ):
        raise OAuthTransportError("oauth_request_invalid")
    return item


def _object_response(response: PublicHTTPResponse) -> Mapping[str, object]:
    if response.status_code != 200:
        raise OAuthTransportError("oauth_provider_unavailable")
    value = _json_value(response.content)
    if not isinstance(value, Mapping):
        raise OAuthTransportError("oauth_response_invalid")
    return value


def _json_value(raw: bytes) -> object:
    if not isinstance(raw, bytes) or len(raw) > _MAX_RESPONSE_BYTES:
        raise OAuthTransportError("oauth_response_invalid")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        return json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("constant")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise OAuthTransportError("oauth_response_invalid") from exc


def _positive_int(value: Mapping[str, object], name: str, maximum: int) -> int:
    result = value.get(name)
    if type(result) is not int or not 1 <= result <= maximum:
        raise OAuthTransportError("oauth_response_invalid")
    return result


def _openai_device_start(response: PublicHTTPResponse) -> dict[str, object]:
    value = _object_response(response)
    if not {"device_auth_id", "user_code", "interval"} <= set(value):
        raise OAuthTransportError("oauth_response_invalid")
    return {
        "device_auth_id": _string(value, "device_auth_id", 4096),
        "user_code": _string(value, "user_code", 512),
        "interval": _string(value, "interval", 16),
    }


def _token_response(response: PublicHTTPResponse, *, openai: bool) -> dict[str, object]:
    value = _object_response(response)
    required = (
        {"access_token", "refresh_token", "id_token"}
        if openai
        else {
            "access_token",
            "refresh_token",
        }
    )
    if not required <= set(value):
        raise OAuthTransportError("oauth_response_invalid")
    result: dict[str, object] = {
        "access_token": _string(value, "access_token", 16_384),
        "refresh_token": _string(value, "refresh_token", 16_384),
    }
    if openai:
        result["id_token"] = _string(value, "id_token", 16_384)
    if "expires_in" in value:
        result["expires_in"] = _positive_int(value, "expires_in", 31_536_000)
    return result


def _opencode_token_response(value: Mapping[str, object]) -> dict[str, object]:
    if not {"access_token", "refresh_token", "expires_in"} <= set(value):
        raise OAuthTransportError("oauth_response_invalid")
    result: dict[str, object] = {
        "access_token": _string(value, "access_token", 16_384),
        "refresh_token": _string(value, "refresh_token", 16_384),
        "expires_in": _positive_int(value, "expires_in", 31_536_000),
    }
    org_id = value.get("org_id")
    if "org_id" in value:
        if org_id is not None and not isinstance(org_id, str):
            raise OAuthTransportError("oauth_response_invalid")
        if isinstance(org_id, str):
            try:
                if len(org_id.encode("utf-8")) > 1024:
                    raise OAuthTransportError("oauth_response_invalid")
            except UnicodeEncodeError as exc:
                raise OAuthTransportError("oauth_response_invalid") from exc
        result["org_id"] = org_id
    return result


def _normalized_opencode_verification_uri(value: str) -> str | None:
    """Resolve native relative links against the fixed OpenCode console origin."""
    try:
        if any(ord(character) < 0x20 or character == "\\" for character in value):
            return None
        original = urlsplit(value)
        if original.scheme or original.netloc:
            if (
                original.scheme != "https"
                or original.hostname != "opencode.ai"
                or original.port not in {None, 443}
                or original.username is not None
                or original.password is not None
            ):
                return None
            resolved = value
        else:
            if not value.startswith("/") or value.startswith("//"):
                return None
            resolved = urljoin(_OPENCODE_VERIFICATION_BASE, value)
        parsed = urlsplit(resolved)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "opencode.ai"
            or parsed.port not in {None, 443}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path != "/console/device"
            or parsed.fragment
        ):
            return None
        pairs = parse_qsl(
            parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=2
        )
        fields = dict(pairs)
        if (
            len(pairs) != 2
            or len(fields) != 2
            or fields.get("client_id") != _OPENCODE_CLIENT_ID
            or re.fullmatch(r"[A-Za-z0-9-]{1,256}", fields.get("user_code", "")) is None
        ):
            return None
        return urlunsplit(("https", "opencode.ai", "/console/device", urlencode(fields), ""))
    except ValueError:
        return None


__all__ = ["OAuthTransport", "OAuthTransportError"]
