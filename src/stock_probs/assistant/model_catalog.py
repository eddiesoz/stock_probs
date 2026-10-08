"""Application-owned assistant model policy, separate from development model routing."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from importlib.resources import files
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

from stock_probs.assistant.net import PublicHTTPError, request_public_https
from stock_probs.assistant.schemas import AssistantModelPolicy

_MAX_CATALOG_BYTES = 1_048_576
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}$")
_MODEL_CACHE_SECONDS = 300.0
_CATALOG_FAILURE_RETRY_SECONDS = 5.0


class ModelCatalogAuthorizationError(Exception):
    """Signal that a privileged catalog refresh lost its authorization."""


async def _require_authorization(
    authorization_check: Callable[[], Awaitable[object] | object] | None,
) -> None:
    """Fail closed when a privileged catalog refresh loses its caller authorization."""

    if authorization_check is None:
        return
    try:
        authorized = authorization_check()
        if inspect.isawaitable(authorized):
            authorized = await authorized
    except Exception as exc:
        raise ModelCatalogAuthorizationError from exc
    if authorized is not True:
        raise ModelCatalogAuthorizationError


def known_model_exclusion_reason(
    zen_policy: Mapping[str, object],
    *,
    provider_id: object,
    endpoint_url: object,
    native_model_id: object,
) -> str | None:
    """Return the catalog reason for an exact model on the known Zen provider route.

    The local application ID may be opaque or aliased. Exclusion therefore binds to the
    upstream model ID and the catalog's exact provider or canonical endpoint identity.
    """

    zen_provider_id = zen_policy.get("provider_id")
    models_url = _canonical_policy_endpoint(zen_policy.get("models_url"))
    exclusions = zen_policy.get("excluded_models")
    if (
        not isinstance(zen_provider_id, str)
        or not zen_provider_id
        or models_url is None
        or not models_url.endswith("/models")
        or not isinstance(exclusions, Mapping)
        or any(
            not isinstance(key, str) or not isinstance(reason, str) or not reason
            for key, reason in exclusions.items()
        )
    ):
        raise ValueError("model_exclusion_policy_invalid")
    zen_base_url = models_url.removesuffix("/models")
    if not isinstance(native_model_id, str) or not native_model_id:
        return None
    reason = exclusions.get(native_model_id.casefold())
    if not isinstance(reason, str):
        return None
    if provider_id == zen_provider_id:
        return reason
    endpoint = _canonical_policy_endpoint(endpoint_url)
    if endpoint == zen_base_url:
        return reason
    if _policy_endpoint_host(endpoint_url) == _policy_endpoint_host(models_url):
        raise ValueError("model_exclusion_endpoint_ambiguous")
    return None


def _canonical_policy_endpoint(value: object) -> str | None:
    """Normalize only the HTTPS endpoint components used by fixed provider routing."""

    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (port is not None and port != 443)
    ):
        return None
    hostname = parsed.hostname.rstrip(".").casefold()
    try:
        netloc = f"[{hostname}]" if ":" in hostname else hostname.encode("idna").decode("ascii")
        decoded_path = unquote(parsed.path, encoding="utf-8", errors="strict")
    except UnicodeError:
        return None
    segments: list[str] = []
    for segment in decoded_path.split("/"):
        if segment in {"", "."}:
            continue
        if segment == "..":
            if segments:
                segments.pop()
            continue
        segments.append(segment)
    normalized_path = "/" + "/".join(segments) if segments else ""
    return urlunsplit(("https", netloc, normalized_path, "", ""))


def _policy_endpoint_host(value: object) -> str | None:
    """Return a normalized host even when another URL component needs fail-closed handling."""

    if not isinstance(value, str):
        return None
    try:
        hostname = urlsplit(value).hostname
        if not hostname:
            return None
        hostname = hostname.rstrip(".").casefold()
        return hostname if ":" in hostname else hostname.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class AssistantModel(AssistantModelPolicy):
    """Reviewed privacy policy joined to a currently discovered provider model."""

    availability_reason: str | None = None
    native_provider_id: str | None = None
    privacy_policy_version: str | None = None
    billing_policy_version: str | None = None
    billing_class: str | None = None
    privacy_disclosure: str | None = None
    cost_disclosure: str | None = None


class AssistantModelCatalog:
    """List models from a fixed provider inventory and fail closed when discovery is stale."""

    def __init__(
        self,
        settings: object | None = None,
        *,
        requester: Any | None = None,
        catalog_path: str | None = None,
        clock: Any = time.monotonic,
    ) -> None:
        self._clock = clock
        self._requester = requester
        if catalog_path is None:
            self._policy = json.loads(
                files("stock_probs.assistant")
                .joinpath("assistant_catalog.json")
                .read_text(encoding="utf-8")
            )
        else:
            with open(catalog_path, encoding="utf-8") as source:
                self._policy = json.load(source)
        self._models: tuple[AssistantModel, ...] = ()
        self._loaded_at = 0.0
        self._retry_at = 0.0
        self._refresh_lock = asyncio.Lock()
        self._native_models: tuple[AssistantModel, ...] = ()
        self._native_loaded_at = 0.0

    async def refresh(
        self,
        *,
        authorization_check: Callable[[], Awaitable[object] | object] | None = None,
    ) -> tuple[AssistantModel, ...]:
        """Force one single-flight refresh with a bounded request and response body."""

        async with self._refresh_lock:
            return await self._refresh_locked(authorization_check=authorization_check)

    async def ensure_fresh(
        self, *, minimum_validity_seconds: float = 0.0
    ) -> tuple[AssistantModel, ...]:
        """Refresh on normal demand, suppressing duplicate and immediately repeated failures."""

        if (
            not isinstance(minimum_validity_seconds, int | float)
            or isinstance(minimum_validity_seconds, bool)
            or not 0 <= minimum_validity_seconds <= 120.0
        ):
            raise ValueError("minimum_validity_seconds is outside the supported bound")
        if self._fresh_for(minimum_validity_seconds):
            return self.list_models()
        if self._clock() < self._retry_at:
            return self.list_models()
        async with self._refresh_lock:
            if self._fresh_for(minimum_validity_seconds):
                return self.list_models()
            if self._clock() < self._retry_at:
                return self.list_models()
            return await self._refresh_locked()

    def _fresh_for(self, minimum_validity_seconds: float) -> bool:
        age = self._clock() - self._loaded_at
        return self._loaded_at > 0 and age + minimum_validity_seconds < _MODEL_CACHE_SECONDS

    async def _refresh_locked(
        self,
        *,
        authorization_check: Callable[[], Awaitable[object] | object] | None = None,
    ) -> tuple[AssistantModel, ...]:
        """Refresh the fixed Zen inventory with one absolute deadline and a strict body cap."""

        policy = self._policy["zen"]
        try:
            await _require_authorization(authorization_check)
            async with asyncio.timeout(7.0):
                if self._requester is not None:
                    response = await self._requester(str(policy["models_url"]))
                elif authorization_check is None:
                    response = await request_public_https(
                        str(policy["models_url"]),
                        timeout_seconds=6.5,
                        max_response_bytes=_MAX_CATALOG_BYTES,
                    )
                else:
                    response = await request_public_https(
                        str(policy["models_url"]),
                        timeout_seconds=6.5,
                        max_response_bytes=_MAX_CATALOG_BYTES,
                        authorization_check=authorization_check,
                    )
            await _require_authorization(authorization_check)
            if response.status_code != 200:
                raise PublicHTTPError("model_catalog_unavailable")
            payload = json.loads(response.content)
            if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
                raise ValueError("model catalog response has wrong shape")
        except (
            TimeoutError,
            PublicHTTPError,
            OSError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            await _require_authorization(authorization_check)
            if (
                authorization_check is not None
                and isinstance(exc, PublicHTTPError)
                and exc.code
                in {"provider_authorization_required", "provider_authorization_timeout"}
            ):
                raise ModelCatalogAuthorizationError from None
            self._models = ()
            self._loaded_at = 0.0
            self._retry_at = self._clock() + _CATALOG_FAILURE_RETRY_SECONDS
            return self.list_models()
        models = self._parse_zen_rows(payload["data"])
        await _require_authorization(authorization_check)
        self._models = models
        self._loaded_at = self._clock()
        self._retry_at = 0.0
        return self.list_models()

    def list_models(self) -> tuple[AssistantModel, ...]:
        """Return current eligible models; an expired or failed inventory is unavailable."""

        zen_models = self._models if self._clock() - self._loaded_at < _MODEL_CACHE_SECONDS else ()
        native_models = (
            self._native_models
            if self._native_loaded_at > 0
            and self._clock() - self._native_loaded_at < _MODEL_CACHE_SECONDS
            else ()
        )
        combined: dict[str, AssistantModel] = {}
        for model in (*zen_models, *native_models):
            combined.setdefault(model.model_id, model)
        return tuple(combined.values())

    def set_native_models(self, models: tuple[AssistantModel, ...]) -> None:
        """Replace bounded provider-adapter discovery from supported live inventories."""

        self._native_models = tuple(models)
        self._native_loaded_at = self._clock()

    def _parse_zen_rows(self, rows: list[object]) -> tuple[AssistantModel, ...]:
        policy = self._policy["zen"]
        reviewed: Mapping[str, Mapping[str, object]] = policy["reviewed_models"]
        eligible: list[AssistantModel] = []
        for row in rows[:500]:
            if not isinstance(row, dict):
                continue
            model_id = row.get("id")
            if not isinstance(model_id, str) or not _MODEL_ID.fullmatch(model_id):
                continue
            normalized = model_id.casefold()
            if (
                known_model_exclusion_reason(
                    policy,
                    provider_id=policy.get("provider_id"),
                    endpoint_url=policy.get("models_url"),
                    native_model_id=normalized,
                )
                is not None
            ):
                continue
            model_policy = reviewed.get(normalized)
            if (
                model_policy is None
                or model_policy.get("available") is not True
                or model_policy.get("route") != "openai-compatible"
            ):
                continue
            # The exact reviewed inventory is authoritative. Live metadata cannot broaden
            # consent, billing, training, or provider-route policy.
            eligible.append(
                AssistantModel(
                    model_id=f"{policy['provider_id']}/{normalized}",
                    provider_id=str(policy["provider_id"]),
                    display_name=str(model_policy["display_name"])[:160],
                    available=bool(model_policy["available"]),
                    free=bool(model_policy["free"]),
                    training=bool(model_policy["training"]),
                    terms_url=str(policy["terms_url"]),
                    terms_reviewed_at=str(policy["terms_reviewed_at"]),
                    policy_version=str(policy["policy_version"]),
                    disclosure=str(model_policy["disclosure"]),
                    data_collection_allowed=bool(model_policy["data_collection_allowed"]),
                    data_collection_default=bool(model_policy["data_collection_default"]),
                    availability_reason=None,
                    native_provider_id="assistant-proxy",
                    privacy_policy_version=str(
                        model_policy.get("privacy_policy_version", policy["privacy_policy_version"])
                    ),
                    billing_policy_version=str(
                        model_policy.get("billing_policy_version", policy["billing_policy_version"])
                    ),
                    billing_class="free" if bool(model_policy["free"]) else "paid",
                    privacy_disclosure=str(model_policy["disclosure"]),
                    cost_disclosure=str(
                        model_policy.get(
                            "cost_disclosure",
                            "No charge is advertised for this temporarily free model; "
                            "availability can change.",
                        )
                    ),
                )
            )
        return tuple(eligible)

    def get_model(self, model_id: str) -> AssistantModel | None:
        """Return one exact currently discovered model without accepting provider aliases."""

        return next((model for model in self.list_models() if model.model_id == model_id), None)
