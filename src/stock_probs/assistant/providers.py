"""Typed provider administration and an encrypted write-only credential vault."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import inspect
import ipaddress
import json
import math
import os
import re
import secrets
import stat
import tempfile
import threading
import time
import unicodedata
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from stock_probs.assistant.model_catalog import (
    AssistantModel,
    AssistantModelCatalog,
    ModelCatalogAuthorizationError,
    known_model_exclusion_reason,
)
from stock_probs.assistant.native_provider_adapters import (
    NATIVE_WEBFETCH_DESCRIPTION_SHA256,
    NativeAdapterDescriptor,
    NativeConfiguredModel,
    NativeProviderDescriptorError,
    native_output_token_budget,
    native_webfetch_schema,
    native_websearch_description_sha256,
    native_websearch_schema,
    project_gemini_tool_schema,
    project_opencode_console_models,
    resolve_native_adapter,
    validated_output_token_count,
)
from stock_probs.assistant.net import (
    PublicHTTPError,
    bind_stream_authorization,
    is_public_unicast,
    request_public_https,
    stream_public_https,
)
from stock_probs.assistant.search import MAX_SEARCH_QUERY_BYTES, validate_webfetch_url
from stock_probs.config import Settings, ensure_private_directory

_PROVIDER_ID = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}$")
_NATIVE_ZEN_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_NATIVE_ZEN_USER_AGENT_MAX = 256
_TOOL_CALL_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MAX_SECRET_BYTES = 4096
_MAX_METADATA_BYTES = 16_384
_MAX_VALIDATE_BYTES = 262_144
_MAX_PROXY_CHUNK_BYTES = 32 * 1024
_MODEL_POLICY_KEY = "_model_policy"
_OPENCODE_REVIEW_KEY = "_opencode_model_reviews"
_MAX_MODEL_POLICIES = 256
_MAX_POLICY_REVISION = 2_147_483_647
_MODEL_CACHE_SECONDS = 300.0
_MODEL_REFRESH_FAILURE_RETRY_SECONDS = 5.0
_MODEL_DISCOVERY_TIMEOUT_SECONDS = 7.0
_MODEL_DISCOVERY_PROVIDERS = frozenset({"openai", "anthropic", "google", "custom"})
_CUSTOM_DISCLOSURE_BYTES = 2000
_CUSTOM_BILLING_CLASSES = frozenset({"unknown", "free", "paid"})
_NATIVE_OAUTH_ATTEMPT_LIMIT = 32
_NATIVE_OAUTH_ATTEMPT_TTL_SECONDS = 600.0
_OAUTH_CREDENTIAL_FILE_LIMIT = 131_072
_OPENCODE_REVIEW_FILE_LIMIT = 1_048_576
_MAX_OPENCODE_REVIEW_ROWS = 256
_MAX_OPENCODE_MODELS_PER_OWNER = 128
_OPENCODE_CONFIG_URL = "https://opencode.ai/console/api/v2/config"
_OPENCODE_REFRESH_URL = "https://opencode.ai/console/auth/device/token"
_OPENCODE_CLIENT_ID = "opencode-cli"
_OPENCODE_TERMS_URL = "https://opencode.ai/terms"
_OPENCODE_DEFAULT_ENDPOINTS = {
    "openai-responses": "https://api.openai.com/v1",
    "anthropic-messages": "https://api.anthropic.com/v1",
    "google-generative-language": "https://generativelanguage.googleapis.com/v1beta",
}
_OPENCODE_TRAINING_POLICIES = frozenset({"unknown", "no_training", "training_possible"})
_OPENCODE_CONFIDENTIAL_POLICIES = frozenset({"unknown", "allowed", "prohibited"})
_KEY_CONTEXT = b"stock-probs assistant provider vault key v1"
_AAD_CONTEXT = b"stock-probs assistant provider credential v1:"
_OAUTH_AAD_CONTEXT = b"stock-probs assistant OAuth credential v1:"
_NATIVE_OAUTH_UI_METHODS: dict[tuple[str, str], tuple[str, str]] = {
    ("openai", "chatgpt-browser"): ("ChatGPT browser sign-in", "browser"),
    ("openai", "chatgpt-headless"): ("ChatGPT headless sign-in", "device"),
    ("opencode", "device"): ("OpenCode device sign-in", "device"),
}
_CHATGPT_OAUTH_METHODS = frozenset({"chatgpt-browser", "chatgpt-headless"})
_CHATGPT_REFRESH_URL = "https://auth.openai.com/oauth/token"
_CHATGPT_UPSTREAM_URL = "https://chatgpt.com/backend-api/codex/responses"
_CHATGPT_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
_OPENCODE_CLIENT_ID = "opencode-cli"
_NATIVE_SESSION_ID = re.compile(r"^ses[\x21-\x7e]{0,61}$")
_NATIVE_OPENCODE_SESSION_ID = re.compile(r"^ses_[0-9a-f]{12}[A-Za-z0-9]{14}$")
_NATIVE_PROJECT_ID_MAX = 128
_MAX_OAUTH_TOKEN_BYTES = 32_768


class ProviderUnavailable(Exception):
    """Safe non-secret provider operation error for public routes."""

    def __init__(self, code: str = "provider_unavailable") -> None:
        super().__init__(code)
        self.code = code


class CredentialRejected(Exception):
    """Safe credential rejection that never includes the submitted value."""

    def __init__(self, code: str = "credential_rejected") -> None:
        super().__init__(code)
        self.code = code


async def _stream_with_authorization(
    url: str,
    *,
    authorization_check: Callable[[], Awaitable[bool | None] | bool],
    **options: object,
) -> AsyncIterator[bytes]:
    """Run each bounded transport read with its provider's live authorization bound."""

    if not callable(authorization_check):
        raise CredentialRejected("oauth_authorization_required")

    async def check_transport_authorization() -> bool:
        result = authorization_check()
        if inspect.isawaitable(result):
            allowed = await result
            if allowed is not None and allowed is not True:
                raise CredentialRejected("oauth_authorization_required")
        elif result is not True:
            raise CredentialRejected("oauth_authorization_required")
        return True

    iterator = stream_public_https(url, **options).__aiter__()
    try:
        while True:
            with bind_stream_authorization(check_transport_authorization):
                try:
                    chunk = await anext(iterator)
                except StopAsyncIteration:
                    return
            yield chunk
    finally:
        with bind_stream_authorization(check_transport_authorization):
            await iterator.aclose()


@dataclass(frozen=True, slots=True)
class ProviderSummary:
    """Browser-safe provider settings; credential values and native auth data never escape."""

    provider_id: str
    display_name: str
    auth_methods: tuple[str, ...]
    selected_model_id: str | None
    selected_base_url: str | None
    credential_required: bool
    credential_configured: bool
    oauth_connected: bool
    connection_status: str
    terms_url: str | None
    native_provider_id: str
    adapter_id: str
    protocol: str
    supported_auth_methods: tuple[str, ...]
    endpoint_editable: bool
    credential_supported: bool
    validation_requires_credential: bool
    adapter_supported: bool
    unsupported_reason: str | None
    selected_terms_url: str | None
    selected_privacy_disclosure: str | None
    selected_billing_disclosure: str | None
    selected_billing_class: str | None
    selected_endpoint_policy_reviewed: bool

    def public_dict(self) -> dict[str, object]:
        """Return the closed provider summary contract used by the admin route."""

        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "auth_methods": list(self.auth_methods),
            "selected_model_id": self.selected_model_id,
            "selected_base_url": self.selected_base_url,
            "credential_required": self.credential_required,
            "credential_configured": self.credential_configured,
            "oauth_connected": self.oauth_connected,
            "connection_status": self.connection_status,
            "terms_url": self.terms_url,
            "native_provider_id": self.native_provider_id,
            "adapter_id": self.adapter_id,
            "protocol": self.protocol,
            "supported_auth_methods": list(self.supported_auth_methods),
            "endpoint_editable": self.endpoint_editable,
            "credential_supported": self.credential_supported,
            "validation_requires_credential": self.validation_requires_credential,
            "adapter_supported": self.adapter_supported,
            "unsupported_reason": self.unsupported_reason,
            "selected_terms_url": self.selected_terms_url,
            "selected_privacy_disclosure": self.selected_privacy_disclosure,
            "selected_billing_disclosure": self.selected_billing_disclosure,
            "selected_billing_class": self.selected_billing_class,
            "selected_endpoint_policy_reviewed": self.selected_endpoint_policy_reviewed,
        }


@dataclass(slots=True)
class _ManagedOAuthAttempt:
    """Ephemeral app-side OAuth state bound to one admin session."""

    attempt_id: str
    integration_id: str
    method_id: str
    owner_id: int
    session_id: str
    mode: str
    expires_at: float
    status: str
    authorization_url: str | None
    instructions: str | None
    callback_state: str | None = field(default=None, repr=False, compare=False)
    transport_capability: str | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class _OpenCodeModelRecord:
    """Owner-scoped Console model snapshot; no native overlays or credentials are retained."""

    owner_id: int
    model: AssistantModel
    config_provider_id: str
    config_model_id: str
    native_model_id: str
    adapter: NativeAdapterDescriptor
    package_id: str
    endpoint: str
    config_fingerprint: str


