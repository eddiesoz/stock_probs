"""Application-owned assistant model policy, separate from development model routing."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from importlib.resources import files
from typing import Any, Protocol, TypeVar, cast
from urllib.parse import unquote, urlsplit, urlunsplit

from stock_probs.assistant.net import PublicHTTPError, request_public_https
from stock_probs.assistant.schemas import AssistantModelPolicy

_MAX_CATALOG_BYTES = 1_048_576
_ZEN_MODELS_URL = "https://opencode.ai/zen/v1/models"
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}$")
_MODEL_CACHE_SECONDS = 300.0
_CATALOG_FAILURE_RETRY_SECONDS = 5.0

_AuthorityResult = TypeVar("_AuthorityResult")


class _AuthorityLock(Protocol):
    def acquire(self, blocking: bool = True) -> bool: ...

    def release(self) -> None: ...


async def run_policy_authority(
    lock: _AuthorityLock,
    operation: Callable[[], _AuthorityResult],
    authorize: Callable[[], Awaitable[None]],
    *,
    admission_seconds: float,
) -> _AuthorityResult:
    """Bound admission, then retain an admitted atomic operation through cancellation."""

    deadline = time.monotonic() + admission_seconds
    abandoned = threading.Event()
    admitted = threading.Event()
    admission_gate = threading.Lock()

    def available() -> bool:
        if not lock.acquire(blocking=False):
            return False
        lock.release()
        return True

    def attempt() -> tuple[bool, _AuthorityResult | None]:
        if not lock.acquire(blocking=False):
            return False, None
        try:
            # A queued worker must never publish after its caller abandons admission.
            with admission_gate:
                if abandoned.is_set() or time.monotonic() >= deadline:
                    raise TimeoutError
                admitted.set()
            return True, operation()
        finally:
            lock.release()

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        async with asyncio.timeout(remaining):
            # Probe without blocking or retaining authority on the event loop. A busy
            # transaction must not consume executor workers merely waiting for its lock.
            while not available():
                await asyncio.sleep(0.01)
            await authorize()
        pending = asyncio.create_task(asyncio.to_thread(attempt))
        try:
            acquired, result = await asyncio.wait_for(
                asyncio.shield(pending), max(0.0, deadline - time.monotonic())
            )
        except (asyncio.CancelledError, TimeoutError) as interruption:
            with admission_gate:
                abandoned.set()
                began = admitted.is_set()
            if not began:
                # A queued attempt can be abandoned promptly. The same gate prevents
                # a dispatched worker from crossing into publication afterward.
                pending.cancel()
                pending.add_done_callback(
                    lambda done: done.exception() if not done.cancelled() else None
                )
                raise
            # Cancellation cannot stop a thread. Drain its actual outcome before the
            # request retires; later cancellations must not detach an admitted write.
            cancelled = isinstance(interruption, asyncio.CancelledError)
            while not pending.done():
                try:
                    await asyncio.shield(pending)
                except asyncio.CancelledError:
                    cancelled = True
                except Exception:
                    break
            if cancelled:
                pending.exception()
                raise asyncio.CancelledError from None
            acquired, result = pending.result()
        if acquired:
            return cast(_AuthorityResult, result)


class ModelCatalogAuthorizationError(Exception):
    """Signal that a privileged catalog refresh lost its authorization."""


async def _require_authorization(
    authorization_check: Callable[[], Awaitable[object] | object] | None,
) -> None:
    """Fail closed when a privileged catalog refresh loses its caller authorization."""

    if authorization_check is None:
        return
    try:
        authorized = (
            authorization_check()
            if inspect.iscoroutinefunction(authorization_check)
            else await asyncio.to_thread(authorization_check)
        )
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


@dataclass(frozen=True, slots=True)
class _CatalogSnapshot:
    """Publish model rows and their freshness timestamps as one immutable generation."""

    zen_models: tuple[AssistantModel, ...] = ()
    zen_loaded_at: float = 0.0
    native_models: tuple[AssistantModel, ...] = ()
    native_loaded_at: float = 0.0
    retry_at: float = 0.0


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
        self.policy_lock = threading.RLock()
        self._snapshot = _CatalogSnapshot()
        self._refresh_lock = asyncio.Lock()

    @property
    def _models(self) -> tuple[AssistantModel, ...]:
        return self._snapshot.zen_models

    @property
    def _loaded_at(self) -> float:
        return self._snapshot.zen_loaded_at

    @property
    def _retry_at(self) -> float:
        return self._snapshot.retry_at

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
        snapshot = self._snapshot
        age = self._clock() - snapshot.zen_loaded_at
        return snapshot.zen_loaded_at > 0 and age + minimum_validity_seconds < _MODEL_CACHE_SECONDS

    async def _refresh_locked(
        self,
        *,
        authorization_check: Callable[[], Awaitable[object] | object] | None = None,
    ) -> tuple[AssistantModel, ...]:
        """Refresh the fixed Zen inventory with one absolute deadline and a strict body cap."""

        policy = self._policy["zen"]
        models_url = str(policy["models_url"])
        # Native OpenCode V2 uses this fixed marker for its no-user-key Zen inventory request.
        headers = {"authorization": "Bearer public"} if models_url == _ZEN_MODELS_URL else {}
        try:
            await _require_authorization(authorization_check)
            async with asyncio.timeout(7.0):
                if self._requester is not None:
                    response = await self._requester(models_url)
                elif authorization_check is None:
                    response = await request_public_https(
                        models_url,
                        headers=headers,
                        timeout_seconds=6.5,
                        max_response_bytes=_MAX_CATALOG_BYTES,
                    )
                else:
                    response = await request_public_https(
                        models_url,
                        headers=headers,
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
            await self._publish_zen_authorized(
                (), 0.0, self._clock() + _CATALOG_FAILURE_RETRY_SECONDS, authorization_check
            )
            return self.list_models()
        models = self._parse_zen_rows(payload["data"])
        await _require_authorization(authorization_check)
        await self._publish_zen_authorized(models, self._clock(), 0.0, authorization_check)
        return self.list_models()

    async def _publish_zen_authorized(
        self,
        models: tuple[AssistantModel, ...],
        loaded_at: float,
        retry_at: float,
        authorization_check: Callable[[], Awaitable[object] | object] | None,
    ) -> None:
        """Recheck publication authorization after contention without awaiting under the lock."""

        try:
            await run_policy_authority(
                self.policy_lock,
                lambda: self._publish_zen(models, loaded_at, retry_at),
                lambda: _require_authorization(authorization_check),
                admission_seconds=7.0,
            )
        except TimeoutError:
            raise PublicHTTPError("model_catalog_unavailable") from None

    def _publish_zen(
        self, models: tuple[AssistantModel, ...], loaded_at: float, retry_at: float
    ) -> None:
        """Serialize only the snapshot replacement; callers perform network work beforehand."""

        with self.policy_lock:
            self._snapshot = replace(
                self._snapshot, zen_models=models, zen_loaded_at=loaded_at, retry_at=retry_at
            )

    def list_models(self) -> tuple[AssistantModel, ...]:
        """Return current eligible models; an expired or failed inventory is unavailable."""

        snapshot = self._snapshot
        now = self._clock()
        zen_models = (
            snapshot.zen_models if now - snapshot.zen_loaded_at < _MODEL_CACHE_SECONDS else ()
        )
        native_models = (
            snapshot.native_models
            if snapshot.native_loaded_at > 0
            and now - snapshot.native_loaded_at < _MODEL_CACHE_SECONDS
            else ()
        )
        combined: dict[str, AssistantModel] = {}
        for model in (*zen_models, *native_models):
            combined.setdefault(model.model_id, model)
        return tuple(combined.values())

    def set_native_models(self, models: tuple[AssistantModel, ...]) -> None:
        """Replace bounded provider-adapter discovery from supported live inventories."""

        with self.policy_lock:
            self._snapshot = replace(
                self._snapshot, native_models=tuple(models), native_loaded_at=self._clock()
            )

    def policy_deadlines(self, model_id: str) -> tuple[tuple[Callable[[], float], float], ...]:
        """Return pure clock bounds for the exact model's current snapshot."""

        snapshot = self._snapshot
        if any(model.model_id == model_id for model in snapshot.zen_models):
            return ((self._clock, snapshot.zen_loaded_at + _MODEL_CACHE_SECONDS),)
        if any(model.model_id == model_id for model in snapshot.native_models):
            return ((self._clock, snapshot.native_loaded_at + _MODEL_CACHE_SECONDS),)
        return ()

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
