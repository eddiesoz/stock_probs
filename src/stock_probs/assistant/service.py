"""Assistant orchestration over existing services and the canonical application database."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import inspect
import json
import math
import re
import secrets
import threading
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

from stock_probs.assistant.feature_filters import (
    InvalidFeatureFilter,
    history_export_query,
    normalize_history_action_filters,
    normalize_history_filters,
    normalize_market_chart_range,
    normalize_market_columns,
    normalize_market_filters,
    normalize_market_refresh,
)
from stock_probs.assistant.providers import ProviderUnavailable
from stock_probs.assistant.schemas import (
    AssistantContextQuery,
    AssistantContextRef,
    AssistantModelPolicy,
    AssistantTurnContext,
    AssistantTurnResult,
)
from stock_probs.assistant.search import validate_webfetch_url
from stock_probs.assistant.storage import (
    ASSISTANT_ACTIVE_GLOBAL,
    ASSISTANT_ACTIVE_PER_USER,
    ASSISTANT_DATABASE_LIMIT,
    ASSISTANT_GLOBAL_HISTORY_LIMIT,
    ASSISTANT_TOOLS_PER_TURN,
    ASSISTANT_TURN_SECONDS,
    ASSISTANT_USER_HISTORY_LIMIT,
    AssistantStorage,
    AssistantStorageConflict,
    AssistantStorageError,
    AssistantStorageNotFound,
    AssistantStorageQuotaExceeded,
)
from stock_probs.auth import AuthContext, AuthManager
from stock_probs.config import Settings
from stock_probs.domain import DomainError, safe_news_url
from stock_probs.repository import Repository
from stock_probs.service import ForecastService

_PROMPT_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    re.compile(
        r"sk-(?:ant-(?:(?:api|admin|svc)\d{0,4}-)?[A-Za-z0-9_-]{24,}|"
        r"proj-[A-Za-z0-9_-]{24,}|[A-Za-z0-9]{32,})"
    ),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    # Google API keys use the fixed `AIza` prefix followed by 35 URL-safe characters.
    re.compile(r"AIza[A-Za-z0-9_-]{35}"),
    re.compile(
        r"(?i)\b(?:csrf|session|recovery|invitation|totp|authenticator)\s*(?:code|token|key)?\s*[:=]\s*[A-Za-z0-9_-]{6,}"
    ),
    re.compile(
        r"(?i)\b(?:my\s+)?(?:authenticator|totp|two[- ]factor)\s+"
        r"(?:verification\s+)?(?:code|passcode|number)\s+(?:is\s+)?\d{6}\b"
    ),
    re.compile(r"(?i)\b(?:password|api[ _-]?key|client[ _-]?secret)\s*[:=]\s*\S{6,}"),
)
_SAFE_ERROR_CODES = frozenset(
    {
        "worker_unavailable",
        "provider_unavailable",
        "provider_policy_changed",
        "tool_failed",
        "tool_unavailable",
        "turn_timeout",
        "turn_cancelled",
        "invalid_runtime_event",
        "runtime_restarted",
        "output_too_large",
        "empty_response",
        "sensitive_output_rejected",
        "session_revoked",
    }
)
_ACTION_TYPES = frozenset(
    {
        "watchlist.add",
        "watchlist.remove",
        "portfolio.add",
        "portfolio.remove",
        "portfolio.set_quantity",
        "forecast.create",
        "outcome.record",
        "reconstruction.run",
        "invitation.create",
        "backup.create",
        "restore.promote",
        "provider.settings",
        "account.sessions.manage",
        "history.export.csv",
        "history.export.json",
        "theme.set",
        "filters.apply",
        "notes.set",
        "notes.clear",
        "alerts.add",
        "alerts.remove",
        "forecast.reopen",
        "market.open",
        "market.filters.apply",
        "market.chart_range.set",
        "market.columns.set",
        "market.refresh",
    }
)
_APPROVED_QUANTITY_KEY = "_approved_current_quantity"


def _utf8_chunks(value: str, *, max_bytes: int = 8192) -> list[str]:
    """Split text into valid UTF-8 chunks without exceeding the event byte limit."""
    chunks: list[str] = []
    current: list[str] = []
    current_bytes = 0
    for character in value:
        character_bytes = len(character.encode("utf-8"))
        if character_bytes > max_bytes:
            raise ValueError("maximum chunk size is smaller than one UTF-8 character")
        if current and current_bytes + character_bytes > max_bytes:
            chunks.append("".join(current))
            current = []
            current_bytes = 0
        current.append(character)
        current_bytes += character_bytes
    if current:
        chunks.append("".join(current))
    return chunks


ASSISTANT_RUNTIME_START_SECONDS = 3.0
ASSISTANT_RUNTIME_RETRY_SECONDS = 5.0
_WEBFETCH_PREVIEW_REASON = (
    "Review this exact public destination. Its URL may contain private account or workspace data."
)


@dataclass(slots=True)
class _WebfetchWaiter:
    """One volatile exact-URL decision; its authority ends with this active native turn."""

    user_id: int
    conversation_id: str
    turn_id: str
    execution_id: str
    session_id: str
    model_id: str
    policy_version: str
    context_version: str
    url: str
    confirmation_phrase: str
    expires_at: datetime
    future: asyncio.Future[str | None]


class AssistantUnavailable(Exception):
    """Report a safe feature, model, or runtime availability boundary."""

    def __init__(self, code: str, status_code: int = 503):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class AssistantConsentRequired(AssistantUnavailable):
    """Require an exact active model policy acceptance before sending any prompt data."""

    def __init__(self):
        super().__init__("assistant_consent_required", 428)


class AssistantService:
    """Own assistant policy, context binding, runtime tasks, and browser action dispatch."""

    def __init__(
        self,
        settings: Settings,
        repository: Repository,
        forecast_service: ForecastService,
        auth_manager: AuthManager,
        *,
        runtime: object | None = None,
        catalog: object | None = None,
        providers: object | None = None,
        clock: Any = None,
        backups: object | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.forecast_service = forecast_service
        self.auth_manager = auth_manager
        self.storage = AssistantStorage(repository)
        self.runtime = runtime
        self.catalog = catalog
        self.providers = providers
        self.backups = backups
        self.clock = clock or (lambda: datetime.now(UTC))
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._execution_by_turn: dict[str, str] = {}
        self._emitters: dict[str, Any] = {}
        self._search_waiters: dict[str, asyncio.Future[str | None]] = {}
        self._webfetch_waiters: dict[str, _WebfetchWaiter] = {}
        self._webfetch_waiter_lock = threading.Lock()
        self._task_lock = asyncio.Lock()
        self._started = False
        self._runtime_start_failed = False
        self._runtime_last_start_attempt = 0.0
        self._runtime_start_lock = asyncio.Lock()
        # The HTTP MCP dispatcher and native runtime share this fixed app gateway.
        # Keep its import local to avoid a module cycle through the tool schemas.
        from stock_probs.assistant.tools import AssistantToolGateway

        self.tool_gateway = AssistantToolGateway(self)

    def now(self) -> datetime:
        """Return one aware UTC clock value for persistence and expiry comparisons."""

        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("assistant clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    async def ensure_model_inventory(
        self,
        *,
        minimum_validity_seconds: float = 0.0,
        owner_id: int | None = None,
        authorization_check: Callable[[], Awaitable[bool] | bool] | None = None,
    ) -> tuple[object, ...]:
        """Refresh global discovery and append only this owner's Console model snapshot."""

        inventory: tuple[object, ...]
        ensure = getattr(self.providers, "ensure_model_inventory", None)
        if not callable(ensure):
            ensure = getattr(self.catalog, "ensure_model_inventory", None)
        if not callable(ensure):
            inventory = tuple(self._raw_models())
        else:
            try:
                result = ensure(minimum_validity_seconds=minimum_validity_seconds)
                if inspect.isawaitable(result):
                    result = await result
            except Exception:
                result = ()
            inventory = tuple(result) if isinstance(result, tuple | list) else ()

        # OpenCode Console config is per-owner and is deliberately absent from the shared
        # catalog. Resolve its safe model rows only after the current owner session is checked.
        owner_inventory = getattr(self.providers, "ensure_opencode_model_inventory", None)
        get_owner_model = getattr(self.providers, "get_opencode_model", None)
        if (
            type(owner_id) is not int
            or owner_id < 1
            or not callable(authorization_check)
            or not callable(owner_inventory)
            or not callable(get_owner_model)
        ):
            return inventory
        try:
            rows = owner_inventory(
                owner_id=owner_id,
                authorization_check=authorization_check,
                minimum_validity_seconds=minimum_validity_seconds,
            )
            if inspect.isawaitable(rows):
                rows = await rows
        except Exception:
            # A disconnected or unavailable optional provider must not hide approved models
            # from other providers. A selected owner-only ID still fails closed at policy().
            return inventory
        if not isinstance(rows, tuple | list):
            return inventory
        models: list[object] = []
        seen = {
            mapping.get("model_id", mapping.get("id"))
            for value in inventory
            if (mapping := self._model_mapping(value)) is not None
        }
        for row in rows:
            mapping = self._model_mapping(row)
            model_id = mapping.get("model_id") if mapping is not None else None
            if not isinstance(model_id, str) or model_id in seen:
                continue
            try:
                model = get_owner_model(model_id, owner_id=owner_id)
            except ProviderUnavailable:
                model = None
            if model is None:
                continue
            models.append(model)
            seen.add(model_id)
        return (*inventory, *models)

    def can_access(self, context: AuthContext) -> bool:
        """Apply the configured fail-closed rollout after workspace authentication."""

        if not self.settings.assistant_enabled or self.operator_disabled or not context.user.active:
            return False
        if context.auth_method != "github" or context.mfa_method != "totp":
            return False
        github_id = context.user.github_id
        if type(github_id) is not int:
            return False
        if self.settings.assistant_rollout_mode == "owner_canary":
            allowlist = self.settings.assistant_canary_github_ids or (
                (self.settings.owner_github_id,) if self.settings.owner_github_id else ()
            )
            return context.user.role == "admin" and github_id in allowlist
        return self.settings.assistant_rollout_mode == "invited"

    def require_admin(self, context: AuthContext, *, step_up: bool = False) -> None:
        """Require a current administrator for routes that expose privileged settings."""

        self.require_access(context)
        if context.user.role != "admin":
            raise AssistantUnavailable("not_found", 404)
        if step_up and not self.auth_manager.has_recent_step_up(context, self.now()):
            raise AssistantUnavailable("totp_step_up_required", 403)

    async def start(self) -> None:
        """Close stale leases after restart and start the optional local runtime in isolation."""

        if self._started:
            return
        self._started = True
        self.storage.reconcile_interrupted_actions(now=self.now())
        interrupted = self.storage.interrupt_active_turns(now=self.now())
        for turn in interrupted:
            # Restart events are best-effort when the conversation's quota is full.
            with suppress(AssistantStorageError):
                self.storage.append_event(
                    int(turn["user_id"]),
                    str(turn["conversation_id"]),
                    str(turn["id"]),
                    event_type="error",
                    data={
                        "code": "runtime_restarted",
                        "message": "The assistant turn stopped during restart.",
                    },
                    now=self.now(),
                )
        if not self.settings.assistant_enabled or self.runtime is None:
            return
        starter = getattr(self.runtime, "start", None)
        if callable(starter):
            # A broken worker must not hold FastAPI lifespan startup or app health indefinitely.
            self._runtime_last_start_attempt = asyncio.get_running_loop().time()
            self._runtime_start_failed = not await self._bounded_runtime_call(
                starter, timeout=ASSISTANT_RUNTIME_START_SECONDS
            )

    async def close(self) -> None:
        """Cancel active local work and erase ephemeral runtime conversation references."""

        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=2.0)
        closer = getattr(self.runtime, "close", None)
        if callable(closer):
            await self._bounded_runtime_call(closer, timeout=2.0)
        self._started = False

    @staticmethod
    async def _bounded_runtime_call(function: Any, *args: object, timeout: float = 2.0) -> bool:
        """Keep worker shutdown and explicit cancellation bounded even for a stuck adapter."""

        try:
            result = function(*args)
        except (Exception, asyncio.CancelledError):
            return False
        if not asyncio.iscoroutine(result) and not hasattr(result, "__await__"):
            return True
        operation = asyncio.ensure_future(result)
        done, _ = await asyncio.wait({operation}, timeout=timeout)
        if not done:
            operation.cancel()
            operation.add_done_callback(
                lambda task: task.exception() if not task.cancelled() else None
            )
            return False
        try:
            operation.result()
            return True
        except Exception:
            return False

    @staticmethod
    async def _bounded_runtime_result(
        function: Any, *args: object, timeout: float = 2.0
    ) -> object | None:
        """Return a worker result only after a bounded call; timeout/failure stays unknown."""

        try:
            result = function(*args)
        except (Exception, asyncio.CancelledError):
            return None
        if not asyncio.iscoroutine(result) and not hasattr(result, "__await__"):
            return result
        operation = asyncio.ensure_future(result)
        done, _ = await asyncio.wait({operation}, timeout=timeout)
        if not done:
            operation.cancel()
            operation.add_done_callback(
                lambda task: task.exception() if not task.cancelled() else None
            )
            return None
        try:
            return operation.result()
        except Exception:
            return None

    def require_access(self, context: AuthContext) -> None:
        """Hide this route from non-canary users without disclosing rollout state."""

        if self.settings.assistant_enabled and self.operator_disabled:
            raise AssistantUnavailable("assistant_worker_unavailable", 503)
        if not self.can_access(context):
            raise AssistantUnavailable("not_found", 404)

    @property
    def operator_disabled(self) -> bool:
        """Read the runtime's terminal in-process kill latch without trusting config reload."""

        return getattr(self.runtime, "operator_disabled", False) is True

    def _runtime_status(self) -> dict[str, object]:
        if not self.settings.assistant_enabled:
            return {"status": "disabled", "message": None}
        if self.runtime is None:
            return {"status": "unavailable", "message": "Assistant runtime is unavailable."}
        status_method = getattr(self.runtime, "status", None)
        if callable(status_method):
            try:
                status = status_method()
                if isinstance(status, Mapping):
                    value = status.get("status", "unavailable")
                    if value == "ready":
                        self._runtime_start_failed = False
                    return {"status": value, "message": status.get("message")}
                value = getattr(status, "status", None)
                message = getattr(status, "message", None)
                if isinstance(value, str):
                    if value == "ready":
                        self._runtime_start_failed = False
                    return {"status": value, "message": message}
            except Exception:
                return {"status": "unavailable", "message": "Assistant runtime is unavailable."}
        if self._runtime_start_failed:
            return {"status": "unavailable", "message": "Assistant runtime is unavailable."}
        return {"status": "ready" if self._started else "starting", "message": None}

    def status(self, user_id: int) -> dict[str, object]:
        """Return per-owner quota and optional worker state; callers authenticate first."""

        usage = self.storage.usage(user_id)
        worker = self._runtime_status()
        enabled = self.settings.assistant_enabled and not self.operator_disabled
        return {
            "available": enabled and worker["status"] == "ready",
            "enabled": enabled,
            "worker": {"status": worker["status"], "reason": worker.get("message")},
            "limits": {
                "active_per_user": ASSISTANT_ACTIVE_PER_USER,
                "active_global": ASSISTANT_ACTIVE_GLOBAL,
                "tools_per_turn": ASSISTANT_TOOLS_PER_TURN,
                "turn_seconds": ASSISTANT_TURN_SECONDS,
            },
            "storage": {
                "user_bytes": usage["user_bytes"],
                "user_limit": ASSISTANT_USER_HISTORY_LIMIT,
                "global_bytes": usage["global_bytes"],
                "global_limit": ASSISTANT_GLOBAL_HISTORY_LIMIT,
                "database_bytes": usage["database_bytes"],
                "database_limit": ASSISTANT_DATABASE_LIMIT,
                "backup_retention_note": (
                    "Deleted conversations are removed from the current database; existing "
                    "verified backups retain their normal retention."
                ),
            },
        }

    @staticmethod
    def _model_mapping(value: object) -> dict[str, object] | None:
        if isinstance(value, Mapping):
            return {str(key): item for key, item in value.items()}
        if hasattr(value, "__dataclass_fields__"):
            return {name: getattr(value, name) for name in value.__dataclass_fields__}
        if hasattr(value, "model_dump"):
            return cast(dict[str, object], value.model_dump(mode="python"))
        return None

    def model_policies(
        self,
        model_inventory: tuple[object, ...] | list[object] | None = None,
        *,
        owner_id: int | None = None,
    ) -> list[AssistantModelPolicy]:
        """Adapt the runtime's fixed reviewed catalog into the backend's closed policy DTO."""

        if self.catalog is None and model_inventory is None:
            return []
        lister = getattr(self.catalog, "list_models", None)
        values: object = (
            model_inventory
            if model_inventory is not None
            else lister()
            if callable(lister)
            else getattr(self.catalog, "models", ())
        )
        if asyncio.iscoroutine(values):
            raise RuntimeError("model catalog list_models must be synchronous")
        policies: list[AssistantModelPolicy] = []
        if not isinstance(values, tuple | list):
            return policies
        for value in values:
            item = self._model_mapping(value)
            if item is None:
                continue
            # Runtime's public field is model_id; its catalog may call presentation fields name.
            model_id = item.get("model_id", item.get("id"))
            provider_id = item.get("provider_id", item.get("provider"))
            display_name = item.get("display_name", item.get("name", model_id))
            policy_version = item.get("policy_version")
            if not all(
                isinstance(field, str) and field
                for field in (model_id, provider_id, display_name, policy_version)
            ):
                continue
            try:
                policy = AssistantModelPolicy(
                    model_id=cast(str, model_id),
                    provider_id=cast(str, provider_id),
                    display_name=cast(str, display_name),
                    available=bool(item.get("available", False)),
                    free=bool(item.get("free", False)),
                    training=(
                        item.get("training") == "data_collection"
                        if isinstance(item.get("training"), str)
                        else bool(item.get("training", item.get("data_collection_allowed", True)))
                    ),
                    terms_url=cast(str, item.get("terms_url", "")),
                    terms_reviewed_at=cast(str, item.get("terms_reviewed_at", "")),
                    policy_version=cast(str, policy_version),
                    disclosure=cast(str, item.get("disclosure", "")),
                    data_collection_allowed=bool(item.get("data_collection_allowed", False)),
                    data_collection_default=bool(item.get("data_collection_default", False)),
                )
                state_reader = getattr(self.providers, "model_policy_state", None)
                if callable(state_reader):
                    state = state_reader(policy.model_id, owner_id=owner_id)
                    generation = state.get("policy_version") if isinstance(state, Mapping) else None
                    if isinstance(generation, str) and 1 <= len(generation) <= 80:
                        policy = replace(policy, policy_version=generation)
                policies.append(policy)
            except (ProviderUnavailable, TypeError, ValueError):
                continue
        return policies

    def model_response(
        self,
        user_id: int,
        *,
        model_inventory: tuple[object, ...] | list[object] | None = None,
    ) -> dict[str, object]:
        """Join catalog policies to exact per-user versioned consent summaries."""

        consent_by_key = {
            (str(item["model_id"]), str(item["policy_version"])): item
            for item in self.storage.consent_summaries(user_id)
        }
        items: list[dict[str, object]] = []
        raw_by_id = {
            str(mapping.get("model_id", mapping.get("id"))): mapping
            for raw in self._raw_models(model_inventory)
            if (mapping := self._model_mapping(raw)) is not None
            and isinstance(mapping.get("model_id", mapping.get("id")), str)
        }
        for policy in self.model_policies(model_inventory, owner_id=user_id):
            consent = consent_by_key.get((policy.model_id, policy.policy_version))
            raw = dict(raw_by_id.get(policy.model_id, {}))
            state_reader = getattr(self.providers, "model_policy_state", None)
            if callable(state_reader):
                try:
                    admin_state = state_reader(policy.model_id, owner_id=user_id)
                except Exception:
                    admin_state = None
                if isinstance(admin_state, Mapping):
                    for key in (
                        "native_provider_id",
                        "enabled",
                        "privacy_policy_version",
                        "privacy_disclosure",
                        "billing_class",
                        "billing_policy_version",
                        "cost_disclosure",
                        "revision",
                        "usable",
                        "availability_reason",
                        "acknowledged_privacy_policy_version",
                        "acknowledged_billing_policy_version",
                        "policy_version",
                    ):
                        if key in admin_state:
                            raw[key] = admin_state[key]
            native_provider_id = raw.get("native_provider_id")
            availability_reason = raw.get("availability_reason")
            billing_class = raw.get("billing_class")
            if not isinstance(billing_class, str) or billing_class not in {
                "unknown",
                "free",
                "paid",
            }:
                billing_class = "free" if policy.free else None
            enabled = raw.get("enabled") is True
            privacy_version = raw.get("privacy_policy_version")
            if not isinstance(privacy_version, str) or not privacy_version:
                privacy_version = policy.policy_version
            privacy_disclosure = raw.get("privacy_disclosure")
            if not isinstance(privacy_disclosure, str):
                privacy_disclosure = policy.disclosure
            cost_disclosure = raw.get("cost_disclosure")
            billing_policy_version = raw.get("billing_policy_version")
            revision = raw.get("revision")
            if type(revision) is not int or revision < 0:
                revision = 0
            items.append(
                {
                    "model_id": policy.model_id,
                    "provider_id": policy.provider_id,
                    "native_provider_id": (
                        native_provider_id if isinstance(native_provider_id, str) else None
                    ),
                    "display_name": policy.display_name,
                    "available": policy.available,
                    "enabled": enabled,
                    "free": policy.free,
                    "training_uses_data": policy.training,
                    "privacy_policy_version": privacy_version,
                    "privacy_disclosure": privacy_disclosure,
                    "billing_class": billing_class,
                    "billing_policy_version": (
                        billing_policy_version if isinstance(billing_policy_version, str) else None
                    ),
                    "cost_disclosure": cost_disclosure
                    if isinstance(cost_disclosure, str)
                    else None,
                    "revision": revision,
                    # A model is usable only when the runtime's reviewed adapter, live discovery,
                    # provider configuration, admin approval, and policy acknowledgements agree.
                    "usable": raw.get("usable") is True,
                    "availability_reason": (
                        availability_reason if isinstance(availability_reason, str) else None
                    ),
                    "id": policy.model_id,
                    "provider": policy.provider_id,
                    "name": policy.display_name,
                    "availability": "available" if policy.available else "unavailable",
                    "training": "data_collection" if policy.training else "no_training",
                    "terms_url": policy.terms_url,
                    "terms_reviewed_at": policy.terms_reviewed_at,
                    "policy_version": policy.policy_version,
                    "disclosure": policy.disclosure,
                    "consent": {
                        "accepted": bool(consent and consent["accepted_terms"]),
                        "data_collection_opt_in": bool(
                            consent and consent["data_collection_opt_in"]
                        ),
                        "accepted_at": consent["recorded_at"] if consent else None,
                    },
                }
            )
        return {"items": items}

    def _raw_models(
        self, model_inventory: tuple[object, ...] | list[object] | None = None
    ) -> tuple[object, ...] | list[object]:
        """Return raw reviewed catalog items for one already bounded display projection."""

        if model_inventory is not None:
            return model_inventory
        if self.catalog is None:
            return ()
        lister = getattr(self.catalog, "list_models", None)
        values = lister() if callable(lister) else getattr(self.catalog, "models", ())
        return values if isinstance(values, tuple | list) else ()

    def has_model_in_inventory(
        self, model_id: str, model_inventory: tuple[object, ...] | list[object]
    ) -> bool:
        """Check an exact ID against the refreshed, fixed catalog snapshot."""

        return any(
            (mapping := self._model_mapping(item)) is not None
            and mapping.get("model_id", mapping.get("id")) == model_id
            for item in model_inventory
        )

    def policy(
        self,
        model_id: str,
        *,
        model_inventory: tuple[object, ...] | list[object] | None = None,
        owner_id: int | None = None,
    ) -> AssistantModelPolicy:
        policy = next(
            (
                item
                for item in self.model_policies(model_inventory, owner_id=owner_id)
                if item.model_id == model_id
            ),
            None,
        )
        if policy is None or not policy.available:
            raise AssistantUnavailable("model_unavailable", 503)
        state_reader = getattr(self.providers, "model_policy_state", None)
        if callable(state_reader):
            try:
                admin_state = state_reader(model_id, owner_id=owner_id)
            except Exception:
                raise AssistantUnavailable("model_unavailable", 503) from None
            if not isinstance(admin_state, Mapping) or (
                admin_state.get("enabled") is not True or admin_state.get("usable") is not True
            ):
                raise AssistantUnavailable("model_unavailable", 503)
            privacy_version = admin_state.get("privacy_policy_version")
            privacy_ack = admin_state.get("acknowledged_privacy_policy_version")
            if not isinstance(privacy_version, str) or privacy_ack != privacy_version:
                raise AssistantUnavailable("model_unavailable", 503)
            generation = admin_state.get("policy_version")
            if not isinstance(generation, str) or generation != policy.policy_version:
                raise AssistantUnavailable("model_unavailable", 503)
            if admin_state.get("billing_class") == "paid":
                billing_version = admin_state.get("billing_policy_version")
                if (
                    not isinstance(billing_version, str)
                    or admin_state.get("acknowledged_billing_policy_version") != billing_version
                ):
                    raise AssistantUnavailable("model_unavailable", 503)
        else:
            catalog_row = next(
                (
                    mapping
                    for raw in self._raw_models(model_inventory)
                    if (mapping := self._model_mapping(raw)) is not None
                    and mapping.get("model_id", mapping.get("id")) == model_id
                ),
                None,
            )
            if (
                catalog_row is None
                or catalog_row.get("enabled") is not True
                or catalog_row.get("usable") is not True
            ):
                raise AssistantUnavailable("model_unavailable", 503)
        return policy

    def record_consent(
        self,
        user_id: int,
        model_id: str,
        *,
        policy_version: str,
        accepted_terms: bool,
        data_collection_opt_in: bool,
        model_inventory: tuple[object, ...] | list[object] | None = None,
    ) -> dict[str, object]:
        policy = self.policy(model_id, model_inventory=model_inventory, owner_id=user_id)
        if policy.policy_version != policy_version:
            raise AssistantStorageConflict("policy_version")
        if data_collection_opt_in and not policy.data_collection_allowed:
            raise AssistantUnavailable("data_collection_not_allowed", 422)
        return self.storage.create_consent(
            user_id,
            model_id=model_id,
            policy_version=policy_version,
            accepted_terms=accepted_terms,
            data_collection_opt_in=data_collection_opt_in,
            recorded_at=self.now(),
        )

    @staticmethod
    def _digest(value: object) -> str:
        canonical = json.dumps(
            value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def resolve_context(self, user_id: int, query: AssistantContextQuery) -> dict[str, object]:
        """Validate every resource reference with the existing owner-scoped app services."""

        if query.route in {"/admin", "/account", "/api-docs"} and query.symbol is not None:
            raise AssistantUnavailable("context_instrument_not_supported", 422)
        if (query.event_id is not None or query.result_id is not None) and query.route not in {
            "/",
            "/research",
            "/tools/forecast",
            "/tools/live-trading",
            "/tools/markets",
        }:
            raise AssistantUnavailable("context_reference_not_supported", 422)
        instrument: dict[str, str] | None = None
        if query.symbol is not None and query.asset_type is not None:
            normalized = query.symbol.strip().upper()
            lookup = self.forecast_service.lookup(normalized, 1)
            candidates = lookup.get("items", []) if isinstance(lookup, Mapping) else []
            identity = next(
                (
                    item
                    for item in candidates
                    if isinstance(item, Mapping)
                    and item.get("canonical_symbol") == normalized
                    and item.get("asset_type") == query.asset_type
                    and str(item.get("provider", "")).casefold() == str(query.provider).casefold()
                    and str(item.get("exchange", "")).casefold() == str(query.exchange).casefold()
                ),
                None,
            )
            if identity is None:
                raise AssistantUnavailable("context_instrument_unavailable", 409)
            instrument = {
                "symbol": str(identity["canonical_symbol"]),
                "asset_type": str(identity["asset_type"]),
                "provider": str(identity["provider"]),
                "exchange": str(identity["exchange"]),
                # This display label comes from the validated app identity response. URL text is
                # never accepted as a display-name source or sent as assistant instructions.
                "display_name": str(identity["display_name"]),
            }

        event_ref: dict[str, object] | None = None
        result_ref: dict[str, object] | None = None
        if query.event_id is not None:
            if query.route in {"/admin", "/account", "/api-docs"}:
                raise AssistantUnavailable("context_reference_not_supported", 422)
            reconstruction = self.repository.reconstruction(user_id, query.event_id)
            if not isinstance(reconstruction, Mapping):
                raise AssistantStorageNotFound()
            event = reconstruction.get("event")
            results = reconstruction.get("results")
            if not isinstance(event, Mapping) or not isinstance(results, list):
                raise AssistantStorageNotFound()
            if int(event.get("id", 0)) != query.event_id:
                raise AssistantStorageNotFound()
            event_ref = {
                "id": query.event_id,
                "version": self._digest(event),
            }
            if query.result_id is not None:
                selected = next(
                    (
                        result
                        for result in results
                        if isinstance(result, Mapping)
                        and int(result.get("id", 0)) == query.result_id
                    ),
                    None,
                )
                if selected is None:
                    raise AssistantStorageNotFound()
                result_ref = {"id": query.result_id, "version": self._digest(selected)}

        version_payload = {
            "route": query.route,
            "instrument": instrument,
            "event_ref": event_ref,
            "result_ref": result_ref,
        }
        context = {
            **version_payload,
            "context_version": self._digest(version_payload),
        }
        if query.event_id is None:
            fields = ["current route"]
            if instrument is not None:
                fields.append("selected public instrument reference")
        else:
            fields = ["current route", "owner-validated saved event reference"]
            if instrument is not None:
                fields.append("selected public instrument reference")
            if result_ref is not None:
                fields.append("owner-validated saved result reference")
        return {
            "context": AssistantContextRef.model_validate(context).model_dump(mode="json"),
            "preview": {
                "summary": "Only the selected page and validated references are attached.",
                "fields": fields,
                "note": (
                    "Private holdings and history are read only through an explicit assistant tool."
                ),
            },
        }

    def validate_context(self, user_id: int, context: AssistantContextRef) -> dict[str, object]:
        """Re-resolve all references and reject stale pages before persisting or sending a turn."""

        query = AssistantContextQuery(
            route=context.route,
            symbol=context.instrument.symbol if context.instrument else None,
            asset_type=context.instrument.asset_type if context.instrument else None,
            provider=context.instrument.provider if context.instrument else None,
            exchange=context.instrument.exchange if context.instrument else None,
            event_id=context.event_ref.id if context.event_ref else None,
            result_id=context.result_ref.id if context.result_ref else None,
        )
        current = self.resolve_context(user_id, query)["context"]
        if not isinstance(current, Mapping):
            raise AssistantStorageError("assistant context validator returned invalid data")
        if not hmac.compare_digest(
            str(current.get("context_version", "")), context.context_version
        ) or current != context.model_dump(mode="json"):
            raise AssistantStorageConflict("context_stale")
        return dict(current)

    def conversation_create(
        self, user_id: int, *, title: str | None, context: AssistantContextRef | None
    ) -> dict[str, object]:
        if context is None:
            response = self.resolve_context(user_id, AssistantContextQuery(route="/overview"))
            raw_context = cast(dict[str, object], response["context"])
        else:
            raw_context = self.validate_context(user_id, context)
        return self.storage.create_conversation(
            user_id,
            title=(title or "New conversation").strip(),
            context=raw_context,
            context_version=str(raw_context["context_version"]),
            created_at=self.now(),
        )

    def conversation_detail(
        self,
        context: AuthContext,
        conversation_id: str,
        *,
        message_page: int,
        message_page_size: int,
        event_page: int,
        event_page_size: int,
        action_page: int,
        action_page_size: int,
    ) -> dict[str, object]:
        """Return owner history with confirmation material scoped to its issuing session."""

        self.require_access(context)
        detail = self.storage.get_conversation(
            context.user.id,
            conversation_id,
            message_page=message_page,
            message_page_size=message_page_size,
            event_page=event_page,
            event_page_size=event_page_size,
            action_page=action_page,
            action_page_size=action_page_size,
            session_id=context.session_id,
            now=self.now(),
        )
        turns_by_id = {
            str(turn.get("id")): turn
            for turn in cast(list[dict[str, object]], detail.get("turns", []))
        }
        for action in cast(list[dict[str, object]], detail.get("actions", [])):
            action_type = action.get("action_type")
            raw_payload = action.pop("_proposal_payload", None)
            session_matches = action.pop("_proposal_session_matches", False) is True
            version = action.pop("_proposal_action_version", None)
            context_version = action.pop("_proposal_context_version", None)
            action["proposal"] = None
            action["availability"] = "unavailable"
            if (
                not isinstance(action_type, str)
                or not isinstance(raw_payload, Mapping)
                or type(version) is not int
                or not isinstance(context_version, str)
            ):
                continue
            try:
                safe_payload = self._validate_persisted_action_payload(action_type, raw_payload)
            except AssistantUnavailable:
                continue
            proposal = self._safe_action_card(action_type, safe_payload)
            confirmation_phrase: str | None = None
            availability = "different_session" if not session_matches else "expired"
            if action.get("status") == "pending":
                if session_matches:
                    turn = turns_by_id.get(str(action.get("turn_id", "")))
                    if (
                        not isinstance(turn, Mapping)
                        or turn.get("context_version") != context_version
                    ):
                        availability = "stale"
                    elif not self.policy_still_authorized(
                        context.user.id,
                        str(turn.get("model_id", "")),
                        str(turn.get("policy_version", "")),
                    ):
                        availability = "policy_changed"
                    else:
                        try:
                            self._validate_action_target(context.user.id, action_type, safe_payload)
                            if action_type in {
                                "invitation.create",
                                "backup.create",
                                "restore.promote",
                                "provider.settings",
                            }:
                                self.require_admin(context, step_up=True)
                            confirmation_phrase = f"CONFIRM {str(action['action_id'])[-8:]}"
                            availability = "confirmable"
                        except (AssistantUnavailable, AssistantStorageError):
                            availability = "authorization_required"
            elif action.get("status") == "expired":
                availability = "expired"
            proposal["action_version"] = version
            proposal["context_version"] = context_version
            proposal["confirmation_phrase"] = confirmation_phrase
            action["proposal"] = proposal
            action["availability"] = availability
        events = detail.get("events")
        if isinstance(events, dict) and isinstance(events.get("items"), list):
            events["items"] = [
                self.project_event_for_browser(context, event)
                for event in events["items"]
                if isinstance(event, Mapping)
            ]
        return detail

    def project_event_for_browser(
        self, context: AuthContext, event: Mapping[str, object]
    ) -> dict[str, object]:
        """Remove an action phrase from replay unless this is its live issuing session."""

        projected = dict(event)
        data = event.get("data")
        if not isinstance(data, Mapping):
            return projected
        safe_data = dict(data)
        if event.get("type") == "proposed_action":
            action_id = safe_data.get("action_id")
            try:
                action = (
                    self.storage.get_action(context.user.id, action_id)
                    if isinstance(action_id, str)
                    else None
                )
            except AssistantStorageError:
                action = None
            if (
                action is None
                or action.get("session_id") != context.session_id
                or action.get("status") != "pending"
                or str(action.get("expires_at", "")) <= self.now().isoformat()
            ):
                safe_data.pop("confirmation_phrase", None)
        elif event.get("type") == "webfetch_preview":
            preview_id = safe_data.get("preview_id")
            with self._webfetch_waiter_lock:
                waiter = (
                    self._webfetch_waiters.get(preview_id) if isinstance(preview_id, str) else None
                )
            if (
                waiter is None
                or waiter.user_id != context.user.id
                or waiter.session_id != context.session_id
                or waiter.future.done()
                or self.now() >= waiter.expires_at
            ):
                safe_data.pop("url", None)
                safe_data.pop("confirmation_phrase", None)
        projected["data"] = safe_data
        return projected

    def consent_response(
        self,
        user_id: int,
        model_id: str,
        *,
        policy_version: str,
        accepted_terms: bool,
        data_collection_opt_in: bool,
        model_inventory: tuple[object, ...] | list[object] | None = None,
    ) -> dict[str, object]:
        """Persist a user's explicit choice for one exact model policy version."""

        return self.record_consent(
            user_id,
            model_id,
            policy_version=policy_version,
            accepted_terms=accepted_terms,
            data_collection_opt_in=data_collection_opt_in,
            model_inventory=model_inventory,
        )

    async def cancel_turn(
        self, context: AuthContext, conversation_id: str, turn_id: str
    ) -> dict[str, object]:
        """Stop one owner turn and close its durable slot even when the worker is unavailable."""

        self.require_access(context)
        turn = self.storage.get_turn(context.user.id, conversation_id, turn_id)
        if turn["status"] not in {"queued", "running"}:
            raise AssistantStorageConflict("turn_not_active")
        lease = self.storage.execution_for_turn(context.user.id, conversation_id, turn_id)
        if lease and lease.get("status") == "active":
            execution_id = str(lease["execution_id"])
            self._cancel_webfetch_waiters(execution_id)
            cancel_runtime = getattr(self.runtime, "cancel_execution", None)
            if callable(cancel_runtime):
                await self._bounded_runtime_call(cancel_runtime, execution_id, timeout=2.0)
            task = self._tasks.get(execution_id)
            if task is not None and not task.done():
                task.cancel()
                await asyncio.wait({task}, timeout=2.0)
            self.storage.close_execution(execution_id, now=self.now(), revoked=True)
            self.storage.set_turn_status(
                context.user.id,
                conversation_id,
                turn_id,
                status="cancelled",
                now=self.now(),
                error_code="turn_cancelled",
            )
        updated = self.storage.get_turn(context.user.id, conversation_id, turn_id)
        return {"turn_id": turn_id, "status": updated["status"]}

    async def delete_conversation(
        self,
        context: AuthContext,
        conversation_id: str,
        *,
        expected_revision: int,
        confirmation_phrase: str,
    ) -> dict[str, object]:
        """Stop ephemeral work, clear its runtime cache, then purge the exact owner chat."""

        self.require_access(context)
        # Reject stale requests before cancelling a turn or asking the native worker to purge.
        # The storage deletion transaction repeats this owner/revision/phrase check after the
        # asynchronous cache-clear boundary to protect against concurrent changes.
        self.storage.validate_conversation_delete(
            context.user.id,
            conversation_id,
            expected_revision=expected_revision,
            confirmation_phrase=confirmation_phrase,
        )
        execution_ids = self.storage.active_conversation_executions(
            context.user.id, conversation_id
        )
        for execution_id in execution_ids:
            cancel_runtime = getattr(self.runtime, "cancel_execution", None)
            if callable(cancel_runtime):
                await self._bounded_runtime_call(cancel_runtime, execution_id, timeout=2.0)
            task = self._tasks.get(execution_id)
            if task is not None and not task.done():
                task.cancel()
        active_tasks = [self._tasks[item] for item in execution_ids if item in self._tasks]
        if active_tasks:
            for task in active_tasks:
                task.cancel()
            await asyncio.wait(active_tasks, timeout=2.0)
        for execution_id in execution_ids:
            lease = self.storage.execution_lease(execution_id)
            if lease is None:
                continue
            with suppress(AssistantStorageError):
                self.storage.close_execution(execution_id, now=self.now(), revoked=True)
                self.storage.set_turn_status(
                    int(lease["user_id"]),
                    conversation_id,
                    str(lease["turn_id"]),
                    status="cancelled",
                    now=self.now(),
                    error_code="turn_cancelled",
                )
        # Cancellation can await; don't start a native cache purge after authority expires.
        current = self._require_live_action_context(context, requires_admin_step_up=False)
        self.require_access(current)
        clear = getattr(self.runtime, "clear_conversation_cache", None)
        if (
            not callable(clear)
            or await self._bounded_runtime_result(
                # The fixed native supervisor waits up to 20 seconds for idle-worker HOME purge.
                # Leave room for the purge request and status polling; still keep the HTTP
                # operation bounded and fail closed unless the exact purge reports True.
                clear,
                conversation_id,
                timeout=24.0,
            )
            is not True
        ):
            raise AssistantUnavailable("assistant_cache_clear_pending", 503)
        # Cache clearing is an await boundary; recheck live access before deleting persistent chat.
        current = self._require_live_action_context(context, requires_admin_step_up=False)
        self.require_access(current)
        return self.storage.delete_conversation(
            context.user.id,
            conversation_id,
            expected_revision=expected_revision,
            confirmation_phrase=confirmation_phrase,
            deleted_at=self.now(),
        )

    def _validate_action_target(
        self, user_id: int, action_type: str, payload: Mapping[str, object]
    ) -> None:
        """Re-resolve immutable target identities before consuming an approval phrase."""

        safe = (
            self._validate_persisted_action_payload(action_type, payload)
            if _APPROVED_QUANTITY_KEY in payload
            else self._validate_action_payload(action_type, payload)
        )
        instrument_actions = {
            "watchlist.add",
            "watchlist.remove",
            "portfolio.add",
            "portfolio.remove",
            "portfolio.set_quantity",
            "forecast.create",
            "market.open",
            "market.chart_range.set",
            "notes.set",
            "notes.clear",
            "alerts.add",
            "alerts.remove",
        }
        if action_type in instrument_actions:
            identity = self._resolve_identity(
                str(safe["symbol"]),
                str(safe["asset_type"]),
                str(safe["provider"]),
                str(safe["exchange"]),
            )
            if action_type.startswith("portfolio."):
                items = self.repository.instrument_list_items(user_id, "portfolio")
                current = next(
                    (
                        item
                        for item in items
                        if item.get("provider") == identity.get("provider")
                        and item.get("canonical_symbol") == identity.get("canonical_symbol")
                        and item.get("asset_type") == identity.get("asset_type")
                    ),
                    None,
                )
                exists = current is not None
                should_exist = action_type in {"portfolio.remove", "portfolio.set_quantity"}
                if exists != should_exist:
                    raise AssistantStorageConflict("action_target_changed")
                if action_type in {"portfolio.remove", "portfolio.set_quantity"}:
                    approved_quantity = safe.get(_APPROVED_QUANTITY_KEY)
                    if current is None or current.get("quantity") != approved_quantity:
                        raise AssistantStorageConflict("action_target_changed")
        elif action_type == "forecast.reopen":
            saved = self.repository.reconstruction(user_id, int(safe["event_id"]))
            if not isinstance(saved, Mapping) or not isinstance(saved.get("event"), Mapping):
                raise AssistantStorageNotFound()
            if not hmac.compare_digest(self._digest(saved["event"]), str(safe["event_version"])):
                raise AssistantStorageConflict("action_target_changed")
        elif action_type == "outcome.record":
            if self.repository.forecast_result(user_id, int(safe["result_id"])) is None:
                raise AssistantStorageNotFound()
        elif action_type == "reconstruction.run":
            if self.repository.reconstruction(user_id, int(safe["event_id"])) is None:
                raise AssistantStorageNotFound()

    @staticmethod
    def _validate_action_context(
        action_type: str,
        payload: Mapping[str, object],
        context: Mapping[str, object],
    ) -> None:
        """Keep browser handoffs on their exact page and selected public instrument."""

        route = context.get("route")
        if action_type == "filters.apply" and route != "/":
            raise AssistantStorageConflict("action_context_stale")
        market_actions = {
            "market.filters.apply",
            "market.chart_range.set",
            "market.columns.set",
            "market.refresh",
        }
        if action_type not in market_actions:
            return
        if route != "/tools/markets":
            raise AssistantStorageConflict("action_context_stale")
        if action_type != "market.chart_range.set":
            return
        instrument = context.get("instrument")
        if not isinstance(instrument, Mapping):
            raise AssistantStorageConflict("action_context_stale")
        if (
            str(instrument.get("symbol", "")).upper() != payload.get("symbol")
            or instrument.get("asset_type") != payload.get("asset_type")
            or str(instrument.get("provider", "")).casefold()
            != str(payload.get("provider", "")).casefold()
            or str(instrument.get("exchange", "")).casefold()
            != str(payload.get("exchange", "")).casefold()
        ):
            raise AssistantStorageConflict("action_context_stale")

    def confirm_action(
        self,
        context: AuthContext,
        conversation_id: str,
        action_id: str,
        *,
        action_version: int,
        page_context: AssistantContextRef,
        confirmation_phrase: str,
        allow: bool,
    ) -> dict[str, object]:
        """Consume one browser decision, dispatch a typed action, and persist its receipt."""

        self.require_access(context)
        proposal = self.storage.get_action(context.user.id, action_id)
        if proposal.get("conversation_id") != conversation_id:
            raise AssistantStorageNotFound()
        requires_admin_step_up = proposal.get("action_type") in {
            "invitation.create",
            "backup.create",
            "restore.promote",
            "provider.settings",
        }
        if not isinstance(requires_admin_step_up, bool):
            requires_admin_step_up = False
        self._require_live_action_context(context, requires_admin_step_up=requires_admin_step_up)
        current_context = self.validate_context(context.user.id, page_context)
        if not hmac.compare_digest(
            str(current_context.get("context_version", "")),
            str(proposal.get("context_version", "")),
        ):
            raise AssistantStorageConflict("action_context_stale")
        if proposal.get("session_id") != context.session_id:
            raise AssistantStorageConflict("action_session_stale")
        issuing_turn = self.storage.get_turn(
            context.user.id, conversation_id, str(proposal.get("turn_id", ""))
        )
        model_id = str(issuing_turn.get("model_id", ""))
        policy_version = str(issuing_turn.get("policy_version", ""))
        action_type = str(proposal["action_type"])

        def authorize_action() -> AuthContext:
            current = self._require_live_action_context(
                context, requires_admin_step_up=requires_admin_step_up
            )
            if not self.policy_still_authorized(context.user.id, model_id, policy_version):
                raise AssistantStorageConflict("action_policy_stale")
            return current

        authorize_action()
        if not self.policy_still_authorized(context.user.id, model_id, policy_version):
            raise AssistantStorageConflict("action_policy_stale")
        if not allow:
            declined = self.storage.deny_action(
                context.user.id,
                action_id,
                action_version=action_version,
                session_id=context.session_id,
                context_version=str(current_context["context_version"]),
                now=self.now(),
            )
            return {
                "action_id": action_id,
                "status": "denied",
                "message": "The proposed action was declined.",
                "receipt_id": declined["id"],
            }
        self._validate_action_target(
            context.user.id,
            action_type,
            cast(Mapping[str, object], proposal["payload"]),
        )
        self._validate_action_context(
            action_type,
            cast(Mapping[str, object], proposal["payload"]),
            current_context,
        )
        current_context = self.validate_context(context.user.id, page_context)
        if not hmac.compare_digest(
            str(current_context.get("context_version", "")),
            str(proposal.get("context_version", "")),
        ):
            raise AssistantStorageConflict("action_context_stale")
        self._validate_action_context(
            action_type,
            cast(Mapping[str, object], proposal["payload"]),
            current_context,
        )
        authorize_action()
        action = self.storage.claim_action(
            context.user.id,
            action_id,
            action_version=action_version,
            confirmation_phrase=confirmation_phrase,
            session_id=context.session_id,
            context_version=str(current_context["context_version"]),
            now=self.now(),
        )
        try:
            current_context = authorize_action()
            outcome, result = self.dispatch_confirmed_action(
                context.user.id,
                str(action["action_type"]),
                cast(Mapping[str, object], action["payload"]),
                confirmed_by=current_context,
                authorization_check=authorize_action,
            )
            authorize_action()
        except AssistantUnavailable:
            with suppress(AssistantStorageError):
                self.storage.mark_action_unknown(context.user.id, action_id, now=self.now())
            raise
        except AssistantStorageError:
            with suppress(AssistantStorageError):
                self.storage.mark_action_unknown(context.user.id, action_id, now=self.now())
            raise
        except Exception:
            with suppress(AssistantStorageError):
                self.storage.mark_action_unknown(context.user.id, action_id, now=self.now())
            raise AssistantUnavailable("tool_failed", 502) from None
        try:
            receipt = self.storage.finish_action(
                context.user.id,
                action_id,
                outcome=outcome,
                result=result,
                now=self.now(),
            )
        except Exception:
            # A domain write may have committed before receipt persistence failed. Preserve
            # the one-use claim and report uncertainty; never imply it had no effect.
            try:
                receipt = self.storage.mark_action_unknown(
                    context.user.id, action_id, now=self.now()
                )
            except AssistantStorageError:
                # A commit can succeed even when its caller observes an exception. If the
                # reservation is already terminal, report its durable state instead of
                # converting a known result into an error or retryable action.
                try:
                    receipt = self.storage.get_action_receipt(context.user.id, action_id)
                except AssistantStorageError:
                    raise AssistantUnavailable("tool_failed", 503) from None
                if receipt is None or receipt.get("outcome") == "executing":
                    raise AssistantUnavailable("tool_failed", 503) from None
        public_result = cast(Mapping[str, object], receipt.get("result", {}))
        receipt_outcome = receipt.get("outcome")
        if receipt_outcome not in {"applied", "handed_off", "denied", "failed", "unknown"}:
            raise AssistantUnavailable("tool_failed", 503)
        response = {
            "action_id": action_id,
            "status": receipt_outcome,
            "message": str(public_result.get("message", "Action completed."))[:500],
            "receipt_id": receipt["id"],
        }
        if receipt_outcome == "handed_off":
            destination = self._safe_action_destination(public_result.get("destination"))
            if destination is not None:
                response["destination"] = destination
            browser_action = public_result.get("browser_action")
            if isinstance(browser_action, Mapping):
                safe_browser_action = self._safe_browser_action(browser_action)
                if safe_browser_action is not None:
                    response["browser_action"] = safe_browser_action
        return response

    @staticmethod
    def _safe_action_destination(value: object) -> str | None:
        """Keep navigation receipts on exact application routes with a fixed query vocabulary."""

        if (
            not isinstance(value, str)
            or len(value) > 512
            or not value.startswith("/")
            or value.startswith("//")
            or "\\" in value
        ):
            return None
        if value in {
            "/admin#invitations",
            "/admin#backups",
            "/admin#restore",
            "/admin#assistant-providers",
            "/account#sessions",
            "/api/v1/history-export.csv",
            "/api/v1/history-export.json",
        }:
            return value
        parsed = urlsplit(value)
        try:
            pairs = parse_qsl(
                parsed.query,
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=16,
            )
        except ValueError:
            return None
        if (
            parsed.path == "/"
            and parsed.fragment == "result-section"
            and len(pairs) == 1
            and pairs[0][0] == "event_id"
            and re.fullmatch(r"[1-9][0-9]{0,9}", pairs[0][1])
        ):
            return f"/?event_id={pairs[0][1]}#result-section"
        if parsed.path == "/tools/markets" and not parsed.fragment and len(pairs) == 4:
            values = dict(pairs)
            if (
                len(values) == 4
                and set(values) == {"symbol", "asset_type", "provider", "exchange"}
                and re.fullmatch(r"[A-Z0-9.^-]{1,15}", values["symbol"])
                and values["asset_type"] in {"stock", "etf"}
                and re.fullmatch(r"[A-Za-z0-9 ._-]{1,80}", values["provider"])
                and re.fullmatch(r"[A-Za-z0-9 ._-]{1,40}", values["exchange"])
            ):
                return value
        if parsed.path == "/" and parsed.fragment == "history-heading" and len(pairs) <= 10:
            values = dict(pairs)
            if len(values) != len(pairs) or set(values) - {"q", "status", "asset_type"}:
                return None
            query = values.get("q", "")
            status = values.get("status", "")
            asset_type = values.get("asset_type", "")
            if (
                len(query) <= 30
                and (not status or status in {"successful", "repeated", "failed"})
                and (not asset_type or asset_type in {"stock", "etf"})
            ):
                return value
        if (
            parsed.path in {"/api/v1/history-export.csv", "/api/v1/history-export.json"}
            and not parsed.fragment
            and pairs
        ):
            values = dict(pairs)
            if len(values) != len(pairs):
                return None
            allowed = {
                "q",
                "symbol",
                "status",
                "asset_type",
                "analysis_kind",
                "submitted_from",
                "submitted_to",
                "model",
                "horizon",
                "sort_by",
                "sort_order",
            }
            if set(values) - allowed or not {"sort_by", "sort_order"} <= set(values):
                return None
            if values["sort_by"] not in {"event_id", "symbol", "company", "status"}:
                return None
            if values["sort_order"] not in {"asc", "desc"}:
                return None
            start = values.get("submitted_from", "")
            end = values.get("submitted_to", "")
            if start:
                if not start.endswith("T00:00:00Z"):
                    return None
                values["submitted_from"] = start.removesuffix("T00:00:00Z")
            if end:
                if not end.endswith("T23:59:59.999Z"):
                    return None
                values["submitted_to"] = end.removesuffix("T23:59:59.999Z")
            filters: dict[str, object] = {
                "query": values.get("q", ""),
                "symbol": values.get("symbol", ""),
                "status": values.get("status", ""),
                "asset_type": values.get("asset_type", ""),
                "analysis_kind": values.get("analysis_kind", ""),
                "submitted_from": values.get("submitted_from", ""),
                "submitted_to": values.get("submitted_to", ""),
                "model": values.get("model", ""),
                "horizon": values.get("horizon", ""),
                "sort": f"{values['sort_by']}:{values['sort_order']}",
            }
            try:
                normalized = normalize_history_filters(filters)
            except InvalidFeatureFilter:
                return None
            query_values = history_export_query(normalized)
            suffix = urlencode(query_values)
            return f"{parsed.path}?{suffix}"
        return None

    @staticmethod
    def _safe_browser_action(value: Mapping[str, object]) -> dict[str, object] | None:
        """Return only fixed browser bridge payloads; never reflect model arguments wholesale."""

        action_type = value.get("type")
        payload = value.get("payload")
        if not isinstance(action_type, str) or not isinstance(payload, Mapping):
            return None
        if action_type not in {
            "theme.set",
            "filters.apply",
            "market.filters.apply",
            "market.chart_range.set",
            "market.columns.set",
            "market.refresh",
            "notes.set",
            "notes.clear",
            "alerts.add",
            "alerts.remove",
        }:
            return None
        try:
            if action_type in {"notes.set", "notes.clear", "alerts.remove"}:
                # These focus existing controls only; no browser-local content is overwritten.
                safe = AssistantService._validate_action_payload("market.open", payload)
            else:
                safe = AssistantService._validate_action_payload(action_type, payload)
        except AssistantUnavailable:
            return None
        destination = value.get("destination")
        expected_route = (
            "/tools/live-trading"
            if action_type.startswith(("notes.", "alerts."))
            else "/"
            if action_type == "filters.apply"
            else "/tools/markets"
            if action_type.startswith("market.")
            else None
        )
        if expected_route is None:
            if destination is not None:
                return None
        elif (
            not isinstance(destination, Mapping)
            or destination.get("kind") != "current-page"
            or destination.get("route") != expected_route
        ):
            return None
        focus_target = (
            "notes-heading"
            if action_type.startswith("notes.")
            else "alerts-heading"
            if action_type == "alerts.remove"
            else None
        )
        expected_destination_fields = {"kind", "route"}
        if focus_target is not None:
            expected_destination_fields.add("focus")
        if action_type == "alerts.add":
            expected_destination_fields.add("handler")
        if expected_route is not None and set(destination) != expected_destination_fields:
            return None
        if focus_target is not None and destination.get("focus") != focus_target:
            return None
        if action_type == "alerts.add" and destination.get("handler") != "alerts.add":
            return None
        result: dict[str, object] = {
            "type": action_type,
            "payload": safe,
        }
        if expected_route is not None:
            result["destination"] = {"kind": "current-page", "route": expected_route}
            if focus_target is not None:
                result["destination"]["focus"] = focus_target
            if action_type == "alerts.add":
                result["destination"]["handler"] = "alerts.add"
        return result

    async def await_search_approval(
        self,
        runtime_context: AssistantTurnContext,
        query: str,
        emit: Any,
    ) -> str | None:
        """Pause one search until its exact query is approved in the same browser conversation."""

        self._validate_prompt(query)
        try:
            turn = self.storage.get_turn(
                runtime_context.user_id,
                runtime_context.conversation_id,
                runtime_context.turn_id,
            )
            if (
                turn.get("status") != "running"
                or turn.get("model_id") != runtime_context.model_id
                or turn.get("context_version") != runtime_context.context_version
            ):
                return None
            lease = self.storage.authorize_tool_call(
                runtime_context.execution_id,
                runtime_context.capability,
                now=self.now(),
                marks_private_read=False,
            )
        except AssistantStorageError:
            return None
        if (
            int(lease.get("user_id", 0)) != runtime_context.user_id
            or lease.get("conversation_id") != runtime_context.conversation_id
            or lease.get("turn_id") != runtime_context.turn_id
            or lease.get("context_version") != runtime_context.context_version
            or not self.validate_execution_session(lease)
            or not self._execution_current(
                runtime_context.user_id,
                runtime_context.execution_id,
                str(turn["model_id"]),
                str(turn["policy_version"]),
            )
        ):
            raise AssistantUnavailable("session_revoked", 403)
        # Prompt text, durable chat history, page context, and prior receipts can all carry
        # private data before an MCP read occurs. The safe default therefore previews every
        # builtin web request; only a future server-derived fixed public-symbol query may use
        # a separately typed exemption.
        preview = self.storage.create_search_preview(
            runtime_context.user_id,
            runtime_context.conversation_id,
            runtime_context.turn_id,
            runtime_context.execution_id,
            query_text=query,
            context_version=runtime_context.context_version,
            confirmation_phrase="",
            now=self.now(),
            expires_at=min(
                self.now() + timedelta(seconds=ASSISTANT_TURN_SECONDS),
                datetime.fromisoformat(str(lease["expires_at"])).astimezone(UTC),
            ),
        )
        preview_id = str(preview["id"])
        phrase = str(preview["confirmation_phrase"])
        future: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
        self._search_waiters[preview_id] = future
        self._emitters[runtime_context.execution_id] = emit
        try:
            await emit(
                {
                    "type": "private_context_preview",
                    "data": {
                        "preview_id": preview_id,
                        "query": query,
                        "reason": "Review this exact search before it leaves the local service.",
                        "context_version": runtime_context.context_version,
                        "expires_at": preview["expires_at"],
                        "confirmation_phrase": phrase,
                    },
                }
            )
            try:
                remaining = max(
                    0.0,
                    (
                        datetime.fromisoformat(str(lease["expires_at"])).astimezone(UTC)
                        - self.now()
                    ).total_seconds(),
                )
                return await asyncio.wait_for(
                    future, timeout=min(ASSISTANT_TURN_SECONDS, remaining)
                )
            except TimeoutError:
                return None
        finally:
            self._search_waiters.pop(preview_id, None)
            if self._emitters.get(runtime_context.execution_id) is emit:
                self._emitters.pop(runtime_context.execution_id, None)

    async def await_webfetch_approval(
        self,
        runtime_context: AssistantTurnContext,
        url: str,
        emit: Any,
    ) -> str | None:
        """Pause native fetching until this exact URL is approved in the issuing session."""

        validated_url = validate_webfetch_url(url)
        if validated_url != url:
            return None
        try:
            turn = self.storage.get_turn(
                runtime_context.user_id,
                runtime_context.conversation_id,
                runtime_context.turn_id,
            )
            if (
                turn.get("status") != "running"
                or turn.get("model_id") != runtime_context.model_id
                or turn.get("policy_version") != runtime_context.policy_version
                or turn.get("context_version") != runtime_context.context_version
            ):
                return None
            lease = self.storage.authorize_tool_call(
                runtime_context.execution_id,
                runtime_context.capability,
                now=self.now(),
                marks_private_read=False,
            )
        except AssistantStorageError:
            return None
        if (
            int(lease.get("user_id", 0)) != runtime_context.user_id
            or lease.get("conversation_id") != runtime_context.conversation_id
            or lease.get("turn_id") != runtime_context.turn_id
            or lease.get("session_id") is None
            or lease.get("context_version") != runtime_context.context_version
            or not self.validate_execution_session(lease)
            or not self._execution_current(
                runtime_context.user_id,
                runtime_context.execution_id,
                runtime_context.model_id,
                runtime_context.policy_version,
            )
        ):
            raise AssistantUnavailable("session_revoked", 403)
        try:
            lease_expiry = datetime.fromisoformat(str(lease["expires_at"])).astimezone(UTC)
        except (KeyError, TypeError, ValueError):
            return None
        now = self.now()
        expires_at = min(now + timedelta(seconds=ASSISTANT_TURN_SECONDS), lease_expiry)
        if expires_at <= now:
            return None
        preview_id = secrets.token_hex(16)
        phrase = f"FETCH {preview_id[-8:]}"
        future: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
        waiter = _WebfetchWaiter(
            user_id=runtime_context.user_id,
            conversation_id=runtime_context.conversation_id,
            turn_id=runtime_context.turn_id,
            execution_id=runtime_context.execution_id,
            session_id=str(lease["session_id"]),
            model_id=runtime_context.model_id,
            policy_version=runtime_context.policy_version,
            context_version=runtime_context.context_version,
            url=url,
            confirmation_phrase=phrase,
            expires_at=expires_at,
            future=future,
        )
        with self._webfetch_waiter_lock:
            if any(
                existing.execution_id == runtime_context.execution_id
                for existing in self._webfetch_waiters.values()
            ):
                return None
            if len(self._webfetch_waiters) >= ASSISTANT_ACTIVE_GLOBAL:
                return None
            self._webfetch_waiters[preview_id] = waiter
        try:
            await emit(
                {
                    "type": "webfetch_preview",
                    "data": {
                        "preview_id": preview_id,
                        "url": url,
                        "reason": _WEBFETCH_PREVIEW_REASON,
                        "context_version": runtime_context.context_version,
                        "expires_at": expires_at.isoformat(),
                        "confirmation_phrase": phrase,
                    },
                }
            )
            loop = asyncio.get_running_loop()
            deadline = loop.time() + min(
                ASSISTANT_TURN_SECONDS, max(0.0, (expires_at - self.now()).total_seconds())
            )
            while not future.done():
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return None
                await asyncio.wait({future}, timeout=min(1.0, remaining))
                if future.done():
                    break
                if not self._execution_current(
                    runtime_context.user_id,
                    runtime_context.execution_id,
                    runtime_context.model_id,
                    runtime_context.policy_version,
                ):
                    return None
            approved = future.result()
            if approved != url or not self._execution_current(
                runtime_context.user_id,
                runtime_context.execution_id,
                runtime_context.model_id,
                runtime_context.policy_version,
            ):
                return None
            return url
        finally:
            self._remove_webfetch_waiter(preview_id, waiter)

    def get_webfetch_preview(
        self,
        context: AuthContext,
        conversation_id: str,
        turn_id: str,
        preview_id: str,
    ) -> dict[str, object]:
        """Return a pending exact destination only to its live issuing browser session."""

        waiter = self._require_live_webfetch_waiter(context, conversation_id, turn_id, preview_id)
        return {"preview": self._webfetch_preview_dto(preview_id, waiter)}

    def confirm_webfetch_preview(
        self,
        context: AuthContext,
        conversation_id: str,
        turn_id: str,
        preview_id: str,
        *,
        page_context: AssistantContextRef | None,
        context_version: str,
        confirmation_phrase: str,
        allow: bool,
    ) -> dict[str, object]:
        """Consume one live same-session URL approval and release only its exact destination."""

        waiter = self._require_live_webfetch_waiter(context, conversation_id, turn_id, preview_id)
        if not hmac.compare_digest(waiter.context_version, context_version):
            raise AssistantStorageConflict("webfetch_context_stale")
        if allow:
            if page_context is None:
                raise AssistantStorageConflict("webfetch_context_stale")
            try:
                canonical_context = self.validate_context(context.user.id, page_context)
            except AssistantStorageConflict as error:
                if str(error) == "context_stale":
                    raise AssistantStorageConflict("webfetch_context_stale") from None
                raise
            if not hmac.compare_digest(
                page_context.context_version, waiter.context_version
            ) or not hmac.compare_digest(
                str(canonical_context.get("context_version", "")), waiter.context_version
            ):
                raise AssistantStorageConflict("webfetch_context_stale")
            if not hmac.compare_digest(waiter.confirmation_phrase, confirmation_phrase):
                raise AssistantStorageConflict("webfetch_confirmation")
        # Claim the exact waiter while holding the cross-thread lock. Two browser requests can
        # both finish their live-context checks before either reaches this point.
        with self._webfetch_waiter_lock:
            if self._webfetch_waiters.get(preview_id) is not waiter or waiter.future.done():
                raise AssistantStorageConflict("webfetch_replayed")
            del self._webfetch_waiters[preview_id]
        waiter.future.get_loop().call_soon_threadsafe(
            self._finish_webfetch_waiter, waiter.future, waiter.url if allow else None
        )
        return {"preview_id": preview_id, "status": "approved" if allow else "denied"}

    def _require_live_webfetch_waiter(
        self,
        context: AuthContext,
        conversation_id: str,
        turn_id: str,
        preview_id: str,
    ) -> _WebfetchWaiter:
        self.require_access(context)
        with self._webfetch_waiter_lock:
            waiter = self._webfetch_waiters.get(preview_id)
        if (
            waiter is None
            or waiter.user_id != context.user.id
            or waiter.conversation_id != conversation_id
            or waiter.turn_id != turn_id
            or waiter.session_id != context.session_id
        ):
            raise AssistantStorageNotFound()
        if waiter.future.done() or self.now() >= waiter.expires_at:
            self._cancel_webfetch_waiter(preview_id, waiter)
            raise AssistantStorageConflict("webfetch_preview_expired")
        current = self._live_auth_context(
            user_id=context.user.id,
            session_id=context.session_id,
            token_hash=context.token_hash,
            expected_csrf_hash=context.csrf_token_hash,
        )
        if current is None:
            self._cancel_webfetch_waiter(preview_id, waiter)
            raise AssistantUnavailable("session_revoked", 403)
        turn = self.storage.get_turn(context.user.id, conversation_id, turn_id)
        lease = self.storage.execution_lease(waiter.execution_id)
        if (
            not lease
            or lease.get("status") != "active"
            or lease.get("session_id") != context.session_id
            or lease.get("user_id") != context.user.id
            or lease.get("conversation_id") != conversation_id
            or lease.get("turn_id") != turn_id
            or turn.get("status") != "running"
            or turn.get("context_version") != waiter.context_version
            or turn.get("model_id") != waiter.model_id
            or turn.get("policy_version") != waiter.policy_version
            or not self.validate_execution_session(lease)
            or not self._execution_current(
                context.user.id,
                waiter.execution_id,
                waiter.model_id,
                waiter.policy_version,
            )
        ):
            self._cancel_webfetch_waiter(preview_id, waiter)
            raise AssistantStorageConflict("webfetch_session_stale")
        return waiter

    @staticmethod
    def _webfetch_preview_dto(preview_id: str, waiter: _WebfetchWaiter) -> dict[str, object]:
        return {
            "preview_id": preview_id,
            "url": waiter.url,
            "reason": _WEBFETCH_PREVIEW_REASON,
            "context_version": waiter.context_version,
            "expires_at": waiter.expires_at.isoformat(),
            "confirmation_phrase": waiter.confirmation_phrase,
        }

    def _cancel_webfetch_waiter(self, preview_id: str, waiter: _WebfetchWaiter) -> None:
        with self._webfetch_waiter_lock:
            removed = self._webfetch_waiters.get(preview_id) is waiter
            if removed:
                del self._webfetch_waiters[preview_id]
        if removed and not waiter.future.done():
            waiter.future.get_loop().call_soon_threadsafe(
                self._finish_webfetch_waiter, waiter.future, None
            )

    def _remove_webfetch_waiter(self, preview_id: str, waiter: _WebfetchWaiter) -> None:
        """Remove only this approval, never a replacement registered for the same identifier."""

        with self._webfetch_waiter_lock:
            if self._webfetch_waiters.get(preview_id) is waiter:
                self._webfetch_waiters.pop(preview_id, None)

    @staticmethod
    def _finish_webfetch_waiter(future: asyncio.Future[str | None], result: str | None) -> None:
        if not future.done():
            future.set_result(result)

    def _cancel_webfetch_waiters(self, execution_id: str) -> None:
        with self._webfetch_waiter_lock:
            waiters = tuple(self._webfetch_waiters.items())
        for preview_id, waiter in waiters:
            if waiter.execution_id == execution_id:
                self._cancel_webfetch_waiter(preview_id, waiter)

    def confirm_search_preview(
        self,
        context: AuthContext,
        conversation_id: str,
        turn_id: str,
        preview_id: str,
        *,
        page_context: AssistantContextRef,
        context_version: str,
        confirmation_phrase: str,
        allow: bool,
    ) -> dict[str, object]:
        """Persist and deliver one authenticated exact-query decision to its waiting call."""

        self.require_access(context)
        turn = self.storage.get_turn(context.user.id, conversation_id, turn_id)
        if turn.get("status") != "running" or turn.get("context_version") != context_version:
            raise AssistantStorageConflict("search_context_stale")
        canonical = self.validate_context(context.user.id, page_context)
        if not hmac.compare_digest(str(canonical.get("context_version", "")), context_version):
            raise AssistantStorageConflict("search_context_stale")
        lease_ref = self.storage.execution_for_turn(context.user.id, conversation_id, turn_id)
        lease = (
            self.storage.execution_lease(str(lease_ref["execution_id"]))
            if lease_ref and lease_ref.get("execution_id")
            else None
        )
        if (
            not lease
            or lease.get("session_id") != context.session_id
            or lease.get("status") != "active"
            or not self.validate_execution_session(lease)
            or not self._execution_current(
                context.user.id,
                str(lease.get("execution_id", "")),
                str(turn.get("model_id")),
                str(turn.get("policy_version")),
            )
        ):
            raise AssistantStorageConflict("search_session_stale")
        future = self._search_waiters.get(preview_id)
        if future is None or future.done():
            raise AssistantStorageConflict("search_execution_not_waiting")
        preview = self.storage.resolve_search_preview(
            context.user.id,
            conversation_id,
            turn_id,
            preview_id,
            context_version=context_version,
            confirmation_phrase=confirmation_phrase,
            allow=allow,
            now=self.now(),
        )
        future.set_result(str(preview["query_text"]) if allow else None)
        return {"preview_id": preview_id, "status": preview["status"]}

    async def _ensure_runtime_ready(self) -> None:
        """Retry a failed optional worker start at a bounded cadence without app restart."""

        if not self.settings.assistant_enabled or self.operator_disabled or self.runtime is None:
            raise AssistantUnavailable("assistant_worker_unavailable", 503)
        if self._runtime_status().get("status") == "ready":
            return
        loop = asyncio.get_running_loop()
        if loop.time() - self._runtime_last_start_attempt >= ASSISTANT_RUNTIME_RETRY_SECONDS:
            async with self._runtime_start_lock:
                if self._runtime_status().get("status") != "ready" and (
                    loop.time() - self._runtime_last_start_attempt
                    >= ASSISTANT_RUNTIME_RETRY_SECONDS
                ):
                    starter = getattr(self.runtime, "start", None)
                    self._runtime_last_start_attempt = loop.time()
                    if callable(starter):
                        self._runtime_start_failed = not await self._bounded_runtime_call(
                            starter, timeout=ASSISTANT_RUNTIME_START_SECONDS
                        )
                    else:
                        self._runtime_start_failed = True
        if self._runtime_status().get("status") != "ready":
            raise AssistantUnavailable("assistant_worker_unavailable", 503)

    async def refresh_runtime_status(self) -> None:
        """Perform one cadence-bounded health/start retry for authenticated status polling."""

        try:
            await self._ensure_runtime_ready()
        except AssistantUnavailable as exc:
            if exc.code != "assistant_worker_unavailable":
                raise

    @staticmethod
    def _validate_prompt(prompt: str) -> str:
        normalized = prompt.strip()
        if not normalized:
            raise ValueError("prompt must contain visible text")
        if re.fullmatch(r"\d{6}", normalized) or any(
            pattern.search(normalized) for pattern in _PROMPT_SECRET_PATTERNS
        ):
            raise AssistantUnavailable("sensitive_input_rejected", 422)
        return normalized

    @staticmethod
    def contains_known_secret_text(value: object) -> bool:
        """Fail closed on bounded strings matching known credential formats."""

        pending = [value]
        inspected = 0
        while pending:
            item = pending.pop()
            inspected += 1
            if inspected > 8192:
                return True
            if isinstance(item, str):
                if any(pattern.search(item) for pattern in _PROMPT_SECRET_PATTERNS):
                    return True
            elif isinstance(item, Mapping):
                pending.extend(item.keys())
                pending.extend(item.values())
            elif isinstance(item, list | tuple):
                pending.extend(item)
        return False

    def persist_tool_receipt(
        self,
        lease: Mapping[str, object],
        name: str,
        result: object,
    ) -> dict[str, object] | None:
        """Store a compact owner-scoped digest and citations for a completed app read."""

        if name == "assistant.propose_action":
            # Its persisted proposed_action card is already the canonical durable record.
            return None
        user_id = lease.get("user_id")
        conversation_id = lease.get("conversation_id")
        turn_id = lease.get("turn_id")
        context_version = lease.get("context_version")
        if (
            type(user_id) is not int
            or not isinstance(conversation_id, str)
            or not isinstance(turn_id, str)
            or not isinstance(context_version, str)
            or name not in self.tool_gateway_names()
        ):
            raise AssistantUnavailable("session_revoked", 403)
        try:
            canonical = json.dumps(
                result,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise AssistantUnavailable("invalid_runtime_event", 502) from exc
        if len(canonical) > 65_536:
            raise AssistantUnavailable("tool_result_too_large", 413)
        if self.contains_known_secret_text(result):
            raise AssistantUnavailable("sensitive_output_rejected", 502)

        source_candidates: list[dict[str, object]] = []
        data = result.get("data") if isinstance(result, Mapping) else None
        if name == "market.news" and isinstance(data, Mapping):
            raw_items = data.get("items")
            items = raw_items[:5] if isinstance(raw_items, list) else []
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                try:
                    safe_url = safe_news_url(item.get("url"))
                except DomainError:
                    continue
                title = str(item.get("title", "")).strip()[:300]
                if not title:
                    continue
                published: datetime | None = None
                raw_published = item.get("published_at")
                if isinstance(raw_published, str):
                    try:
                        parsed = datetime.fromisoformat(raw_published)
                        if parsed.tzinfo is not None:
                            published = parsed.astimezone(UTC)
                    except ValueError:
                        pass
                source_candidates.append(
                    {
                        "title": title,
                        "url": safe_url,
                        "source_ref": str(item.get("id", ""))[:128] or None,
                        "retrieved_at": self.now(),
                        "as_of": published,
                    }
                )

        provider: str | None = None
        as_of: str | None = None
        metadata = data if isinstance(data, Mapping) else result
        if isinstance(metadata, Mapping):
            raw_provider = metadata.get("provider")
            if isinstance(raw_provider, str) and 0 < len(raw_provider) <= 80:
                provider = raw_provider
            raw_as_of = metadata.get("as_of")
            if isinstance(raw_as_of, str) and 0 < len(raw_as_of) <= 64:
                as_of = raw_as_of
        resource_refs: dict[str, object] = {}
        if name == "history.saved_forecast" and isinstance(result, Mapping):
            event = result.get("event")
            if isinstance(event, Mapping) and type(event.get("id")) is int:
                resource_refs["event_id"] = int(event["id"])
            results = result.get("results")
            if isinstance(results, list):
                resource_refs["result_ids"] = [
                    int(item["id"])
                    for item in results[:20]
                    if isinstance(item, Mapping) and type(item.get("id")) is int
                ]

        event_data: dict[str, object] = {
            "receipt_id": secrets.token_hex(16),
            "name": name,
            "status": "completed",
            "description": "The approved application read completed.",
            "result_sha256": hashlib.sha256(canonical).hexdigest(),
            "result_bytes": len(canonical),
            "context_version": context_version,
            "resource_refs": resource_refs,
        }
        if provider is not None:
            event_data["provider"] = provider
        if as_of is not None:
            event_data["as_of"] = as_of
        return self.storage.append_tool_receipt(
            user_id,
            conversation_id,
            turn_id,
            data=event_data,
            sources=source_candidates,
            now=self.now(),
        )

    @staticmethod
    def tool_gateway_names() -> frozenset[str]:
        """Return the fixed MCP catalog names for receipt validation without model data."""

        return frozenset(
            {
                "workspace.summary",
                "workspace.instrument_lists",
                "history.search",
                "history.saved_forecast",
                "history.outcomes",
                "market.instrument_search",
                "market.quote",
                "market.bars",
                "market.compare",
                "market.news",
                "assistant.propose_action",
            }
        )

    async def create_turn(
        self,
        context: AuthContext,
        conversation_id: str,
        *,
        prompt: str,
        model_id: str,
        policy_version: str,
        page_context: AssistantContextRef,
        context_preview_accepted: bool,
    ) -> dict[str, object]:
        """Persist an explicitly requested turn and run it only in isolated local runtime."""

        self.require_access(context)
        await self._ensure_runtime_ready()
        prompt = self._validate_prompt(prompt)
        canonical_context = self.validate_context(context.user.id, page_context)
        if not context_preview_accepted:
            raise AssistantUnavailable("context_preview_required", 409)
        inventory = await self.ensure_model_inventory(
            minimum_validity_seconds=120.0,
            owner_id=context.user.id,
            authorization_check=lambda: self._assistant_session_is_live(
                context.user.id, context.session_id, context.token_hash
            ),
        )
        policy = self.policy(model_id, model_inventory=inventory, owner_id=context.user.id)
        if policy.policy_version != policy_version:
            raise AssistantStorageConflict("policy_version")
        consent = self.storage.current_consent(context.user.id, model_id, policy_version)
        if not consent or not consent.get("accepted_terms"):
            raise AssistantConsentRequired()
        if policy.training and not consent.get("data_collection_opt_in"):
            raise AssistantConsentRequired()
        if bool(consent.get("data_collection_opt_in")) and not policy.data_collection_allowed:
            raise AssistantStorageConflict("policy_changed")
        capability = secrets.token_urlsafe(36)
        now = self.now()
        # Readiness and inventory refresh can await; bind persistence to the still-live session.
        if not self._assistant_session_is_live(
            context.user.id, context.session_id, context.token_hash
        ):
            raise AssistantUnavailable("assistant_authorization_required", 403)
        record = self.storage.create_turn(
            context.user.id,
            conversation_id,
            prompt=prompt,
            model_id=model_id,
            policy_version=policy_version,
            context=canonical_context,
            context_version=str(canonical_context["context_version"]),
            session_id=context.session_id,
            session_token_hash=context.token_hash,
            capability=capability,
            now=now,
            expires_at=now + timedelta(seconds=ASSISTANT_TURN_SECONDS),
        )
        turn_id = str(record["id"])
        execution_id = str(record["execution_id"])
        task = asyncio.create_task(
            self._run_turn(
                context=context,
                conversation_id=conversation_id,
                turn_id=turn_id,
                execution_id=execution_id,
                capability=capability,
                model_id=model_id,
                policy=policy,
                prompt=prompt,
                canonical_context=canonical_context,
            ),
            name=f"assistant-turn-{execution_id}",
        )
        async with self._task_lock:
            self._tasks[execution_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(execution_id, None))
        return {"turn": {key: value for key, value in record.items() if key != "execution_id"}}

    async def _run_turn(
        self,
        *,
        context: AuthContext,
        conversation_id: str,
        turn_id: str,
        execution_id: str,
        capability: str,
        model_id: str,
        policy: AssistantModelPolicy,
        prompt: str,
        canonical_context: Mapping[str, object],
    ) -> None:
        generated: list[str] = []
        output_tail = ""
        generated_size = 0
        useful_event_seen = False
        result_status = "failed"
        error_code = "worker_unavailable"
        runtime_task: asyncio.Future[Any] | None = None
        runtime_context = AssistantTurnContext(
            user_id=context.user.id,
            app_id="signal-ledger",
            conversation_id=conversation_id,
            turn_id=turn_id,
            execution_id=execution_id,
            capability=capability,
            model_id=model_id,
            policy_version=policy.policy_version,
            context_version=str(canonical_context["context_version"]),
            page_context=dict(canonical_context),
            history=self.storage.conversation_history(
                context.user.id, conversation_id, exclude_turn_id=turn_id
            ),
        )
        try:
            self.storage.set_turn_status(
                context.user.id,
                conversation_id,
                turn_id,
                status="running",
                now=self.now(),
            )

            async def emit(event: Mapping[str, object]) -> None:
                nonlocal generated_size, output_tail, useful_event_seen
                if not self._execution_current(
                    context.user.id, execution_id, model_id, policy.policy_version
                ):
                    raise AssistantUnavailable("session_revoked", 403)
                event_type = event.get("type")
                data = event.get("data")
                if event_type == "complete":
                    return
                normalized_type, normalized_data = self._normalize_runtime_event(
                    str(event_type or ""),
                    data,
                    context.user.id,
                    conversation_id,
                    turn_id,
                    execution_id=execution_id,
                )
                if normalized_type == "meta" and (
                    normalized_data.get("model_id") != model_id
                    or normalized_data.get("policy_version") != policy.policy_version
                    or normalized_data.get("context_version") != runtime_context.context_version
                ):
                    raise AssistantUnavailable("invalid_runtime_event", 502)
                if normalized_type == "token":
                    token = normalized_data.get("text")
                    if isinstance(token, str):
                        byte_count = len(token.encode("utf-8"))
                        if generated_size + byte_count > 65_536:
                            raise AssistantUnavailable("output_too_large", 413)
                        generated_size += byte_count
                        combined = output_tail + token
                        if self.contains_known_secret_text(combined):
                            raise AssistantUnavailable("sensitive_output_rejected", 502)
                        safe_length = max(0, len(combined) - 256)
                        safe_text = combined[:safe_length]
                        output_tail = combined[safe_length:]
                        if not safe_text:
                            return
                        for chunk in _utf8_chunks(safe_text):
                            generated.append(chunk)
                            self.storage.append_event(
                                context.user.id,
                                conversation_id,
                                turn_id,
                                event_type="token",
                                data={"text": chunk},
                                now=self.now(),
                            )
                        return
                elif normalized_type in {"proposed_action", "source"}:
                    useful_event_seen = True
                self.storage.append_event(
                    context.user.id,
                    conversation_id,
                    turn_id,
                    event_type=normalized_type,
                    data=normalized_data,
                    now=self.now(),
                )

            runner = getattr(self.runtime, "run_turn", None)
            if not callable(runner):
                raise AssistantUnavailable("assistant_worker_unavailable", 503)
            run_result = runner(context=runtime_context, prompt=prompt, emit=emit)
            if not asyncio.iscoroutine(run_result) and not hasattr(run_result, "__await__"):
                raise AssistantUnavailable("invalid_runtime_event", 502)
            runtime_task = asyncio.ensure_future(run_result)
            lease = self.storage.execution_lease(execution_id)
            try:
                expires_at = datetime.fromisoformat(str((lease or {}).get("expires_at", "")))
                if expires_at.tzinfo is None:
                    raise ValueError
                remaining = max(0.0, (expires_at.astimezone(UTC) - self.now()).total_seconds())
            except ValueError:
                remaining = 0.0
            finished, pending = await asyncio.wait(
                {runtime_task}, timeout=min(ASSISTANT_TURN_SECONDS, remaining)
            )
            if pending:
                runtime_task.cancel()
                runtime_task.add_done_callback(
                    lambda task: task.exception() if not task.cancelled() else None
                )
                await self._bounded_runtime_call(
                    getattr(self.runtime, "cancel_execution", lambda *_: None),
                    execution_id,
                    timeout=2.0,
                )
                raise TimeoutError
            raw_result = runtime_task.result()
            if not isinstance(raw_result, AssistantTurnResult) or raw_result.status not in {
                "completed",
                "cancelled",
                "failed",
                "timed_out",
            }:
                raise AssistantUnavailable("invalid_runtime_event", 502)
            result_status = raw_result.status
            error_code = raw_result.error_code or "worker_unavailable"
            if result_status == "completed" and not self._execution_current(
                context.user.id, execution_id, model_id, policy.policy_version
            ):
                result_status = "failed"
                error_code = "session_revoked"
            if result_status == "completed" and output_tail:
                if self.contains_known_secret_text(output_tail):
                    result_status = "failed"
                    error_code = "sensitive_output_rejected"
                elif not self._execution_current(
                    context.user.id, execution_id, model_id, policy.policy_version
                ):
                    result_status = "failed"
                    error_code = "session_revoked"
                else:
                    generated.append(output_tail)
                    self.storage.append_event(
                        context.user.id,
                        conversation_id,
                        turn_id,
                        event_type="token",
                        data={"text": output_tail},
                        now=self.now(),
                    )
                output_tail = ""
            if (
                result_status == "completed"
                and not generated
                and not useful_event_seen
                and not self.storage.has_useful_turn_output(
                    context.user.id, conversation_id, turn_id
                )
            ):
                result_status = "failed"
                error_code = "empty_response"
            if result_status == "completed" and generated:
                self.storage.append_message(
                    context.user.id,
                    conversation_id,
                    turn_id,
                    role="assistant",
                    content="".join(generated),
                    now=self.now(),
                )
        except asyncio.CancelledError:
            result_status = "cancelled"
            error_code = "turn_cancelled"
            if runtime_task is not None and not runtime_task.done():
                runtime_task.cancel()
                runtime_task.add_done_callback(
                    lambda task: task.exception() if not task.cancelled() else None
                )
            await self._bounded_runtime_call(
                getattr(self.runtime, "cancel_execution", lambda *_: None),
                execution_id,
                timeout=2.0,
            )
        except TimeoutError:
            result_status = "timed_out"
            error_code = "turn_timeout"
        except AssistantUnavailable as exc:
            result_status = "failed"
            error_code = exc.code if exc.code in _SAFE_ERROR_CODES else "worker_unavailable"
        except AssistantStorageQuotaExceeded:
            result_status = "failed"
            error_code = "tool_failed"
        except Exception:
            result_status = "failed"
            error_code = "worker_unavailable"
        finally:
            finish_timing = getattr(self.runtime, "_finish_turn_timing_diagnostic", None)
            if callable(finish_timing):
                with suppress(Exception):
                    finish_timing(execution_id, context.user.id, result_status)
            self._cancel_webfetch_waiters(execution_id)
            with suppress(Exception):
                self.storage.close_execution(
                    execution_id, now=self.now(), revoked=result_status != "completed"
                )
            try:
                changed = self.storage.set_turn_status(
                    context.user.id,
                    conversation_id,
                    turn_id,
                    status=result_status,
                    now=self.now(),
                    error_code=error_code if result_status != "completed" else None,
                )
                if changed:
                    if result_status != "completed":
                        self.storage.append_event(
                            context.user.id,
                            conversation_id,
                            turn_id,
                            event_type="error",
                            data={
                                "code": error_code
                                if error_code in _SAFE_ERROR_CODES
                                else "worker_unavailable",
                                "message": self._safe_error_message(error_code),
                            },
                            now=self.now(),
                        )
                    self.storage.append_event(
                        context.user.id,
                        conversation_id,
                        turn_id,
                        event_type="complete",
                        data={"status": result_status, "assistant_message_id": None},
                        now=self.now(),
                    )
            except AssistantStorageError:
                pass
            clear = getattr(self.runtime, "clear_conversation_cache", None)
            if result_status != "completed" and callable(clear):
                await self._bounded_runtime_call(clear, conversation_id, timeout=2.0)

    @staticmethod
    def _safe_error_message(code: str) -> str:
        return {
            "provider_unavailable": "The selected model provider is unavailable.",
            "turn_timeout": "The assistant turn reached its time limit.",
            "turn_cancelled": "The assistant turn was cancelled.",
            "provider_policy_changed": (
                "The model policy changed. Review the current policy to continue."
            ),
            "runtime_restarted": "The assistant turn stopped during restart.",
            "output_too_large": "The assistant response exceeded the saved transcript limit.",
            "empty_response": "The assistant returned no usable response.",
            "sensitive_output_rejected": (
                "The assistant output included sensitive credential-like text and was withheld."
            ),
            "session_revoked": "The signed-in session is no longer active.",
        }.get(code, "The assistant could not complete this turn.")

    def _normalize_runtime_event(
        self,
        event_type: str,
        data: object,
        user_id: int,
        conversation_id: str,
        turn_id: str,
        *,
        execution_id: str,
    ) -> tuple[str, dict[str, object]]:
        if not isinstance(data, Mapping):
            raise AssistantUnavailable("invalid_runtime_event", 502)
        if event_type == "meta":
            return "meta", {
                "model_id": str(data.get("model_id", ""))[:160],
                "policy_version": str(data.get("policy_version", ""))[:80],
                "context_version": str(data.get("context_version", ""))[:64],
            }
        if event_type == "token":
            text = data.get("text")
            if not isinstance(text, str) or len(text.encode("utf-8")) > 8192:
                raise AssistantUnavailable("invalid_runtime_event", 502)
            if self.contains_known_secret_text(text):
                raise AssistantUnavailable("sensitive_output_rejected", 502)
            return "token", {"text": text}
        if event_type == "tool":
            # Arguments are intentionally never persisted or sent back to the browser.
            normalized = {
                "name": str(data.get("name", "assistant tool"))[:80],
                "call_id": str(data.get("call_id", ""))[:128],
                "status": str(data.get("status", "running"))[:32],
                "description": str(data.get("description", "Using an approved local tool."))[:240],
            }
            if self.contains_known_secret_text(normalized):
                raise AssistantUnavailable("sensitive_output_rejected", 502)
            return "tool", normalized
        if event_type == "source":
            if self.contains_known_secret_text(data):
                raise AssistantUnavailable("sensitive_output_rejected", 502)
            url = data.get("url")
            safe_url: str | None = None
            if isinstance(url, str):
                try:
                    safe_url = safe_news_url(url)
                except DomainError:
                    safe_url = None
            title = str(data.get("title", "Source")).strip()[:300] or "Source"
            source_type = str(data.get("source_type", "public"))[:40]
            retrieved = self.now()
            as_of: datetime | None = None
            try:
                raw_retrieved = data.get("retrieved_at")
                if isinstance(raw_retrieved, str):
                    parsed_retrieved = datetime.fromisoformat(raw_retrieved)
                    if parsed_retrieved.tzinfo is not None:
                        retrieved = parsed_retrieved.astimezone(UTC)
            except ValueError:
                pass
            try:
                raw_as_of = data.get("as_of")
                if isinstance(raw_as_of, str):
                    parsed_as_of = datetime.fromisoformat(raw_as_of)
                    if parsed_as_of.tzinfo is not None:
                        as_of = parsed_as_of.astimezone(UTC)
            except ValueError:
                pass
            saved = self.storage.create_source(
                user_id,
                conversation_id,
                turn_id,
                source_type=source_type,
                title=title,
                url=safe_url,
                source_ref=(str(data.get("source_ref"))[:256] if data.get("source_ref") else None),
                retrieved_at=retrieved,
                as_of=as_of,
                metadata={},
            )
            return "source", {
                "source_id": str(saved["id"]),
                "title": title,
                "url": safe_url,
                "source_type": source_type,
                "retrieved_at": str(saved["retrieved_at"]),
                "as_of": saved["as_of"],
            }
        if event_type == "proposed_action":
            action_type = data.get("action_type")
            payload = data.get("payload")
            if (
                not isinstance(action_type, str)
                or action_type not in _ACTION_TYPES
                or not isinstance(payload, Mapping)
            ):
                raise AssistantUnavailable("invalid_runtime_event", 502)
            if self.contains_known_secret_text(payload):
                raise AssistantUnavailable("sensitive_output_rejected", 502)
            action = self.create_action_proposal(
                user_id,
                conversation_id,
                turn_id,
                action_type,
                payload,
                execution_id=execution_id,
            )
            action["context_version"] = str(
                self.storage.get_turn(user_id, conversation_id, turn_id)["context_version"]
            )
            return "proposed_action", action
        if event_type == "private_context_preview":
            if self.contains_known_secret_text(data):
                raise AssistantUnavailable("sensitive_output_rejected", 502)
            return "private_context_preview", {
                "preview_id": str(data.get("preview_id", ""))[:36],
                "query": str(data.get("query", ""))[:1000],
                "reason": str(
                    data.get("reason", "This search includes private workspace information.")
                )[:300],
                "context_version": str(data.get("context_version", ""))[:64],
                "expires_at": str(data.get("expires_at", ""))[:40],
                "confirmation_phrase": str(data.get("confirmation_phrase", ""))[:100],
            }
        if event_type == "webfetch_preview":
            preview_id = data.get("preview_id")
            url = data.get("url")
            context_version = data.get("context_version")
            expires_at = data.get("expires_at")
            phrase = data.get("confirmation_phrase")
            with self._webfetch_waiter_lock:
                waiter = (
                    self._webfetch_waiters.get(preview_id) if isinstance(preview_id, str) else None
                )
            if (
                set(data)
                != {
                    "preview_id",
                    "url",
                    "reason",
                    "context_version",
                    "expires_at",
                    "confirmation_phrase",
                }
                or not isinstance(preview_id, str)
                or re.fullmatch(r"[0-9a-f]{32}", preview_id) is None
                or validate_webfetch_url(url) != url
                or not isinstance(context_version, str)
                or not isinstance(expires_at, str)
                or not isinstance(phrase, str)
                or waiter is None
                or waiter.url != url
                or waiter.context_version != context_version
                or waiter.confirmation_phrase != phrase
                or waiter.expires_at.isoformat() != expires_at
            ):
                raise AssistantUnavailable("invalid_runtime_event", 502)
            if self.contains_known_secret_text(data):
                raise AssistantUnavailable("sensitive_output_rejected", 502)
            return "webfetch_preview", self._webfetch_preview_dto(preview_id, waiter) | {
                "reason": _WEBFETCH_PREVIEW_REASON
            }
        if event_type == "error":
            code = data.get("code")
            safe_code = (
                code
                if isinstance(code, str) and code in _SAFE_ERROR_CODES
                else "worker_unavailable"
            )
            return "error", {"code": safe_code, "message": self._safe_error_message(safe_code)}
        raise AssistantUnavailable("invalid_runtime_event", 502)

    @staticmethod
    def _safe_action_card(action_type: str, payload: Mapping[str, object]) -> dict[str, object]:
        symbol = payload.get("symbol")
        if isinstance(symbol, str):
            symbol = symbol.strip().upper()[:15]
        titles = {
            "watchlist.add": "Add to watchlist",
            "watchlist.remove": "Remove from watchlist",
            "portfolio.add": "Add holding",
            "portfolio.remove": "Remove holding",
            "portfolio.set_quantity": "Change portfolio quantity",
            "forecast.create": "Create a forecast",
            "outcome.record": "Record a forecast outcome",
            "reconstruction.run": "Run historical reconstruction",
            "invitation.create": "Continue in invitation settings",
            "backup.create": "Continue in backup settings",
            "restore.promote": "Continue in restore settings",
            "provider.settings": "Manage assistant provider settings",
            "account.sessions.manage": "Review signed-in sessions",
            "history.export.csv": "Download authorized CSV history",
            "history.export.json": "Download authorized JSON history",
            "theme.set": "Change display theme",
            "filters.apply": "Apply research filters",
            "market.filters.apply": "Apply market filters",
            "market.chart_range.set": "Change chart range",
            "market.columns.set": "Change market table columns",
            "market.refresh": "Refresh market data",
            "notes.set": "Open the browser note controls",
            "notes.clear": "Open the browser note controls",
            "alerts.add": "Add a browser-only price alert",
            "alerts.remove": "Open the browser alert controls",
            "forecast.reopen": "Open saved forecast",
            "market.open": "Open selected market instrument",
        }
        summary = f"{titles[action_type]}" + (f" for {symbol}" if symbol else "")
        changes: list[dict[str, object]] = []
        exact_preview_types = {
            "filters.apply",
            "history.export.csv",
            "history.export.json",
            "market.filters.apply",
            "market.chart_range.set",
            "market.columns.set",
            "market.refresh",
        }
        for key, label in (
            ("symbol", "Instrument"),
            ("asset_type", "Asset type"),
            ("provider", "Provider"),
            ("exchange", "Exchange"),
            ("analysis_kind", "Analysis type"),
            ("submitted_from", "Submitted from"),
            ("submitted_to", "Submitted through"),
            ("model", "Model name or version"),
            ("horizon", "Forecast horizon"),
            ("sort", "Sort"),
            ("page_size", "Rows per page"),
            ("min_price", "Minimum price"),
            ("max_price", "Maximum price"),
            ("min_change", "Minimum percent change"),
            ("max_change", "Maximum percent change"),
            ("min_volume", "Minimum volume"),
            ("quote_field", "Additional quote metric"),
            ("quote_min", "Metric minimum"),
            ("quote_max", "Metric maximum"),
            ("range", "Chart range"),
            ("show_all_columns", "Show all quote columns"),
            ("kind", "List"),
            ("quantity", "Quantity"),
            ("result_id", "Saved result"),
            ("state", "Outcome state"),
            ("observed_close", "Observed close"),
            ("observed_at", "Observed at"),
            ("cutoff", "Reconstruction cutoff"),
            ("interval", "Forecast interval"),
            ("theme", "Theme"),
            ("query", "Search query"),
            ("status", "History status"),
            ("threshold", "Alert threshold"),
            ("note", "Outcome note"),
        ):
            value = payload.get(key)
            if key == "kind" and action_type == "market.refresh":
                label = "Refresh target"
            if key == "interval" and action_type == "forecast.create" and value is None:
                changes.append({"label": label, "after": "Default forecast horizons"})
                continue
            if action_type in exact_preview_types and key in payload:
                if isinstance(value, bool):
                    display = "true" if value else "false"
                elif value == "":
                    display = "(empty; clear this control)"
                else:
                    display = str(value)
                changes.append({"label": label, "after": display})
                continue
            if key == "quantity" and key in payload:
                changes.append(
                    {
                        "label": label,
                        "after": "remove quantity" if value is None else str(value),
                    }
                )
            elif (
                value is not None
                and isinstance(value, str | int | float)
                and len(str(value)) <= (1000 if key == "note" else 500)
            ):
                changes.append({"label": label, "after": str(value)})
        if _APPROVED_QUANTITY_KEY in payload:
            current_quantity = payload[_APPROVED_QUANTITY_KEY]
            changes.insert(
                4,
                {
                    "label": "Current quantity",
                    "after": "not set" if current_quantity is None else str(current_quantity),
                },
            )
        return {"title": titles[action_type], "summary": summary, "changes": changes}

    def create_action_proposal(
        self,
        user_id: int,
        conversation_id: str,
        turn_id: str,
        action_type: str,
        payload: Mapping[str, object],
        *,
        execution_id: str,
    ) -> dict[str, object]:
        """Store one fixed-schema proposal and emit only its display-safe projection."""

        if action_type not in _ACTION_TYPES:
            raise AssistantUnavailable("tool_unavailable", 422)
        safe_payload = self._validate_action_payload(action_type, payload)
        lease = self.storage.execution_lease(execution_id)
        if (
            not lease
            or lease.get("status") != "active"
            or int(lease.get("user_id", 0)) != user_id
            or lease.get("conversation_id") != conversation_id
            or lease.get("turn_id") != turn_id
        ):
            raise AssistantUnavailable("session_revoked", 403)
        if action_type in {"portfolio.remove", "portfolio.set_quantity"}:
            identity = self._resolve_identity(
                str(safe_payload["symbol"]),
                str(safe_payload["asset_type"]),
                str(safe_payload["provider"]),
                str(safe_payload["exchange"]),
            )
            current = next(
                (
                    item
                    for item in self.repository.instrument_list_items(user_id, "portfolio")
                    if item.get("provider") == identity.get("provider")
                    and item.get("canonical_symbol") == identity.get("canonical_symbol")
                    and item.get("asset_type") == identity.get("asset_type")
                ),
                None,
            )
            if current is None:
                raise AssistantStorageConflict("action_target_changed")
            safe_payload[_APPROVED_QUANTITY_KEY] = current.get("quantity")
        if action_type in {
            "invitation.create",
            "backup.create",
            "restore.promote",
            "provider.settings",
        }:
            user_record = self.auth_manager.store.auth_get_user_by_id(user_id)
            if (
                not user_record
                or user_record.get("role") != "admin"
                or not user_record.get("active")
            ):
                raise AssistantUnavailable("not_found", 404)
        record = self.storage.create_action(
            user_id,
            conversation_id,
            turn_id,
            action_type=action_type,
            payload=safe_payload,
            action_version=1,
            session_id=str(lease["session_id"]),
            context_version=str(lease["context_version"]),
            execution_id=execution_id,
            confirmation_phrase="storage binds this confirmation to its generated identifier",
            now=self.now(),
            expires_at=self.now() + timedelta(minutes=5),
        )
        actual_id = str(record["id"])
        card = self._safe_action_card(action_type, safe_payload)
        return {
            "action_id": actual_id,
            "action_type": action_type,
            **card,
            "version": 1,
            "context_version": str(record["context_version"]),
            "expires_at": record["expires_at"],
            "confirmation_phrase": str(record["confirmation_phrase"]),
        }

    @staticmethod
    def _validate_action_payload(
        action_type: str, payload: Mapping[str, object]
    ) -> dict[str, object]:
        """Accept only fields for the named fixed action; model-supplied extras are rejected."""

        schemas: dict[str, frozenset[str]] = {
            "watchlist.add": frozenset({"symbol", "asset_type", "provider", "exchange"}),
            "watchlist.remove": frozenset({"symbol", "asset_type", "provider", "exchange"}),
            "portfolio.add": frozenset(
                {"symbol", "asset_type", "provider", "exchange", "quantity"}
            ),
            "portfolio.remove": frozenset({"symbol", "asset_type", "provider", "exchange"}),
            "portfolio.set_quantity": frozenset(
                {"symbol", "asset_type", "provider", "exchange", "quantity"}
            ),
            "forecast.create": frozenset(
                {"symbol", "asset_type", "provider", "exchange", "interval"}
            ),
            "outcome.record": frozenset(
                {"result_id", "observed_close", "observed_at", "state", "note"}
            ),
            "reconstruction.run": frozenset({"event_id", "cutoff"}),
            "invitation.create": frozenset(),
            "backup.create": frozenset(),
            "restore.promote": frozenset(),
            "provider.settings": frozenset(),
            "account.sessions.manage": frozenset(),
            "history.export.csv": frozenset(
                {
                    "query",
                    "symbol",
                    "asset_type",
                    "status",
                    "analysis_kind",
                    "submitted_from",
                    "submitted_to",
                    "model",
                    "horizon",
                    "sort",
                }
            ),
            "history.export.json": frozenset(
                {
                    "query",
                    "symbol",
                    "asset_type",
                    "status",
                    "analysis_kind",
                    "submitted_from",
                    "submitted_to",
                    "model",
                    "horizon",
                    "sort",
                }
            ),
            "theme.set": frozenset({"theme"}),
            "filters.apply": frozenset(
                {
                    "query",
                    "asset_type",
                    "status",
                    "analysis_kind",
                    "submitted_from",
                    "submitted_to",
                    "model",
                    "horizon",
                    "sort",
                    "page_size",
                }
            ),
            "notes.set": frozenset({"symbol", "asset_type", "provider", "exchange"}),
            "notes.clear": frozenset({"symbol", "asset_type", "provider", "exchange"}),
            "alerts.add": frozenset({"symbol", "asset_type", "provider", "exchange", "threshold"}),
            "alerts.remove": frozenset({"symbol", "asset_type", "provider", "exchange"}),
            "forecast.reopen": frozenset({"event_id", "event_version"}),
            "market.open": frozenset({"symbol", "asset_type", "provider", "exchange"}),
            "market.filters.apply": frozenset(
                {
                    "query",
                    "exchange",
                    "asset_type",
                    "sort",
                    "min_price",
                    "max_price",
                    "min_change",
                    "max_change",
                    "min_volume",
                    "quote_field",
                    "quote_min",
                    "quote_max",
                }
            ),
            "market.chart_range.set": frozenset(
                {"symbol", "asset_type", "provider", "exchange", "range"}
            ),
            "market.columns.set": frozenset({"show_all_columns"}),
            "market.refresh": frozenset({"kind"}),
        }
        allowed = schemas[action_type]
        if set(payload) - allowed:
            raise AssistantUnavailable("invalid_runtime_event", 422)
        if action_type in {"history.export.csv", "history.export.json", "filters.apply"}:
            try:
                return (
                    normalize_history_action_filters(payload)
                    if action_type == "filters.apply"
                    else normalize_history_filters(payload)
                )
            except InvalidFeatureFilter as exc:
                raise AssistantUnavailable("invalid_runtime_event", 422) from exc
        if action_type == "market.filters.apply":
            try:
                return normalize_market_filters(payload)
            except InvalidFeatureFilter as exc:
                raise AssistantUnavailable("invalid_runtime_event", 422) from exc
        if action_type == "market.chart_range.set":
            try:
                return normalize_market_chart_range(payload)
            except InvalidFeatureFilter as exc:
                raise AssistantUnavailable("invalid_runtime_event", 422) from exc
        if action_type == "market.columns.set":
            try:
                return normalize_market_columns(payload)
            except InvalidFeatureFilter as exc:
                raise AssistantUnavailable("invalid_runtime_event", 422) from exc
        if action_type == "market.refresh":
            try:
                return normalize_market_refresh(payload)
            except InvalidFeatureFilter as exc:
                raise AssistantUnavailable("invalid_runtime_event", 422) from exc
        result: dict[str, object] = {}
        for key, value in payload.items():
            if key == "interval" and value is None and action_type == "forecast.create":
                result[key] = None
                continue
            if key in {
                "symbol",
                "asset_type",
                "provider",
                "exchange",
                "state",
                "observed_at",
                "cutoff",
                "note",
                "theme",
                "query",
                "status",
                "event_version",
                "interval",
                "range",
                "kind",
            }:
                maximum = 1000 if key == "note" else 500
                if not isinstance(value, str) or len(value) > maximum:
                    raise AssistantUnavailable("invalid_runtime_event", 422)
                result[key] = value.strip()
            elif key in {"result_id", "event_id"}:
                if type(value) is not int or value < 1:
                    raise AssistantUnavailable("invalid_runtime_event", 422)
                result[key] = value
            elif key in {"quantity", "observed_close"}:
                if value is not None and (
                    type(value) not in {int, float} or not math.isfinite(float(value)) or value < 0
                ):
                    raise AssistantUnavailable("invalid_runtime_event", 422)
                result[key] = value
            elif key == "threshold":
                if (
                    type(value) not in {int, float}
                    or not math.isfinite(float(value))
                    or value <= 0
                    or value > 1_000_000_000
                ):
                    raise AssistantUnavailable("invalid_runtime_event", 422)
                result[key] = float(value)
            elif key == "show_all_columns":
                if type(value) is not bool:
                    raise AssistantUnavailable("invalid_runtime_event", 422)
                result[key] = value
        required = {
            "watchlist.add": {"symbol", "asset_type", "provider", "exchange"},
            "watchlist.remove": {"symbol", "asset_type", "provider", "exchange"},
            "portfolio.add": {"symbol", "asset_type", "provider", "exchange"},
            "portfolio.remove": {"symbol", "asset_type", "provider", "exchange"},
            "portfolio.set_quantity": {"symbol", "asset_type", "provider", "exchange", "quantity"},
            "forecast.create": {"symbol", "asset_type", "provider", "exchange"},
            "outcome.record": {"result_id", "observed_at", "state"},
            "reconstruction.run": {"event_id", "cutoff"},
            "theme.set": {"theme"},
            "filters.apply": {"query"},
            "notes.set": {"symbol", "asset_type", "provider", "exchange"},
            "notes.clear": {"symbol", "asset_type", "provider", "exchange"},
            "alerts.add": {"symbol", "asset_type", "provider", "exchange", "threshold"},
            "alerts.remove": {"symbol", "asset_type", "provider", "exchange"},
            "forecast.reopen": {"event_id", "event_version"},
            "market.open": {"symbol", "asset_type", "provider", "exchange"},
            "market.chart_range.set": {"symbol", "asset_type", "provider", "exchange", "range"},
            "market.columns.set": {"show_all_columns"},
            "market.refresh": {"kind"},
        }.get(action_type, set())
        if not required <= set(result):
            raise AssistantUnavailable("invalid_runtime_event", 422)
        if "asset_type" in result and result["asset_type"] not in {"stock", "etf"}:
            raise AssistantUnavailable("invalid_runtime_event", 422)
        if action_type == "forecast.create":
            interval = result.get("interval")
            if interval is not None and interval not in {
                "5min",
                "daily",
                "weekly",
                "monthly",
                "quarterly",
            }:
                raise AssistantUnavailable("invalid_runtime_event", 422)
            result["interval"] = interval
        instrument_actions = {
            "watchlist.add",
            "watchlist.remove",
            "portfolio.add",
            "portfolio.remove",
            "portfolio.set_quantity",
            "forecast.create",
            "market.open",
            "market.chart_range.set",
            "notes.set",
            "notes.clear",
            "alerts.add",
            "alerts.remove",
        }
        if action_type in instrument_actions:
            symbol = result.get("symbol")
            asset_type = result.get("asset_type")
            if (
                not isinstance(symbol, str)
                or re.fullmatch(r"[A-Z0-9.^-]{1,15}", symbol.upper()) is None
            ):
                raise AssistantUnavailable("invalid_runtime_event", 422)
            if asset_type not in {"stock", "etf"}:
                raise AssistantUnavailable("invalid_runtime_event", 422)
            result["symbol"] = symbol.upper()
            if not isinstance(result.get("provider"), str) or not isinstance(
                result.get("exchange"), str
            ):
                raise AssistantUnavailable("invalid_runtime_event", 422)
            if (
                not 1 <= len(str(result["provider"])) <= 80
                or not 1 <= len(str(result["exchange"])) <= 40
            ):
                raise AssistantUnavailable("invalid_runtime_event", 422)
            if not re.fullmatch(r"[A-Za-z0-9 ._-]+", str(result["provider"])) or not re.fullmatch(
                r"[A-Za-z0-9 ._-]+", str(result["exchange"])
            ):
                raise AssistantUnavailable("invalid_runtime_event", 422)
        if action_type == "theme.set" and result.get("theme") not in {"light", "dark", "system"}:
            raise AssistantUnavailable("invalid_runtime_event", 422)
        if (
            action_type == "forecast.reopen"
            and re.fullmatch(r"[0-9a-f]{64}", str(result.get("event_version", ""))) is None
        ):
            raise AssistantUnavailable("invalid_runtime_event", 422)
        if action_type in {"outcome.record", "reconstruction.run"}:
            try:
                timestamp = datetime.fromisoformat(
                    str(result.get("observed_at", result.get("cutoff", "")))
                )
            except ValueError as exc:
                raise AssistantUnavailable("invalid_runtime_event", 422) from exc
            if timestamp.tzinfo is None:
                raise AssistantUnavailable("invalid_runtime_event", 422)
        if action_type == "outcome.record" and result.get("note"):
            AssistantService._validate_prompt(str(result["note"]))
        return result

    @staticmethod
    def _validate_persisted_action_payload(
        action_type: str, payload: Mapping[str, object]
    ) -> dict[str, object]:
        """Validate immutable proposals, including server-only compare-and-swap state."""

        raw = dict(payload)
        expected_quantity = raw.pop(_APPROVED_QUANTITY_KEY, None)
        has_expected_quantity = _APPROVED_QUANTITY_KEY in payload
        safe = AssistantService._validate_action_payload(action_type, raw)
        if action_type in {"portfolio.remove", "portfolio.set_quantity"}:
            if not has_expected_quantity or (
                expected_quantity is not None
                and (
                    type(expected_quantity) not in {int, float}
                    or not math.isfinite(float(expected_quantity))
                    or expected_quantity < 0
                )
            ):
                raise AssistantUnavailable("invalid_runtime_event", 422)
            safe[_APPROVED_QUANTITY_KEY] = expected_quantity
        elif has_expected_quantity:
            raise AssistantUnavailable("invalid_runtime_event", 422)
        return safe

    def dispatch_confirmed_action(
        self,
        user_id: int,
        action_type: str,
        payload: Mapping[str, object],
        *,
        confirmed_by: AuthContext,
        authorization_check: Callable[[], AuthContext] | None = None,
    ) -> tuple[str, dict[str, object]]:
        """Execute only narrow app-owned mutations; privileged flows hand off to secure UI."""

        def authorize() -> AuthContext:
            current = authorization_check() if authorization_check is not None else confirmed_by
            if current.user.id != user_id or not self.can_access(current):
                raise AssistantUnavailable("session_revoked", 403)
            return current

        def before_persist() -> None:
            authorize()

        confirmed_by = authorize()
        if confirmed_by.user.id != user_id or not self.can_access(confirmed_by):
            raise AssistantUnavailable("not_found", 404)
        safe = self._validate_persisted_action_payload(action_type, payload)
        if action_type in {
            "invitation.create",
            "backup.create",
            "restore.promote",
            "provider.settings",
        }:
            self.require_admin(confirmed_by, step_up=True)
            # The existing settings pages collect identity/backup fields and fresh TOTP proof.
            destination = {
                "invitation.create": "/admin#invitations",
                "backup.create": "/admin#backups",
                "restore.promote": "/admin#restore",
                "provider.settings": "/admin#assistant-providers",
            }[action_type]
            return "handed_off", {
                "message": "Continue in the protected administrator screen.",
                "destination": destination,
            }
        if action_type == "account.sessions.manage":
            authorize()
            return "handed_off", {
                "message": "Continue in the protected account session screen.",
                "destination": "/account#sessions",
            }
        if action_type == "history.export.csv":
            authorize()
            query = urlencode(history_export_query(safe))
            return "handed_off", {
                "message": "The authorized CSV history export is ready to download.",
                "destination": f"/api/v1/history-export.csv?{query}",
            }
        if action_type == "history.export.json":
            authorize()
            query = urlencode(history_export_query(safe))
            return "handed_off", {
                "message": "The authorized JSON history export is ready to download.",
                "destination": f"/api/v1/history-export.json?{query}",
            }
        browser_action_types = {
            "theme.set",
            "filters.apply",
            "market.filters.apply",
            "market.chart_range.set",
            "market.columns.set",
            "market.refresh",
        }
        if action_type in browser_action_types:
            authorize()
            result: dict[str, object] = {
                "message": "The confirmed browser action is ready to apply on this page.",
                "browser_action": {"type": action_type, "payload": safe},
            }
            if action_type == "filters.apply":
                result["destination"] = "/#history-heading"
                cast(dict[str, object], result["browser_action"])["destination"] = {
                    "kind": "current-page",
                    "route": "/",
                }
            elif action_type.startswith("market."):
                cast(dict[str, object], result["browser_action"])["destination"] = {
                    "kind": "current-page",
                    "route": "/tools/markets",
                }
            return "handed_off", result
        if action_type in {"notes.set", "notes.clear", "alerts.add", "alerts.remove"}:
            self._resolve_identity(
                str(safe["symbol"]),
                str(safe["asset_type"]),
                str(safe["provider"]),
                str(safe["exchange"]),
            )
            authorize()
            if action_type in {"notes.set", "notes.clear", "alerts.remove"}:
                focus = "notes-heading" if action_type.startswith("notes.") else "alerts-heading"
                bridge_payload = {
                    key: safe[key] for key in ("symbol", "asset_type", "provider", "exchange")
                }
                return "handed_off", {
                    "message": (
                        "The existing browser controls are open. No note or alert was changed."
                    ),
                    "browser_action": {
                        "type": action_type,
                        "payload": bridge_payload,
                        "destination": {
                            "kind": "current-page",
                            "route": "/tools/live-trading",
                            "focus": focus,
                        },
                    },
                }
            return "handed_off", {
                "message": (
                    "The price alert was submitted to this browser's existing alert handler."
                ),
                "browser_action": {
                    "type": action_type,
                    "payload": safe,
                    "destination": {
                        "kind": "current-page",
                        "route": "/tools/live-trading",
                        "handler": "alerts.add",
                    },
                },
            }
        if action_type == "forecast.reopen":
            event_id = int(safe["event_id"])
            saved = self.repository.reconstruction(user_id, event_id)
            if not isinstance(saved, Mapping) or not isinstance(saved.get("event"), Mapping):
                raise AssistantStorageNotFound()
            if not hmac.compare_digest(self._digest(saved["event"]), str(safe["event_version"])):
                raise AssistantStorageConflict("action_target_changed")
            authorize()
            return "handed_off", {
                "message": "Open the owner-validated saved forecast.",
                "destination": f"/?event_id={event_id}#result-section",
            }
        if action_type == "market.open":
            identity = self._resolve_identity(
                str(safe["symbol"]),
                str(safe["asset_type"]),
                str(safe["provider"]),
                str(safe["exchange"]),
            )
            authorize()
            destination = "/tools/markets?" + "&".join(
                f"{key}={quote(str(value), safe='')}"
                for key, value in (
                    ("symbol", identity["canonical_symbol"]),
                    ("asset_type", identity["asset_type"]),
                    ("provider", identity["provider"]),
                    ("exchange", identity["exchange"]),
                )
            )
            return "handed_off", {
                "message": "Open the validated instrument on the markets page.",
                "destination": destination,
            }
        if action_type == "watchlist.add":
            identity = self._resolve_identity(
                str(safe["symbol"]),
                str(safe["asset_type"]),
                str(safe["provider"]),
                str(safe["exchange"]),
            )
            authorize()
            self.repository.add_instrument_list_item(
                "watchlist",
                owner_user_id=user_id,
                provider=str(identity["provider"]),
                canonical_symbol=str(identity["canonical_symbol"]),
                asset_type=str(identity["asset_type"]),
                exchange=str(identity.get("exchange", "")),
                display_name=str(identity.get("display_name", identity["canonical_symbol"])),
                added_at=self.now(),
            )
            return "applied", {"message": "The instrument was added to the watchlist."}
        if action_type == "watchlist.remove":
            identity = self._resolve_identity(
                str(safe["symbol"]),
                str(safe["asset_type"]),
                str(safe["provider"]),
                str(safe["exchange"]),
            )
            authorize()
            removed = self.repository.remove_instrument_list_item(
                "watchlist",
                owner_user_id=user_id,
                provider=str(identity["provider"]),
                canonical_symbol=str(identity["canonical_symbol"]),
                asset_type=str(identity["asset_type"]),
            )
            if not removed:
                raise AssistantStorageConflict("action_target_changed")
            return "applied", {"message": "The instrument was removed from the watchlist."}
        if action_type == "portfolio.add":
            identity = self._resolve_identity(
                str(safe["symbol"]),
                str(safe["asset_type"]),
                str(safe["provider"]),
                str(safe["exchange"]),
            )
            authorize()
            try:
                self.repository.add_instrument_list_item(
                    "portfolio",
                    owner_user_id=user_id,
                    provider=str(identity["provider"]),
                    canonical_symbol=str(identity["canonical_symbol"]),
                    asset_type=str(identity["asset_type"]),
                    exchange=str(identity.get("exchange", "")),
                    display_name=str(identity.get("display_name", identity["canonical_symbol"])),
                    added_at=self.now(),
                    quantity=cast(float | None, safe.get("quantity")),
                )
            except ValueError as exc:
                # A concurrent list edit may invalidate the pre-confirmation target check.
                raise AssistantStorageConflict("action_target_changed") from exc
            return "applied", {"message": "The instrument was added to the portfolio."}
        if action_type == "portfolio.remove":
            identity = self._resolve_identity(
                str(safe["symbol"]),
                str(safe["asset_type"]),
                str(safe["provider"]),
                str(safe["exchange"]),
            )
            authorize()
            removed = self.repository.remove_instrument_list_item(
                "portfolio",
                owner_user_id=user_id,
                provider=str(identity["provider"]),
                canonical_symbol=str(identity["canonical_symbol"]),
                asset_type=str(identity["asset_type"]),
                expected_quantity=cast(float | None, safe[_APPROVED_QUANTITY_KEY]),
            )
            if not removed:
                raise AssistantStorageConflict("action_target_changed")
            return "applied", {"message": "The instrument was removed from the portfolio."}
        if action_type == "portfolio.set_quantity":
            identity = self._resolve_identity(
                str(safe["symbol"]),
                str(safe["asset_type"]),
                str(safe["provider"]),
                str(safe["exchange"]),
            )
            authorize()
            updated = self.repository.set_instrument_list_item_holding(
                "portfolio",
                owner_user_id=user_id,
                provider=str(identity["provider"]),
                canonical_symbol=str(identity["canonical_symbol"]),
                asset_type=str(identity["asset_type"]),
                quantity=cast(float | None, safe["quantity"]),
                expected_quantity=cast(float | None, safe[_APPROVED_QUANTITY_KEY]),
            )
            if not updated:
                raise AssistantStorageConflict("action_target_changed")
            return "applied", {"message": "The portfolio quantity was updated."}
        if action_type == "forecast.create":
            self._resolve_identity(
                str(safe["symbol"]),
                str(safe["asset_type"]),
                str(safe["provider"]),
                str(safe["exchange"]),
            )
            authorize()
            result = self.forecast_service.search(
                str(safe["symbol"]),
                str(safe["asset_type"]),
                cast(str | None, safe.get("interval")),
                owner_user_id=user_id,
                before_persist=before_persist,
            )
            event = result.get("event") if isinstance(result, Mapping) else None
            if not isinstance(event, Mapping):
                raise AssistantStorageError("forecast service returned an invalid result")
            return "applied", {"message": "A new forecast was saved.", "event_id": event.get("id")}
        if action_type == "outcome.record":
            observed_at = datetime.fromisoformat(str(safe["observed_at"]))
            authorize()
            result = self.forecast_service.append_outcome(
                int(safe["result_id"]),
                cast(float | None, safe.get("observed_close")),
                observed_at,
                str(safe["state"]),
                str(safe.get("note", "")),
                owner_user_id=user_id,
                before_persist=before_persist,
            )
            if result is None:
                raise AssistantStorageNotFound()
            return "applied", {"message": "The forecast outcome was recorded."}
        if action_type == "reconstruction.run":
            cutoff = datetime.fromisoformat(str(safe["cutoff"]))
            authorize()
            result = self.forecast_service.fresh_historical_reconstruction(
                int(safe["event_id"]),
                cutoff,
                owner_user_id=user_id,
                before_persist=authorize,
            )
            if result is None:
                raise AssistantStorageNotFound()
            return "applied", {"message": "Historical reconstruction was saved."}
        raise AssistantUnavailable("tool_unavailable", 422)

    def _resolve_identity(
        self, symbol: str, asset_type: str, provider: str, exchange: str
    ) -> Mapping[str, object]:
        normalized = symbol.strip().upper()
        lookup = self.forecast_service.lookup(normalized, 1)
        items = lookup.get("items", []) if isinstance(lookup, Mapping) else []
        identity = next(
            (
                item
                for item in items
                if isinstance(item, Mapping)
                and item.get("canonical_symbol") == normalized
                and item.get("asset_type") == asset_type
                and item.get("provider") == provider
                and item.get("exchange") == exchange
            ),
            None,
        )
        if identity is None:
            raise AssistantStorageConflict("action_target_changed")
        return identity

    def validate_execution_session(self, lease: Mapping[str, object]) -> bool:
        """Revalidate the persisted auth session, current role, and canary on each MCP call."""

        token_hash = lease.get("session_token_hash")
        session_id = lease.get("session_id")
        user_id = lease.get("user_id")
        if (
            not isinstance(token_hash, str)
            or type(user_id) is not int
            or not isinstance(session_id, str)
        ):
            return False
        return (
            self._live_auth_context(
                user_id=user_id,
                session_id=session_id,
                token_hash=token_hash,
            )
            is not None
        )

    def _assistant_session_is_live(self, user_id: int, session_id: str, token_hash: str) -> bool:
        """Return whether the same authenticated assistant session still has access."""

        current = self._live_auth_context(
            user_id=user_id,
            session_id=session_id,
            token_hash=token_hash,
        )
        return bool(current is not None and self.can_access(current))

    def _live_auth_context(
        self,
        *,
        user_id: int,
        session_id: str,
        token_hash: str,
        expected_csrf_hash: str | None = None,
    ) -> AuthContext | None:
        """Resolve current session, factor, and account state without trusting a cached context."""

        try:
            record = self.repository.get_session(token_hash, now=self.now(), touch=True)
            if (
                not record
                or record.get("session_id") != session_id
                or int(record.get("user_id", 0)) != user_id
                or (
                    expected_csrf_hash is not None
                    and (
                        not isinstance(record.get("csrf_token_hash"), str)
                        or not hmac.compare_digest(
                            str(record["csrf_token_hash"]), expected_csrf_hash
                        )
                    )
                )
            ):
                return None
            if record.get("auth_method") != "github" or record.get("mfa_method") != "totp":
                return None
            verified_at = datetime.fromisoformat(str(record.get("mfa_verified_at", "")))
            if verified_at.tzinfo is None or verified_at > self.now():
                return None
            factor = self.auth_manager.store.auth_get_totp_factor(user_id)
            if not factor or factor.get("id", factor.get("factor_id")) != record.get(
                "mfa_factor_id"
            ):
                return None
            user_record = self.auth_manager.store.auth_get_user_by_id(user_id)
            if not user_record:
                return None
            user = self.auth_manager.user_from_record(user_record)
            context = AuthContext(
                user=user,
                session_id=session_id,
                token_hash=token_hash,
                csrf_token_hash=str(record.get("csrf_token_hash", "")),
                auth_method="github",
                mfa_method="totp",
                mfa_verified_at=(
                    datetime.fromisoformat(str(record["mfa_verified_at"]))
                    if record.get("mfa_verified_at")
                    else None
                ),
                mfa_factor_id=(
                    int(record["mfa_factor_id"]) if record.get("mfa_factor_id") else None
                ),
            )
            return context if self.can_access(context) and bool(user.active) else None
        except Exception:
            return None

    def _require_live_action_context(
        self,
        original: AuthContext,
        *,
        requires_admin_step_up: bool,
    ) -> AuthContext:
        """Reject action execution if its issuing session or privileges changed mid-request."""

        current = self._live_auth_context(
            user_id=original.user.id,
            session_id=original.session_id,
            token_hash=original.token_hash,
            expected_csrf_hash=original.csrf_token_hash,
        )
        if current is None:
            raise AssistantUnavailable("session_revoked", 403)
        if requires_admin_step_up:
            self.require_admin(current, step_up=True)
        return current

    def _execution_current(
        self, user_id: int, execution_id: str, model_id: str, policy_version: str
    ) -> bool:
        """Fail closed between every runtime event if owner session or consent was revoked."""

        lease = self.storage.execution_lease(execution_id)
        if not lease or lease.get("status") != "active" or int(lease.get("user_id", 0)) != user_id:
            return False
        if not self.validate_execution_session(lease):
            return False
        try:
            turn = self.storage.get_turn(
                user_id, str(lease["conversation_id"]), str(lease["turn_id"])
            )
        except AssistantStorageError:
            return False
        return (
            turn.get("status") == "running"
            and turn.get("model_id") == model_id
            and turn.get("policy_version") == policy_version
            and self.policy_still_authorized(user_id, model_id, policy_version)
        )

    def policy_still_authorized(self, user_id: int, model_id: str, policy_version: str) -> bool:
        """Invalidate an execution as soon as provider policy or explicit consent changes."""

        try:
            policy = self.policy(model_id, owner_id=user_id)
            consent = self.storage.current_consent(user_id, model_id, policy_version)
            return (
                policy.policy_version == policy_version
                and bool(consent and consent.get("accepted_terms"))
                and (not policy.training or bool(consent and consent.get("data_collection_opt_in")))
                and (
                    not consent
                    or not consent.get("data_collection_opt_in")
                    or policy.data_collection_allowed
                )
            )
        except (AssistantUnavailable, AssistantStorageError):
            return False


class suppress_runtime_errors:
    """Narrow exception suppressor used only while revoking already-owned turn leases."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        return True