class AssistantProviderManager:
    """Manage only fixed provider adapters and encrypted durable credentials."""

    def __init__(
        self,
        settings: Settings,
        catalog: AssistantModelCatalog | None = None,
        *,
        vault_dir: Path | None = None,
        runtime: Any | None = None,
        clock: Any = time.monotonic,
    ) -> None:
        self.settings = settings
        self.catalog = catalog
        self.vault_dir = vault_dir or (settings.data_dir / "assistant-vault")
        self.runtime = runtime
        self._clock = clock
        self._inventory_lock = asyncio.Lock()
        self._provider_models: dict[str, tuple[AssistantModel, ...]] = {}
        self._provider_inventory_loaded_at: dict[str, float] = {}
        self._provider_inventory_retry_at: dict[str, float] = {}
        self._provider_inventory_status: dict[str, str] = {}
        self._opencode_models: dict[int, tuple[_OpenCodeModelRecord, ...]] = {}
        self._opencode_loaded_at: dict[int, float] = {}
        self._opencode_unsupported_counts: dict[int, int] = {}
        self._opencode_refresh_lock = asyncio.Lock()
        self._oauth_lock = asyncio.Lock()
        self._oauth_refresh_lock = asyncio.Lock()
        self._oauth_attempts: dict[str, _ManagedOAuthAttempt] = {}
        self._oauth_transport_register: Callable[..., object] | None = None
        self._oauth_transport_revoke: Callable[..., object] | None = None
        # Endpoint syntax is checked here; actual requests pin and revalidate DNS at connect time.
        self._lock = threading.RLock()
        self._config_path = self.vault_dir / "providers.json"
        self._definitions = self._load_definitions()
        self._publish_provider_models()

    def attach_runtime(self, runtime: Any) -> None:
        """Attach the one supervised OpenCode server after constructing both facades."""

        self.runtime = runtime

    def attach_oauth_transport(
        self,
        register: Callable[..., object],
        revoke: Callable[..., object],
    ) -> None:
        """Attach the internal OAuth egress capability registry."""

        if not callable(register) or not callable(revoke):
            raise TypeError("OAuth transport callbacks must be callable")
        self._oauth_transport_register = register
        self._oauth_transport_revoke = revoke

    async def list_native_oauth_methods(self) -> tuple[dict[str, object], ...]:
        """List fixed UI methods intersected with bounded native discovery.

        ChatGPT credentials can use the fixed, owner-bound Responses bridge. OpenCode's
        device credential remains a separate provider protocol and is not model-enabled.
        """

        lister = getattr(self.runtime, "list_native_integrations", None)
        if not callable(lister):
            raise ProviderUnavailable("oauth_unavailable")
        try:
            integrations = await lister()
        except Exception as exc:
            raise ProviderUnavailable("oauth_unavailable") from exc
        if not isinstance(integrations, list) or len(integrations) > 512:
            raise ProviderUnavailable("oauth_unavailable")

        available: set[tuple[str, str]] = set()
        for integration in integrations:
            if not isinstance(integration, Mapping):
                raise ProviderUnavailable("oauth_unavailable")
            integration_id = integration.get("integration_id")
            methods = integration.get("methods")
            if (
                not isinstance(integration_id, str)
                or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", integration_id)
                or not isinstance(methods, list)
                or len(methods) > 32
            ):
                raise ProviderUnavailable("oauth_unavailable")
            for method in methods:
                if not isinstance(method, Mapping):
                    continue
                method_id = method.get("method_id")
                if (
                    isinstance(method_id, str)
                    and (integration_id, method_id) in _NATIVE_OAUTH_UI_METHODS
                    and method.get("kind") == "oauth"
                ):
                    available.add((integration_id, method_id))

        return tuple(
            {
                "integration_id": integration_id,
                "method_id": method_id,
                "label": label,
                "mode": mode,
                "connection_status": "available",
                "connection_supported": True,
                "model_access_supported": integration_id == "openai",
                "availability_reason": (
                    None if integration_id == "openai" else "oauth_proxy_pending"
                ),
            }
            for (integration_id, method_id), (label, mode) in sorted(
                _NATIVE_OAUTH_UI_METHODS.items()
            )
            if (integration_id, method_id) in available
        )

    async def list_native_oauth_attempts(
        self, *, owner_id: int, session_id: str
    ) -> tuple[dict[str, object], ...]:
        """Return only active attempts belonging to this exact app session."""

        self._validate_oauth_actor(owner_id, session_id)
        async with self._oauth_lock:
            await self._expire_managed_oauth_attempts()
            attempts = tuple(
                attempt
                for attempt in self._oauth_attempts.values()
                if attempt.owner_id == owner_id
                and secrets.compare_digest(attempt.session_id, session_id)
                and attempt.status not in {"cancelled", "expired", "denied"}
            )
            return tuple(self._managed_oauth_public(attempt) for attempt in attempts)

    async def list_native_oauth_connections(
        self, *, owner_id: int
    ) -> tuple[dict[str, object], ...]:
        """List encrypted owner connections without returning credential material."""

        self._validate_oauth_owner(owner_id)
        output: list[dict[str, object]] = []
        async with self._oauth_lock:
            with self._lock:
                for integration_id, method_id in sorted(_NATIVE_OAUTH_UI_METHODS):
                    credential = self._read_oauth_credential(integration_id, method_id, owner_id)
                    if credential is None:
                        continue
                    if (
                        credential.get("type") != "oauth"
                        or credential.get("methodID") != method_id
                        or not isinstance(credential.get("access"), str)
                        or not isinstance(credential.get("refresh"), str)
                    ):
                        raise ProviderUnavailable("oauth_vault_unavailable")
                    supported = integration_id == "openai"
                    output.append(
                        {
                            "integration_id": integration_id,
                            "method_id": method_id,
                            "status": "connected",
                            "model_access_supported": supported,
                            "availability_reason": None if supported else "oauth_proxy_pending",
                        }
                    )
                    del credential
        return tuple(output)

    @staticmethod
    def _validate_oauth_owner(owner_id: int) -> None:
        if type(owner_id) is not int or owner_id < 1:
            raise CredentialRejected("oauth_connection_not_found")

    async def begin_native_oauth(
        self,
        integration_id: str,
        method_id: str,
        *,
        owner_id: int,
        session_id: str,
        session_token_hash: str,
    ) -> dict[str, object]:
        """Start one discovered native OAuth flow without exposing its native attempt ID."""

        self._validate_oauth_actor(owner_id, session_id)
        if (
            not isinstance(session_token_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", session_token_hash) is None
        ):
            raise CredentialRejected("oauth_attempt_not_found")
        if (integration_id, method_id) not in _NATIVE_OAUTH_UI_METHODS:
            raise CredentialRejected("oauth_method_unavailable")
        runtime_begin = getattr(self.runtime, "begin_native_oauth", None)
        if not callable(runtime_begin):
            raise ProviderUnavailable("oauth_unavailable")
        register_transport = self._oauth_transport_register
        if not callable(register_transport) or not callable(self._oauth_transport_revoke):
            raise ProviderUnavailable("oauth_unavailable")
        methods = await self.list_native_oauth_methods()
        if not any(
            row["integration_id"] == integration_id and row["method_id"] == method_id
            for row in methods
        ):
            raise CredentialRejected("oauth_method_unavailable")

        async with self._oauth_lock:
            await self._expire_managed_oauth_attempts()
            if len(self._oauth_attempts) >= _NATIVE_OAUTH_ATTEMPT_LIMIT:
                raise ProviderUnavailable("oauth_unavailable")
            if integration_id == "openai":
                with self._lock:
                    if any(
                        self._read_oauth_credential("openai", method, owner_id) is not None
                        for method in _CHATGPT_OAUTH_METHODS
                    ):
                        raise CredentialRejected("oauth_connection_already_exists")
            attempt_id = secrets.token_hex(16)
            _label, listed_mode = _NATIVE_OAUTH_UI_METHODS[(integration_id, method_id)]
            attempt = _ManagedOAuthAttempt(
                attempt_id=attempt_id,
                integration_id=integration_id,
                method_id=method_id,
                owner_id=owner_id,
                session_id=session_id,
                mode=listed_mode,
                expires_at=time.time() + _NATIVE_OAUTH_ATTEMPT_TTL_SECONDS,
                status="starting",
                authorization_url=None,
                instructions=None,
            )
            self._oauth_attempts[attempt_id] = attempt
            try:
                capability = register_transport(
                    attempt_id,
                    integration_id,
                    method_id,
                    owner_id,
                    session_id,
                    attempt.expires_at,
                    session_token_hash=session_token_hash,
                )
                if inspect.isawaitable(capability):
                    capability = await capability
                if (
                    not isinstance(capability, str)
                    or re.fullmatch(r"[0-9a-f]{32}", capability) is None
                ):
                    raise ProviderUnavailable("oauth_unavailable")
                attempt.transport_capability = capability
                launch = await runtime_begin(
                    integration_id,
                    method_id,
                    attempt_id=attempt_id,
                    owner_id=owner_id,
                    session_id=session_id,
                    capability=capability,
                )
                if not isinstance(launch, Mapping):
                    raise ProviderUnavailable("oauth_unavailable")
                native_mode = launch.get("mode")
                expires_at = launch.get("expires_at")
                url = launch.get("url")
                instructions = launch.get("instructions")
                try:
                    url_size = len(url.encode("utf-8")) if isinstance(url, str) else 0
                    instructions_size = (
                        len(instructions.encode("utf-8")) if isinstance(instructions, str) else 0
                    )
                except UnicodeEncodeError:
                    raise ProviderUnavailable("oauth_unavailable") from None
                if (
                    native_mode not in {"auto", "code"}
                    or type(expires_at) not in {int, float}
                    or not time.time() < float(expires_at) <= time.time() + 600.0
                    or not isinstance(url, str)
                    or not 1 <= url_size <= 4096
                    or any(unicodedata.category(char).startswith("C") for char in url)
                    or not isinstance(instructions, str)
                    or instructions_size > 2048
                    or any(unicodedata.category(char).startswith("C") for char in instructions)
                ):
                    raise ProviderUnavailable("oauth_unavailable")
                callback_state = self._validate_native_oauth_launch(
                    integration_id, method_id, url, instructions
                )
                if native_mode != "auto":
                    raise ProviderUnavailable("oauth_unavailable")
                attempt.mode = "code" if native_mode == "code" else listed_mode
                attempt.expires_at = float(expires_at)
                attempt.authorization_url = url
                attempt.instructions = instructions
                attempt.callback_state = callback_state
                attempt.status = "pending"
                return self._managed_oauth_public(attempt)
            except BaseException:
                cancel = getattr(self.runtime, "cancel_native_oauth", None)
                if callable(cancel):
                    with suppress(Exception):
                        await cancel(
                            integration_id,
                            attempt_id,
                            owner_id=owner_id,
                            session_id=session_id,
                        )
                with suppress(Exception):
                    await self._revoke_oauth_transport(attempt)
                self._oauth_attempts.pop(attempt_id, None)
                raise

    async def native_oauth_status(
        self, attempt_id: str, *, owner_id: int, session_id: str
    ) -> dict[str, object]:
        """Read one session-bound attempt status without consuming a successful handoff."""

        async with self._oauth_lock:
            attempt = self._managed_oauth_attempt(attempt_id, owner_id, session_id)
            if attempt.status not in {"connected", "cancelled", "expired", "denied"} and (
                attempt.expires_at <= time.time()
            ):
                await self._cancel_expired_oauth_attempt(attempt)
                return self._managed_oauth_public(attempt)
            if attempt.status in {"connected", "cancelled", "expired", "denied"}:
                return self._managed_oauth_public(attempt)
            status = await self._runtime_oauth_status(attempt)
            attempt.status = status
            return self._managed_oauth_public(attempt)

    async def complete_native_oauth(
        self,
        attempt_id: str,
        *,
        owner_id: int,
        session_id: str,
        code: str | None = None,
        authorization_check: Callable[[], Awaitable[bool] | bool],
    ) -> dict[str, object]:
        """Complete a flow and encrypt its one-time handoff after live authorization."""

        async with self._oauth_lock:
            attempt = self._managed_oauth_attempt(attempt_id, owner_id, session_id)
            if attempt.status == "connected":
                return self._managed_oauth_public(attempt)
            if attempt.expires_at <= time.time():
                await self._cancel_expired_oauth_attempt(attempt)
                return self._managed_oauth_public(attempt)
            if code is not None:
                complete = getattr(self.runtime, "complete_native_oauth", None)
                if not callable(complete):
                    raise ProviderUnavailable("oauth_unavailable")
                await complete(
                    attempt.integration_id,
                    attempt.attempt_id,
                    owner_id=owner_id,
                    session_id=session_id,
                    code=code,
                )
            status = await self._runtime_oauth_status(attempt)
            attempt.status = status
            if status != "handoff_ready":
                return self._managed_oauth_public(attempt)

            take = getattr(self.runtime, "take_native_oauth_handoff", None)
            if not callable(take):
                raise ProviderUnavailable("oauth_unavailable")
            credential = await take(
                attempt.integration_id,
                attempt.attempt_id,
                owner_id=owner_id,
                session_id=session_id,
            )
            self._validate_native_oauth_payload(credential, attempt)
            try:
                authorized = authorization_check()
                if inspect.isawaitable(authorized):
                    authorized = await authorized
            except Exception:
                authorized = False
            if authorized is not True:
                await self._cancel_runtime_oauth(attempt)
                attempt.status = "cancelled"
                attempt.authorization_url = None
                attempt.instructions = None
                attempt.callback_state = None
                await self._revoke_oauth_transport(attempt)
                del credential
                raise CredentialRejected("oauth_authorization_required")
            self._write_oauth_credential(
                attempt.integration_id,
                attempt.method_id,
                owner_id,
                credential,
            )
            attempt.status = "connected"
            attempt.authorization_url = None
            attempt.instructions = None
            attempt.callback_state = None
            # Drop the only manager reference to the transient bearer/refresh values promptly.
            del credential
            return self._managed_oauth_public(attempt)

    async def submit_native_oauth_callback(
        self,
        attempt_id: str,
        *,
        owner_id: int,
        session_id: str,
        callback_url: str,
    ) -> dict[str, object]:
        """Submit a pasted callback URL to the exact native attempt, never fetch it."""

        async with self._oauth_lock:
            attempt = self._managed_oauth_attempt(attempt_id, owner_id, session_id)
            self._validate_native_oauth_callback(attempt, callback_url)
            if attempt.expires_at <= time.time():
                await self._cancel_expired_oauth_attempt(attempt)
                return self._managed_oauth_public(attempt)
            callback = getattr(self.runtime, "submit_native_oauth_callback", None)
            if not callable(callback):
                raise ProviderUnavailable("oauth_unavailable")
            await callback(
                attempt.integration_id,
                attempt.attempt_id,
                owner_id=owner_id,
                session_id=session_id,
                callback_url=callback_url,
            )
            attempt.status = await self._runtime_oauth_status(attempt)
            return self._managed_oauth_public(attempt)

    @staticmethod
    def _validate_native_oauth_launch(
        integration_id: str,
        method_id: str,
        url: str,
        instructions: str,
    ) -> str | None:
        """Accept only the pinned native V2 launch forms for reviewed OAuth methods."""

        try:
            parsed = urlsplit(url)
            query_rows = parse_qsl(
                parsed.query,
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=12,
                encoding="utf-8",
                errors="strict",
            )
            port = parsed.port
        except (ValueError, UnicodeError):
            raise ProviderUnavailable("oauth_unavailable") from None
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or parsed.hostname is None
            or port not in {None, 443}
            or parsed.netloc.lower()
            not in {parsed.hostname.lower(), f"{parsed.hostname.lower()}:443"}
        ):
            raise ProviderUnavailable("oauth_unavailable")
        query: dict[str, str] = {}
        for key, value in query_rows:
            if key in query:
                raise ProviderUnavailable("oauth_unavailable")
            query[key] = value

        if integration_id == "openai" and method_id == "chatgpt-browser":
            required = {
                "response_type",
                "client_id",
                "redirect_uri",
                "scope",
                "code_challenge",
                "code_challenge_method",
                "id_token_add_organizations",
                "codex_cli_simplified_flow",
                "state",
                "originator",
            }
            challenge = query.get("code_challenge", "")
            state = query.get("state", "")
            if (
                parsed.hostname != "auth.openai.com"
                or parsed.path != "/oauth/authorize"
                or set(query) != required
                or query.get("response_type") != "code"
                or query.get("client_id") != "app_EMoamEEZ73f0CkXaXp7hrann"
                or query.get("redirect_uri") != "http://localhost:1455/auth/callback"
                or query.get("scope") != "openid profile email offline_access"
                or query.get("code_challenge_method") != "S256"
                or query.get("id_token_add_organizations") != "true"
                or query.get("codex_cli_simplified_flow") != "true"
                or query.get("originator") != "opencode"
                or re.fullmatch(r"[A-Za-z0-9_-]{43}", challenge) is None
                or re.fullmatch(r"[A-Za-z0-9_-]{43}", state) is None
                or instructions
                != "Complete authorization in your browser. This window will close automatically."
            ):
                raise ProviderUnavailable("oauth_unavailable")
            return state

        if integration_id == "openai" and method_id == "chatgpt-headless":
            if (
                parsed.hostname != "auth.openai.com"
                or parsed.path != "/codex/device"
                or parsed.query
                or re.fullmatch(r"Enter code: [A-Za-z0-9-]{1,256}", instructions) is None
            ):
                raise ProviderUnavailable("oauth_unavailable")
            return None

        if integration_id == "opencode" and method_id == "device":
            if (
                parsed.hostname != "opencode.ai"
                or parsed.path != "/console/device"
                or set(query) != {"user_code", "client_id"}
                or query.get("client_id") != "opencode-cli"
                or re.fullmatch(r"[A-Za-z0-9-]{1,256}", query.get("user_code", "")) is None
                or instructions != f"Enter code: {query['user_code']}"
            ):
                raise ProviderUnavailable("oauth_unavailable")
            return None
        raise ProviderUnavailable("oauth_unavailable")

    @staticmethod
    def _validate_native_oauth_callback(attempt: _ManagedOAuthAttempt, callback_url: str) -> None:
        """Validate a pasted loopback callback without making any network request."""

        if (
            attempt.integration_id != "openai"
            or attempt.method_id != "chatgpt-browser"
            or attempt.callback_state is None
            or not isinstance(callback_url, str)
            or len(callback_url.encode("utf-8", errors="ignore")) > 4096
            or any(unicodedata.category(char).startswith("C") for char in callback_url)
        ):
            raise CredentialRejected("oauth_callback_invalid")
        try:
            parsed = urlsplit(callback_url)
            query_rows = parse_qsl(
                parsed.query,
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=4,
                encoding="utf-8",
                errors="strict",
            )
            port = parsed.port
        except (ValueError, UnicodeError):
            raise CredentialRejected("oauth_callback_invalid") from None
        query: dict[str, str] = {}
        for key, value in query_rows:
            if key in query:
                raise CredentialRejected("oauth_callback_invalid")
            query[key] = value
        if (
            parsed.scheme != "http"
            or parsed.hostname != "localhost"
            or port != 1455
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path != "/auth/callback"
            or parsed.fragment
            or set(query) != {"code", "state"}
            or not 1 <= len(query.get("code", "").encode("utf-8")) <= 2048
            or any(unicodedata.category(char).startswith("C") for char in query.get("code", ""))
            or not secrets.compare_digest(query.get("state", ""), attempt.callback_state)
        ):
            raise CredentialRejected("oauth_callback_invalid")

    async def cancel_native_oauth(
        self, attempt_id: str, *, owner_id: int, session_id: str
    ) -> dict[str, object]:
        """Cancel one pending attempt, wiping its native handoff and releasing the HOME hold."""

        async with self._oauth_lock:
            attempt = self._managed_oauth_attempt(attempt_id, owner_id, session_id)
            if attempt.status == "connected":
                raise CredentialRejected("oauth_attempt_conflict")
            cancel = getattr(self.runtime, "cancel_native_oauth", None)
            if not callable(cancel):
                raise ProviderUnavailable("oauth_unavailable")
            await cancel(
                attempt.integration_id,
                attempt.attempt_id,
                owner_id=owner_id,
                session_id=session_id,
            )
            attempt.status = "cancelled"
            attempt.authorization_url = None
            attempt.instructions = None
            attempt.callback_state = None
            await self._revoke_oauth_transport(attempt)
            return self._managed_oauth_public(attempt)

    @staticmethod
    def _validate_oauth_actor(owner_id: int, session_id: str) -> None:
        if (
            type(owner_id) is not int
            or owner_id < 1
            or not isinstance(session_id, str)
            or re.fullmatch(r"[0-9a-f]{32}", session_id) is None
        ):
            raise CredentialRejected("oauth_attempt_not_found")

    def _managed_oauth_attempt(
        self, attempt_id: str, owner_id: int, session_id: str
    ) -> _ManagedOAuthAttempt:
        self._validate_oauth_actor(owner_id, session_id)
        if not isinstance(attempt_id, str) or re.fullmatch(r"[0-9a-f]{32}", attempt_id) is None:
            raise CredentialRejected("oauth_attempt_not_found")
        attempt = self._oauth_attempts.get(attempt_id)
        if (
            attempt is None
            or attempt.owner_id != owner_id
            or not secrets.compare_digest(attempt.session_id, session_id)
        ):
            raise CredentialRejected("oauth_attempt_not_found")
        return attempt

    async def _cancel_expired_oauth_attempt(self, attempt: _ManagedOAuthAttempt) -> None:
        await self._cancel_runtime_oauth(attempt)
        attempt.status = "expired"
        attempt.authorization_url = None
        attempt.instructions = None
        attempt.callback_state = None
        await self._revoke_oauth_transport(attempt)

    async def _cancel_runtime_oauth(self, attempt: _ManagedOAuthAttempt) -> None:
        cancel = getattr(self.runtime, "cancel_native_oauth", None)
        if not callable(cancel):
            raise ProviderUnavailable("oauth_unavailable")
        await cancel(
            attempt.integration_id,
            attempt.attempt_id,
            owner_id=attempt.owner_id,
            session_id=attempt.session_id,
        )

    async def _revoke_oauth_transport(self, attempt: _ManagedOAuthAttempt) -> None:
        if attempt.transport_capability is None:
            return
        revoke = self._oauth_transport_revoke
        if not callable(revoke):
            raise ProviderUnavailable("oauth_unavailable")
        result = revoke(attempt.attempt_id)
        if inspect.isawaitable(result):
            await result
        attempt.transport_capability = None

    async def _runtime_oauth_status(self, attempt: _ManagedOAuthAttempt) -> str:
        status_reader = getattr(self.runtime, "native_oauth_status", None)
        if not callable(status_reader):
            raise ProviderUnavailable("oauth_unavailable")
        try:
            status = await status_reader(
                attempt.integration_id,
                attempt.attempt_id,
                owner_id=attempt.owner_id,
                session_id=attempt.session_id,
            )
        except Exception as exc:
            raise ProviderUnavailable("oauth_unavailable") from exc
        if status not in {"pending", "handoff_ready", "denied", "expired", "cancelled"}:
            raise ProviderUnavailable("oauth_unavailable")
        if status in {"denied", "expired", "cancelled"}:
            attempt.authorization_url = None
            attempt.instructions = None
            attempt.callback_state = None
        if status != "pending":
            await self._revoke_oauth_transport(attempt)
        return status

    async def _expire_managed_oauth_attempts(self) -> None:
        now = time.time()
        for attempt_id, attempt in tuple(self._oauth_attempts.items()):
            if attempt.expires_at <= now and attempt.status not in {
                "connected",
                "cancelled",
                "expired",
                "denied",
            }:
                cancel = getattr(self.runtime, "cancel_native_oauth", None)
                if callable(cancel):
                    await cancel(
                        attempt.integration_id,
                        attempt_id,
                        owner_id=attempt.owner_id,
                        session_id=attempt.session_id,
                    )
                attempt.status = "expired"
                attempt.authorization_url = None
                attempt.instructions = None
                attempt.callback_state = None
                await self._revoke_oauth_transport(attempt)

        terminal = [
            attempt_id
            for attempt_id, attempt in self._oauth_attempts.items()
            if attempt.status in {"connected", "cancelled", "expired", "denied"}
        ]
        while len(self._oauth_attempts) >= _NATIVE_OAUTH_ATTEMPT_LIMIT and terminal:
            self._oauth_attempts.pop(terminal.pop(0), None)

    @staticmethod
    def _managed_oauth_public(attempt: _ManagedOAuthAttempt) -> dict[str, object]:
        return {
            "attempt_id": attempt.attempt_id,
            "integration_id": attempt.integration_id,
            "method_id": attempt.method_id,
            "status": attempt.status,
            "mode": attempt.mode,
            "expires_at": attempt.expires_at,
            "authorization_url": attempt.authorization_url,
            "instructions": attempt.instructions,
        }

    @staticmethod
    def _validate_native_oauth_payload(credential: object, attempt: _ManagedOAuthAttempt) -> None:
        if (
            not isinstance(credential, Mapping)
            or set(credential) - {"type", "methodID", "access", "refresh", "expires", "metadata"}
            or credential.get("type") != "oauth"
            or credential.get("methodID") != attempt.method_id
        ):
            raise ProviderUnavailable("oauth_unavailable")
        for credential_field in ("access", "refresh"):
            value = credential.get(credential_field)
            if (
                not isinstance(value, str)
                or not 1 <= len(value.encode("utf-8")) <= 32_768
                or any(unicodedata.category(char).startswith("C") for char in value)
            ):
                raise ProviderUnavailable("oauth_unavailable")
        expires = credential.get("expires")
        now_ms = int(time.time() * 1000)
        if type(expires) is not int or not now_ms < expires <= now_ms + 366 * 86_400_000:
            raise ProviderUnavailable("oauth_unavailable")
        metadata = credential.get("metadata", {})
        if metadata is None:
            metadata = {}
        allowed = (
            {"accountID"}
            if attempt.integration_id == "openai"
            else {"server", "accountID", "email", "orgID", "orgName"}
        )
        if not isinstance(metadata, Mapping) or len(metadata) > 8 or set(metadata) - allowed:
            raise ProviderUnavailable("oauth_unavailable")
        for value in metadata.values():
            if (
                not isinstance(value, str)
                or len(value.encode("utf-8")) > 512
                or any(unicodedata.category(char).startswith("C") for char in value)
            ):
                raise ProviderUnavailable("oauth_unavailable")
        if (
            attempt.integration_id == "opencode"
            and metadata.get("server") != "https://opencode.ai/console"
        ):
            raise ProviderUnavailable("oauth_unavailable")

    def _oauth_credential_path(self, integration_id: str, owner_id: int, method_id: str) -> Path:
        if (
            (integration_id, method_id) not in _NATIVE_OAUTH_UI_METHODS
            or type(owner_id) is not int
            or owner_id < 1
        ):
            raise ProviderUnavailable("oauth_unavailable")
        return self.vault_dir / f"oauth-{integration_id}-{method_id}-{owner_id}.json"

    @staticmethod
    def _oauth_credential_aad(integration_id: str, owner_id: int, method_id: str) -> bytes:
        return (
            _OAUTH_AAD_CONTEXT
            + integration_id.encode("ascii")
            + b":"
            + method_id.encode("ascii")
            + b":"
            + str(owner_id).encode("ascii")
        )

    def _write_oauth_credential(
        self,
        integration_id: str,
        method_id: str,
        owner_id: int,
        credential: Mapping[str, object],
    ) -> None:
        self._ensure_vault()
        try:
            plaintext = json.dumps(
                credential,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError) as exc:
            raise ProviderUnavailable("oauth_vault_unavailable") from exc
        if len(plaintext) > _OAUTH_CREDENTIAL_FILE_LIMIT - 256:
            raise ProviderUnavailable("oauth_vault_unavailable")
        nonce = os.urandom(12)
        encrypted = AESGCM(self._vault_key()).encrypt(
            nonce,
            plaintext,
            self._oauth_credential_aad(integration_id, owner_id, method_id),
        )
        content = json.dumps(
            {
                "version": 1,
                "value": base64.urlsafe_b64encode(nonce + encrypted).decode("ascii"),
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        self._atomic_write(
            self._oauth_credential_path(integration_id, owner_id, method_id), content
        )

    def _read_oauth_credential(
        self, integration_id: str, method_id: str, owner_id: int
    ) -> dict[str, object] | None:
        path = self._oauth_credential_path(integration_id, owner_id, method_id)
        try:
            raw = _read_private_file(path, _OAUTH_CREDENTIAL_FILE_LIMIT)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ProviderUnavailable("oauth_vault_unavailable") from exc
        try:
            envelope = json.loads(raw)
            packed = base64.urlsafe_b64decode(envelope["value"].encode("ascii"))
            if (
                envelope.get("version") != 1
                or not 29 <= len(packed) <= _OAUTH_CREDENTIAL_FILE_LIMIT
            ):
                raise ValueError("invalid OAuth envelope")
            plaintext = AESGCM(self._vault_key()).decrypt(
                packed[:12],
                packed[12:],
                self._oauth_credential_aad(integration_id, owner_id, method_id),
            )
            value = json.loads(plaintext)
            if not isinstance(value, dict):
                raise ValueError("invalid OAuth value")
            return value
        except Exception as exc:
            raise ProviderUnavailable("oauth_vault_unavailable") from exc

    async def clear_native_oauth_connection(
        self,
        integration_id: str,
        method_id: str,
        *,
        owner_id: int,
        authorization_check: Callable[[], Awaitable[bool] | bool],
    ) -> bool:
        """Revalidate the admin session immediately before deleting one fixed vault entry."""

        self._validate_oauth_owner(owner_id)
        path = self._oauth_credential_path(integration_id, owner_id, method_id)
        if not callable(authorization_check):
            raise CredentialRejected("oauth_authorization_required")
        async with self._oauth_lock:
            try:
                authorized = authorization_check()
                if inspect.isawaitable(authorized):
                    authorized = await authorized
            except Exception:
                authorized = False
            if authorized is not True:
                raise CredentialRejected("oauth_authorization_required")
            with self._lock:
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:
                    raise ProviderUnavailable("oauth_vault_unavailable") from exc
        return True

    def list_providers(self) -> tuple[ProviderSummary, ...]:
        """Return provider configuration and credential presence without disclosing secrets."""

        state = self._read_metadata()
        output: list[ProviderSummary] = []
        for provider_id, definition in self._definitions.items():
            config = state.get(provider_id, {})
            credential_configured = self._credential_exists(provider_id)
            configured = credential_configured
            endpoint_configured = isinstance(config.get("base_url"), str) or isinstance(
                definition.get("default_base_url"), str
            )
            if provider_id == "custom":
                configured = endpoint_configured and config.get("endpoint_policy_reviewed") is True
            endpoint = config.get("base_url", definition.get("default_base_url"))
            selected_model = config.get("model_id")
            inventory_loaded_at = self._provider_inventory_loaded_at.get(provider_id, 0.0)
            inventory_current = (
                inventory_loaded_at > 0
                and self._clock() - inventory_loaded_at < _MODEL_CACHE_SECONDS
                and configured
            )
            inventory_failure = self._provider_inventory_status.get(provider_id)
            if self._clock() >= self._provider_inventory_retry_at.get(provider_id, 0.0):
                inventory_failure = None
            output.append(
                ProviderSummary(
                    provider_id=provider_id,
                    display_name=str(definition["display_name"]),
                    auth_methods=tuple(str(item) for item in definition["auth_methods"]),
                    selected_model_id=(selected_model if isinstance(selected_model, str) else None),
                    selected_base_url=(endpoint if isinstance(endpoint, str) else None),
                    credential_required=bool(definition["credential_required"]),
                    credential_configured=credential_configured,
                    oauth_connected=False,
                    connection_status=(
                        "unavailable"
                        if not definition["adapter_supported"]
                        else inventory_failure
                        if inventory_failure in {"unavailable", "validation_failed"}
                        else "connected"
                        if inventory_current
                        else "configured"
                        if configured or provider_id == "opencode-zen"
                        else "unconfigured"
                    ),
                    terms_url=(
                        str(definition["terms_url"]) if definition.get("terms_url") else None
                    ),
                    native_provider_id=str(definition["native_provider_id"]),
                    adapter_id=str(definition["adapter_id"]),
                    protocol=str(definition["protocol"]),
                    supported_auth_methods=tuple(str(item) for item in definition["auth_methods"]),
                    endpoint_editable=bool(definition["endpoint_editable"]),
                    credential_supported=bool(definition["credential_supported"]),
                    validation_requires_credential=bool(
                        definition["validation_requires_credential"]
                    ),
                    adapter_supported=bool(definition["adapter_supported"]),
                    unsupported_reason=(
                        None
                        if definition["adapter_supported"]
                        else str(definition["unsupported_reason"])
                    ),
                    selected_terms_url=(
                        config.get("terms_url")
                        if provider_id == "custom" and isinstance(config.get("terms_url"), str)
                        else None
                    ),
                    selected_privacy_disclosure=(
                        config.get("privacy_disclosure")
                        if provider_id == "custom"
                        and isinstance(config.get("privacy_disclosure"), str)
                        else None
                    ),
                    selected_billing_disclosure=(
                        config.get("billing_disclosure")
                        if provider_id == "custom"
                        and isinstance(config.get("billing_disclosure"), str)
                        else None
                    ),
                    selected_billing_class=(
                        config.get("billing_class")
                        if provider_id == "custom"
                        and config.get("billing_class") in _CUSTOM_BILLING_CLASSES
                        else None
                    ),
                    selected_endpoint_policy_reviewed=(
                        config.get("endpoint_policy_reviewed") is True
                    ),
                )
            )
        return tuple(output)

    def update_provider(
        self,
        provider_id: str,
        *,
        model_id: str | None = None,
        base_url: str | None = None,
        credential: str | None = None,
    ) -> ProviderSummary:
        """Validate then atomically apply a fixed provider's model, URL, and key settings."""

        definition = self._require_provider(provider_id)
        if provider_id == "custom":
            raise ProviderUnavailable("custom_policy_review_required")
        if model_id is None and base_url is None and credential is None:
            raise ProviderUnavailable("empty_provider_update")
        if definition.get("adapter_supported") is not True and (
            model_id is not None or credential is not None or provider_id != "custom"
        ):
            raise ProviderUnavailable("provider_adapter_unsupported")
        next_model = self._validated_model(provider_id, model_id) if model_id is not None else None
        next_url: str | None = None
        if base_url is not None:
            if definition.get("endpoint_editable") is not True:
                raise ProviderUnavailable("endpoint_not_supported")
            next_url = _validate_public_https_url(base_url)
        next_secret: str | None = None
        if credential is not None:
            if definition.get("credential_supported") is not True:
                raise ProviderUnavailable("credential_not_supported")
            if not isinstance(credential, str):
                raise CredentialRejected("credential_invalid")
            try:
                credential_bytes = credential.strip().encode("utf-8")
            except UnicodeEncodeError as exc:
                raise CredentialRejected("credential_invalid") from exc
            if not credential.strip() or len(credential_bytes) > _MAX_SECRET_BYTES:
                raise CredentialRejected("credential_invalid")
            next_secret = credential.strip()

        with self._lock:
            state_before = self._read_metadata()
            credential_before = self._read_credential(provider_id)
            new_state = {key: dict(value) for key, value in state_before.items()}
            provider_state = dict(new_state.get(provider_id, {}))
            if next_model is not None:
                provider_state["model_id"] = next_model
            if next_url is not None:
                provider_state["base_url"] = next_url
            new_state[provider_id] = provider_state
            try:
                # Each file replacement is atomic; a failed second write or runtime sync restores
                # the prior pair while holding the manager lock so readers never observe a split.
                if next_secret is not None:
                    self._write_credential(provider_id, next_secret)
                self._write_metadata(new_state)
                self._sync_runtime_configuration(provider_id, definition, provider_state)
            except Exception as exc:
                try:
                    self._write_metadata(state_before)
                    if credential_before is None:
                        self._credential_path(provider_id).unlink(missing_ok=True)
                    else:
                        self._write_credential(provider_id, credential_before)
                except Exception as rollback_exc:
                    raise ProviderUnavailable("provider_update_rollback_failed") from rollback_exc
                if isinstance(exc, ProviderUnavailable | CredentialRejected):
                    raise
                raise ProviderUnavailable("provider_update_failed") from exc
        self._invalidate_provider_inventory(provider_id)
        return next(item for item in self.list_providers() if item.provider_id == provider_id)

    def set_model(self, provider_id: str, model_id: str) -> ProviderSummary:
        """Compatibility wrapper for the atomic provider update operation."""

        return self.update_provider(provider_id, model_id=model_id)

    def set_custom_endpoint(self, provider_id: str, base_url: str) -> ProviderSummary:
        """Reject endpoint-only updates that would lack exact reviewed policy metadata."""

        if provider_id != "custom":
            raise ProviderUnavailable("custom_endpoint_not_supported")
        raise ProviderUnavailable("custom_policy_review_required")

    def configure_custom_endpoint(
        self,
        *,
        base_url: str,
        terms_url: str,
        privacy_disclosure: str,
        billing_disclosure: str,
        billing_class: str,
        endpoint_policy_reviewed: bool,
        credential: str | None = None,
        model_id: str | None = None,
    ) -> ProviderSummary:
        """Atomically save a custom endpoint and its administrator-provided policy tuple."""

        definition = self._require_provider("custom")
        if (
            endpoint_policy_reviewed is not True
            or not isinstance(billing_class, str)
            or billing_class not in _CUSTOM_BILLING_CLASSES
        ):
            raise ProviderUnavailable("custom_policy_review_required")
        canonical_endpoint = _validate_public_https_url(base_url)
        canonical_terms = _validate_public_terms_url(terms_url)
        privacy = _validate_custom_disclosure(privacy_disclosure)
        billing = _validate_custom_disclosure(billing_disclosure)
        next_secret: str | None = None
        if credential is not None:
            if not isinstance(credential, str):
                raise CredentialRejected("credential_invalid")
            try:
                credential_bytes = credential.strip().encode("utf-8")
            except UnicodeEncodeError as exc:
                raise CredentialRejected("credential_invalid") from exc
            if not credential.strip() or len(credential_bytes) > _MAX_SECRET_BYTES:
                raise CredentialRejected("credential_invalid")
            next_secret = credential.strip()
        policy_versions = _custom_policy_versions(
            canonical_endpoint,
            canonical_terms,
            privacy,
            billing,
            billing_class,
        )
        reviewed_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        with self._lock:
            state_before = self._read_metadata()
            credential_before = self._read_credential("custom")
            new_state = {key: dict(value) for key, value in state_before.items()}
            provider_state = dict(new_state.get("custom", {}))
            previous_endpoint = provider_state.get("base_url")
            endpoint_changed = previous_endpoint != canonical_endpoint
            previous_identity = _custom_policy_identity(provider_state)
            next_identity = _custom_policy_identity(
                {
                    "base_url": canonical_endpoint,
                    "terms_url": canonical_terms,
                    "privacy_disclosure": privacy,
                    "billing_disclosure": billing,
                    "billing_class": billing_class,
                    "endpoint_policy_reviewed": True,
                    **policy_versions,
                }
            )
            tuple_changed = previous_identity != next_identity
            if model_id is not None:
                if tuple_changed:
                    raise ProviderUnavailable("custom_model_selection_requires_validation")
                self._validated_model("custom", model_id)
            provider_state.update(
                {
                    "base_url": canonical_endpoint,
                    "terms_url": canonical_terms,
                    "privacy_disclosure": privacy,
                    "billing_disclosure": billing,
                    "billing_class": billing_class,
                    "endpoint_policy_reviewed": True,
                    "terms_reviewed_at": reviewed_at,
                    **policy_versions,
                }
            )
            if model_id is not None:
                provider_state["model_id"] = model_id
            elif tuple_changed:
                provider_state.pop("model_id", None)
            new_state["custom"] = provider_state
            try:
                if next_secret is not None:
                    self._write_credential("custom", next_secret)
                elif endpoint_changed:
                    # A custom key is scoped to the exact administrator-reviewed endpoint.
                    # Never carry it to a new host/path merely because the admin omitted a
                    # replacement key in the update request.
                    self._credential_path("custom").unlink(missing_ok=True)
                self._write_metadata(new_state)
                self._sync_runtime_configuration("custom", definition, provider_state)
            except Exception as exc:
                try:
                    self._write_metadata(state_before)
                    if credential_before is None:
                        self._credential_path("custom").unlink(missing_ok=True)
                    else:
                        self._write_credential("custom", credential_before)
                except Exception as rollback_exc:
                    raise ProviderUnavailable("provider_update_rollback_failed") from rollback_exc
                if isinstance(exc, ProviderUnavailable | CredentialRejected):
                    raise
                raise ProviderUnavailable("provider_update_failed") from exc
        self._invalidate_provider_inventory("custom")
        return next(item for item in self.list_providers() if item.provider_id == "custom")

    def set_credential(self, provider_id: str, secret: str) -> ProviderSummary:
        """Encrypt one key for the app-side provider proxy without passing it to OpenCode."""

        return self.update_provider(provider_id, credential=secret)

    def clear_credential(self, provider_id: str) -> ProviderSummary:
        """Clear this provider's encrypted credential, endpoint, and selected model."""

        definition = self._require_provider(provider_id)
        with self._lock:
            state_before = self._read_metadata()
            credential_before = self._read_credential(provider_id)
            new_state = {key: dict(value) for key, value in state_before.items()}
            new_state.pop(provider_id, None)
            try:
                self._credential_path(provider_id).unlink(missing_ok=True)
                self._write_metadata(new_state)
                self._sync_runtime_configuration(provider_id, definition, {})
            except Exception as exc:
                try:
                    self._write_metadata(state_before)
                    if credential_before is not None:
                        self._write_credential(provider_id, credential_before)
                except Exception as rollback_exc:
                    raise ProviderUnavailable("provider_update_rollback_failed") from rollback_exc
                raise ProviderUnavailable("provider_clear_failed") from exc
        self._invalidate_provider_inventory(provider_id)
        return next(item for item in self.list_providers() if item.provider_id == provider_id)

    async def validate(
        self,
        provider_id: str,
        *,
        authorization_check: Callable[[], Awaitable[bool] | bool] | None = None,
    ) -> ProviderSummary:
        """Make one bounded, no-redirect model inventory request and return only safe status."""

        if authorization_check is not None:
            await _require_live_authorization(authorization_check)
        definition = self._require_provider(provider_id)
        if provider_id in _MODEL_DISCOVERY_PROVIDERS:
            await self._refresh_provider_inventory(
                provider_id, authorization_check=authorization_check
            )
            if authorization_check is not None:
                await _require_live_authorization(authorization_check)
            return next(item for item in self.list_providers() if item.provider_id == provider_id)
        if definition["adapter_supported"] is not True and provider_id != "opencode-zen":
            raise ProviderUnavailable("provider_adapter_unsupported")
        state = self._read_metadata().get(provider_id, {})
        base_url = state.get("base_url", definition.get("default_base_url"))
        if provider_id == "opencode-zen":
            if self.catalog is None:
                raise ProviderUnavailable("provider_unavailable")
            try:
                if authorization_check is None:
                    refreshed = await self.catalog.refresh()
                else:
                    refreshed = await self.catalog.refresh(authorization_check=authorization_check)
            except ModelCatalogAuthorizationError:
                raise CredentialRejected("oauth_authorization_required") from None
            if authorization_check is not None:
                await _require_live_authorization(authorization_check)
            if not refreshed:
                raise ProviderUnavailable("provider_unavailable")
            return next(item for item in self.list_providers() if item.provider_id == provider_id)
        if not isinstance(base_url, str):
            raise ProviderUnavailable("endpoint_not_configured")
        secret = self._read_credential(provider_id)
        if definition["credential_required"] and secret is None:
            raise CredentialRejected("credential_required")
        _validate_public_https_url(base_url)
        headers = _provider_headers(provider_id, secret)
        endpoint = base_url.rstrip("/") + "/models"
        try:
            if authorization_check is None:
                response = await request_public_https(
                    endpoint,
                    headers=headers,
                    timeout_seconds=5.0,
                    max_response_bytes=_MAX_VALIDATE_BYTES,
                )
            else:
                response = await request_public_https(
                    endpoint,
                    headers=headers,
                    timeout_seconds=5.0,
                    max_response_bytes=_MAX_VALIDATE_BYTES,
                    authorization_check=authorization_check,
                )
            if authorization_check is not None:
                await _require_live_authorization(authorization_check)
            if response.status_code in {401, 403}:
                raise CredentialRejected()
            if response.status_code != 200:
                raise ProviderUnavailable("provider_unavailable")
        except (CredentialRejected, ProviderUnavailable):
            raise
        except PublicHTTPError as exc:
            if authorization_check is not None:
                await _require_live_authorization(authorization_check)
                if exc.code in {
                    "provider_authorization_required",
                    "provider_authorization_timeout",
                }:
                    raise CredentialRejected("oauth_authorization_required") from None
            raise ProviderUnavailable("provider_unavailable") from exc
        if authorization_check is not None:
            await _require_live_authorization(authorization_check)
        return next(item for item in self.list_providers() if item.provider_id == provider_id)

    async def ensure_model_inventory(
        self, *, minimum_validity_seconds: float = 0.0
    ) -> tuple[object, ...]:
        """Demand-refresh Zen and configured compatible-provider model inventories."""

        if self.catalog is None:
            return ()
        ensure_fresh = getattr(self.catalog, "ensure_fresh", None)
        if not callable(ensure_fresh):
            list_models = getattr(self.catalog, "list_models", None)
            values = list_models() if callable(list_models) else ()
            return tuple(values) if isinstance(values, tuple | list) else ()
        values = await ensure_fresh(minimum_validity_seconds=minimum_validity_seconds)
        if not isinstance(values, tuple | list):
            values = ()
        await self._refresh_configured_provider_inventories(minimum_validity_seconds)
        list_models = getattr(self.catalog, "list_models", None)
        current = list_models() if callable(list_models) else values
        return tuple(current) if isinstance(current, tuple | list) else tuple(values)

    async def ensure_opencode_model_inventory(
        self,
        *,
        owner_id: int,
        authorization_check: Callable[[], Awaitable[bool] | bool],
        force: bool = False,
        minimum_validity_seconds: float = 0.0,
    ) -> tuple[dict[str, object], ...]:
        """Fetch one owner's fixed OpenCode Console config without global catalog publication.

        Console config is untrusted input. Only the closed native package registry, exact model
        identifiers, a public HTTPS endpoint, and display text enter the per-owner snapshot;
        remote headers, body overlays, settings, variants, and credentials are discarded.
        """

        self._validate_oauth_owner(owner_id)
        if not callable(authorization_check):
            raise CredentialRejected("oauth_authorization_required")
        if (
            not isinstance(minimum_validity_seconds, int | float)
            or isinstance(minimum_validity_seconds, bool)
            or not 0 <= minimum_validity_seconds <= 120.0
        ):
            raise ProviderUnavailable("model_inventory_invalid")
        await _require_live_authorization(authorization_check)
        loaded_at = self._opencode_loaded_at.get(owner_id, 0.0)
        if (
            not force
            and loaded_at > 0
            and self._clock() - loaded_at + minimum_validity_seconds < _MODEL_CACHE_SECONDS
        ):
            return self._opencode_public_inventory(owner_id)

        async with self._opencode_refresh_lock:
            await _require_live_authorization(authorization_check)
            loaded_at = self._opencode_loaded_at.get(owner_id, 0.0)
            if (
                not force
                and loaded_at > 0
                and self._clock() - loaded_at + minimum_validity_seconds < _MODEL_CACHE_SECONDS
            ):
                return self._opencode_public_inventory(owner_id)
            credential = self._owned_opencode_credential(owner_id)
            if credential is None:
                raise CredentialRejected("oauth_connection_required")
            credential = await self._refresh_opencode_credential_if_needed(
                owner_id, credential, authorization_check
            )
            access_token = credential.get("access")
            if not isinstance(access_token, str):
                raise CredentialRejected("oauth_connection_required")
            org_id = (
                credential.get("metadata", {}).get("orgID")
                if isinstance(credential.get("metadata"), Mapping)
                else None
            )
            headers = {"authorization": f"Bearer {access_token}"}
            # This organization identifier is sent only to the fixed OpenCode Console host.
            if isinstance(org_id, str) and org_id:
                headers["x-org-id"] = org_id
            try:
                async with asyncio.timeout(_MODEL_DISCOVERY_TIMEOUT_SECONDS):
                    response = await request_public_https(
                        _OPENCODE_CONFIG_URL,
                        headers=headers,
                        timeout_seconds=_MODEL_DISCOVERY_TIMEOUT_SECONDS - 0.5,
                        max_response_bytes=_MAX_VALIDATE_BYTES,
                        authorization_check=authorization_check,
                    )
            except PublicHTTPError as exc:
                if exc.code in {
                    "provider_authorization_required",
                    "provider_authorization_timeout",
                }:
                    raise CredentialRejected("oauth_authorization_required") from None
                raise ProviderUnavailable("opencode_inventory_unavailable") from exc
            except (OSError, TimeoutError) as exc:
                raise ProviderUnavailable("opencode_inventory_unavailable") from exc
            await _require_live_authorization(authorization_check)
            if response.status_code in {401, 403}:
                raise CredentialRejected("oauth_connection_required")
            if response.status_code != 200:
                raise ProviderUnavailable("opencode_inventory_unavailable")
            try:
                payload = json.loads(response.content)
                candidates, unsupported_count = project_opencode_console_models(payload)
            except (json.JSONDecodeError, UnicodeError, NativeProviderDescriptorError) as exc:
                raise ProviderUnavailable("opencode_inventory_unavailable") from exc
            provider_rows = payload.get("providers") if isinstance(payload, Mapping) else None
            if not isinstance(provider_rows, Mapping):
                raise ProviderUnavailable("opencode_inventory_unavailable")

            reviews = self._read_opencode_reviews(owner_id)
            records: list[_OpenCodeModelRecord] = []
            for candidate in candidates:
                try:
                    endpoint = self._opencode_candidate_endpoint(provider_rows, candidate)
                except ProviderUnavailable:
                    unsupported_count += 1
                    continue
                if (
                    self._known_model_exclusion_reason(
                        "opencode-console", endpoint, candidate.native_model_id
                    )
                    is not None
                ):
                    unsupported_count += 1
                    continue
                config_fingerprint = _opencode_config_fingerprint(
                    candidate.config_provider_id,
                    candidate.config_model_id,
                    candidate.native_model_id,
                    candidate.display_name,
                    candidate.adapter,
                    endpoint,
                )
                model_id = self._opencode_model_id(owner_id, config_fingerprint)
                review = reviews.get(model_id)
                if (
                    not isinstance(review, Mapping)
                    or review.get("config_fingerprint") != config_fingerprint
                ):
                    review = None
                model = self._opencode_assistant_model(model_id, candidate, endpoint, review)
                records.append(
                    _OpenCodeModelRecord(
                        owner_id=owner_id,
                        model=model,
                        config_provider_id=candidate.config_provider_id,
                        config_model_id=candidate.config_model_id,
                        native_model_id=candidate.native_model_id,
                        adapter=candidate.adapter,
                        package_id=candidate.package_id,
                        endpoint=endpoint,
                        config_fingerprint=config_fingerprint,
                    )
                )
            if len(records) > _MAX_OPENCODE_MODELS_PER_OWNER:
                raise ProviderUnavailable("opencode_inventory_unavailable")
            await _require_live_authorization(authorization_check)
            self._opencode_models[owner_id] = tuple(records)
            self._opencode_loaded_at[owner_id] = self._clock()
            self._opencode_unsupported_counts[owner_id] = min(2048, unsupported_count)
            return self._opencode_public_inventory(owner_id)

    def opencode_inventory_summary(self, *, owner_id: int) -> dict[str, object]:
        """Return counts only for the owner-scoped current Console inventory."""

        self._validate_oauth_owner(owner_id)
        if self._opencode_loaded_at.get(owner_id, 0.0) <= 0:
            return {"model_count": 0, "unsupported_model_count": 0}
        return {
            "model_count": len(self._opencode_models.get(owner_id, ())),
            "unsupported_model_count": self._opencode_unsupported_counts.get(owner_id, 0),
        }

    def get_opencode_model(self, model_id: str, *, owner_id: int) -> AssistantModel:
        """Resolve only a model in this owner's current Console snapshot."""

        record = self._opencode_record(model_id, owner_id=owner_id)
        return record.model

    def _opencode_public_inventory(self, owner_id: int) -> tuple[dict[str, object], ...]:
        return tuple(
            self._opencode_public_model(record)
            for record in self._opencode_models.get(owner_id, ())
        )

    def _opencode_public_model(self, record: _OpenCodeModelRecord) -> dict[str, object]:
        review = self._read_opencode_reviews(record.owner_id).get(record.model.model_id)
        reviewed = (
            isinstance(review, Mapping)
            and review.get("config_fingerprint") == record.config_fingerprint
            and review.get("endpoint_policy_reviewed") is True
        )
        policy = self.model_policy_state(record.model.model_id, owner_id=record.owner_id)
        return {
            "model_id": record.model.model_id,
            "display_name": record.model.display_name,
            "native_model_id": record.native_model_id,
            "provider_id": "opencode-console",
            "adapter_id": record.adapter.adapter_id,
            "protocol": record.adapter.protocol,
            "package_id": record.package_id,
            "endpoint": record.endpoint,
            "available": record.model.available,
            "reviewed": reviewed,
            "billing_class": record.model.billing_class or "unknown",
            "terms_url": record.model.terms_url or None,
            "privacy_disclosure": record.model.privacy_disclosure or None,
            "billing_disclosure": record.model.cost_disclosure or None,
            "training_policy": (
                review.get("training_policy")
                if reviewed and isinstance(review, Mapping)
                else "unknown"
            ),
            "confidential_data_policy": (
                review.get("confidential_data_policy")
                if reviewed and isinstance(review, Mapping)
                else "unknown"
            ),
            "privacy_policy_version": record.model.privacy_policy_version,
            "billing_policy_version": record.model.billing_policy_version,
            "enabled": policy.get("enabled") is True,
            "revision": policy.get("revision", 0),
            "review_revision": (
                int(review["revision"])
                if (
                    isinstance(review, Mapping)
                    and review.get("config_fingerprint") == record.config_fingerprint
                )
                else 0
            ),
            "usable": policy.get("usable") is True,
            "availability_reason": policy.get("availability_reason"),
            "config_fingerprint": record.config_fingerprint,
        }

    def _opencode_candidate_endpoint(
        self, provider_rows: Mapping[str, object], candidate: NativeConfiguredModel
    ) -> str:
        provider = provider_rows.get(candidate.config_provider_id)
        if not isinstance(provider, Mapping):
            raise ProviderUnavailable("provider_endpoint_not_configured")
        models = provider.get("models", {})
        model = models.get(candidate.config_model_id) if isinstance(models, Mapping) else None
        if not isinstance(model, Mapping):
            raise ProviderUnavailable("provider_endpoint_not_configured")
        model_settings = model.get("settings", {})
        provider_settings = provider.get("settings", {})
        model_endpoint = (
            model_settings.get("baseURL") if isinstance(model_settings, Mapping) else None
        )
        provider_endpoint = (
            provider_settings.get("baseURL") if isinstance(provider_settings, Mapping) else None
        )
        endpoint = model_endpoint if model_endpoint is not None else provider_endpoint
        if endpoint is None:
            endpoint = _OPENCODE_DEFAULT_ENDPOINTS.get(candidate.adapter.adapter_id)
        if not isinstance(endpoint, str):
            raise ProviderUnavailable("provider_endpoint_not_configured")
        return _validate_public_https_url(endpoint)

    def _opencode_model_id(self, owner_id: int, config_fingerprint: str) -> str:
        material = f"opencode-console:v1:{owner_id}:{config_fingerprint}".encode("ascii")
        digest = hmac.new(self._vault_key(), material, hashlib.sha256).hexdigest()
        return f"opencode-console/{digest}"

    @staticmethod
    def _opencode_assistant_model(
        model_id: str,
        candidate: NativeConfiguredModel,
        endpoint: str,
        review: Mapping[str, object] | None,
    ) -> AssistantModel:
        training_policy = review.get("training_policy") if review is not None else "unknown"
        confidential_policy = (
            review.get("confidential_data_policy") if review is not None else "unknown"
        )
        billing_class = review.get("billing_class") if review is not None else "unknown"
        approved = bool(
            review is not None
            and review.get("endpoint_policy_reviewed") is True
            and training_policy in _OPENCODE_TRAINING_POLICIES - {"unknown"}
            and confidential_policy == "allowed"
            and billing_class in {"free", "paid"}
        )
        privacy = str(review.get("privacy_disclosure", "")) if review else ""
        billing = str(review.get("billing_disclosure", "")) if review else ""
        terms_url = str(review.get("terms_url", "")) if review else ""
        reviewed_at = str(review.get("terms_reviewed_at", "")) if review else ""
        privacy_version = str(review.get("privacy_policy_version", "")) if review else ""
        billing_version = str(review.get("billing_policy_version", "")) if review else ""
        policy_version = str(review.get("policy_version", "")) if review else ""
        unreviewed_identity = hashlib.sha256(model_id.encode("ascii")).hexdigest()[:32]
        if not privacy_version:
            privacy_version = f"op0-{unreviewed_identity}"
        if not billing_version:
            billing_version = f"ob0-{unreviewed_identity}"
        if not policy_version:
            policy_version = f"ou0-{unreviewed_identity}"
        return AssistantModel(
            model_id=model_id,
            provider_id="opencode-console",
            display_name=candidate.display_name,
            available=approved,
            free=billing_class == "free",
            training=training_policy != "no_training",
            terms_url=terms_url,
            terms_reviewed_at=reviewed_at,
            policy_version=policy_version,
            disclosure=privacy or "Administrator review is required before this model can be used.",
            data_collection_allowed=training_policy == "training_possible",
            data_collection_default=False,
            availability_reason=(None if approved else "model_policy_review_required"),
            native_provider_id=candidate.adapter.native_provider_id,
            privacy_policy_version=privacy_version,
            billing_policy_version=billing_version,
            billing_class=str(billing_class),
            privacy_disclosure=privacy,
            cost_disclosure=billing,
        )

    def _opencode_record(self, model_id: str, *, owner_id: int) -> _OpenCodeModelRecord:
        self._validate_oauth_owner(owner_id)
        if (
            not isinstance(model_id, str)
            or re.fullmatch(r"opencode-console/[0-9a-f]{64}", model_id) is None
            or self._clock() - self._opencode_loaded_at.get(owner_id, 0.0) >= _MODEL_CACHE_SECONDS
        ):
            raise ProviderUnavailable("model_unavailable")
        record = next(
            (
                item
                for item in self._opencode_models.get(owner_id, ())
                if item.model.model_id == model_id and item.owner_id == owner_id
            ),
            None,
        )
        if record is None:
            raise ProviderUnavailable("model_unavailable")
        if (
            self._known_model_exclusion_reason(
                "opencode-console", record.endpoint, record.native_model_id
            )
            is not None
        ):
            raise ProviderUnavailable("model_unavailable")
        return record

    def _opencode_review_path(self, owner_id: int) -> Path:
        self._validate_oauth_owner(owner_id)
        return self.vault_dir / f"opencode-model-reviews-{owner_id}.json"

    def _read_opencode_reviews(self, owner_id: int) -> dict[str, dict[str, object]]:
        try:
            raw = _read_private_file(
                self._opencode_review_path(owner_id), _OPENCODE_REVIEW_FILE_LIMIT
            )
        except FileNotFoundError:
            return {}
        except OSError as exc:
            raise ProviderUnavailable("provider_config_unavailable") from exc
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ProviderUnavailable("provider_config_invalid") from exc
        if not isinstance(value, Mapping) or len(value) > _MAX_OPENCODE_REVIEW_ROWS:
            raise ProviderUnavailable("provider_config_invalid")
        result: dict[str, dict[str, object]] = {}
        for model_id, row in value.items():
            expected_fields = {
                "config_fingerprint",
                "terms_url",
                "privacy_disclosure",
                "billing_disclosure",
                "billing_class",
                "training_policy",
                "confidential_data_policy",
                "endpoint_policy_reviewed",
                "terms_reviewed_at",
                "policy_version",
                "privacy_policy_version",
                "billing_policy_version",
                "revision",
            }
            if (
                not isinstance(model_id, str)
                or re.fullmatch(r"opencode-console/[0-9a-f]{64}", model_id) is None
                or not isinstance(row, Mapping)
                or set(row) != expected_fields
                or type(row.get("endpoint_policy_reviewed")) is not bool
                or row.get("billing_class") not in _CUSTOM_BILLING_CLASSES
                or row.get("training_policy") not in _OPENCODE_TRAINING_POLICIES
                or row.get("confidential_data_policy") not in _OPENCODE_CONFIDENTIAL_POLICIES
                or type(row.get("revision")) is not int
                or not 1 <= row["revision"] <= _MAX_POLICY_REVISION
            ):
                raise ProviderUnavailable("provider_config_invalid")
            fingerprint = row.get("config_fingerprint")
            if (
                not isinstance(fingerprint, str)
                or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None
            ):
                raise ProviderUnavailable("provider_config_invalid")
            try:
                terms = _validate_public_terms_url(row.get("terms_url"))
                privacy = _validate_custom_disclosure(row.get("privacy_disclosure"))
                billing = _validate_custom_disclosure(row.get("billing_disclosure"))
                reviewed_at = row.get("terms_reviewed_at")
                if not isinstance(reviewed_at, str) or len(reviewed_at) > 40:
                    raise ProviderUnavailable("provider_config_invalid")
                moment = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
                if moment.tzinfo is None:
                    raise ProviderUnavailable("provider_config_invalid")
                versions = _opencode_policy_versions(
                    model_id,
                    fingerprint,
                    terms,
                    privacy,
                    billing,
                    str(row["billing_class"]),
                    str(row["training_policy"]),
                    str(row["confidential_data_policy"]),
                )
            except (ProviderUnavailable, ValueError, TypeError) as exc:
                raise ProviderUnavailable("provider_config_invalid") from exc
            if any(row.get(key) != value for key, value in versions.items()):
                raise ProviderUnavailable("provider_config_invalid")
            result[model_id] = {**dict(row), **versions}
        return result

    def _write_opencode_reviews(
        self, owner_id: int, reviews: Mapping[str, Mapping[str, object]]
    ) -> None:
        content = json.dumps(
            reviews, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        if len(content) > _OPENCODE_REVIEW_FILE_LIMIT:
            raise ProviderUnavailable("provider_config_invalid")
        self._atomic_write(self._opencode_review_path(owner_id), content)

    async def review_opencode_model(
        self,
        model_id: str,
        *,
        owner_id: int,
        terms_url: str,
        privacy_disclosure: str,
        billing_disclosure: str,
        billing_class: str,
        training_policy: str,
        confidential_data_policy: str,
        endpoint_policy_reviewed: bool,
        expected_revision: int,
        expected_config_fingerprint: str,
        authorization_check: Callable[[], Awaitable[bool] | bool],
    ) -> dict[str, object]:
        """Persist an explicit owner-scoped review bound to one live config fingerprint."""

        await self.ensure_opencode_model_inventory(
            owner_id=owner_id,
            authorization_check=authorization_check,
            force=True,
        )
        async with self._opencode_refresh_lock:
            record = self._opencode_record(model_id, owner_id=owner_id)
            return await self._review_opencode_model_current(
                record,
                terms_url=terms_url,
                privacy_disclosure=privacy_disclosure,
                billing_disclosure=billing_disclosure,
                billing_class=billing_class,
                training_policy=training_policy,
                confidential_data_policy=confidential_data_policy,
                endpoint_policy_reviewed=endpoint_policy_reviewed,
                expected_revision=expected_revision,
                expected_config_fingerprint=expected_config_fingerprint,
                authorization_check=authorization_check,
            )

    async def _review_opencode_model_current(
        self,
        record: _OpenCodeModelRecord,
        *,
        terms_url: str,
        privacy_disclosure: str,
        billing_disclosure: str,
        billing_class: str,
        training_policy: str,
        confidential_data_policy: str,
        endpoint_policy_reviewed: bool,
        expected_revision: int,
        expected_config_fingerprint: str,
        authorization_check: Callable[[], Awaitable[bool] | bool],
    ) -> dict[str, object]:
        model_id = record.model.model_id
        owner_id = record.owner_id
        if (
            endpoint_policy_reviewed is not True
            or billing_class not in _CUSTOM_BILLING_CLASSES
            or training_policy not in _OPENCODE_TRAINING_POLICIES
            or confidential_data_policy not in _OPENCODE_CONFIDENTIAL_POLICIES
            or type(expected_revision) is not int
            or not 0 <= expected_revision <= _MAX_POLICY_REVISION
            or not isinstance(expected_config_fingerprint, str)
            or not secrets.compare_digest(expected_config_fingerprint, record.config_fingerprint)
        ):
            raise ProviderUnavailable("model_inventory_changed")
        try:
            canonical_terms = _validate_public_terms_url(terms_url)
            clean_privacy = _validate_custom_disclosure(privacy_disclosure)
            clean_billing = _validate_custom_disclosure(billing_disclosure)
        except ProviderUnavailable as exc:
            raise ProviderUnavailable("custom_policy_review_required") from exc
        if not callable(authorization_check):
            raise CredentialRejected("oauth_authorization_required")
        async with self._oauth_lock:
            await _require_live_authorization(authorization_check)
            with self._lock:
                reviews = self._read_opencode_reviews(owner_id)
                previous = reviews.get(model_id)
                previous_revision = int(previous["revision"]) if previous else 0
                if previous_revision != expected_revision:
                    raise ProviderUnavailable("model_policy_conflict")
                if previous_revision >= _MAX_POLICY_REVISION:
                    raise ProviderUnavailable("model_policy_revision_exhausted")
                reviewed_at = (
                    datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                )
                versions = _opencode_policy_versions(
                    model_id,
                    record.config_fingerprint,
                    canonical_terms,
                    clean_privacy,
                    clean_billing,
                    billing_class,
                    training_policy,
                    confidential_data_policy,
                )
                row: dict[str, object] = {
                    "config_fingerprint": record.config_fingerprint,
                    "terms_url": canonical_terms,
                    "privacy_disclosure": clean_privacy,
                    "billing_disclosure": clean_billing,
                    "billing_class": billing_class,
                    "training_policy": training_policy,
                    "confidential_data_policy": confidential_data_policy,
                    "endpoint_policy_reviewed": True,
                    "terms_reviewed_at": reviewed_at,
                    **versions,
                    "revision": previous_revision + 1,
                }
                reviews[model_id] = row
                self._write_opencode_reviews(owner_id, reviews)
        updated_record = self._opencode_record(model_id, owner_id=owner_id)
        candidate = self._find_opencode_candidate(updated_record)
        updated_model = self._opencode_assistant_model(
            model_id, candidate, updated_record.endpoint, row
        )
        self._replace_opencode_record(
            owner_id, model_id, lambda item: _replace_opencode_model(item, updated_model)
        )
        return self._opencode_public_model(self._opencode_record(model_id, owner_id=owner_id))

    async def clear_opencode_model_review(
        self,
        model_id: str,
        *,
        owner_id: int,
        expected_revision: int,
        authorization_check: Callable[[], Awaitable[bool] | bool],
    ) -> bool:
        """Revoke one exact review and its separate model-policy approval fail-closed."""

        await self.ensure_opencode_model_inventory(
            owner_id=owner_id,
            authorization_check=authorization_check,
            force=True,
        )
        async with self._opencode_refresh_lock:
            self._opencode_record(model_id, owner_id=owner_id)
            return await self._clear_opencode_model_review_current(
                model_id,
                owner_id=owner_id,
                expected_revision=expected_revision,
                authorization_check=authorization_check,
            )

    async def _clear_opencode_model_review_current(
        self,
        model_id: str,
        *,
        owner_id: int,
        expected_revision: int,
        authorization_check: Callable[[], Awaitable[bool] | bool],
    ) -> bool:
        if type(expected_revision) is not int or expected_revision < 0:
            raise ProviderUnavailable("model_policy_invalid")
        if not callable(authorization_check):
            raise CredentialRejected("oauth_authorization_required")
        async with self._oauth_lock:
            await _require_live_authorization(authorization_check)
            with self._lock:
                reviews = self._read_opencode_reviews(owner_id)
                previous = reviews.get(model_id)
                if previous is None:
                    raise ProviderUnavailable("model_unavailable")
                if previous.get("revision") != expected_revision:
                    raise ProviderUnavailable("model_policy_conflict")
                if expected_revision >= _MAX_POLICY_REVISION:
                    raise ProviderUnavailable("model_policy_revision_exhausted")
                tombstone = dict(previous)
                tombstone["endpoint_policy_reviewed"] = False
                tombstone["revision"] = expected_revision + 1
                reviews[model_id] = tombstone
                self._write_opencode_reviews(owner_id, reviews)
                state = self._read_metadata()
                policies = dict(state.get(_MODEL_POLICY_KEY, {}))
                policies.pop(model_id, None)
                if policies:
                    state[_MODEL_POLICY_KEY] = policies
                else:
                    state.pop(_MODEL_POLICY_KEY, None)
                self._write_metadata(state)
        self._refresh_cached_opencode_review(owner_id, model_id, tombstone)
        return True

    def _find_opencode_candidate(self, record: _OpenCodeModelRecord) -> NativeConfiguredModel:
        # The public cache intentionally keeps only reviewed model metadata. Reconstruct the
        # exact candidate from the closed adapter and record fields for versioned review updates.
        return NativeConfiguredModel(
            config_provider_id=record.config_provider_id,
            config_model_id=record.config_model_id,
            native_model_id=record.native_model_id,
            display_name=record.model.display_name,
            package_id=record.package_id,
            adapter=record.adapter,
        )

    def _replace_opencode_record(
        self,
        owner_id: int,
        model_id: str,
        replace_record: Callable[[_OpenCodeModelRecord], _OpenCodeModelRecord],
    ) -> None:
        rows = self._opencode_models.get(owner_id, ())
        self._opencode_models[owner_id] = tuple(
            replace_record(record) if record.model.model_id == model_id else record
            for record in rows
        )

    def _refresh_cached_opencode_review(
        self,
        owner_id: int,
        model_id: str,
        review: Mapping[str, object] | None,
    ) -> None:
        def rebuild(record: _OpenCodeModelRecord) -> _OpenCodeModelRecord:
            candidate = self._find_opencode_candidate(record)
            model = self._opencode_assistant_model(model_id, candidate, record.endpoint, review)
            return _replace_opencode_model(record, model)

        self._replace_opencode_record(owner_id, model_id, rebuild)

    async def _refresh_configured_provider_inventories(
        self, minimum_validity_seconds: float
    ) -> None:
        """Refresh configured supported adapters only on model-read or turn demand."""

        configured = []
        for provider_id in sorted(_MODEL_DISCOVERY_PROVIDERS):
            inventory_is_stale = not self._provider_inventory_fresh(
                provider_id, minimum_validity_seconds
            )
            if self._provider_inventory_configured(provider_id) and inventory_is_stale:
                configured.append(provider_id)
        if not configured:
            return
        async with self._inventory_lock:
            pending = [
                provider_id
                for provider_id in configured
                if self._provider_inventory_configured(provider_id)
                and not self._provider_inventory_fresh(provider_id, minimum_validity_seconds)
                and self._clock() >= self._provider_inventory_retry_at.get(provider_id, 0.0)
            ]
            if not pending:
                return
            await asyncio.gather(
                *(self._refresh_provider_inventory_locked(provider_id) for provider_id in pending),
                return_exceptions=True,
            )

    def _provider_inventory_configured(self, provider_id: str) -> bool:
        """Require keys for vendor APIs, but reviewed endpoint metadata for custom."""

        if provider_id != "custom":
            return self._credential_exists(provider_id)
        state = self._read_metadata().get("custom", {})
        return isinstance(state.get("base_url"), str) and _custom_review_fields_present(state)

    async def _refresh_provider_inventory(
        self,
        provider_id: str,
        *,
        authorization_check: Callable[[], Awaitable[bool] | bool] | None = None,
    ) -> None:
        """Force one configured provider's bounded inventory refresh for admin validation."""

        if authorization_check is not None:
            await _require_live_authorization(authorization_check)
        if provider_id not in _MODEL_DISCOVERY_PROVIDERS:
            raise ProviderUnavailable("provider_adapter_unsupported")
        async with self._inventory_lock:
            if authorization_check is not None:
                await _require_live_authorization(authorization_check)
            await self._refresh_provider_inventory_locked(
                provider_id, authorization_check=authorization_check
            )

    async def _refresh_provider_inventory_locked(
        self,
        provider_id: str,
        *,
        authorization_check: Callable[[], Awaitable[bool] | bool] | None = None,
    ) -> None:
        """Fetch and validate one provider's model rows without retaining response metadata."""

        if authorization_check is not None:
            await _require_live_authorization(authorization_check)
        definition = self._require_provider(provider_id)
        if definition.get("adapter_supported") is not True:
            self._replace_provider_models(provider_id, ())
            raise ProviderUnavailable("provider_adapter_unsupported")
        state = self._read_metadata().get(provider_id, {})
        base_url = state.get("base_url", definition.get("default_base_url"))
        secret = self._read_credential(provider_id)
        if not isinstance(base_url, str):
            self._replace_provider_models(provider_id, ())
            raise ProviderUnavailable("endpoint_not_configured")
        if provider_id == "custom" and not _custom_review_fields_present(state):
            self._replace_provider_models(provider_id, ())
            raise ProviderUnavailable("custom_policy_review_required")
        if secret is None and definition.get("credential_required") is True:
            self._replace_provider_models(provider_id, ())
            raise CredentialRejected("credential_required")
        endpoint, _query = _provider_inventory_target(provider_id, base_url)
        try:
            if authorization_check is not None:
                await _require_live_authorization(authorization_check)
            async with asyncio.timeout(_MODEL_DISCOVERY_TIMEOUT_SECONDS):
                if authorization_check is None:
                    response = await request_public_https(
                        endpoint,
                        headers=_provider_headers(provider_id, secret),
                        timeout_seconds=_MODEL_DISCOVERY_TIMEOUT_SECONDS - 0.5,
                        max_response_bytes=_MAX_VALIDATE_BYTES,
                    )
                else:
                    response = await request_public_https(
                        endpoint,
                        headers=_provider_headers(provider_id, secret),
                        timeout_seconds=_MODEL_DISCOVERY_TIMEOUT_SECONDS - 0.5,
                        max_response_bytes=_MAX_VALIDATE_BYTES,
                        authorization_check=authorization_check,
                    )
            if authorization_check is not None:
                await _require_live_authorization(authorization_check)
            if response.status_code in {401, 403}:
                raise CredentialRejected()
            if response.status_code != 200:
                raise ProviderUnavailable("provider_unavailable")
            payload = json.loads(response.content)
            rows_key = "models" if provider_id == "google" else "data"
            rows = payload.get(rows_key) if isinstance(payload, Mapping) else None
            if not isinstance(rows, list) or len(rows) > 4096:
                raise ProviderUnavailable("provider_response_invalid")
            models = self._parse_provider_model_rows(provider_id, rows)
        except CredentialRejected as exc:
            if authorization_check is not None:
                await _require_live_authorization(authorization_check)
                if exc.code == "oauth_authorization_required":
                    raise
            self._replace_provider_models(provider_id, ())
            self._provider_inventory_status[provider_id] = "validation_failed"
            self._provider_inventory_retry_at[provider_id] = (
                self._clock() + _MODEL_REFRESH_FAILURE_RETRY_SECONDS
            )
            raise
        except ProviderUnavailable:
            if authorization_check is not None:
                await _require_live_authorization(authorization_check)
            self._replace_provider_models(provider_id, ())
            self._provider_inventory_status[provider_id] = "unavailable"
            self._provider_inventory_retry_at[provider_id] = (
                self._clock() + _MODEL_REFRESH_FAILURE_RETRY_SECONDS
            )
            raise
        except (TimeoutError, PublicHTTPError, OSError, ValueError, TypeError) as exc:
            if authorization_check is not None:
                await _require_live_authorization(authorization_check)
                if isinstance(exc, PublicHTTPError) and exc.code in {
                    "provider_authorization_required",
                    "provider_authorization_timeout",
                }:
                    raise CredentialRejected("oauth_authorization_required") from None
            self._replace_provider_models(provider_id, ())
            self._provider_inventory_status[provider_id] = "unavailable"
            self._provider_inventory_retry_at[provider_id] = (
                self._clock() + _MODEL_REFRESH_FAILURE_RETRY_SECONDS
            )
            raise ProviderUnavailable("provider_unavailable") from exc
        if authorization_check is not None:
            await _require_live_authorization(authorization_check)
        self._provider_models[provider_id] = models
        self._provider_inventory_loaded_at[provider_id] = self._clock()
        self._provider_inventory_status[provider_id] = "connected"
        self._provider_inventory_retry_at.pop(provider_id, None)
        self._publish_provider_models()

    def _parse_provider_model_rows(
        self, provider_id: str, rows: list[object]
    ) -> tuple[AssistantModel, ...]:
        """Join discovered opaque model IDs to fixed provider-reviewed policy metadata."""

        definition = self._require_provider(provider_id)
        provider_state = self._read_metadata().get(provider_id, {})
        if provider_id == "custom":
            state = provider_state
            if not _custom_review_fields_present(state):
                raise ProviderUnavailable("custom_policy_review_required")
            policy = _custom_model_policy(state)
        else:
            policy = definition
        configured_endpoint = provider_state.get("base_url", definition.get("default_base_url"))
        endpoint_base = (
            _validate_public_https_url(configured_endpoint)
            if isinstance(configured_endpoint, str)
            else None
        )
        versions = (
            "policy_version",
            "privacy_policy_version",
            "billing_policy_version",
            "terms_url",
            "terms_reviewed_at",
            "privacy_disclosure",
            "cost_disclosure",
            "billing_class",
        )
        if any(not isinstance(policy.get(field), str) or not policy[field] for field in versions):
            raise ProviderUnavailable("model_policy_review_required")
        accepted: dict[str, AssistantModel] = {}
        for row in rows[:4096]:
            if not isinstance(row, Mapping):
                continue
            raw_id = row.get("id")
            if provider_id == "google":
                raw_id = row.get("name")
                methods = row.get("supportedGenerationMethods")
                if not isinstance(methods, list) or "generateContent" not in methods:
                    continue
            if not isinstance(raw_id, str) or not _MODEL_ID.fullmatch(raw_id):
                continue
            if provider_id == "google" and raw_id.startswith("models/"):
                raw_id = raw_id.removeprefix("models/")
                if not _MODEL_ID.fullmatch(raw_id):
                    continue
            model_id = raw_id if raw_id.startswith(f"{provider_id}/") else f"{provider_id}/{raw_id}"
            if len(model_id) > 160 or not _MODEL_ID.fullmatch(model_id):
                continue
            native_model_id = (
                raw_id.removeprefix(f"{provider_id}/")
                if raw_id.startswith(f"{provider_id}/")
                else raw_id
            )
            if (
                self._known_model_exclusion_reason(provider_id, endpoint_base, native_model_id)
                is not None
            ):
                continue
            display_name = row.get("displayName", row.get("name"))
            if (
                not isinstance(display_name, str)
                or not 1 <= len(display_name) <= 160
                or any(ord(character) < 32 or ord(character) == 127 for character in display_name)
            ):
                display_name = raw_id
            accepted.setdefault(
                model_id,
                AssistantModel(
                    model_id=model_id,
                    provider_id=provider_id,
                    display_name=display_name[:160],
                    available=True,
                    free=policy.get("billing_class") == "free",
                    training=policy.get("training") is True,
                    terms_url=str(policy["terms_url"]),
                    terms_reviewed_at=str(policy["terms_reviewed_at"]),
                    policy_version=str(policy["policy_version"]),
                    disclosure=str(policy["privacy_disclosure"]),
                    data_collection_allowed=policy.get("data_collection_allowed") is True,
                    data_collection_default=policy.get("data_collection_default") is True,
                    native_provider_id=str(definition["native_provider_id"]),
                    privacy_policy_version=str(policy["privacy_policy_version"]),
                    billing_policy_version=str(policy["billing_policy_version"]),
                    billing_class=str(policy["billing_class"]),
                    privacy_disclosure=str(policy["privacy_disclosure"]),
                    cost_disclosure=str(policy["cost_disclosure"]),
                ),
            )
        return tuple(accepted.values())

    def _provider_inventory_fresh(self, provider_id: str, minimum_validity_seconds: float) -> bool:
        loaded_at = self._provider_inventory_loaded_at.get(provider_id, 0.0)
        return loaded_at > 0 and self._clock() - loaded_at + minimum_validity_seconds < (
            _MODEL_CACHE_SECONDS
        )

    def _replace_provider_models(
        self, provider_id: str, models: tuple[AssistantModel, ...]
    ) -> None:
        self._provider_models.pop(provider_id, None)
        self._provider_inventory_loaded_at.pop(provider_id, None)
        self._provider_inventory_status.pop(provider_id, None)
        if models:
            self._provider_models[provider_id] = models
            self._provider_inventory_loaded_at[provider_id] = self._clock()
        self._publish_provider_models()

    def _publish_provider_models(self) -> None:
        """Expose only the current provider snapshots to the shared model catalog."""

        if self.catalog is None:
            return
        now = self._clock()
        discovered = tuple(
            model
            for provider_id, rows in self._provider_models.items()
            if now - self._provider_inventory_loaded_at.get(provider_id, 0.0) < _MODEL_CACHE_SECONDS
            for model in rows
        )
        models = (*self._reviewed_native_oauth_models(), *discovered)
        set_native_models = getattr(self.catalog, "set_native_models", None)
        if callable(set_native_models):
            set_native_models(tuple(models))

    def _reviewed_native_oauth_models(self) -> tuple[AssistantModel, ...]:
        """Build only the fixed OAuth model IDs and disclosures checked into the catalog."""

        definition = self._definitions.get("openai-chatgpt")
        reviewed = definition.get("reviewed_models") if definition else None
        if not isinstance(reviewed, Mapping):
            return ()
        required_text = (
            "terms_url",
            "terms_reviewed_at",
            "policy_version",
            "privacy_policy_version",
            "billing_policy_version",
            "privacy_disclosure",
            "cost_disclosure",
        )
        if any(
            not isinstance(definition.get(key), str) or not definition[key] for key in required_text
        ):
            return ()
        models: list[AssistantModel] = []
        for native_model_id, display_name in reviewed.items():
            if (
                not isinstance(native_model_id, str)
                or not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", native_model_id)
                or not isinstance(display_name, str)
                or not 1 <= len(display_name) <= 160
            ):
                continue
            models.append(
                AssistantModel(
                    model_id=f"openai-chatgpt/{native_model_id}",
                    provider_id="openai-chatgpt",
                    display_name=display_name,
                    available=True,
                    free=False,
                    training=True,
                    terms_url=str(definition["terms_url"]),
                    terms_reviewed_at=str(definition["terms_reviewed_at"]),
                    policy_version=str(definition["privacy_policy_version"]),
                    disclosure=str(definition["privacy_disclosure"]),
                    data_collection_allowed=True,
                    data_collection_default=False,
                    native_provider_id="openai",
                    privacy_policy_version=str(definition["privacy_policy_version"]),
                    billing_policy_version=str(definition["billing_policy_version"]),
                    billing_class="unknown",
                    privacy_disclosure=str(definition["privacy_disclosure"]),
                    cost_disclosure=str(definition["cost_disclosure"]),
                )
            )
        return tuple(models)

    def _invalidate_provider_inventory(self, provider_id: str) -> None:
        """Expire discovery immediately after endpoint, credential, or model changes."""

        if provider_id in _MODEL_DISCOVERY_PROVIDERS:
            self._replace_provider_models(provider_id, ())
            self._provider_inventory_retry_at.pop(provider_id, None)

    def model_policy_state(
        self, model_id: str, *, owner_id: int | None = None
    ) -> dict[str, object]:
        """Return one exact model's persisted admin approval state and safe policy metadata."""

        model = self._reviewed_model(model_id, owner_id=owner_id)
        current = self._current_policy_versions(model)
        is_opencode = getattr(model, "provider_id", None) == "opencode-console"
        opencode_record = (
            self._opencode_record(model_id, owner_id=owner_id)
            if is_opencode and owner_id is not None
            else None
        )
        review = (
            self._read_opencode_reviews(owner_id).get(model_id)
            if is_opencode and owner_id is not None
            else None
        )
        review_revision = (
            int(review["revision"])
            if isinstance(review, Mapping)
            and opencode_record is not None
            and review.get("config_fingerprint") == opencode_record.config_fingerprint
            else 0
        )
        with self._lock:
            state = self._read_metadata()
            endpoint_identity = (
                opencode_record.config_fingerprint
                if opencode_record is not None
                else self._endpoint_identity(model, state)
            )
            stored = state.get(_MODEL_POLICY_KEY, {}).get(model_id)
            if stored is None:
                record = self._default_model_policy(model, current, endpoint_identity)
                if record["enabled"] is True:
                    policies = dict(state.get(_MODEL_POLICY_KEY, {}))
                    policies[model_id] = record
                    state[_MODEL_POLICY_KEY] = policies
                    self._write_metadata(state)
            else:
                record = dict(stored)
        summary = self._reviewed_model_summary(model)
        policy_generation = self._consent_policy_version(summary, record, endpoint_identity)
        provider_id = str(getattr(model, "provider_id", ""))
        definition = self._definitions.get(provider_id, {})
        model_available = getattr(model, "available", False) is True
        acknowledgements_current = (
            record["acknowledged_privacy_policy_version"] == current["privacy_policy_version"]
            and record["acknowledged_billing_policy_version"] == current["billing_policy_version"]
        )
        endpoint_identity_current = (
            endpoint_identity is not None
            and record.get("endpoint_identity_sha256") == endpoint_identity
        )
        enabled = record["enabled"] is True
        adapter_supported = (
            _opencode_adapter_is_supported(self._opencode_record(model_id, owner_id=owner_id))
            if is_opencode and owner_id is not None
            else definition.get("adapter_supported") is True
        )
        connection_ready = self._model_connection_ready(model, definition, owner_id=owner_id)
        usable = bool(
            model_available
            and enabled
            and acknowledgements_current
            and endpoint_identity_current
            and adapter_supported
            and connection_ready
        )
        availability_reason = None
        if not model_available:
            availability_reason = (
                "model_policy_review_required"
                if is_opencode
                and getattr(model, "availability_reason", None) == "model_policy_review_required"
                else "model_unavailable"
            )
        elif not adapter_supported:
            availability_reason = "provider_adapter_unsupported"
        elif not acknowledgements_current:
            availability_reason = "policy_acknowledgement_required"
        elif not endpoint_identity_current:
            availability_reason = "provider_endpoint_changed"
        elif not enabled:
            availability_reason = "model_disabled_by_admin"
        elif not connection_ready:
            availability_reason = (
                "oauth_connection_required"
                if provider_id == "openai-chatgpt"
                else "provider_not_ready"
            )
        return {
            **summary,
            **record,
            "policy_version": policy_generation,
            "review_policy_version": summary["policy_version"],
            "endpoint_identity_sha256": record.get("endpoint_identity_sha256"),
            "current_endpoint_identity_sha256": endpoint_identity,
            "review_revision": review_revision,
            "usable": usable,
            "availability_reason": availability_reason,
        }

    def update_model_policy(
        self,
        model_id: str,
        *,
        enabled: bool,
        acknowledged_privacy_policy_version: str | None,
        acknowledged_billing_policy_version: str | None,
        expected_revision: int,
        owner_id: int | None = None,
    ) -> dict[str, object]:
        """CAS-update one exact reviewed model's admin enablement and policy acknowledgements."""

        if type(enabled) is not bool:
            raise ProviderUnavailable("model_policy_invalid")
        if type(expected_revision) is not int or not 0 <= expected_revision <= _MAX_POLICY_REVISION:
            raise ProviderUnavailable("model_policy_invalid")
        model = self._reviewed_model(model_id, owner_id=owner_id)
        is_opencode = getattr(model, "provider_id", None) == "opencode-console"
        current = self._current_policy_versions(model)
        if enabled:
            self._require_reviewed_disclosures(model)
        provider_id = str(getattr(model, "provider_id", ""))
        definition = self._definitions.get(provider_id)
        if enabled and is_opencode:
            record = self._opencode_record(model_id, owner_id=owner_id)
            if not _opencode_adapter_is_supported(record):
                raise ProviderUnavailable("provider_adapter_unsupported")
        elif enabled and (definition is None or definition.get("adapter_supported") is not True):
            raise ProviderUnavailable("provider_adapter_unsupported")
        if not bool(getattr(model, "available", False)) and enabled:
            raise ProviderUnavailable("model_unavailable")
        if enabled and acknowledged_privacy_policy_version != current["privacy_policy_version"]:
            raise ProviderUnavailable("privacy_policy_ack_required")
        if enabled and acknowledged_billing_policy_version != current["billing_policy_version"]:
            raise ProviderUnavailable("billing_policy_ack_required")
        current_privacy_version = current["privacy_policy_version"]
        current_billing_version = current["billing_policy_version"]
        if (
            acknowledged_privacy_policy_version is not None
            and acknowledged_privacy_policy_version != current_privacy_version
        ):
            raise ProviderUnavailable("privacy_policy_version_mismatch")
        if (
            acknowledged_billing_policy_version is not None
            and acknowledged_billing_policy_version != current_billing_version
        ):
            raise ProviderUnavailable("billing_policy_version_mismatch")

        with self._lock:
            state = self._read_metadata()
            policies = dict(state.get(_MODEL_POLICY_KEY, {}))
            previous = policies.get(model_id)
            if previous is None:
                previous = self._default_model_policy(
                    model,
                    current,
                    (
                        self._opencode_record(model_id, owner_id=owner_id).config_fingerprint
                        if is_opencode and owner_id is not None
                        else self._endpoint_identity(model, state)
                    ),
                )
            if previous["revision"] != expected_revision:
                raise ProviderUnavailable("model_policy_conflict")
            endpoint_identity = (
                self._opencode_record(model_id, owner_id=owner_id).config_fingerprint
                if is_opencode and owner_id is not None
                else self._endpoint_identity(model, state)
            )
            if enabled and endpoint_identity is None:
                raise ProviderUnavailable("provider_endpoint_not_configured")
            next_privacy = acknowledged_privacy_policy_version
            next_billing = acknowledged_billing_policy_version
            if not enabled:
                next_privacy = (
                    acknowledged_privacy_policy_version
                    if acknowledged_privacy_policy_version is not None
                    else previous["acknowledged_privacy_policy_version"]
                )
                next_billing = (
                    acknowledged_billing_policy_version
                    if acknowledged_billing_policy_version is not None
                    else previous["acknowledged_billing_policy_version"]
                )
            candidate = {
                "enabled": enabled,
                "acknowledged_privacy_policy_version": next_privacy,
                "acknowledged_billing_policy_version": next_billing,
                "revision": expected_revision,
                "endpoint_identity_sha256": (
                    endpoint_identity if enabled else previous.get("endpoint_identity_sha256")
                ),
            }
            comparable_previous = {key: previous.get(key) for key in candidate}
            if candidate != comparable_previous:
                if expected_revision == _MAX_POLICY_REVISION:
                    raise ProviderUnavailable("model_policy_revision_exhausted")
                candidate["revision"] = expected_revision + 1
                policies[model_id] = candidate
                state[_MODEL_POLICY_KEY] = policies
                self._write_metadata(state)
            else:
                candidate = comparable_previous
        return self.model_policy_state(model_id, owner_id=owner_id)

    def proxy_chat_completion(
        self,
        provider_id: str,
        model_id: str,
        body: Mapping[str, object],
        *,
        owner_id: int | None = None,
        app_session_id: str | None = None,
        native_session_id: str | None = None,
        native_user_agent: str | None = None,
        native_client: str | None = None,
        native_opencode_session: str | None = None,
        native_opencode_project: str | None = None,
        native_session_affinity: str | None = None,
        native_session_id_alias: str | None = None,
        authorization_check: Callable[[], Awaitable[bool] | bool] | None = None,
        app_tools: list[dict[str, object]] | None = None,
    ) -> AsyncIterator[bytes]:
        """Return a bounded sanitized SSE iterator for one reviewed native V2 model request."""

        if provider_id == "opencode-console":
            return self._proxy_opencode_compatible_chat(
                model_id,
                body,
                owner_id=owner_id,
                app_session_id=app_session_id,
                authorization_check=authorization_check,
                app_tools=app_tools,
            )

        definition = self._require_provider(provider_id)
        if provider_id == "openai-chatgpt":
            raise ProviderUnavailable("provider_request_invalid")
        if provider_id != "opencode-zen" and definition.get("protocol") != "openai-compatible-chat":
            raise ProviderUnavailable("provider_adapter_unsupported")
        native_zen_headers: dict[str, str] = {}
        if provider_id == "opencode-zen":
            validated_identity = _native_zen_upstream_headers(
                native_user_agent,
                native_client,
                native_opencode_session,
                native_opencode_project,
                native_session_affinity,
                native_session_id_alias,
            )
            if validated_identity is None:
                raise ProviderUnavailable("provider_request_invalid")
            native_zen_headers = validated_identity
        model = self.catalog.get_model(model_id) if self.catalog is not None else None
        if (
            model is None
            or not model.available
            or model.provider_id != provider_id
            or not isinstance(body, Mapping)
            or body.get("model") != "assistant-selected"
            or body.get("stream") is not True
            or set(body)
            - {
                "model",
                "messages",
                "stream",
                "temperature",
                "max_tokens",
                "tools",
                "tool_choice",
                "store",
                "stream_options",
            }
            or ("store" in body and body.get("store") is not False)
        ):
            raise ProviderUnavailable("model_unavailable")
        max_tokens = body.get("max_tokens", native_output_token_budget())
        validated_max_tokens = validated_output_token_count(max_tokens)
        if validated_max_tokens is None:
            raise ProviderUnavailable("provider_request_invalid")
        stream_options = body.get("stream_options")
        if "stream_options" in body and (
            not isinstance(stream_options, Mapping)
            or dict(stream_options) != {"include_usage": True}
        ):
            raise ProviderUnavailable("provider_request_invalid")
        messages = body.get("messages")
        if not isinstance(messages, list) or not 1 <= len(messages) <= 32:
            raise ProviderUnavailable("provider_request_invalid")
        if app_tools is not None or provider_id == "opencode-zen":
            if not isinstance(app_tools, list) or not 1 <= len(app_tools) <= 11:
                raise ProviderUnavailable("provider_request_invalid")
            allowed_tools = _native_application_tools(app_tools, protocol="openai-compatible-chat")
            clean_tools, declared_tool_names = _validate_native_compatible_tools(
                body.get("tools"), allowed_tools
            )
        else:
            clean_tools, declared_tool_names = _validated_tools(body.get("tools"))
        clean_messages = _validated_messages(messages, declared_tool_names)
        tool_choice = body.get("tool_choice")
        if tool_choice is not None and (
            not isinstance(tool_choice, str)
            or tool_choice not in {"auto", "none", *declared_tool_names}
        ):
            raise ProviderUnavailable("provider_request_invalid")

        config = self._read_metadata().get(provider_id, {})
        base_url = config.get("base_url", definition.get("default_base_url"))
        if not isinstance(base_url, str):
            raise ProviderUnavailable("endpoint_not_configured")
        canonical_base = _validate_public_https_url(base_url)
        native_model_id = _upstream_model_id(model_id, provider_id)
        if (
            self._known_model_exclusion_reason(provider_id, canonical_base, native_model_id)
            is not None
        ):
            raise ProviderUnavailable("model_unavailable")
        secret = self._read_credential(provider_id)
        if definition["credential_required"] and secret is None:
            raise CredentialRejected("credential_required")
        if provider_id == "anthropic":
            raise ProviderUnavailable("provider_adapter_unsupported")
        if provider_id not in {"opencode-zen", "openai", "google", "custom"}:
            raise ProviderUnavailable("provider_adapter_unsupported")

        upstream: dict[str, object] = {
            "model": _upstream_model_id(model_id, provider_id),
            "messages": clean_messages,
            "stream": True,
            # OpenCode's observed native request explicitly sets this, and the app also
            # enforces it here when a compatible client omits the field.
            "store": False,
        }
        if stream_options is not None:
            upstream["stream_options"] = {"include_usage": True}
        for parameter_name in ("temperature", "tool_choice"):
            if parameter_name in body:
                upstream[parameter_name] = body[parameter_name]
        upstream["max_tokens"] = validated_max_tokens
        if clean_tools is not None:
            upstream["tools"] = clean_tools
        encoded = json.dumps(
            upstream, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        if len(encoded) > 262_144:
            raise ProviderUnavailable("provider_request_invalid")
        endpoint = canonical_base + "/chat/completions"
        headers = {
            "accept": "text/event-stream",
            **_provider_headers(provider_id, secret),
            **native_zen_headers,
        }
        secret_identity = self._provider_secret_identity(secret)

        async def check_current() -> None:
            if not callable(authorization_check):
                raise CredentialRejected("oauth_authorization_required")
            await _require_live_authorization(authorization_check)
            if not secrets.compare_digest(
                self._provider_secret_identity(self._read_credential(provider_id)),
                secret_identity,
            ):
                raise CredentialRejected("provider_credential_changed")

        async def sanitized_chunks():
            pending = bytearray()
            event_data: list[bytes] = []
            total_output = 0
            tool_call_state = _OpenAIToolCallStreamState()
            secret_guard = _SecretStreamGuard(secret, protocol="openai-compatible-chat")

            async def emit_event(data_lines: list[bytes]):
                nonlocal total_output
                if not data_lines:
                    return None
                raw = b"\n".join(data_lines)
                try:
                    text = raw.decode("utf-8", "strict")
                except UnicodeDecodeError as exc:
                    raise ProviderUnavailable("provider_response_invalid") from exc
                safe = _sanitize_openai_sse_data(
                    text, declared_tool_names=declared_tool_names, state=tool_call_state
                )
                if safe is None:
                    return None
                frame = b"data: " + safe.encode("utf-8") + b"\n\n"
                return frame

            await check_current()
            async for chunk in _stream_with_authorization(
                endpoint,
                authorization_check=check_current,
                headers=headers,
                body=encoded,
                timeout_seconds=120.0,
                max_response_bytes=1_048_576,
            ):
                await check_current()
                pending.extend(chunk)
                if len(pending) > 65_536:
                    raise ProviderUnavailable("provider_response_invalid")
                while b"\n" in pending:
                    line, _, remainder = pending.partition(b"\n")
                    pending = bytearray(remainder)
                    line = line.rstrip(b"\r")
                    if not line:
                        frame = await emit_event(event_data)
                        event_data = []
                        if frame is not None:
                            for safe_frame in secret_guard.push(frame):
                                await check_current()
                                total_output += len(safe_frame)
                                if total_output > 1_048_576:
                                    raise ProviderUnavailable("provider_response_too_large")
                                for start in range(0, len(safe_frame), _MAX_PROXY_CHUNK_BYTES):
                                    await check_current()
                                    yield safe_frame[start : start + _MAX_PROXY_CHUNK_BYTES]
                    elif line.startswith(b"data:"):
                        event_data.append(line[5:].lstrip())
                        if sum(len(part) for part in event_data) > 65_536:
                            raise ProviderUnavailable("provider_response_invalid")
            if pending:
                line = bytes(pending).rstrip(b"\r")
                if line.startswith(b"data:"):
                    event_data.append(line[5:].lstrip())
            frame = await emit_event(event_data)
            if frame is not None:
                for safe_frame in secret_guard.push(frame):
                    await check_current()
                    total_output += len(safe_frame)
                    if total_output > 1_048_576:
                        raise ProviderUnavailable("provider_response_too_large")
                    for start in range(0, len(safe_frame), _MAX_PROXY_CHUNK_BYTES):
                        await check_current()
                        yield safe_frame[start : start + _MAX_PROXY_CHUNK_BYTES]
            tool_call_state.require_complete()
            for safe_frame in secret_guard.finish():
                await check_current()
                total_output += len(safe_frame)
                if total_output > 1_048_576:
                    raise ProviderUnavailable("provider_response_too_large")
                for start in range(0, len(safe_frame), _MAX_PROXY_CHUNK_BYTES):
                    await check_current()
                    yield safe_frame[start : start + _MAX_PROXY_CHUNK_BYTES]

        return sanitized_chunks()

    def _proxy_opencode_compatible_chat(
        self,
        model_id: str,
        body: Mapping[str, object],
        *,
        owner_id: int | None,
        app_session_id: str | None,
        authorization_check: Callable[[], Awaitable[bool] | bool] | None,
        app_tools: list[dict[str, object]] | None,
    ) -> AsyncIterator[bytes]:
        """Proxy one reviewed Console-compatible model through the app-owned key vault."""

        if not isinstance(app_tools, list) or not 1 <= len(app_tools) <= 11:
            raise ProviderUnavailable("provider_request_invalid")
        record, upstream_provider, definition, policy_version = self._opencode_proxy_context(
            model_id,
            owner_id=owner_id,
            app_session_id=app_session_id,
            authorization_check=authorization_check,
            protocol="openai-compatible-chat",
        )
        if record.adapter.integration_id is not None:
            raise ProviderUnavailable("provider_adapter_unsupported")
        upstream = _validated_native_provider_body(
            "openai-compatible-chat",
            body,
            model_alias="assistant-selected",
            upstream_model_id=record.native_model_id,
            app_tools=app_tools,
        )
        encoded = _encode_provider_request(upstream)
        return self._opencode_proxy_stream(
            record,
            upstream_provider,
            definition,
            encoded,
            policy_version=policy_version,
            authorization_check=authorization_check,
            compatible_chat=True,
        )

    def _opencode_proxy_context(
        self,
        model_id: str,
        *,
        owner_id: int | None,
        app_session_id: str | None,
        authorization_check: Callable[[], Awaitable[bool] | bool] | None,
        protocol: str,
    ) -> tuple[_OpenCodeModelRecord, str, dict[str, Any], str]:
        """Resolve an owner-scoped model and its fixed protocol before accepting a turn."""

        if (
            owner_id is None
            or type(owner_id) is not int
            or not isinstance(app_session_id, str)
            or not 1 <= len(app_session_id) <= 128
            or not callable(authorization_check)
        ):
            raise CredentialRejected("oauth_authorization_required")
        record = self._opencode_record(model_id, owner_id=owner_id)
        if record.adapter.protocol != protocol or not _opencode_adapter_is_supported(record):
            raise ProviderUnavailable("provider_adapter_unsupported")
        policy = self.model_policy_state(model_id, owner_id=owner_id)
        if policy.get("usable") is not True:
            raise ProviderUnavailable("model_unavailable")
        upstream_provider = record.adapter.integration_id or "custom"
        definition = self._require_provider(upstream_provider)
        if (
            definition.get("adapter_supported") is not True
            or definition.get("protocol") != protocol
            or (upstream_provider == "custom" and protocol != "openai-compatible-chat")
        ):
            raise ProviderUnavailable("provider_adapter_unsupported")
        return record, upstream_provider, definition, str(policy["policy_version"])

    def _opencode_proxy_stream(
        self,
        record: _OpenCodeModelRecord,
        upstream_provider: str,
        definition: Mapping[str, object],
        encoded_body: bytes,
        *,
        policy_version: str,
        authorization_check: Callable[[], Awaitable[bool] | bool] | None,
        compatible_chat: bool,
    ) -> AsyncIterator[bytes]:
        """Stream only after refreshing the bound Console snapshot and rechecking its lease."""

        if len(encoded_body) > 262_144:
            raise ProviderUnavailable("provider_request_invalid")
        descriptor = record.adapter
        base_endpoint = record.endpoint.rstrip("/")
        if descriptor.protocol == "google-generative-language":
            encoded_model_id = quote(record.native_model_id, safe="-._~")
            suffix = descriptor.route_suffix.format(model=encoded_model_id)
        else:
            suffix = descriptor.route_suffix
        endpoint = base_endpoint + "/" + suffix
        if descriptor.upstream_query:
            endpoint += "?" + urlencode(descriptor.upstream_query)

        async def guarded_chunks():
            assert authorization_check is not None
            await _require_live_authorization(authorization_check)
            await self.ensure_opencode_model_inventory(
                owner_id=record.owner_id,
                authorization_check=authorization_check,
                force=True,
            )
            current_record = self._opencode_record(record.model.model_id, owner_id=record.owner_id)
            if (
                current_record.config_fingerprint != record.config_fingerprint
                or current_record.adapter != descriptor
                or self.model_policy_state(record.model.model_id, owner_id=record.owner_id).get(
                    "policy_version"
                )
                != policy_version
            ):
                raise ProviderUnavailable("model_inventory_changed")
            if not self._opencode_execution_usable(record, policy_version):
                raise ProviderUnavailable("model_unavailable")

            secret = self._read_credential(upstream_provider)
            if definition.get("credential_required") is True and secret is None:
                raise CredentialRejected("credential_required")
            if upstream_provider != "custom" and secret is None:
                raise CredentialRejected("credential_required")
            secret_identity = self._provider_secret_identity(secret)
            headers = {"accept": "text/event-stream", **dict(descriptor.upstream_static_headers)}
            if secret is not None:
                if descriptor.upstream_auth_scheme == "bearer":
                    headers[descriptor.upstream_auth_header] = f"Bearer {secret}"
                else:
                    headers[descriptor.upstream_auth_header] = secret

            async def check_current() -> None:
                await _require_live_authorization(authorization_check)
                if not self._opencode_execution_usable(record, policy_version):
                    raise CredentialRejected("oauth_authorization_required")
                if not secrets.compare_digest(
                    self._provider_secret_identity(self._read_credential(upstream_provider)),
                    secret_identity,
                ):
                    raise CredentialRejected("provider_credential_changed")

            total = 0
            pending = bytearray()
            secret_guard = _SecretStreamGuard(secret, protocol=descriptor.protocol)
            tool_call_state = _OpenAIToolCallStreamState()
            declared_tool_names: set[str] = set()
            if compatible_chat:
                upstream_request = json.loads(encoded_body)
                raw_tools = (
                    upstream_request.get("tools") if isinstance(upstream_request, Mapping) else None
                )
                if isinstance(raw_tools, list):
                    declared_tool_names = {
                        str(item["function"]["name"])
                        for item in raw_tools
                        if isinstance(item, Mapping)
                        and isinstance(item.get("function"), Mapping)
                        and isinstance(item["function"].get("name"), str)
                    }

            await check_current()
            async for chunk in _stream_with_authorization(
                endpoint,
                authorization_check=check_current,
                headers=headers,
                body=encoded_body,
                timeout_seconds=120.0,
                max_response_bytes=1_048_576,
            ):
                if not isinstance(chunk, bytes) or not chunk or len(chunk) > _MAX_PROXY_CHUNK_BYTES:
                    raise ProviderUnavailable("provider_response_invalid")
                total += len(chunk)
                if total > 1_048_576:
                    raise ProviderUnavailable("provider_response_too_large")
                pending.extend(chunk)
                if len(pending) > 65_536 and _sse_event_boundary(pending) is None:
                    raise ProviderUnavailable("provider_response_invalid")
                while True:
                    boundary = _sse_event_boundary(pending)
                    if boundary is None:
                        break
                    _start, end = boundary
                    if end > 65_536:
                        raise ProviderUnavailable("provider_response_invalid")
                    frame = bytes(pending[:end])
                    del pending[:end]
                    if compatible_chat:
                        frame = _sanitize_compatible_frame(
                            frame,
                            declared_tool_names=declared_tool_names,
                            state=tool_call_state,
                        )
                        if frame is None:
                            continue
                    safe_frames = secret_guard.push(frame)
                    for safe_frame in safe_frames:
                        await check_current()
                        yield safe_frame
            if pending:
                frame = bytes(pending)
                if compatible_chat:
                    frame = _sanitize_compatible_frame(
                        frame,
                        declared_tool_names=declared_tool_names,
                        state=tool_call_state,
                    )
                if frame is not None:
                    for safe_frame in secret_guard.push(frame):
                        await check_current()
                        yield safe_frame
            if compatible_chat:
                tool_call_state.require_complete()
            for safe_frame in secret_guard.finish():
                await check_current()
                yield safe_frame

        return guarded_chunks()

    def _opencode_execution_usable(self, record: _OpenCodeModelRecord, policy_version: str) -> bool:
        """Recheck this owner's reviewed config and current policy before forwarding data."""

        try:
            current = self._opencode_record(record.model.model_id, owner_id=record.owner_id)
            state = self.model_policy_state(record.model.model_id, owner_id=record.owner_id)
        except ProviderUnavailable:
            return False
        return bool(
            current.config_fingerprint == record.config_fingerprint
            and current.adapter == record.adapter
            and state.get("usable") is True
            and state.get("policy_version") == policy_version
        )

    def _provider_secret_identity(self, secret: str | None) -> str:
        if secret is None:
            return "none"
        return hmac.new(self._vault_key(), secret.encode("utf-8"), hashlib.sha256).hexdigest()

    def proxy_native_stream(
        self,
        provider_id: str,
        model_id: str,
        body: Mapping[str, object],
        *,
        path_model_id: str | None,
        query: tuple[tuple[str, str], ...],
        app_tools: list[dict[str, object]],
        owner_id: int | None = None,
        app_session_id: str | None = None,
        native_session_id: str | None = None,
        authorization_check: Callable[[], Awaitable[bool] | bool] | None = None,
    ) -> AsyncIterator[bytes]:
        """Proxy one exact native vendor protocol while keeping credentials app-side.

        The protocol, endpoint and upstream credential header are derived from the closed
        catalog and adapter registry. The native URL/model alias and query must match the
        package's observed request exactly; no caller-selected upstream route is accepted.
        """

        if provider_id == "opencode-console":
            return self._proxy_opencode_native_stream(
                model_id,
                body,
                path_model_id=path_model_id,
                query=query,
                app_tools=app_tools,
                owner_id=owner_id,
                app_session_id=app_session_id,
                authorization_check=authorization_check,
            )

        definition = self._require_provider(provider_id)
        try:
            descriptor = resolve_native_adapter(
                str(definition["adapter_id"]), str(definition["native_provider_id"])
            )
        except (KeyError, ValueError) as exc:
            raise ProviderUnavailable("provider_adapter_unsupported") from exc
        if (
            descriptor.protocol
            not in {
                "openai-responses",
                "anthropic-messages",
                "google-generative-language",
            }
            or definition.get("protocol") != descriptor.protocol
            or definition.get("adapter_supported") is not True
            or tuple(query) != descriptor.fixed_query
        ):
            raise ProviderUnavailable("provider_request_invalid")
        model = self.catalog.get_model(model_id) if self.catalog is not None else None
        if model is None or not model.available or model.provider_id != provider_id:
            raise ProviderUnavailable("model_unavailable")
        alias = "assistant-selected"
        if descriptor.protocol == "google-generative-language":
            if path_model_id != alias:
                raise ProviderUnavailable("provider_request_invalid")
        elif path_model_id is not None:
            raise ProviderUnavailable("provider_request_invalid")

        upstream_body = _validated_native_provider_body(
            descriptor.protocol,
            body,
            model_alias=alias,
            upstream_model_id=_upstream_model_id(model_id, provider_id),
            app_tools=app_tools,
        )
        upstream_model_id = _upstream_model_id(model_id, provider_id)
        encoded = json.dumps(
            upstream_body, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        if len(encoded) > 262_144:
            raise ProviderUnavailable("provider_request_invalid")

        oauth_backed = provider_id == "openai-chatgpt"
        if oauth_backed:
            if (
                owner_id is None
                or type(owner_id) is not int
                or not isinstance(app_session_id, str)
                or not 1 <= len(app_session_id) <= 128
                or not isinstance(native_session_id, str)
                or _NATIVE_SESSION_ID.fullmatch(native_session_id) is None
                or not callable(authorization_check)
            ):
                raise CredentialRejected("oauth_authorization_required")
            secret = None
            canonical_base = "https://chatgpt.com/backend-api/codex"
        else:
            state = self._read_metadata().get(provider_id, {})
            base_url = state.get("base_url", definition.get("default_base_url"))
            if not isinstance(base_url, str):
                raise ProviderUnavailable("endpoint_not_configured")
            canonical_base = _validate_public_https_url(base_url).rstrip("/")
            secret = self._read_credential(provider_id)
        if definition.get("credential_required") is True and secret is None and not oauth_backed:
            raise CredentialRejected("credential_required")
        if secret is None and not oauth_backed:
            raise CredentialRejected("credential_required")
        if descriptor.protocol == "google-generative-language":
            suffix = descriptor.route_suffix.format(model=upstream_model_id)
        else:
            suffix = descriptor.route_suffix
        endpoint = canonical_base + "/" + suffix
        if descriptor.upstream_query:
            endpoint += "?" + urlencode(descriptor.upstream_query)
        if oauth_backed:
            endpoint = _CHATGPT_UPSTREAM_URL
            upstream_credential = None
        elif descriptor.upstream_auth_scheme == "bearer":
            upstream_credential = f"Bearer {secret}"
        else:
            upstream_credential = secret
        headers = {"accept": "text/event-stream", **dict(descriptor.upstream_static_headers)}
        if oauth_backed:
            headers.update(
                {
                    "authorization": "",
                    "originator": "opencode",
                    "session-id": native_session_id or "",
                    "x-codex-beta-features": "remote_compaction_v2",
                }
            )
        else:
            headers[descriptor.upstream_auth_header] = upstream_credential or ""

        secret_identity = self._provider_secret_identity(secret)

        async def check_current() -> None:
            if not callable(authorization_check):
                raise CredentialRejected("oauth_authorization_required")
            await _require_live_authorization(authorization_check)
            if not oauth_backed and not secrets.compare_digest(
                self._provider_secret_identity(self._read_credential(provider_id)),
                secret_identity,
            ):
                raise CredentialRejected("provider_credential_changed")

        async def guarded_chunks():
            """Validate each complete SSE event before releasing any of its bytes."""

            oauth_credential: dict[str, object] | None = None
            if oauth_backed:
                assert owner_id is not None and authorization_check is not None
                if self.model_policy_state(model_id, owner_id=owner_id).get("usable") is not True:
                    raise ProviderUnavailable("model_unavailable")
                await _require_live_authorization(authorization_check)
                selected = self._owned_chatgpt_credential(owner_id)
                if selected is None:
                    raise CredentialRejected("oauth_connection_required")
                method_id, oauth_credential = selected
                oauth_credential = await self._refresh_chatgpt_credential_if_needed(
                    owner_id,
                    method_id,
                    oauth_credential,
                    authorization_check,
                )
                access_token = oauth_credential.get("access")
                if not isinstance(access_token, str):
                    raise CredentialRejected("oauth_connection_required")
                headers["authorization"] = f"Bearer {access_token}"
                account_id = (
                    oauth_credential.get("metadata", {}).get("accountID")
                    if isinstance(oauth_credential.get("metadata"), Mapping)
                    else None
                )
                if isinstance(account_id, str) and account_id:
                    headers["chatgpt-account-id"] = account_id
                await check_current()
            total = 0
            pending = bytearray()
            secret_guard = _SecretStreamGuard(
                str(oauth_credential["access"]) if oauth_credential is not None else secret,
                protocol=descriptor.protocol,
            )
            await check_current()
            async for chunk in _stream_with_authorization(
                endpoint,
                authorization_check=check_current,
                headers=headers,
                body=encoded,
                timeout_seconds=120.0,
                max_response_bytes=1_048_576,
            ):
                await check_current()
                if not isinstance(chunk, bytes) or not chunk or len(chunk) > _MAX_PROXY_CHUNK_BYTES:
                    raise ProviderUnavailable("provider_response_invalid")
                total += len(chunk)
                if total > 1_048_576:
                    raise ProviderUnavailable("provider_response_too_large")
                pending.extend(chunk)
                if len(pending) > 65_536 and _sse_event_boundary(pending) is None:
                    raise ProviderUnavailable("provider_response_invalid")
                while True:
                    boundary = _sse_event_boundary(pending)
                    if boundary is None:
                        break
                    _start, end = boundary
                    if end > 65_536:
                        raise ProviderUnavailable("provider_response_invalid")
                    frame = bytes(pending[:end])
                    del pending[:end]
                    for safe_frame in secret_guard.push(frame):
                        await check_current()
                        for offset in range(0, len(safe_frame), _MAX_PROXY_CHUNK_BYTES):
                            await check_current()
                            yield safe_frame[offset : offset + _MAX_PROXY_CHUNK_BYTES]
            if pending:
                frame = bytes(pending)
                for safe_frame in secret_guard.push(frame):
                    await check_current()
                    for offset in range(0, len(safe_frame), _MAX_PROXY_CHUNK_BYTES):
                        await check_current()
                        yield safe_frame[offset : offset + _MAX_PROXY_CHUNK_BYTES]
            for safe_frame in secret_guard.finish():
                await check_current()
                for offset in range(0, len(safe_frame), _MAX_PROXY_CHUNK_BYTES):
                    await check_current()
                    yield safe_frame[offset : offset + _MAX_PROXY_CHUNK_BYTES]

        return guarded_chunks()

    def _proxy_opencode_native_stream(
        self,
        model_id: str,
        body: Mapping[str, object],
        *,
        path_model_id: str | None,
        query: tuple[tuple[str, str], ...],
        app_tools: list[dict[str, object]],
        owner_id: int | None,
        app_session_id: str | None,
        authorization_check: Callable[[], Awaitable[bool] | bool] | None,
    ) -> AsyncIterator[bytes]:
        """Dispatch only the exact vendor protocol and route captured in this owner's review."""

        try:
            initial_record = (
                self._opencode_record(model_id, owner_id=owner_id) if owner_id is not None else None
            )
        except ProviderUnavailable:
            initial_record = None
        if initial_record is None:
            raise ProviderUnavailable("model_unavailable")
        protocol = initial_record.adapter.protocol
        if protocol == "openai-compatible-chat":
            raise ProviderUnavailable("provider_request_invalid")
        record, upstream_provider, definition, policy_version = self._opencode_proxy_context(
            model_id,
            owner_id=owner_id,
            app_session_id=app_session_id,
            authorization_check=authorization_check,
            protocol=protocol,
        )
        descriptor = record.adapter
        if (
            protocol
            not in {
                "openai-responses",
                "anthropic-messages",
                "google-generative-language",
            }
            or tuple(query) != descriptor.fixed_query
        ):
            raise ProviderUnavailable("provider_request_invalid")
        if protocol == "google-generative-language":
            if path_model_id != "assistant-selected":
                raise ProviderUnavailable("provider_request_invalid")
        elif path_model_id is not None:
            raise ProviderUnavailable("provider_request_invalid")
        upstream = _validated_native_provider_body(
            protocol,
            body,
            model_alias="assistant-selected",
            upstream_model_id=record.native_model_id,
            app_tools=app_tools,
        )
        encoded = _encode_provider_request(upstream)
        return self._opencode_proxy_stream(
            record,
            upstream_provider,
            definition,
            encoded,
            policy_version=policy_version,
            authorization_check=authorization_check,
            compatible_chat=False,
        )

    def _validated_model(self, provider_id: str, model_id: str) -> str:
        if not isinstance(model_id, str) or not _MODEL_ID.fullmatch(model_id):
            raise ProviderUnavailable("invalid_model_id")
        model = self.catalog.get_model(model_id) if self.catalog is not None else None
        if model is None or not model.available or model.provider_id != provider_id:
            raise ProviderUnavailable("model_unavailable")
        definition = self._definitions.get(provider_id)
        provider_state = self._read_metadata().get(provider_id, {})
        endpoint = (
            provider_state.get("base_url", definition.get("default_base_url"))
            if definition is not None
            else None
        )
        canonical_endpoint = (
            _validate_public_https_url(endpoint) if isinstance(endpoint, str) else None
        )
        if (
            self._known_model_exclusion_reason(
                provider_id, canonical_endpoint, _upstream_model_id(model_id, provider_id)
            )
            is not None
        ):
            raise ProviderUnavailable("model_unavailable")
        return model_id

    def native_execution_descriptor(
        self, model_id: str, *, owner_id: int | None = None
    ) -> NativeAdapterDescriptor:
        """Return fixed package metadata only for an exact currently usable model."""

        model = self._reviewed_model(model_id, owner_id=owner_id)
        policy = self.model_policy_state(model_id, owner_id=owner_id)
        if policy.get("usable") is not True:
            raise ProviderUnavailable("model_unavailable")
        if getattr(model, "provider_id", None) == "opencode-console":
            if owner_id is None:
                raise ProviderUnavailable("model_unavailable")
            record = self._opencode_record(model_id, owner_id=owner_id)
            if not _opencode_adapter_is_supported(record):
                raise ProviderUnavailable("provider_adapter_unsupported")
            return record.adapter
        provider_id = getattr(model, "provider_id", None)
        if not isinstance(provider_id, str):
            raise ProviderUnavailable("provider_adapter_unsupported")
        definition = self._require_provider(provider_id)
        try:
            descriptor = resolve_native_adapter(
                str(definition["adapter_id"]), str(definition["native_provider_id"])
            )
        except (KeyError, ValueError) as exc:
            raise ProviderUnavailable("provider_adapter_unsupported") from exc
        if (
            definition.get("adapter_supported") is not True
            or definition.get("protocol") != descriptor.protocol
            or getattr(model, "native_provider_id", descriptor.native_provider_id)
            != descriptor.native_provider_id
        ):
            raise ProviderUnavailable("provider_adapter_unsupported")
        return descriptor

    def _reviewed_model(self, model_id: str, *, owner_id: int | None = None) -> object:
        if not isinstance(model_id, str) or not _MODEL_ID.fullmatch(model_id):
            raise ProviderUnavailable("invalid_model_id")
        if model_id.startswith("opencode-console/"):
            if owner_id is None:
                raise ProviderUnavailable("model_unavailable")
            return self.get_opencode_model(model_id, owner_id=owner_id)
        model = self.catalog.get_model(model_id) if self.catalog is not None else None
        if model is None or getattr(model, "model_id", None) != model_id:
            raise ProviderUnavailable("model_unavailable")
        provider_id = getattr(model, "provider_id", None)
        definition = self._definitions.get(provider_id) if isinstance(provider_id, str) else None
        if definition is not None:
            provider_state = self._read_metadata().get(provider_id, {})
            endpoint = provider_state.get("base_url", definition.get("default_base_url"))
            canonical_endpoint = (
                _validate_public_https_url(endpoint) if isinstance(endpoint, str) else None
            )
            if (
                self._known_model_exclusion_reason(
                    provider_id,
                    canonical_endpoint,
                    _upstream_model_id(model_id, provider_id),
                )
                is not None
            ):
                raise ProviderUnavailable("model_unavailable")
        return model

    @staticmethod
    def _default_model_policy(
        model: object,
        current: Mapping[str, str],
        endpoint_identity_sha256: str | None,
    ) -> dict[str, object]:
        enabled = AssistantProviderManager._safe_free_default(model)
        return {
            "enabled": enabled,
            "acknowledged_privacy_policy_version": (
                current["privacy_policy_version"] if enabled else None
            ),
            "acknowledged_billing_policy_version": (
                current["billing_policy_version"] if enabled else None
            ),
            "revision": 1 if enabled else 0,
            "endpoint_identity_sha256": endpoint_identity_sha256 if enabled else None,
        }

    @staticmethod
    def _consent_policy_version(
        summary: Mapping[str, object],
        record: Mapping[str, object],
        current_endpoint_identity_sha256: str | None,
    ) -> str:
        """Version consent from reviewed and acknowledged policy plus admin generation."""

        material = {
            "review_policy_version": summary.get("policy_version"),
            "privacy_policy_version": summary.get("privacy_policy_version"),
            "billing_policy_version": summary.get("billing_policy_version"),
            "acknowledged_privacy_policy_version": record.get(
                "acknowledged_privacy_policy_version"
            ),
            "acknowledged_billing_policy_version": record.get(
                "acknowledged_billing_policy_version"
            ),
            "enabled": record.get("enabled"),
            "revision": record.get("revision"),
            "approved_endpoint_identity_sha256": record.get("endpoint_identity_sha256"),
            "current_endpoint_identity_sha256": current_endpoint_identity_sha256,
        }
        encoded = json.dumps(
            material, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")
        ).encode("ascii")
        return "ap1-" + hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _require_reviewed_disclosures(model: object) -> None:
        """Require explicit policy terms before an administrator enables a model."""

        values = (
            getattr(model, "privacy_policy_version", None),
            getattr(model, "billing_policy_version", None),
            getattr(model, "privacy_disclosure", None) or getattr(model, "disclosure", None),
            getattr(model, "cost_disclosure", None),
            getattr(model, "terms_url", None),
            getattr(model, "terms_reviewed_at", None),
        )
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ProviderUnavailable("model_policy_review_required")
        terms_url = str(values[4])
        if terms_url != terms_url.strip() or any(
            ord(character) < 0x20 or ord(character) == 0x7F for character in terms_url
        ):
            raise ProviderUnavailable("model_policy_review_required")
        try:
            terms = urlsplit(terms_url)
            canonical_terms_url = _validate_public_https_url(terms_url)
        except (ProviderUnavailable, ValueError) as exc:
            raise ProviderUnavailable("model_policy_review_required") from exc
        if (
            terms.scheme != "https"
            or not terms.hostname
            or (terms.port is not None and terms.port != 443)
            or not canonical_terms_url
        ):
            raise ProviderUnavailable("model_policy_review_required")

    def _endpoint_identity(self, model: object, state: Mapping[str, object]) -> str | None:
        """Bind approval to the exact endpoint and adapter that would receive model data."""

        provider_id = getattr(model, "provider_id", None)
        if not isinstance(provider_id, str):
            raise ProviderUnavailable("model_policy_unavailable")
        definition = self._definitions.get(provider_id)
        if definition is None:
            return None
        provider_state = state.get(provider_id, {})
        if not isinstance(provider_state, Mapping):
            raise ProviderUnavailable("provider_config_invalid")
        endpoint = provider_state.get("base_url", definition.get("default_base_url"))
        if not isinstance(endpoint, str):
            return None
        canonical_endpoint = _validate_public_https_url(endpoint)
        material = {
            "provider_id": provider_id,
            "native_provider_id": definition.get("native_provider_id"),
            "adapter_id": definition.get("adapter_id"),
            "protocol": definition.get("protocol"),
            "endpoint": canonical_endpoint,
        }
        if provider_id == "custom":
            if not _custom_review_fields_present(provider_state):
                return None
            material.update(
                {
                    "terms_url": provider_state.get("terms_url"),
                    "privacy_disclosure": provider_state.get("privacy_disclosure"),
                    "billing_disclosure": provider_state.get("billing_disclosure"),
                    "billing_class": provider_state.get("billing_class"),
                    "privacy_policy_version": provider_state.get("privacy_policy_version"),
                    "billing_policy_version": provider_state.get("billing_policy_version"),
                }
            )
        encoded = json.dumps(
            material, sort_keys=True, ensure_ascii=True, separators=(",", ":")
        ).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()

    def _model_connection_ready(
        self,
        model: object,
        definition: Mapping[str, object],
        *,
        owner_id: int | None = None,
    ) -> bool:
        """Require live catalog discovery and the exact provider's current connection."""

        provider_id = getattr(model, "provider_id", None)
        if provider_id == "openai-chatgpt":
            return owner_id is not None and self._owned_chatgpt_credential(owner_id) is not None
        if provider_id == "opencode-console":
            if owner_id is None:
                return False
            try:
                record = self._opencode_record(
                    str(getattr(model, "model_id", "")), owner_id=owner_id
                )
            except ProviderUnavailable:
                return False
            if self._owned_opencode_credential(owner_id) is None:
                return False
            upstream_provider = record.adapter.integration_id or "custom"
            if upstream_provider not in {"openai", "anthropic", "google", "custom"}:
                return False
            upstream_definition = self._definitions.get(upstream_provider)
            if upstream_definition is None:
                return False
            if upstream_definition.get(
                "credential_required"
            ) is True and not self._credential_exists(upstream_provider):
                return False
            if upstream_provider == "custom":
                custom_state = self._read_metadata().get("custom", {})
                if custom_state.get(
                    "base_url"
                ) != record.endpoint or not _custom_review_fields_present(custom_state):
                    return False
            return True
        if provider_id == "opencode-zen":
            # The model object itself came from the current bounded Zen /models snapshot.
            return getattr(model, "available", False) is True
        if (
            provider_id not in _MODEL_DISCOVERY_PROVIDERS
            or definition.get("adapter_supported") is not True
        ):
            return False
        return bool(
            self._provider_inventory_configured(provider_id)
            and self._provider_inventory_fresh(provider_id, 0.0)
            and any(
                getattr(candidate, "model_id", None) == getattr(model, "model_id", None)
                for candidate in self._provider_models.get(provider_id, ())
            )
        )

    def _owned_chatgpt_credential(self, owner_id: int) -> tuple[str, dict[str, object]] | None:
        """Read one structurally valid ChatGPT credential for exactly one app owner."""

        self._validate_oauth_owner(owner_id)
        found: list[tuple[str, dict[str, object]]] = []
        with self._lock:
            for method_id in sorted(_CHATGPT_OAUTH_METHODS):
                credential = self._read_oauth_credential("openai", method_id, owner_id)
                if credential is None:
                    continue
                metadata = credential.get("metadata", {})
                access = credential.get("access")
                refresh = credential.get("refresh")
                expires = credential.get("expires")
                if (
                    credential.get("type") != "oauth"
                    or credential.get("methodID") != method_id
                    or not isinstance(access, str)
                    or not 1 <= len(access.encode("utf-8")) <= _MAX_OAUTH_TOKEN_BYTES
                    or not isinstance(refresh, str)
                    or not 1 <= len(refresh.encode("utf-8")) <= _MAX_OAUTH_TOKEN_BYTES
                    or type(expires) is not int
                    or not isinstance(metadata, Mapping)
                    or set(metadata) - {"accountID"}
                    or (
                        "accountID" in metadata
                        and (
                            not isinstance(metadata["accountID"], str)
                            or not 1 <= len(metadata["accountID"]) <= 512
                        )
                    )
                ):
                    raise ProviderUnavailable("oauth_vault_unavailable")
                found.append((method_id, credential))
        # Multiple credentials create an ambiguous upstream identity. Fail closed and require
        # the administrator to remove one before the account can be used.
        return found[0] if len(found) == 1 else None

    def _owned_opencode_credential(self, owner_id: int) -> dict[str, object] | None:
        """Read the one owner-bound OpenCode device credential without exposing its value."""

        self._validate_oauth_owner(owner_id)
        with self._lock:
            credential = self._read_oauth_credential("opencode", "device", owner_id)
        if credential is None:
            return None
        metadata = credential.get("metadata", {})
        access = credential.get("access")
        refresh = credential.get("refresh")
        if (
            credential.get("type") != "oauth"
            or credential.get("methodID") != "device"
            or not isinstance(access, str)
            or not 1 <= len(access.encode("utf-8")) <= _MAX_OAUTH_TOKEN_BYTES
            or any(unicodedata.category(char).startswith("C") for char in access)
            or not isinstance(refresh, str)
            or not 1 <= len(refresh.encode("utf-8")) <= _MAX_OAUTH_TOKEN_BYTES
            or any(unicodedata.category(char).startswith("C") for char in refresh)
            or type(credential.get("expires")) is not int
            or not isinstance(metadata, Mapping)
            or set(metadata) - {"server", "accountID", "email", "orgID", "orgName"}
            or metadata.get("server") != "https://opencode.ai/console"
            or any(
                not isinstance(value, str)
                or len(value.encode("utf-8")) > 512
                or any(unicodedata.category(char).startswith("C") for char in value)
                for value in metadata.values()
            )
        ):
            raise ProviderUnavailable("oauth_vault_unavailable")
        return credential

    async def _refresh_opencode_credential_if_needed(
        self,
        owner_id: int,
        credential: dict[str, object],
        authorization_check: Callable[[], Awaitable[bool] | bool],
    ) -> dict[str, object]:
        """Refresh only against the fixed OpenCode Console token endpoint."""

        async with self._oauth_refresh_lock:
            await _require_live_authorization(authorization_check)
            current = self._owned_opencode_credential(owner_id)
            if current is None:
                raise CredentialRejected("oauth_connection_required")
            now_ms = int(time.time() * 1000)
            if current["expires"] > now_ms + 120_000:
                return current
            refresh_token = current["refresh"]
            form = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": _OPENCODE_CLIENT_ID,
            }
            await _require_live_authorization(authorization_check)
            try:
                response = await request_public_https(
                    _OPENCODE_REFRESH_URL,
                    method="POST",
                    headers={"accept": "application/json"},
                    body=json.dumps(form, ensure_ascii=False, separators=(",", ":")).encode(
                        "utf-8"
                    ),
                    timeout_seconds=10.0,
                    max_response_bytes=65_536,
                    authorization_check=authorization_check,
                )
            except PublicHTTPError as exc:
                if exc.code in {
                    "provider_authorization_required",
                    "provider_authorization_timeout",
                }:
                    raise CredentialRejected("oauth_authorization_required") from None
                raise ProviderUnavailable("oauth_refresh_unavailable") from exc
            except (OSError, TimeoutError) as exc:
                raise ProviderUnavailable("oauth_refresh_unavailable") from exc
            if response.status_code in {401, 403}:
                raise CredentialRejected("oauth_connection_required")
            if response.status_code != 200:
                raise ProviderUnavailable("oauth_refresh_unavailable")
            try:
                payload = json.loads(response.content)
            except (json.JSONDecodeError, UnicodeError) as exc:
                raise ProviderUnavailable("oauth_refresh_invalid") from exc
            if not isinstance(payload, Mapping) or set(payload) - {
                "access_token",
                "refresh_token",
                "expires_in",
                "org_id",
            }:
                raise ProviderUnavailable("oauth_refresh_invalid")
            access = payload.get("access_token")
            rotated_refresh = payload.get("refresh_token")
            expires_in = payload.get("expires_in")
            org_id = payload.get("org_id")
            if (
                not isinstance(access, str)
                or not 1 <= len(access.encode("utf-8")) <= _MAX_OAUTH_TOKEN_BYTES
                or any(unicodedata.category(char).startswith("C") for char in access)
                or not isinstance(rotated_refresh, str)
                or not 1 <= len(rotated_refresh.encode("utf-8")) <= _MAX_OAUTH_TOKEN_BYTES
                or any(unicodedata.category(char).startswith("C") for char in rotated_refresh)
                or type(expires_in) is not int
                or not 1 <= expires_in <= 366 * 86_400
                or (
                    org_id is not None
                    and (
                        not isinstance(org_id, str)
                        or len(org_id.encode("utf-8")) > 512
                        or any(unicodedata.category(char).startswith("C") for char in org_id)
                    )
                )
            ):
                raise ProviderUnavailable("oauth_refresh_invalid")
            metadata = dict(current["metadata"])
            if org_id is not None:
                if metadata.get("orgID") != org_id:
                    metadata.pop("orgName", None)
                metadata["orgID"] = org_id
                metadata.setdefault("orgName", org_id)
            updated: dict[str, object] = {
                "type": "oauth",
                "methodID": "device",
                "access": access,
                "refresh": rotated_refresh,
                "expires": int(time.time() * 1000) + expires_in * 1000,
                "metadata": metadata,
            }
            async with self._oauth_lock:
                await _require_live_authorization(authorization_check)
                with self._lock:
                    latest = self._owned_opencode_credential(owner_id)
                    if (
                        latest is None
                        or not isinstance(latest.get("refresh"), str)
                        or not secrets.compare_digest(latest["refresh"], refresh_token)
                    ):
                        raise CredentialRejected("oauth_connection_required")
                    self._write_oauth_credential("opencode", "device", owner_id, updated)
            return updated

    async def _refresh_chatgpt_credential_if_needed(
        self,
        owner_id: int,
        method_id: str,
        credential: dict[str, object],
        authorization_check: Callable[[], Awaitable[bool] | bool],
    ) -> dict[str, object]:
        """Refresh a fixed ChatGPT OAuth token without persisting unrelated response fields."""
        if method_id not in _CHATGPT_OAUTH_METHODS:
            raise CredentialRejected("oauth_refresh_required")
        async with self._oauth_refresh_lock:
            # A prior waiter may have rotated the refresh token while this call was queued.
            # Reread only after the serialization lock, and recheck the live lease there.
            await _require_live_authorization(authorization_check)
            with self._lock:
                current = self._read_oauth_credential("openai", method_id, owner_id)
            if (
                current is None
                or current.get("type") != "oauth"
                or current.get("methodID") != method_id
                or not isinstance(current.get("access"), str)
                or not isinstance(current.get("refresh"), str)
                or type(current.get("expires")) is not int
            ):
                raise CredentialRejected("oauth_connection_required")
            now_ms = int(time.time() * 1000)
            if current["expires"] > now_ms + 120_000:
                return current
            refresh_token = current["refresh"]
            if not 1 <= len(refresh_token.encode("utf-8")) <= _MAX_OAUTH_TOKEN_BYTES:
                raise CredentialRejected("oauth_refresh_required")
            form = urlencode(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": _CHATGPT_CLIENT_ID,
                }
            ).encode("utf-8")
            # This is the last live-session check before the fixed refresh request.
            await _require_live_authorization(authorization_check)
            try:
                response = await request_public_https(
                    _CHATGPT_REFRESH_URL,
                    method="POST",
                    headers={"accept": "application/json"},
                    body=form,
                    content_type="application/x-www-form-urlencoded",
                    timeout_seconds=10.0,
                    max_response_bytes=65_536,
                    authorization_check=authorization_check,
                )
            except PublicHTTPError as exc:
                if exc.code in {
                    "provider_authorization_required",
                    "provider_authorization_timeout",
                }:
                    raise CredentialRejected("oauth_authorization_required") from None
                raise ProviderUnavailable("oauth_refresh_unavailable") from exc
            except (OSError, TimeoutError) as exc:
                raise ProviderUnavailable("oauth_refresh_unavailable") from exc
            if response.status_code in {401, 403}:
                raise CredentialRejected("oauth_connection_required")
            if response.status_code != 200:
                raise ProviderUnavailable("oauth_refresh_unavailable")
            try:
                payload = json.loads(response.content)
            except (json.JSONDecodeError, UnicodeError) as exc:
                raise ProviderUnavailable("oauth_refresh_invalid") from exc
            if not isinstance(payload, Mapping):
                raise ProviderUnavailable("oauth_refresh_invalid")
            access = payload.get("access_token")
            rotated_refresh = payload.get("refresh_token", refresh_token)
            expires_in = payload.get("expires_in")
            if (
                not isinstance(access, str)
                or not 1 <= len(access.encode("utf-8")) <= _MAX_OAUTH_TOKEN_BYTES
                or any(unicodedata.category(char).startswith("C") for char in access)
                or not isinstance(rotated_refresh, str)
                or not 1 <= len(rotated_refresh.encode("utf-8")) <= _MAX_OAUTH_TOKEN_BYTES
                or any(unicodedata.category(char).startswith("C") for char in rotated_refresh)
                or type(expires_in) is not int
                or not 1 <= expires_in <= 366 * 86_400
            ):
                raise ProviderUnavailable("oauth_refresh_invalid")
            updated = {
                "type": "oauth",
                "methodID": method_id,
                "access": access,
                "refresh": rotated_refresh,
                "expires": int(time.time() * 1000) + expires_in * 1000,
                "metadata": dict(current.get("metadata", {})),
            }
            self._validate_oauth_credential_for_provider(updated, method_id)
            async with self._oauth_lock:
                with self._lock:
                    latest = self._read_oauth_credential("openai", method_id, owner_id)
                    if (
                        latest is None
                        or latest.get("type") != "oauth"
                        or not isinstance(latest.get("refresh"), str)
                        or not secrets.compare_digest(latest["refresh"], refresh_token)
                    ):
                        raise CredentialRejected("oauth_connection_required")
                    await _require_live_authorization(authorization_check)
                    self._write_oauth_credential("openai", method_id, owner_id, updated)
            return updated

    @staticmethod
    def _validate_oauth_credential_for_provider(
        credential: Mapping[str, object], method_id: str
    ) -> None:
        if (
            credential.get("type") != "oauth"
            or credential.get("methodID") != method_id
            or not isinstance(credential.get("access"), str)
            or not isinstance(credential.get("refresh"), str)
            or type(credential.get("expires")) is not int
            or not isinstance(credential.get("metadata"), Mapping)
        ):
            raise ProviderUnavailable("oauth_refresh_invalid")

    @staticmethod
    def _current_policy_versions(model: object) -> dict[str, str]:
        privacy = getattr(model, "privacy_policy_version", None)
        if not isinstance(privacy, str) or not privacy:
            privacy = getattr(model, "policy_version", None)
        billing = getattr(model, "billing_policy_version", None)
        if not isinstance(billing, str) or not billing:
            billing = getattr(model, "policy_version", None)
        if (
            not isinstance(privacy, str)
            or not 1 <= len(privacy) <= 80
            or not isinstance(billing, str)
            or not 1 <= len(billing) <= 80
        ):
            raise ProviderUnavailable("model_policy_unavailable")
        return {"privacy_policy_version": privacy, "billing_policy_version": billing}

    @staticmethod
    def _safe_free_default(model: object) -> bool:
        """Seed only the catalog-reviewed zero-training, zero-collection free Zen model."""

        return bool(
            getattr(model, "provider_id", None) == "opencode-zen"
            and getattr(model, "available", False) is True
            and getattr(model, "free", False) is True
            and getattr(model, "training", True) is False
            and getattr(model, "data_collection_allowed", True) is False
            and getattr(model, "data_collection_default", True) is False
        )

    @staticmethod
    def _reviewed_model_summary(model: object) -> dict[str, object]:
        model_id = getattr(model, "model_id", None)
        provider_id = getattr(model, "provider_id", None)
        if not isinstance(model_id, str) or not isinstance(provider_id, str):
            raise ProviderUnavailable("model_policy_unavailable")
        versions = AssistantProviderManager._current_policy_versions(model)
        values: dict[str, object] = {
            "model_id": model_id,
            "provider_id": provider_id,
            "native_provider_id": getattr(model, "native_provider_id", provider_id),
            "display_name": getattr(model, "display_name", model_id),
            "available": getattr(model, "available", False) is True,
            "free": getattr(model, "free", False) is True,
            "training": getattr(model, "training", True) is True,
            "terms_url": getattr(model, "terms_url", ""),
            "terms_reviewed_at": getattr(model, "terms_reviewed_at", ""),
            "policy_version": getattr(model, "policy_version", ""),
            **versions,
            "privacy_disclosure": getattr(model, "privacy_disclosure", None)
            or getattr(model, "disclosure", ""),
            "billing_class": getattr(model, "billing_class", None)
            or ("free" if getattr(model, "free", False) else "paid"),
            "cost_disclosure": getattr(model, "cost_disclosure", ""),
            "data_collection_allowed": getattr(model, "data_collection_allowed", False) is True,
            "data_collection_default": getattr(model, "data_collection_default", False) is True,
        }
        if not isinstance(values["native_provider_id"], str):
            raise ProviderUnavailable("model_policy_unavailable")
        return values

    def credential_for_runtime(self, provider_id: str) -> str | None:
        """Return a key transiently to the app-side proxy for one exact upstream call."""

        self._require_provider(provider_id)
        return self._read_credential(provider_id)

    def _require_provider(self, provider_id: str) -> dict[str, Any]:
        if not isinstance(provider_id, str) or not _PROVIDER_ID.fullmatch(provider_id):
            raise ProviderUnavailable("provider_not_supported")
        definition = self._definitions.get(provider_id)
        if definition is None:
            raise ProviderUnavailable("provider_not_supported")
        return definition

    def _known_model_exclusion_reason(
        self, provider_id: object, endpoint_url: object, native_model_id: object
    ) -> str | None:
        """Resolve exact upstream exclusions from the maintained Zen catalog policy."""

        zen_policy = self._definitions.get("opencode-zen")
        if not isinstance(zen_policy, Mapping):
            raise ProviderUnavailable("model_policy_unavailable")
        try:
            return known_model_exclusion_reason(
                zen_policy,
                provider_id=provider_id,
                endpoint_url=endpoint_url,
                native_model_id=native_model_id,
            )
        except ValueError as exc:
            raise ProviderUnavailable("model_policy_unavailable") from exc

    @staticmethod
    def _load_definitions() -> dict[str, dict[str, Any]]:
        source = files("stock_probs.assistant").joinpath("assistant_catalog.json")
        catalog = json.loads(source.read_text(encoding="utf-8"))
        definitions = {str(item["provider_id"]): item for item in catalog["providers"]}
        zen = catalog["zen"]
        definitions[str(zen["provider_id"])] = {
            "provider_id": zen["provider_id"],
            "display_name": zen["display_name"],
            "models_url": zen["models_url"],
            "excluded_models": zen["excluded_models"],
            "auth_methods": ["free_no_key"],
            "default_base_url": "https://opencode.ai/zen/v1",
            "terms_url": zen["terms_url"],
            "runtime_provider_id": zen["provider_id"],
            "credential_required": False,
            "native_provider_id": "assistant-proxy",
            "adapter_id": "openai-compatible-chat",
            "protocol": "openai-compatible-chat",
            "endpoint_editable": False,
            "credential_supported": False,
            "validation_requires_credential": False,
            "adapter_supported": True,
            "unsupported_reason": None,
        }
        return definitions

    def _read_metadata(self) -> dict[str, dict[str, Any]]:
        try:
            self._ensure_vault()
            raw = _read_private_file(self._config_path, _MAX_METADATA_BYTES)
        except FileNotFoundError:
            return {}
        except OSError as exc:
            raise ProviderUnavailable("provider_config_unavailable") from exc
        if len(raw) > _MAX_METADATA_BYTES:
            raise ProviderUnavailable("provider_config_invalid")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderUnavailable("provider_config_invalid") from exc
        if not isinstance(value, dict):
            raise ProviderUnavailable("provider_config_invalid")
        result: dict[str, dict[str, Any]] = {
            key: item
            for key, item in value.items()
            if key in self._definitions and isinstance(item, dict)
        }
        custom_state = result.get("custom")
        if custom_state is not None:
            allowed_custom_fields = {
                "base_url",
                "model_id",
                "terms_url",
                "privacy_disclosure",
                "billing_disclosure",
                "billing_class",
                "endpoint_policy_reviewed",
                "terms_reviewed_at",
                "policy_version",
                "privacy_policy_version",
                "billing_policy_version",
            }
            if set(custom_state) - allowed_custom_fields:
                raise ProviderUnavailable("provider_config_invalid")
            model_id = custom_state.get("model_id")
            if model_id is not None and (
                not isinstance(model_id, str) or not _MODEL_ID.fullmatch(model_id)
            ):
                raise ProviderUnavailable("provider_config_invalid")
            endpoint = custom_state.get("base_url")
            if endpoint is not None and (
                not isinstance(endpoint, str) or _validate_public_https_url(endpoint) != endpoint
            ):
                raise ProviderUnavailable("provider_config_invalid")
            review_fields = set(custom_state) - {"base_url", "model_id"}
            if review_fields and not _custom_review_fields_present(custom_state):
                raise ProviderUnavailable("provider_config_invalid")
        raw_policies = value.get(_MODEL_POLICY_KEY, {})
        if not isinstance(raw_policies, dict) or len(raw_policies) > _MAX_MODEL_POLICIES:
            raise ProviderUnavailable("provider_config_invalid")
        policies: dict[str, dict[str, Any]] = {}
        for model_id, row in raw_policies.items():
            expected_fields = {
                "enabled",
                "acknowledged_privacy_policy_version",
                "acknowledged_billing_policy_version",
                "revision",
            }
            if (
                not isinstance(model_id, str)
                or not _MODEL_ID.fullmatch(model_id)
                or not isinstance(row, dict)
                or not expected_fields <= set(row)
                or set(row) - expected_fields - {"endpoint_identity_sha256"}
                or type(row.get("enabled")) is not bool
                or type(row.get("revision")) is not int
                or not 0 <= row["revision"] <= _MAX_POLICY_REVISION
            ):
                raise ProviderUnavailable("provider_config_invalid")
            for policy_field in (
                "acknowledged_privacy_policy_version",
                "acknowledged_billing_policy_version",
            ):
                version = row.get(policy_field)
                if version is not None and (
                    not isinstance(version, str) or not 1 <= len(version) <= 80
                ):
                    raise ProviderUnavailable("provider_config_invalid")
            endpoint_identity = row.get("endpoint_identity_sha256")
            if endpoint_identity is not None and (
                not isinstance(endpoint_identity, str)
                or re.fullmatch(r"[0-9a-f]{64}", endpoint_identity) is None
            ):
                raise ProviderUnavailable("provider_config_invalid")
            # Pre-identity approvals are retained for admin review but cannot authorize turns.
            policies[model_id] = {
                **row,
                "endpoint_identity_sha256": endpoint_identity,
            }
        if policies:
            result[_MODEL_POLICY_KEY] = policies
        return result

    def _write_metadata(self, state: dict[str, dict[str, Any]]) -> None:
        self._ensure_vault()
        content = json.dumps(state, separators=(",", ":"), sort_keys=True).encode("utf-8")
        if len(content) > _MAX_METADATA_BYTES:
            raise ProviderUnavailable("provider_config_invalid")
        self._atomic_write(self._config_path, content)

    def _write_credential(self, provider_id: str, secret: str) -> None:
        self._ensure_vault()
        nonce = os.urandom(12)
        encrypted = AESGCM(self._vault_key()).encrypt(
            nonce, secret.encode("utf-8"), _AAD_CONTEXT + provider_id.encode("ascii")
        )
        content = json.dumps(
            {"version": 1, "value": base64.urlsafe_b64encode(nonce + encrypted).decode("ascii")},
            separators=(",", ":"),
        ).encode("ascii")
        self._atomic_write(self._credential_path(provider_id), content)

    def _read_credential(self, provider_id: str) -> str | None:
        path = self._credential_path(provider_id)
        try:
            raw = _read_private_file(path, 8192)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ProviderUnavailable("credential_vault_unavailable") from exc
        if len(raw) > 8192:
            raise ProviderUnavailable("credential_vault_invalid")
        try:
            envelope = json.loads(raw)
            packed = base64.urlsafe_b64decode(envelope["value"].encode("ascii"))
            if envelope.get("version") != 1 or not 29 <= len(packed) <= 8192:
                raise ValueError("invalid vault envelope")
            plain = AESGCM(self._vault_key()).decrypt(
                packed[:12], packed[12:], _AAD_CONTEXT + provider_id.encode("ascii")
            )
            return plain.decode("utf-8")
        except Exception as exc:
            raise ProviderUnavailable("credential_vault_unavailable") from exc

    def _vault_key(self) -> bytes:
        secret = self.settings.auth_session_secret.encode("utf-8")
        if len(secret) < 32:
            raise ProviderUnavailable("credential_vault_key_unavailable")
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_KEY_CONTEXT).derive(
            secret
        )

    def _credential_path(self, provider_id: str) -> Path:
        return self.vault_dir / f"credential-{provider_id}.json"

    def _credential_exists(self, provider_id: str) -> bool:
        path = self._credential_path(provider_id)
        try:
            _read_private_file(path, 8192)
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise ProviderUnavailable("credential_vault_unavailable") from exc

    def _ensure_vault(self) -> None:
        try:
            ensure_private_directory(self.vault_dir)
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(self.vault_dir, flags | getattr(os, "O_DIRECTORY", 0))
            try:
                if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                    raise ProviderUnavailable("credential_vault_unavailable")
                os.fchmod(descriptor, 0o700)
            finally:
                os.close(descriptor)
        except (OSError, ValueError) as exc:
            raise ProviderUnavailable("credential_vault_unavailable") from exc

    def _atomic_write(self, target: Path, content: bytes) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix=".provider-", dir=self.vault_dir)
        temporary_path = Path(temporary)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, target)
            directory_fd = os.open(self.vault_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise

    def _sync_runtime_configuration(
        self, provider_id: str, definition: dict[str, Any], state: dict[str, Any]
    ) -> None:
        sync = getattr(self.runtime, "sync_provider_configuration", None)
        if callable(sync):
            try:
                sync(provider_id, definition, state)
            except Exception as exc:
                raise ProviderUnavailable("runtime_configuration_sync_failed") from exc


def _read_private_file(path: Path, max_bytes: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > max_bytes:
            raise OSError("private file has an invalid type or size")
        os.fchmod(descriptor, 0o600)
        result = bytearray()
        while len(result) <= max_bytes:
            chunk = os.read(descriptor, min(4096, max_bytes + 1 - len(result)))
            if not chunk:
                break
            result.extend(chunk)
        if len(result) > max_bytes:
            raise OSError("private file exceeds its size limit")
        return bytes(result)
    finally:
        os.close(descriptor)


def _validated_tools(
    raw_tools: object,
) -> tuple[list[dict[str, object]] | None, set[str]]:
    """Preserve only the bounded function declarations already checked by the app gateway."""

    if raw_tools is None:
        return None, set()
    if not isinstance(raw_tools, list) or not 1 <= len(raw_tools) <= 13:
        raise ProviderUnavailable("provider_request_invalid")
    tools: list[dict[str, object]] = []
    names: set[str] = set()
    try:
        encoded_size = len(
            json.dumps(
                raw_tools,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ProviderUnavailable("provider_request_invalid") from exc
    if encoded_size > 65_536:
        raise ProviderUnavailable("provider_request_invalid")
    for item in raw_tools:
        if not isinstance(item, Mapping) or set(item) != {"type", "function"}:
            raise ProviderUnavailable("provider_request_invalid")
        function = item.get("function")
        if (
            item.get("type") != "function"
            or not isinstance(function, Mapping)
            or set(function) - {"name", "description", "parameters", "strict"}
            or not {"name", "description", "parameters"} <= set(function)
            or ("strict" in function and function.get("strict") is not False)
        ):
            raise ProviderUnavailable("provider_request_invalid")
        name = function.get("name")
        description = function.get("description")
        parameters = function.get("parameters")
        if (
            not isinstance(name, str)
            or not 1 <= len(name) <= 160
            or name in names
            or not isinstance(description, str)
            or _utf8_length(description) is None
            or len(description.encode("utf-8")) > 1000
            or not isinstance(parameters, Mapping)
        ):
            raise ProviderUnavailable("provider_request_invalid")
        names.add(name)
        if name in {"websearch", "webfetch"}:
            try:
                reviewed_schema = (
                    native_websearch_schema("openai-compatible-chat")
                    if name == "websearch"
                    else native_webfetch_schema("openai-compatible-chat")
                )
            except ValueError as exc:
                raise ProviderUnavailable("provider_request_invalid") from exc
            if not _native_tool_schema_matches(
                name,
                description,
                parameters,
                (None, reviewed_schema),
                protocol="openai-compatible-chat",
            ):
                raise ProviderUnavailable("provider_request_invalid")
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": dict(parameters),
                },
            }
        )
    return tools, names


def _validated_messages(
    raw_messages: list[object], declared_tool_names: set[str]
) -> list[dict[str, object]]:
    """Retain bounded OpenAI-compatible tool calls and their matching result messages."""

    messages: list[dict[str, object]] = []
    pending_calls: dict[str, str] = {}
    text_size = 0
    call_count = 0
    for message in raw_messages:
        if not isinstance(message, Mapping):
            raise ProviderUnavailable("provider_request_invalid")
        role = message.get("role")
        content = message.get("content")
        if role == "tool":
            call_id = message.get("tool_call_id")
            if (
                set(message) != {"role", "tool_call_id", "content"}
                or not isinstance(call_id, str)
                or _TOOL_CALL_ID.fullmatch(call_id) is None
                or call_id not in pending_calls
                or not isinstance(content, str)
                or "\x00" in content
            ):
                raise ProviderUnavailable("provider_request_invalid")
            content_bytes = _utf8_length(content)
            if content_bytes is None:
                raise ProviderUnavailable("provider_request_invalid")
            text_size += content_bytes
            if text_size > 65_536:
                raise ProviderUnavailable("provider_request_invalid")
            pending_calls.pop(call_id)
            messages.append({"role": "tool", "tool_call_id": call_id, "content": content})
            continue

        has_calls = "tool_calls" in message
        if role not in {"system", "user", "assistant"}:
            raise ProviderUnavailable("provider_request_invalid")
        if has_calls:
            raw_calls = message.get("tool_calls")
            if (
                role != "assistant"
                or set(message) != {"role", "content", "tool_calls"}
                or (content is not None and not isinstance(content, str))
                or not isinstance(raw_calls, list)
                or not 1 <= len(raw_calls) <= 8
                or pending_calls
            ):
                raise ProviderUnavailable("provider_request_invalid")
        elif set(message) != {"role", "content"} or not isinstance(content, str) or pending_calls:
            raise ProviderUnavailable("provider_request_invalid")
        if content is not None:
            if not isinstance(content, str) or "\x00" in content:
                raise ProviderUnavailable("provider_request_invalid")
            content_bytes = _utf8_length(content)
            if content_bytes is None:
                raise ProviderUnavailable("provider_request_invalid")
            text_size += content_bytes
            if text_size > 65_536:
                raise ProviderUnavailable("provider_request_invalid")

        normalized: dict[str, object] = {"role": role, "content": content}
        if has_calls:
            normalized_calls: list[dict[str, object]] = []
            for raw_call in raw_calls:
                if (
                    not isinstance(raw_call, Mapping)
                    or set(raw_call) != {"id", "type", "function"}
                    or raw_call.get("type") != "function"
                ):
                    raise ProviderUnavailable("provider_request_invalid")
                call_id = raw_call.get("id")
                function = raw_call.get("function")
                if (
                    not isinstance(call_id, str)
                    or _TOOL_CALL_ID.fullmatch(call_id) is None
                    or call_id in pending_calls
                    or not isinstance(function, Mapping)
                    or set(function) != {"name", "arguments"}
                ):
                    raise ProviderUnavailable("provider_request_invalid")
                name = function.get("name")
                arguments = function.get("arguments")
                if (
                    not isinstance(name, str)
                    or name not in declared_tool_names
                    or not isinstance(arguments, str)
                    or _utf8_length(arguments) is None
                    or len(arguments.encode("utf-8")) > 16_384
                    or "\x00" in arguments
                ):
                    raise ProviderUnavailable("provider_request_invalid")
                decoded = _parse_json_object(arguments)
                if decoded is None:
                    raise ProviderUnavailable("provider_request_invalid")
                if name == "websearch" and not _valid_native_search_arguments(decoded):
                    raise ProviderUnavailable("provider_request_invalid")
                if name == "webfetch" and not _valid_native_webfetch_arguments(decoded):
                    raise ProviderUnavailable("provider_request_invalid")
                call_count += 1
                if call_count > 8:
                    raise ProviderUnavailable("provider_request_invalid")
                pending_calls[call_id] = name
                normalized_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": arguments},
                    }
                )
            normalized["tool_calls"] = normalized_calls
        messages.append(normalized)
    if pending_calls:
        raise ProviderUnavailable("provider_request_invalid")
    return messages


def _validate_public_https_url(value: str) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise ProviderUnavailable("invalid_provider_endpoint")
    try:
        if len(value.encode("utf-8")) > 2048:
            raise ProviderUnavailable("invalid_provider_endpoint")
    except UnicodeEncodeError as exc:
        raise ProviderUnavailable("invalid_provider_endpoint") from exc
    if any(character.isspace() for character in value) or any(
        ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F for character in value
    ):
        raise ProviderUnavailable("invalid_provider_endpoint")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ProviderUnavailable("invalid_provider_endpoint") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or (port is not None and port != 443)
        or "\\" in parsed.path
        or any(segment in {".", ".."} for segment in parsed.path.split("/"))
    ):
        raise ProviderUnavailable("invalid_provider_endpoint")
    source_hostname = parsed.hostname.rstrip(".").lower()
    try:
        literal = ipaddress.ip_address(source_hostname)
    except ValueError:
        literal = None
    if literal is not None and not is_public_unicast(literal):
        raise ProviderUnavailable("private_provider_endpoint_rejected")
    if literal is not None:
        hostname = literal.compressed
        netloc_hostname = f"[{hostname}]" if literal.version == 6 else hostname
    else:
        try:
            hostname = source_hostname.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ProviderUnavailable("invalid_provider_endpoint") from exc
        labels = hostname.split(".")
        if len(hostname) > 253 or any(
            not label
            or len(label) > 63
            or re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) is None
            for label in labels
        ):
            raise ProviderUnavailable("invalid_provider_endpoint")
        netloc_hostname = hostname
    netloc = netloc_hostname
    return urlunsplit(("https", netloc, parsed.path.rstrip("/"), "", ""))


def _provider_headers(provider_id: str, secret: str | None) -> dict[str, str]:
    if secret is None:
        if provider_id == "opencode-zen":
            # Native OpenCode V2 uses this fixed public marker on its no-user-key Zen path.
            return {"authorization": "Bearer public"}
        return {}
    if provider_id == "anthropic":
        return {"x-api-key": secret, "anthropic-version": "2023-06-01"}
    if provider_id == "google":
        return {"x-goog-api-key": secret}
    return {"authorization": f"Bearer {secret}"}


def _native_zen_identity_headers(user_agent: object, client: object) -> dict[str, str] | None:
    """Validate the two native OpenCode identity fields allowed on the Zen route."""

    if user_agent is not None and (
        not isinstance(user_agent, str)
        or not user_agent.isascii()
        or len(user_agent) > _NATIVE_ZEN_USER_AGENT_MAX
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in user_agent)
    ):
        return None
    if client is not None and (
        not isinstance(client, str)
        or not client.isascii()
        or _NATIVE_ZEN_COMPONENT.fullmatch(client) is None
    ):
        return None

    components: list[str] | None = None
    if user_agent is not None:
        components = user_agent.split("/")
        if (
            len(components) != 4
            or components[0] != "opencode"
            or any(
                _NATIVE_ZEN_COMPONENT.fullmatch(component) is None for component in components[1:]
            )
        ):
            return None
    if client is not None and (components is None or client != components[-1]):
        return None

    headers: dict[str, str] = {}
    if user_agent is not None:
        headers["user-agent"] = user_agent
    if client is not None:
        headers["x-opencode-client"] = client
    return headers


def _native_zen_upstream_headers(
    user_agent: object,
    client: object,
    native_session: object,
    native_project: object,
    session_affinity: object,
    session_id_alias: object,
) -> dict[str, str] | None:
    """Validate actual native session metadata before forwarding it only to Zen."""

    if (
        not isinstance(native_session, str)
        or _NATIVE_OPENCODE_SESSION_ID.fullmatch(native_session) is None
        or not _valid_native_project_id(native_project)
        or (session_affinity is not None and session_affinity != native_session)
        or (session_id_alias is not None and session_id_alias != native_session)
    ):
        return None
    headers = _native_zen_identity_headers(user_agent, client)
    if headers is None:
        return None
    headers["x-opencode-session"] = native_session
    headers["x-opencode-project"] = native_project
    if session_affinity is not None:
        headers["x-session-affinity"] = session_affinity
    if session_id_alias is not None:
        headers["x-session-id"] = session_id_alias
    return headers


def _valid_native_project_id(value: object) -> bool:
    """Accept bounded opaque project identifiers, never a directory path."""

    return (
        isinstance(value, str)
        and value not in {"", ".", ".."}
        and len(value) <= _NATIVE_PROJECT_ID_MAX
        and value.isascii()
        and value.strip() == value
        and all(0x21 <= ord(character) <= 0x7E for character in value)
        and "/" not in value
        and "\\" not in value
    )


async def _require_live_authorization(
    authorization_check: Callable[[], Awaitable[bool] | bool],
) -> None:
    """Fail closed when the app lease, account session, or policy is no longer current."""

    try:
        allowed = authorization_check()
        if inspect.isawaitable(allowed):
            allowed = await allowed
    except Exception:
        allowed = False
    if allowed is not True:
        raise CredentialRejected("oauth_authorization_required")


def _provider_inventory_target(
    provider_id: str, base_url: str
) -> tuple[str, tuple[tuple[str, str], ...]]:
    """Build one fixed provider model-list request without putting credentials in its URL."""

    canonical = _validate_public_https_url(base_url).rstrip("/")
    if provider_id == "openai":
        return canonical + "/models", ()
    if provider_id == "anthropic":
        # One bounded page is sufficient to present a reviewed, live subset. Pagination is
        # deliberately not followed, so provider-supplied cursors cannot widen network access.
        return canonical + "/models?limit=100", (("limit", "100"),)
    if provider_id == "google":
        return canonical + "/models?pageSize=100", (("pageSize", "100"),)
    if provider_id == "custom":
        return canonical + "/models", ()
    raise ProviderUnavailable("provider_adapter_unsupported")


def _validate_public_terms_url(value: str) -> str:
    """Accept only a canonical public HTTPS terms page on the default TLS port."""

    if not isinstance(value, str) or value != value.strip():
        raise ProviderUnavailable("custom_policy_review_required")
    try:
        if len(value.encode("utf-8")) > 2048:
            raise ProviderUnavailable("custom_policy_review_required")
    except UnicodeEncodeError as exc:
        raise ProviderUnavailable("custom_policy_review_required") from exc
    if any(character.isspace() for character in value) or any(
        ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F for character in value
    ):
        raise ProviderUnavailable("custom_policy_review_required")
    try:
        parsed = urlsplit(value)
        port = parsed.port
        canonical = _validate_public_https_url(value)
    except (ValueError, ProviderUnavailable) as exc:
        raise ProviderUnavailable("custom_policy_review_required") from exc
    if parsed.scheme != "https" or port not in {None, 443} or not parsed.hostname:
        raise ProviderUnavailable("custom_policy_review_required")
    return canonical


def _opencode_config_fingerprint(
    config_provider_id: str,
    config_model_id: str,
    native_model_id: str,
    display_name: str,
    adapter: NativeAdapterDescriptor,
    endpoint: str,
) -> str:
    """Bind owner review to the exact fixed adapter and endpoint projection."""

    material = {
        "provider_id": config_provider_id,
        "model_id": config_model_id,
        "native_model_id": native_model_id,
        "display_name": display_name,
        "adapter_id": adapter.adapter_id,
        "native_provider_id": adapter.native_provider_id,
        "package_id": adapter.package_id,
        "protocol": adapter.protocol,
        "route_suffix": adapter.route_suffix,
        "fixed_query": adapter.fixed_query,
        "upstream_query": adapter.upstream_query,
        "endpoint": endpoint,
    }
    encoded = json.dumps(
        material, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _opencode_policy_versions(
    model_id: str,
    config_fingerprint: str,
    terms_url: str,
    privacy_disclosure: str,
    billing_disclosure: str,
    billing_class: str,
    training_policy: str,
    confidential_data_policy: str,
) -> dict[str, str]:
    """Version exact administrator assertions and the Console model configuration."""

    privacy_material = {
        "model_id": model_id,
        "config_fingerprint": config_fingerprint,
        "terms_url": terms_url,
        "privacy_disclosure": privacy_disclosure,
        "training_policy": training_policy,
        "confidential_data_policy": confidential_data_policy,
    }
    billing_material = {
        "model_id": model_id,
        "config_fingerprint": config_fingerprint,
        "terms_url": terms_url,
        "billing_disclosure": billing_disclosure,
        "billing_class": billing_class,
    }

    def digest(material: Mapping[str, object]) -> str:
        encoded = json.dumps(
            material, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    privacy_version = "ocp1-" + digest(privacy_material)
    billing_version = "ocb1-" + digest(billing_material)
    combined_version = "ocm1-" + digest({"privacy": privacy_version, "billing": billing_version})
    return {
        "policy_version": combined_version,
        "privacy_policy_version": privacy_version,
        "billing_policy_version": billing_version,
    }


def _opencode_adapter_is_supported(record: _OpenCodeModelRecord) -> bool:
    """Re-resolve cached model adapter data through the closed package registry."""

    try:
        descriptor = resolve_native_adapter(
            record.adapter.adapter_id, record.adapter.native_provider_id
        )
    except (NativeProviderDescriptorError, AttributeError):
        return False
    return (
        descriptor == record.adapter
        and descriptor.package_id == record.package_id
        and descriptor.protocol == record.adapter.protocol
        and record.adapter.integration_id in {"openai", "anthropic", "google", None}
    )


def _replace_opencode_model(
    record: _OpenCodeModelRecord, model: AssistantModel
) -> _OpenCodeModelRecord:
    """Update only the cached policy projection while preserving config identity."""

    return replace(record, model=model)


def _validate_custom_disclosure(value: str) -> str:
    """Bound administrator-provided policy text without turning it into verified fact."""

    if not isinstance(value, str) or value != value.strip() or not value.strip():
        raise ProviderUnavailable("custom_policy_review_required")
    try:
        if not 1 <= len(value.encode("utf-8")) <= _CUSTOM_DISCLOSURE_BYTES:
            raise ProviderUnavailable("custom_policy_review_required")
    except UnicodeEncodeError as exc:
        raise ProviderUnavailable("custom_policy_review_required") from exc
    if any(ord(character) < 0x20 and character not in "\t\r\n" for character in value):
        raise ProviderUnavailable("custom_policy_review_required")
    if any(0x7F <= ord(character) <= 0x9F for character in value):
        raise ProviderUnavailable("custom_policy_review_required")
    return value


def _custom_policy_versions(
    base_url: str,
    terms_url: str,
    privacy_disclosure: str,
    billing_disclosure: str,
    billing_class: str,
) -> dict[str, str]:
    """Derive separate policy versions from the exact administrator-reviewed tuple."""

    material = {
        "base_url": base_url,
        "terms_url": terms_url,
        "privacy_disclosure": privacy_disclosure,
        "billing_disclosure": billing_disclosure,
        "billing_class": billing_class,
    }
    encoded = json.dumps(
        material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    full_hash = hashlib.sha256(encoded).hexdigest()
    privacy_hash = hashlib.sha256(b"privacy\x00" + encoded).hexdigest()
    billing_hash = hashlib.sha256(b"billing\x00" + encoded).hexdigest()
    return {
        "policy_version": "custom-policy-" + full_hash[:32],
        "privacy_policy_version": "custom-privacy-" + privacy_hash[:32],
        "billing_policy_version": "custom-billing-" + billing_hash[:32],
    }


def _custom_policy_identity(state: Mapping[str, object]) -> str | None:
    """Return a digest only for the exact saved custom review tuple."""

    if not _custom_review_fields_present(state):
        return None
    material = {
        key: state.get(key)
        for key in (
            "base_url",
            "terms_url",
            "privacy_disclosure",
            "billing_disclosure",
            "billing_class",
            "policy_version",
            "privacy_policy_version",
            "billing_policy_version",
        )
    }
    encoded = json.dumps(
        material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _custom_review_fields_present(state: object) -> bool:
    """Verify completeness and derived versions before using stored custom policy text."""

    if not isinstance(state, Mapping) or state.get("endpoint_policy_reviewed") is not True:
        return False
    base_url = state.get("base_url")
    terms_url = state.get("terms_url")
    privacy = state.get("privacy_disclosure")
    billing = state.get("billing_disclosure")
    billing_class = state.get("billing_class")
    reviewed_at = state.get("terms_reviewed_at")
    if (
        not isinstance(base_url, str)
        or not isinstance(terms_url, str)
        or not isinstance(privacy, str)
        or not isinstance(billing, str)
        or not isinstance(billing_class, str)
        or billing_class not in _CUSTOM_BILLING_CLASSES
        or not isinstance(reviewed_at, str)
        or len(reviewed_at) > 40
    ):
        return False
    try:
        if _validate_public_https_url(base_url) != base_url:
            return False
        if _validate_public_terms_url(terms_url) != terms_url:
            return False
        if _validate_custom_disclosure(privacy) != privacy:
            return False
        if _validate_custom_disclosure(billing) != billing:
            return False
        moment = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            return False
        expected_versions = _custom_policy_versions(
            base_url, terms_url, privacy, billing, billing_class
        )
    except (ProviderUnavailable, ValueError, TypeError, UnicodeEncodeError):
        return False
    return all(state.get(key) == value for key, value in expected_versions.items())


def _custom_model_policy(state: Mapping[str, object]) -> dict[str, object]:
    """Build a cautious model-policy row from explicit, administrator-provided statements."""

    if not _custom_review_fields_present(state):
        raise ProviderUnavailable("custom_policy_review_required")
    return {
        "policy_version": str(state["policy_version"]),
        "privacy_policy_version": str(state["privacy_policy_version"]),
        "billing_policy_version": str(state["billing_policy_version"]),
        "terms_url": str(state["terms_url"]),
        "terms_reviewed_at": str(state["terms_reviewed_at"]),
        "privacy_disclosure": str(state["privacy_disclosure"]),
        "cost_disclosure": str(state["billing_disclosure"]),
        "billing_class": str(state["billing_class"]),
        "training": True,
        "data_collection_allowed": True,
        "data_collection_default": False,
    }


def _validated_native_provider_body(
    protocol: str,
    body: Mapping[str, object],
    *,
    model_alias: str,
    upstream_model_id: str,
    app_tools: list[dict[str, object]],
) -> dict[str, object]:
    """Validate and preserve one vendor's native JSON schema without protocol conversion."""

    if not isinstance(body, Mapping) or not _bounded_json_value(body):
        raise ProviderUnavailable("provider_request_invalid")
    try:
        if (
            len(
                json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
            > 262_144
        ):
            raise ProviderUnavailable("provider_request_invalid")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ProviderUnavailable("provider_request_invalid") from exc

    allowed_tools = _native_application_tools(app_tools, protocol=protocol)
    if protocol == "openai-responses":
        allowed = {
            "model",
            "input",
            "instructions",
            "stream",
            "store",
            "tools",
            "tool_choice",
            "include",
            "max_output_tokens",
            "temperature",
            "top_p",
            "parallel_tool_calls",
            "truncation",
            "prompt_cache_key",
        }
        if (
            set(body) - allowed
            or body.get("model") != model_alias
            or body.get("stream") is not True
            or body.get("store") is not False
            or not _validate_responses_input(body.get("input"), set(allowed_tools))
        ):
            raise ProviderUnavailable("provider_request_invalid")
        instructions = body.get("instructions")
        if instructions is not None and not _bounded_text(instructions, 65_536):
            raise ProviderUnavailable("provider_request_invalid")
        output_tokens = validated_output_token_count(
            body.get("max_output_tokens", native_output_token_budget())
        )
        if output_tokens is None:
            raise ProviderUnavailable("provider_request_invalid")
        _validate_generation_scalars(body, "temperature")
        _validate_generation_scalars(body, "top_p")
        if "prompt_cache_key" in body and not _bounded_text(body["prompt_cache_key"], 256):
            raise ProviderUnavailable("provider_request_invalid")
        if "include" in body and (
            not isinstance(body["include"], list)
            or len(body["include"]) > 8
            or any(
                not isinstance(item, str) or item != "reasoning.encrypted_content"
                for item in body["include"]
            )
        ):
            raise ProviderUnavailable("provider_request_invalid")
        if "tools" in body:
            _validate_responses_tools(body["tools"], allowed_tools)
        if "tool_choice" in body:
            _validate_responses_tool_choice(body["tool_choice"], set(allowed_tools))
        if "truncation" in body and (
            not isinstance(body["truncation"], str)
            or body["truncation"] not in {"auto", "disabled"}
        ):
            raise ProviderUnavailable("provider_request_invalid")
        if "parallel_tool_calls" in body and type(body["parallel_tool_calls"]) is not bool:
            raise ProviderUnavailable("provider_request_invalid")
        request = dict(body)
        request["model"] = upstream_model_id
        request["max_output_tokens"] = output_tokens
        # Native request metadata never needs to select a provider-side stored prompt cache.
        request.pop("prompt_cache_key", None)
        return request

    if protocol == "anthropic-messages":
        allowed = {
            "model",
            "max_tokens",
            "messages",
            "system",
            "stream",
            "tools",
            "tool_choice",
            "temperature",
            "top_p",
            "top_k",
            "stop_sequences",
        }
        if (
            set(body) - allowed
            or body.get("model") != model_alias
            or body.get("stream") is not True
            or type(body.get("max_tokens")) is not int
            or validated_output_token_count(body.get("max_tokens")) is None
            or not _validate_anthropic_messages(body.get("messages"), set(allowed_tools))
        ):
            raise ProviderUnavailable("provider_request_invalid")
        system = body.get("system")
        if system is not None and not _validate_anthropic_system(system):
            raise ProviderUnavailable("provider_request_invalid")
        for field in ("temperature", "top_p", "top_k"):
            _validate_generation_scalars(
                body,
                field,
                maximum=1 if field == "temperature" else None,
            )
        stop_sequences = body.get("stop_sequences")
        if stop_sequences is not None and (
            not isinstance(stop_sequences, list)
            or len(stop_sequences) > 8
            or any(not _bounded_text(value, 256) for value in stop_sequences)
        ):
            raise ProviderUnavailable("provider_request_invalid")
        if "tools" in body:
            _validate_anthropic_tools(body["tools"], allowed_tools)
        if "tool_choice" in body:
            _validate_anthropic_tool_choice(body["tool_choice"], set(allowed_tools))
        request = dict(body)
        request["model"] = upstream_model_id
        return request

    if protocol == "google-generative-language":
        allowed = {"contents", "systemInstruction", "tools", "toolConfig", "generationConfig"}
        if set(body) - allowed or not _validate_google_contents(
            body.get("contents"), set(allowed_tools)
        ):
            raise ProviderUnavailable("provider_request_invalid")
        system = body.get("systemInstruction")
        if system is not None and not _validate_google_system_instruction(system):
            raise ProviderUnavailable("provider_request_invalid")
        if "tools" in body:
            _validate_google_tools(body["tools"], allowed_tools)
        if "toolConfig" in body:
            _validate_google_tool_config(body["toolConfig"], set(allowed_tools))
        generation_config = body.get("generationConfig", {})
        if "generationConfig" in body:
            _validate_google_generation_config(generation_config)
        if not isinstance(generation_config, Mapping):
            raise ProviderUnavailable("provider_request_invalid")
        output_tokens = validated_output_token_count(
            generation_config.get("maxOutputTokens", native_output_token_budget())
        )
        if output_tokens is None:
            raise ProviderUnavailable("provider_request_invalid")
        request = dict(body)
        request["generationConfig"] = {
            **dict(generation_config),
            "maxOutputTokens": output_tokens,
        }
        return request
    if protocol == "openai-compatible-chat":
        allowed = {
            "model",
            "messages",
            "stream",
            "temperature",
            "max_tokens",
            "tools",
            "tool_choice",
            "store",
            "stream_options",
        }
        if (
            set(body) - allowed
            or body.get("model") != model_alias
            or body.get("stream") is not True
            or ("store" in body and body.get("store") is not False)
        ):
            raise ProviderUnavailable("provider_request_invalid")
        stream_options = body.get("stream_options")
        if "stream_options" in body and (
            not isinstance(stream_options, Mapping)
            or dict(stream_options) != {"include_usage": True}
        ):
            raise ProviderUnavailable("provider_request_invalid")
        tools, tool_names = _validate_native_compatible_tools(body.get("tools"), allowed_tools)
        messages = body.get("messages")
        if not isinstance(messages, list) or not 1 <= len(messages) <= 32:
            raise ProviderUnavailable("provider_request_invalid")
        clean_messages = _validated_messages(messages, tool_names)
        tool_choice = body.get("tool_choice")
        if tool_choice is not None and (
            not isinstance(tool_choice, str) or tool_choice not in {"auto", "none", *tool_names}
        ):
            raise ProviderUnavailable("provider_request_invalid")
        if "temperature" in body:
            _validate_generation_scalars(body, "temperature")
        output_tokens = validated_output_token_count(
            body.get("max_tokens", native_output_token_budget())
        )
        if output_tokens is None:
            raise ProviderUnavailable("provider_request_invalid")
        request = dict(body)
        request["model"] = upstream_model_id
        request["max_tokens"] = output_tokens
        request["messages"] = clean_messages
        request["store"] = False
        if tools is None:
            request.pop("tools", None)
        else:
            request["tools"] = tools
        return request
    raise ProviderUnavailable("provider_adapter_unsupported")


def _encode_provider_request(body: Mapping[str, object]) -> bytes:
    """Serialize one already-validated provider request within the shared byte bound."""

    try:
        encoded = json.dumps(
            body, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ProviderUnavailable("provider_request_invalid") from exc
    if len(encoded) > 262_144:
        raise ProviderUnavailable("provider_request_invalid")
    return encoded


def _sanitize_compatible_frame(
    frame: bytes,
    *,
    declared_tool_names: set[str],
    state: _OpenAIToolCallStreamState,
) -> bytes | None:
    """Retain only bounded OpenAI-compatible delta fields from one complete SSE event."""

    try:
        lines = frame.decode("utf-8", "strict").splitlines()
    except UnicodeDecodeError as exc:
        raise ProviderUnavailable("provider_response_invalid") from exc
    data = [line[5:].lstrip() for line in lines if line.startswith("data:")]
    if not data:
        return frame
    safe = _sanitize_openai_sse_data(
        "\n".join(data), declared_tool_names=declared_tool_names, state=state
    )
    if safe is None:
        return None
    return ("data: " + safe + "\n\n").encode("utf-8")


def _bounded_json_value(value: object, *, depth: int = 0, budget: list[int] | None = None) -> bool:
    """Bound nested JSON structure before protocol-specific traversal or serialization."""

    if budget is None:
        budget = [8192]
    budget[0] -= 1
    if budget[0] < 0 or depth > 20:
        return False
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, int):
        return -(2**63) <= value <= 2**63 - 1
    if isinstance(value, float):
        return value == value and abs(value) < float("inf")
    if isinstance(value, str):
        return _bounded_text(value, 65_536)
    if isinstance(value, Mapping):
        return len(value) <= 128 and all(
            isinstance(key, str)
            and len(key) <= 128
            and _bounded_json_value(item, depth=depth + 1, budget=budget)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return len(value) <= 512 and all(
            _bounded_json_value(item, depth=depth + 1, budget=budget) for item in value
        )
    return False


class _SecretStreamGuard:
    """Withhold provider events until configured-secret fragments cannot span them."""

    _MAX_HELD_BYTES = 262_144
    _MAX_HELD_FRAMES = 256

    def __init__(self, secret: str | None, *, protocol: str) -> None:
        if secret is not None and (not isinstance(secret, str) or not secret):
            raise ProviderUnavailable("credential_required")
        self._secret = secret
        self._protocol = protocol
        self._patterns = _secret_byte_patterns(secret) if secret is not None else ()
        self._raw_prefix_tables = tuple(_prefix_table(value) for value in self._patterns)
        self._raw_match_lengths = [0] * len(self._patterns)
        self._raw_offset = 0
        self._text_prefix_table = _prefix_table(secret) if secret is not None else ()
        self._text_match_lengths: dict[str, int] = {}
        self._text_offsets: dict[str, int] = {}
        self._held: list[tuple[bytes, int, dict[str, int]]] = []
        self._held_bytes = 0

    def push(self, frame: bytes) -> tuple[bytes, ...]:
        """Check one complete event and release only frames beyond the secret window."""

        if not isinstance(frame, bytes) or not frame or len(frame) > 65_536:
            raise ProviderUnavailable("provider_response_invalid")
        if self._secret is None:
            return (frame,)
        if _event_contains_secret(frame, self._secret):
            raise ProviderUnavailable("provider_response_secret_rejected")
        for index, pattern in enumerate(self._patterns):
            match_length, found = _advance_prefix_match(
                frame,
                pattern,
                self._raw_prefix_tables[index],
                self._raw_match_lengths[index],
            )
            if found:
                raise ProviderUnavailable("provider_response_secret_rejected")
            self._raw_match_lengths[index] = match_length
        self._raw_offset += len(frame)
        raw_safe_offset = self._raw_offset - max(self._raw_match_lengths, default=0)

        channels = _event_text_channels(frame, self._protocol)
        if len(self._text_offsets) + len(channels) > 512:
            raise ProviderUnavailable("provider_response_invalid")
        channel_ends: dict[str, int] = {}
        for channel, fragment in channels.items():
            match_length, found = _advance_prefix_match(
                fragment,
                self._secret,
                self._text_prefix_table,
                self._text_match_lengths.get(channel, 0),
            )
            if found:
                raise ProviderUnavailable("provider_response_secret_rejected")
            self._text_match_lengths[channel] = match_length
            channel_end = self._text_offsets.get(channel, 0) + len(fragment)
            self._text_offsets[channel] = channel_end
            channel_ends[channel] = channel_end

        self._held.append((frame, self._raw_offset, channel_ends))
        self._held_bytes += len(frame)
        if len(self._held) > self._MAX_HELD_FRAMES or self._held_bytes > self._MAX_HELD_BYTES:
            raise ProviderUnavailable("provider_response_invalid")

        ready: list[bytes] = []
        while self._held:
            _front, raw_end, front_channels = self._held[0]
            raw_unresolved = raw_end > raw_safe_offset
            text_unresolved = any(
                end > self._text_offsets.get(channel, 0) - self._text_match_lengths.get(channel, 0)
                for channel, end in front_channels.items()
            )
            if raw_unresolved or text_unresolved:
                break
            released, _released_raw_end, _released_channels = self._held.pop(0)
            ready.append(released)
            self._held_bytes -= len(released)
        return tuple(ready)

    def finish(self) -> tuple[bytes, ...]:
        """Flush the bounded tail only after upstream EOF confirms no later continuation."""

        frames = tuple(frame for frame, _raw_end, _channels in self._held)
        self._held.clear()
        self._held_bytes = 0
        return frames


def _prefix_table(pattern: str | bytes) -> tuple[int, ...]:
    """Build the fallback table used to track secret-prefix matches incrementally."""

    table = [0] * len(pattern)
    matched = 0
    for index in range(1, len(pattern)):
        while matched and pattern[index] != pattern[matched]:
            matched = table[matched - 1]
        if pattern[index] == pattern[matched]:
            matched += 1
        table[index] = matched
    return tuple(table)


def _advance_prefix_match(
    value: str | bytes,
    pattern: str | bytes,
    table: tuple[int, ...],
    matched: int,
) -> tuple[int, bool]:
    """Return the longest trailing prefix match and whether the secret appeared."""

    found = False
    for character in value:
        while matched and character != pattern[matched]:
            matched = table[matched - 1]
        if character == pattern[matched]:
            matched += 1
        if matched == len(pattern):
            found = True
            matched = table[matched - 1]
    return matched, found


def _secret_byte_patterns(secret: str) -> tuple[bytes, ...]:
    try:
        return tuple(
            dict.fromkeys(
                (
                    secret.encode("utf-8"),
                    json.dumps(secret, ensure_ascii=True)[1:-1].encode("ascii"),
                    json.dumps(secret, ensure_ascii=False)[1:-1].encode("utf-8"),
                )
            )
        )
    except (UnicodeEncodeError, TypeError, ValueError):
        raise ProviderUnavailable("provider_response_invalid") from None


def _event_text_channels(frame: bytes, protocol: str) -> dict[str, str]:
    """Extract bounded output fragments keyed by each protocol's independent stream channel."""

    try:
        lines = frame.decode("utf-8", "strict").splitlines()
    except UnicodeDecodeError as exc:
        raise ProviderUnavailable("provider_response_invalid") from exc
    data_lines = [line[5:].lstrip() for line in lines if line.startswith("data:")]
    if not data_lines:
        return {}
    payload_text = "\n".join(data_lines)
    if payload_text == "[DONE]":
        return {}
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return {}

    output: dict[str, str] = {}

    def add(channel_parts: tuple[object, ...], value: object) -> None:
        if not isinstance(value, str) or not value:
            return
        safe_parts = [str(item)[:128] for item in channel_parts]
        identity = json.dumps(safe_parts, ensure_ascii=True, separators=(",", ":"))
        channel = hashlib.sha256(identity.encode("ascii")).hexdigest()
        output[channel] = output.get(channel, "") + value

    def bounded_id(value: object, default: str) -> object:
        if type(value) is int and 0 <= value <= 1024:
            return value
        if isinstance(value, str) and 1 <= len(value) <= 128:
            return value
        return default

    if protocol == "openai-responses" and isinstance(payload, Mapping):
        event_type = bounded_id(payload.get("type"), "unknown-event")
        output_index = bounded_id(payload.get("output_index"), "no-output")
        if event_type == "response.output_text.delta":
            add(
                (
                    "responses-text",
                    output_index,
                    bounded_id(payload.get("content_index"), "no-content"),
                ),
                payload.get("delta"),
            )
        elif event_type == "response.reasoning_summary_text.delta":
            add(
                (
                    "responses-reasoning",
                    output_index,
                    bounded_id(payload.get("summary_index"), "no-summary"),
                ),
                payload.get("delta"),
            )
        elif event_type == "response.function_call_arguments.delta":
            # output_index is stable for the full function-call item; item_id is not
            # guaranteed on every delta and therefore cannot partition the carry.
            add(("responses-function-args", output_index), payload.get("delta"))
    elif protocol == "openai-compatible-chat" and isinstance(payload, Mapping):
        choices = payload.get("choices")
        if isinstance(choices, list):
            for choice in choices[:8]:
                if not isinstance(choice, Mapping):
                    continue
                choice_index = bounded_id(choice.get("index"), "no-choice")
                delta = choice.get("delta")
                if not isinstance(delta, Mapping):
                    continue
                add(("chat-content", choice_index), delta.get("content"))
                calls = delta.get("tool_calls")
                if isinstance(calls, list):
                    for call in calls[:8]:
                        if not isinstance(call, Mapping):
                            continue
                        function = call.get("function")
                        if isinstance(function, Mapping):
                            call_index = bounded_id(call.get("index"), "no-call-index")
                            add(
                                ("chat-tool-args", choice_index, call_index),
                                function.get("arguments"),
                            )
    elif protocol == "anthropic-messages" and isinstance(payload, Mapping):
        event_type = bounded_id(payload.get("type"), "unknown-event")
        index = bounded_id(payload.get("index"), "no-block")
        delta = payload.get("delta")
        if isinstance(delta, Mapping):
            delta_type = bounded_id(delta.get("type"), "no-delta-type")
            add(("anthropic", event_type, index, delta_type), delta.get("text"))
            add(("anthropic", event_type, index, delta_type), delta.get("partial_json"))
    elif protocol == "google-generative-language" and isinstance(payload, Mapping):
        candidates = payload.get("candidates")
        if isinstance(candidates, list):
            for candidate in candidates[:8]:
                if not isinstance(candidate, Mapping):
                    continue
                candidate_index = bounded_id(candidate.get("index"), "no-candidate")
                content = candidate.get("content")
                parts = content.get("parts") if isinstance(content, Mapping) else None
                if isinstance(parts, list):
                    for part_index, part in enumerate(parts[:32]):
                        if not isinstance(part, Mapping):
                            continue
                        add(("google-text", candidate_index, part_index), part.get("text"))
                        function_call = part.get("functionCall")
                        if isinstance(function_call, Mapping):
                            add(
                                ("google-function-args", candidate_index, part_index),
                                json.dumps(
                                    function_call.get("args"),
                                    ensure_ascii=True,
                                    separators=(",", ":"),
                                ),
                            )
    return output


def _sse_event_boundary(value: bytearray) -> tuple[int, int] | None:
    """Locate one complete SSE frame using LF or CRLF event separators."""

    match = re.search(rb"(?:\r?\n){2}", value)
    return (match.start(), match.end()) if match is not None else None


def _event_contains_secret(frame: bytes, secret: str) -> bool:
    """Detect literal and JSON-decoded secret text before any event bytes are released."""

    if any(pattern and pattern in frame for pattern in _secret_byte_patterns(secret)):
        return True

    try:
        lines = frame.decode("utf-8", "strict").splitlines()
    except UnicodeDecodeError as exc:
        raise ProviderUnavailable("provider_response_invalid") from exc
    data_lines = [line[5:].lstrip() for line in lines if line.startswith("data:")]
    if not data_lines:
        return False
    payload_text = "\n".join(data_lines)
    if payload_text == "[DONE]":
        return False
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return False
    return _json_contains_secret(payload, secret)


def _json_contains_secret(value: object, secret: str) -> bool:
    if isinstance(value, str):
        return secret in value
    if isinstance(value, Mapping):
        return any(
            (isinstance(key, str) and secret in key) or _json_contains_secret(item, secret)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_json_contains_secret(item, secret) for item in value)
    return False


def _bounded_text(value: object, limit: int) -> bool:
    if not isinstance(value, str) or "\x00" in value:
        return False
    byte_length = _utf8_length(value)
    return byte_length is not None and byte_length <= limit


def _utf8_length(value: str) -> int | None:
    """Return the UTF-8 byte length, rejecting lone surrogates as invalid input."""

    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        return None


def _valid_native_search_arguments(value: object) -> bool:
    if not isinstance(value, Mapping) or set(value) != {"query"}:
        return False
    query = value.get("query")
    query_bytes = _utf8_length(query) if isinstance(query, str) else None
    return (
        isinstance(query, str)
        and query_bytes is not None
        and 0 < query_bytes <= MAX_SEARCH_QUERY_BYTES
        and query == query.strip()
        and not any(ord(character) < 32 and character not in "\t\n" for character in query)
    )


def _valid_native_webfetch_arguments(value: object) -> bool:
    """Validate one native fetch call against the exact URL and deadline policy."""

    if not isinstance(value, Mapping) or set(value) - {"url", "format", "timeout"}:
        return False
    url = value.get("url")
    if not isinstance(url, str) or validate_webfetch_url(url) != url:
        return False
    output_format = value.get("format")
    if "format" in value and (
        not isinstance(output_format, str) or output_format not in {"text", "markdown", "html"}
    ):
        return False
    if "timeout" not in value:
        return True
    timeout = value["timeout"]
    if type(timeout) is int:
        return 0 < timeout <= 120
    return type(timeout) is float and math.isfinite(timeout) and 0 < timeout <= 120


def _parse_json_object(value: str) -> dict[str, object] | None:
    """Parse one bounded, duplicate-free JSON object with finite numbers."""

    value_bytes = _utf8_length(value) if isinstance(value, str) else None
    if value_bytes is None or value_bytes > 16_384:
        return None

    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = item
        return result

    try:
        parsed = json.loads(
            value,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
            object_pairs_hook=object_pairs,
        )
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
        return None
    if not isinstance(parsed, dict) or not _bounded_json_value(parsed):
        return None
    return parsed


def _validate_generation_scalars(
    body: Mapping[str, object],
    field: str,
    *,
    maximum: float | None = None,
) -> None:
    if field not in body:
        return
    value = body[field]
    if field in {"max_output_tokens", "top_k"}:
        if type(value) is not int or not 1 <= value <= 8192:
            raise ProviderUnavailable("provider_request_invalid")
        return
    upper_bound = maximum if maximum is not None else (1 if field == "top_p" else 2)
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or not 0 <= value <= upper_bound
    ):
        raise ProviderUnavailable("provider_request_invalid")


def _native_application_tools(
    app_tools: list[dict[str, object]],
    *,
    protocol: str,
) -> dict[str, tuple[str | None, Mapping[str, object] | None]]:
    if not isinstance(app_tools, list) or not 1 <= len(app_tools) <= 32:
        raise ProviderUnavailable("provider_request_invalid")
    output: dict[str, tuple[str | None, Mapping[str, object] | None]] = {}
    for tool in app_tools:
        if not isinstance(tool, Mapping):
            raise ProviderUnavailable("provider_request_invalid")
        name = tool.get("name")
        description = tool.get("description")
        schema = tool.get("inputSchema")
        if (
            not isinstance(name, str)
            or not _bounded_text(name, 160)
            or not isinstance(description, str)
            or not _bounded_text(description, 1000)
            or not isinstance(schema, Mapping)
            or not _bounded_json_value(schema)
        ):
            raise ProviderUnavailable("provider_request_invalid")
        wire_schema: Mapping[str, object] | None
        if protocol == "google-generative-language":
            try:
                wire_schema = project_gemini_tool_schema(schema)
            except ValueError as exc:
                raise ProviderUnavailable("provider_request_invalid") from exc
        else:
            wire_schema = schema
        aliases = {name, "signal-ledger_" + name.replace(".", "_")}
        for alias in aliases:
            if alias in output:
                raise ProviderUnavailable("provider_request_invalid")
            output[alias] = (description, wire_schema)
    try:
        search_schema = native_websearch_schema(protocol)
        webfetch_schema = native_webfetch_schema(protocol)
    except ValueError as exc:
        raise ProviderUnavailable("provider_request_invalid") from exc
    output["websearch"] = (None, search_schema)
    output["webfetch"] = (None, webfetch_schema)
    return output


def _validate_native_compatible_tools(
    raw_tools: object,
    allowed_tools: Mapping[str, tuple[str | None, Mapping[str, object] | None]],
) -> tuple[list[dict[str, object]] | None, set[str]]:
    """Accept only declarations derived from the fixed app gateway or native builtins."""

    if raw_tools is None:
        return None, set()
    if not isinstance(raw_tools, list) or not 1 <= len(raw_tools) <= 13:
        raise ProviderUnavailable("provider_request_invalid")
    try:
        encoded_size = len(
            json.dumps(
                raw_tools, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode("utf-8")
        )
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ProviderUnavailable("provider_request_invalid") from exc
    if encoded_size > 65_536:
        raise ProviderUnavailable("provider_request_invalid")

    output: list[dict[str, object]] = []
    names: set[str] = set()
    for item in raw_tools:
        if not isinstance(item, Mapping) or set(item) != {"type", "function"}:
            raise ProviderUnavailable("provider_request_invalid")
        function = item.get("function")
        if (
            item.get("type") != "function"
            or not isinstance(function, Mapping)
            or set(function) - {"name", "description", "parameters", "strict"}
            or not {"name", "description", "parameters"} <= set(function)
            or ("strict" in function and function.get("strict") is not False)
        ):
            raise ProviderUnavailable("provider_request_invalid")
        name = function.get("name")
        description = function.get("description")
        parameters = function.get("parameters")
        if (
            not isinstance(name, str)
            or name not in allowed_tools
            or name in names
            or not isinstance(description, str)
            or not isinstance(parameters, Mapping)
            or not _native_tool_schema_matches(
                name,
                description,
                parameters,
                allowed_tools[name],
                protocol="openai-compatible-chat",
            )
        ):
            raise ProviderUnavailable("provider_request_invalid")
        names.add(name)
        output.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": dict(parameters),
                    **({"strict": False} if function.get("strict") is False else {}),
                },
            }
        )
    return output, names


def _native_tool_schema_matches(
    name: str,
    description: object,
    schema: object,
    reviewed: tuple[str | None, Mapping[str, object] | None],
    *,
    protocol: str,
) -> bool:
    expected_description, expected_schema = reviewed
    if name == "websearch":
        if (
            not isinstance(description, str)
            or _utf8_length(description) is None
            or hashlib.sha256(description.encode("utf-8")).hexdigest()
            != native_websearch_description_sha256()
        ):
            return False
    elif name == "webfetch":
        if (
            not isinstance(description, str)
            or _utf8_length(description) is None
            or hashlib.sha256(description.encode("utf-8")).hexdigest()
            != NATIVE_WEBFETCH_DESCRIPTION_SHA256
        ):
            return False
    elif description != expected_description:
        return False
    if expected_schema is None:
        return schema is None
    if not isinstance(schema, Mapping):
        return False
    if protocol == "google-generative-language":
        return _canonical_provider_schema(schema) == _canonical_provider_schema(expected_schema)
    return dict(schema) == dict(expected_schema)


def _canonical_provider_schema(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): (
                item.casefold()
                if key == "type" and isinstance(item, str)
                else _canonical_provider_schema(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_canonical_provider_schema(item) for item in value]
    return value


def _validate_responses_input(value: object, tools: set[str]) -> bool:
    if isinstance(value, str):
        return _bounded_text(value, 65_536)
    if not isinstance(value, list) or not 1 <= len(value) <= 64:
        return False
    pending_calls: set[str] = set()
    seen_call_ids: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            return False
        kind = item.get("type")
        if kind == "message":
            role = item.get("role")
            if (
                set(item) != {"type", "role", "content"}
                or not isinstance(role, str)
                or role not in {"system", "developer", "user", "assistant"}
            ):
                return False
            content = item.get("content")
            if isinstance(content, str):
                if not _bounded_text(content, 65_536):
                    return False
            elif not _validate_responses_text_content(content):
                return False
        elif kind == "function_call_output":
            if set(item) != {"type", "call_id", "output"}:
                return False
            call_id = item.get("call_id")
            output = item.get("output")
            if (
                not isinstance(call_id, str)
                or _TOOL_CALL_ID.fullmatch(call_id) is None
                or call_id not in pending_calls
                or not _bounded_text(output, 16_000)
            ):
                return False
            pending_calls.remove(call_id)
        elif kind == "function_call":
            if set(item) - {"type", "call_id", "name", "arguments", "id"} or not {
                "type",
                "call_id",
                "name",
                "arguments",
            } <= set(item):
                return False
            call_id = item.get("call_id")
            name = item.get("name")
            arguments = item.get("arguments")
            if (
                not isinstance(call_id, str)
                or _TOOL_CALL_ID.fullmatch(call_id) is None
                or call_id in seen_call_ids
                or not isinstance(name, str)
                or name not in tools
                or not _bounded_text(arguments, 16_384)
                or not _is_json_object(arguments)
                or (name == "websearch" and not _valid_json_search_arguments(arguments))
                or (
                    "id" in item
                    and (
                        not isinstance(item["id"], str)
                        or _TOOL_CALL_ID.fullmatch(item["id"]) is None
                    )
                )
            ):
                return False
            pending_calls.add(call_id)
            seen_call_ids.add(call_id)
        else:
            return False
    return not pending_calls


def _validate_responses_text_content(value: object) -> bool:
    if not isinstance(value, list) or not 1 <= len(value) <= 64:
        return False
    return all(
        isinstance(item, Mapping)
        and set(item) == {"type", "text"}
        and item.get("type") == "input_text"
        and _bounded_text(item.get("text"), 65_536)
        for item in value
    )


def _validate_responses_tools(
    value: object,
    expected: Mapping[str, tuple[str | None, Mapping[str, object] | None]],
) -> None:
    if not isinstance(value, list) or not 1 <= len(value) <= 13:
        raise ProviderUnavailable("provider_request_invalid")
    seen: set[str] = set()
    for tool in value:
        if not isinstance(tool, Mapping) or set(tool) - {
            "type",
            "name",
            "description",
            "parameters",
            "strict",
        }:
            raise ProviderUnavailable("provider_request_invalid")
        name = tool.get("name")
        reviewed = expected.get(name) if isinstance(name, str) else None
        if (
            tool.get("type") != "function"
            or reviewed is None
            or name in seen
            or not _native_tool_schema_matches(
                str(name),
                tool.get("description"),
                tool.get("parameters"),
                reviewed,
                protocol="openai-responses",
            )
            or ("strict" in tool and tool.get("strict") is not False)
        ):
            raise ProviderUnavailable("provider_request_invalid")
        seen.add(str(name))


def _validate_responses_tool_choice(value: object, names: set[str]) -> None:
    if isinstance(value, str) and value in {"auto", "none", "required"}:
        return
    if (
        isinstance(value, Mapping)
        and set(value) == {"type", "name"}
        and value.get("type") == "function"
        and value.get("name") in names
    ):
        return
    raise ProviderUnavailable("provider_request_invalid")


def _is_json_object(value: str) -> bool:
    try:
        parsed = json.loads(value, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (json.JSONDecodeError, ValueError, TypeError):
        return False
    return isinstance(parsed, Mapping) and _bounded_json_value(parsed)


def _valid_json_search_arguments(value: str) -> bool:
    parsed = _parse_json_object(value)
    return parsed is not None and _valid_native_search_arguments(parsed)


def _valid_json_webfetch_arguments(value: str) -> bool:
    parsed = _parse_json_object(value)
    return parsed is not None and _valid_native_webfetch_arguments(parsed)


def _validate_anthropic_messages(value: object, tools: set[str]) -> bool:
    if not isinstance(value, list) or not 1 <= len(value) <= 64:
        return False
    pending: set[str] = set()
    for message in value:
        if (
            not isinstance(message, Mapping)
            or set(message) != {"role", "content"}
            or not isinstance(message.get("role"), str)
            or message.get("role") not in {"user", "assistant"}
            or not _validate_anthropic_content(
                message.get("content"),
                tools,
                pending=pending,
                role=str(message.get("role")),
            )
        ):
            return False
    return not pending


def _validate_anthropic_content(
    value: object,
    tools: set[str],
    *,
    pending: set[str] | None = None,
    role: str | None = None,
) -> bool:
    if isinstance(value, str):
        return _bounded_text(value, 65_536)
    if not isinstance(value, list) or not 1 <= len(value) <= 64:
        return False
    open_calls = pending if pending is not None else set()
    for block in value:
        if not isinstance(block, Mapping):
            return False
        kind = block.get("type")
        if kind == "text":
            if set(block) - {"type", "text"} or not _bounded_text(block.get("text"), 65_536):
                return False
        elif kind == "tool_use":
            call_id = block.get("id")
            name = block.get("name")
            arguments = block.get("input")
            if (
                set(block) != {"type", "id", "name", "input"}
                or not isinstance(call_id, str)
                or _TOOL_CALL_ID.fullmatch(call_id) is None
                or call_id in open_calls
                or role != "assistant"
                or not isinstance(name, str)
                or name not in tools
                or not isinstance(arguments, Mapping)
                or not _bounded_json_value(arguments)
                or (name == "websearch" and not _valid_native_search_arguments(arguments))
            ):
                return False
            open_calls.add(call_id)
        elif kind == "tool_result":
            call_id = block.get("tool_use_id")
            content = block.get("content")
            if (
                set(block) - {"type", "tool_use_id", "content", "is_error"}
                or not {"type", "tool_use_id", "content"} <= set(block)
                or not isinstance(call_id, str)
                or call_id not in open_calls
                or role != "user"
                or ("is_error" in block and type(block.get("is_error")) is not bool)
                or not _bounded_tool_result(content)
            ):
                return False
            open_calls.remove(call_id)
        else:
            return False
    return True


def _validate_anthropic_system(value: object) -> bool:
    if isinstance(value, str):
        return _bounded_text(value, 65_536)
    if not isinstance(value, list) or not 1 <= len(value) <= 64:
        return False
    return all(
        isinstance(block, Mapping)
        and set(block) == {"type", "text"}
        and block.get("type") == "text"
        and _bounded_text(block.get("text"), 65_536)
        for block in value
    )


def _bounded_tool_result(value: object) -> bool:
    if isinstance(value, str):
        return _bounded_text(value, 16_000)
    if not isinstance(value, list) or not 1 <= len(value) <= 16:
        return False
    return all(
        isinstance(item, Mapping)
        and set(item) == {"type", "text"}
        and item.get("type") == "text"
        and _bounded_text(item.get("text"), 16_000)
        for item in value
    )


def _validate_anthropic_tools(
    value: object,
    expected: Mapping[str, tuple[str | None, Mapping[str, object] | None]],
) -> None:
    if not isinstance(value, list) or not 1 <= len(value) <= 13:
        raise ProviderUnavailable("provider_request_invalid")
    seen: set[str] = set()
    for tool in value:
        if not isinstance(tool, Mapping) or set(tool) != {"name", "description", "input_schema"}:
            raise ProviderUnavailable("provider_request_invalid")
        name = tool.get("name")
        reviewed = expected.get(name) if isinstance(name, str) else None
        if (
            reviewed is None
            or name in seen
            or not _native_tool_schema_matches(
                str(name),
                tool.get("description"),
                tool.get("input_schema"),
                reviewed,
                protocol="anthropic-messages",
            )
        ):
            raise ProviderUnavailable("provider_request_invalid")
        seen.add(str(name))


def _validate_anthropic_tool_choice(value: object, names: set[str]) -> None:
    if not isinstance(value, Mapping) or not isinstance(value.get("type"), str):
        raise ProviderUnavailable("provider_request_invalid")
    kind = value.get("type")
    if kind in {"auto", "none", "any"} and set(value) == {"type"}:
        return
    if kind == "tool" and set(value) == {"type", "name"} and value.get("name") in names:
        return
    raise ProviderUnavailable("provider_request_invalid")


def _validate_google_content(
    value: object,
    tools: set[str],
    *,
    pending_calls: list[str] | None = None,
) -> bool:
    if not isinstance(value, Mapping) or set(value) - {"role", "parts"}:
        return False
    role = value.get("role")
    parts = value.get("parts")
    if role is not None and (not isinstance(role, str) or role not in {"user", "model"}):
        return False
    if not isinstance(parts, list) or not 1 <= len(parts) <= 64:
        return False
    pending = pending_calls if pending_calls is not None else []
    for part in parts:
        if not isinstance(part, Mapping):
            return False
        if set(part) == {"text"} and _bounded_text(part.get("text"), 65_536):
            continue
        function_call = part.get("functionCall")
        function_response = part.get("functionResponse")
        if function_call is not None:
            name = function_call.get("name") if isinstance(function_call, Mapping) else None
            if (
                set(part) != {"functionCall"}
                or not isinstance(function_call, Mapping)
                or set(function_call) - {"name", "args"}
                or not {"name", "args"} <= set(function_call)
                or role != "model"
                or not isinstance(name, str)
                or name not in tools
                or not isinstance(function_call.get("args"), Mapping)
                or not _bounded_json_value(function_call["args"])
                or (
                    name == "websearch"
                    and not _valid_native_search_arguments(function_call["args"])
                )
            ):
                return False
            pending.append(name)
            continue
        if function_response is not None:
            name = function_response.get("name") if isinstance(function_response, Mapping) else None
            if (
                set(part) != {"functionResponse"}
                or not isinstance(function_response, Mapping)
                or set(function_response) - {"name", "response", "willContinue", "scheduling"}
                or not {"name", "response"} <= set(function_response)
                or role != "user"
                or not isinstance(name, str)
                or name not in tools
                or name not in pending
                or not _bounded_json_value(function_response.get("response"))
            ):
                return False
            pending.remove(name)
            continue
        return False
    return True


def _validate_google_contents(value: object, tools: set[str]) -> bool:
    if not isinstance(value, list) or not 1 <= len(value) <= 64:
        return False
    pending: list[str] = []
    return (
        all(_validate_google_content(item, tools, pending_calls=pending) for item in value)
        and not pending
    )


def _validate_google_system_instruction(value: object) -> bool:
    if not isinstance(value, Mapping) or set(value) != {"parts"}:
        return False
    parts = value.get("parts")
    if not isinstance(parts, list) or not 1 <= len(parts) <= 64:
        return False
    return all(
        isinstance(part, Mapping)
        and set(part) == {"text"}
        and _bounded_text(part.get("text"), 65_536)
        for part in parts
    )


def _validate_google_tools(
    value: object,
    expected: Mapping[str, tuple[str | None, Mapping[str, object] | None]],
) -> None:
    if not isinstance(value, list) or len(value) != 1:
        raise ProviderUnavailable("provider_request_invalid")
    item = value[0]
    if not isinstance(item, Mapping) or set(item) != {"functionDeclarations"}:
        raise ProviderUnavailable("provider_request_invalid")
    declarations = item.get("functionDeclarations")
    if not isinstance(declarations, list) or not 1 <= len(declarations) <= 13:
        raise ProviderUnavailable("provider_request_invalid")
    seen: set[str] = set()
    for declaration in declarations:
        if not isinstance(declaration, Mapping) or set(declaration) not in (
            {"name", "description", "parameters"},
            {"name", "description"},
        ):
            raise ProviderUnavailable("provider_request_invalid")
        name = declaration.get("name")
        reviewed = expected.get(name) if isinstance(name, str) else None
        if (
            reviewed is None
            or name in seen
            or not _native_tool_schema_matches(
                str(name),
                declaration.get("description"),
                declaration.get("parameters"),
                reviewed,
                protocol="google-generative-language",
            )
        ):
            raise ProviderUnavailable("provider_request_invalid")
        seen.add(str(name))


def _validate_google_tool_config(value: object, names: set[str]) -> None:
    if not isinstance(value, Mapping) or set(value) != {"functionCallingConfig"}:
        raise ProviderUnavailable("provider_request_invalid")
    config = value.get("functionCallingConfig")
    if not isinstance(config, Mapping) or set(config) - {"mode", "allowedFunctionNames"}:
        raise ProviderUnavailable("provider_request_invalid")
    if not isinstance(config.get("mode"), str) or config.get("mode") not in {
        "AUTO",
        "ANY",
        "NONE",
    }:
        raise ProviderUnavailable("provider_request_invalid")
    allowed = config.get("allowedFunctionNames")
    if allowed is not None and (
        not isinstance(allowed, list)
        or len(allowed) > 13
        or any(not isinstance(name, str) or name not in names for name in allowed)
    ):
        raise ProviderUnavailable("provider_request_invalid")


def _validate_google_generation_config(value: object) -> None:
    if not isinstance(value, Mapping):
        raise ProviderUnavailable("provider_request_invalid")
    allowed = {
        "temperature",
        "topP",
        "topK",
        "maxOutputTokens",
        "stopSequences",
        "responseMimeType",
    }
    if set(value) - allowed:
        raise ProviderUnavailable("provider_request_invalid")
    _validate_generation_scalars(value, "temperature")
    if "topP" in value and not _safe_probability(value["topP"]):
        raise ProviderUnavailable("provider_request_invalid")
    if "topK" in value and (type(value["topK"]) is not int or not 1 <= value["topK"] <= 1024):
        raise ProviderUnavailable("provider_request_invalid")
    if (
        "maxOutputTokens" in value
        and validated_output_token_count(value["maxOutputTokens"]) is None
    ):
        raise ProviderUnavailable("provider_request_invalid")
    if "stopSequences" in value and (
        not isinstance(value["stopSequences"], list)
        or len(value["stopSequences"]) > 8
        or any(not _bounded_text(item, 256) for item in value["stopSequences"])
    ):
        raise ProviderUnavailable("provider_request_invalid")
    if "responseMimeType" in value and (
        not isinstance(value["responseMimeType"], str)
        or value["responseMimeType"] not in {"text/plain", "application/json"}
    ):
        raise ProviderUnavailable("provider_request_invalid")


def _safe_probability(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and 0 <= value <= 1


def _upstream_model_id(model_id: str, provider_id: str) -> str:
    prefix = f"{provider_id}/"
    return model_id[len(prefix) :] if model_id.startswith(prefix) else model_id


class _OpenAIToolCallStreamState:
    """Validate names and require a complete, non-truncated OpenAI stream."""

    def __init__(self) -> None:
        self.names: dict[int, str] = {}
        self.arguments: dict[int, str] = {}
        self.finish_reason: str | None = None
        self.done_seen = False

    def observe(
        self,
        calls: list[object],
        finish_reason: object,
        declared_tool_names: set[str],
    ) -> None:
        if self.done_seen or self.finish_reason is not None:
            raise ProviderUnavailable("provider_response_invalid")
        if len(calls) > 8:
            raise ProviderUnavailable("provider_response_invalid")
        for fallback_index, raw_call in enumerate(calls):
            if not isinstance(raw_call, Mapping):
                raise ProviderUnavailable("provider_response_invalid")
            index = raw_call.get("index", fallback_index)
            if type(index) is not int or not 0 <= index < 8:
                raise ProviderUnavailable("provider_response_invalid")
            function = raw_call.get("function")
            if function is None:
                continue
            if not isinstance(function, Mapping):
                raise ProviderUnavailable("provider_response_invalid")
            fragment = function.get("name")
            if fragment is not None:
                if not isinstance(fragment, str):
                    raise ProviderUnavailable("provider_response_invalid")
                combined = self.names.get(index, "") + fragment
                if len(combined.encode("utf-8")) > 160:
                    raise ProviderUnavailable("provider_response_invalid")
                self.names[index] = combined
            argument_fragment = function.get("arguments")
            if argument_fragment is not None:
                if not isinstance(argument_fragment, str):
                    raise ProviderUnavailable("provider_response_invalid")
                combined_arguments = self.arguments.get(index, "") + argument_fragment
                if len(combined_arguments.encode("utf-8")) > 16_384:
                    raise ProviderUnavailable("provider_response_invalid")
                self.arguments[index] = combined_arguments

        if finish_reason in {"length", "content_filter"}:
            # A truncated or filtered completion is not a complete app answer.
            raise ProviderUnavailable("provider_response_incomplete")
        if finish_reason == "tool_calls":
            if not self.names or any(
                name not in declared_tool_names for name in self.names.values()
            ):
                raise ProviderUnavailable("provider_response_invalid")
            for index, name in self.names.items():
                if name == "websearch" and not _valid_json_search_arguments(
                    self.arguments.get(index, "")
                ):
                    raise ProviderUnavailable("provider_response_invalid")
                if name == "webfetch" and not _valid_json_webfetch_arguments(
                    self.arguments.get(index, "")
                ):
                    raise ProviderUnavailable("provider_response_invalid")
            self.finish_reason = "tool_calls"
        elif finish_reason == "stop":
            if self.names:
                raise ProviderUnavailable("provider_response_invalid")
            self.finish_reason = "stop"
        elif finish_reason is not None:
            raise ProviderUnavailable("provider_response_invalid")

    def observe_done(self) -> None:
        if self.done_seen or self.finish_reason is None:
            raise ProviderUnavailable("provider_response_invalid")
        self.done_seen = True

    def require_terminal(self) -> None:
        if self.finish_reason is None:
            raise ProviderUnavailable("provider_response_invalid")

    def require_complete(self) -> None:
        self.require_terminal()
        if not self.done_seen:
            raise ProviderUnavailable("provider_response_invalid")


def _sanitize_openai_sse_data(
    value: str,
    *,
    declared_tool_names: set[str] | None = None,
    state: _OpenAIToolCallStreamState | None = None,
) -> str | None:
    """Keep only OpenAI stream delta fields needed by V2; drop provider metadata/errors."""

    if value == "[DONE]":
        if state is not None:
            state.observe_done()
        return value
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ProviderUnavailable("provider_response_invalid") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("choices"), list):
        raise ProviderUnavailable("provider_response_invalid")
    if len(payload["choices"]) > 8:
        raise ProviderUnavailable("provider_response_invalid")
    safe_choices: list[dict[str, object]] = []
    allowed_tools = declared_tool_names or set()
    for choice in payload["choices"]:
        if not isinstance(choice, dict) or type(choice.get("index", 0)) is not int:
            raise ProviderUnavailable("provider_response_invalid")
        delta = choice.get("delta", {})
        if not isinstance(delta, dict):
            raise ProviderUnavailable("provider_response_invalid")
        safe_delta: dict[str, object] = {}
        role = delta.get("role")
        if role is not None:
            if role != "assistant":
                raise ProviderUnavailable("provider_response_invalid")
            safe_delta["role"] = role
        content = delta.get("content")
        if content is not None:
            if not isinstance(content, str) or len(content.encode("utf-8")) > 16_384:
                raise ProviderUnavailable("provider_response_invalid")
            safe_delta["content"] = content
        calls = delta.get("tool_calls")
        if calls is not None:
            if not isinstance(calls, list) or len(calls) > 8:
                raise ProviderUnavailable("provider_response_invalid")
            if state is not None:
                state.observe(calls, choice.get("finish_reason"), allowed_tools)
            safe_calls: list[dict[str, object]] = []
            for call in calls:
                if not isinstance(call, dict):
                    raise ProviderUnavailable("provider_response_invalid")
                safe_call: dict[str, object] = {}
                index = call.get("index")
                if index is not None:
                    if type(index) is not int or not 0 <= index < 8:
                        raise ProviderUnavailable("provider_response_invalid")
                    safe_call["index"] = index
                call_id = call.get("id")
                if call_id is not None:
                    if not isinstance(call_id, str) or _TOOL_CALL_ID.fullmatch(call_id) is None:
                        raise ProviderUnavailable("provider_response_invalid")
                    safe_call["id"] = call_id
                kind = call.get("type")
                if kind is not None:
                    if kind != "function":
                        raise ProviderUnavailable("provider_response_invalid")
                    safe_call["type"] = kind
                function = call.get("function")
                if function is not None:
                    if not isinstance(function, dict):
                        raise ProviderUnavailable("provider_response_invalid")
                    safe_function: dict[str, str] = {}
                    name = function.get("name")
                    arguments = function.get("arguments")
                    if name is not None:
                        if not isinstance(name, str) or not 1 <= len(name) <= 160:
                            raise ProviderUnavailable("provider_response_invalid")
                        safe_function["name"] = name
                    if arguments is not None:
                        if (
                            not isinstance(arguments, str)
                            or len(arguments.encode("utf-8")) > 16_384
                        ):
                            raise ProviderUnavailable("provider_response_invalid")
                        safe_function["arguments"] = arguments
                    safe_call["function"] = safe_function
                safe_calls.append(safe_call)
            safe_delta["tool_calls"] = safe_calls
        elif state is not None:
            # Text-only choices require the same explicit terminal validation.
            state.observe([], choice.get("finish_reason"), allowed_tools)
        safe_choice: dict[str, object] = {
            "index": choice.get("index", 0),
            "delta": safe_delta,
        }
        finish_reason = choice.get("finish_reason")
        if finish_reason is not None:
            if finish_reason not in {"stop", "length", "tool_calls", "content_filter"}:
                raise ProviderUnavailable("provider_response_invalid")
            safe_choice["finish_reason"] = finish_reason
        safe_choices.append(safe_choice)
    return json.dumps({"choices": safe_choices}, ensure_ascii=False, separators=(",", ":"))
