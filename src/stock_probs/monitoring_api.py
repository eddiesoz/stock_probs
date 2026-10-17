"""Expose bounded, owner-scoped monitoring reads and safe state changes."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
)

from .auth import AuthContext
from .auth_write_guard import AuthWriteAuthorizationError
from .monitoring_domain import MonitoringError, price
from .monitoring_store import (
    MAX_CURSOR_BYTES,
    MAX_PAGE_SIZE,
    MonitoringArmingUnavailableError,
    MonitoringConflictError,
    MonitoringStore,
    MonitoringStoreError,
)

UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

SymbolInput = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=80),
]
PriceInput = Annotated[StrictStr, Field(min_length=1, max_length=64)]
RevisionInput = Annotated[StrictInt, Field(ge=1, le=2**63 - 1)]
OwnerResolver = Callable[[Request], int | None]
UtcClock = Callable[[], datetime]


def _request_auth_context(request: Request) -> AuthContext | None:
    """Return only the trusted middleware snapshot; never re-read a cookie after body parsing."""
    context = getattr(request.state, "auth_context", None)
    return context if isinstance(context, AuthContext) else None


class _RequestModel(BaseModel):
    """Reject undocumented request fields so clients cannot assert server-owned facts."""

    model_config = ConfigDict(extra="forbid")


class AlertConfiguration(_RequestModel):
    """A bounded, client-editable alert rule without provider observation fields."""

    symbol: SymbolInput
    currency: Annotated[StrictStr, Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")]
    threshold: PriceInput
    direction: Literal["above", "below"]
    repeating: StrictBool

    @field_validator("symbol")
    @classmethod
    def printable_symbol(cls, value: str) -> str:
        """Keep instrument input in the provider's bounded ASCII identity space."""
        if not value.isascii() or not value.isprintable():
            raise ValueError("Use a printable ASCII instrument symbol.")
        return value

    @field_validator("threshold")
    @classmethod
    def finite_positive_threshold(cls, value: str) -> str:
        """Reject malformed or unbounded decimal thresholds before persistence."""
        try:
            price(value)
        except MonitoringError as error:
            raise ValueError("Use a positive finite decimal threshold.") from error
        return value


class AlertCreateRequest(AlertConfiguration):
    """A create request; arming snapshots remain server-owned and are not accepted here."""


class AlertEditRequest(AlertConfiguration):
    """A compare-and-swap edit request for a currently paused rule."""

    expected_revision: RevisionInput


class RevisionRequest(_RequestModel):
    """A revision-bound state transition request."""

    expected_revision: RevisionInput


class NotificationReadRequest(_RequestModel):
    """A revision-bound notification read-state update."""

    expected_revision: RevisionInput
    is_read: StrictBool


class PreferencesRequest(_RequestModel):
    """A bounded notification preference update without an address or owner identifier."""

    expected_revision: Annotated[StrictInt, Field(ge=0, le=2**63 - 1)]
    alert_email: StrictBool
    digest_email: StrictBool
    digest_time: (
        Annotated[StrictStr, Field(min_length=5, max_length=5, pattern=r"^\d{2}:\d{2}$")] | None
    ) = None
    digest_timezone: Annotated[StrictStr, Field(min_length=1, max_length=64)] | None = None

    @field_validator("digest_timezone")
    @classmethod
    def known_timezone(cls, value: str | None) -> str | None:
        """Require a timezone known to the local IANA timezone database."""
        if value is None:
            return value
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("Use a valid timezone name.") from error
        return value


class _ResponseModel(BaseModel):
    """Keep response projections closed and omit internal persistence fields."""

    model_config = ConfigDict(extra="forbid")


class AlertConfigView(_ResponseModel):
    """Public alert configuration fields."""

    symbol: Annotated[StrictStr, Field(min_length=1, max_length=80)]
    currency: Annotated[StrictStr, Field(min_length=3, max_length=3)]
    threshold: PriceInput
    direction: Literal["above", "below"]
    repeating: StrictBool


class ObservationView(_ResponseModel):
    """A bounded, provider-labelled observation recorded for the owner."""

    symbol: Annotated[StrictStr, Field(min_length=1, max_length=80)]
    currency: Annotated[StrictStr, Field(min_length=3, max_length=3)]
    price: PriceInput
    provider: Annotated[StrictStr, Field(min_length=1, max_length=80)]
    observed_at: Annotated[StrictStr, Field(min_length=1, max_length=40)]


class AlertView(_ResponseModel):
    """Owner-facing alert state with baseline readiness distinguished from intent."""

    id: Annotated[StrictStr, Field(min_length=36, max_length=36, pattern=UUID_PATTERN)]
    revision: RevisionInput
    monitor_revision: RevisionInput
    enabled: StrictBool
    configured_enabled: StrictBool
    baseline_ready: StrictBool
    config: AlertConfigView
    arm_generation: Annotated[StrictInt, Field(ge=1, le=2**63 - 1)]
    arm_snapshot_generation: Annotated[StrictInt, Field(ge=1, le=2**63 - 1)] | None
    arm_snapshot_requested_at: Annotated[StrictStr, Field(max_length=40)] | None
    arm_snapshot_received_at: Annotated[StrictStr, Field(max_length=40)] | None
    last_side: Annotated[StrictInt, Field(ge=-1, le=1)] | None
    ready: StrictBool
    last_observed_at: Annotated[StrictStr, Field(max_length=40)] | None
    last_observation: ObservationView | None
    last_check_at: Annotated[StrictStr, Field(max_length=40)] | None
    last_success_at: Annotated[StrictStr, Field(max_length=40)] | None
    state: Literal["arming", "watching", "paused", "triggered", "unavailable"]
    created_at: Annotated[StrictStr, Field(min_length=1, max_length=40)]
    updated_at: Annotated[StrictStr, Field(min_length=1, max_length=40)]


class AlertPage(_ResponseModel):
    """A bounded owner-scoped alert page."""

    items: list[AlertView] = Field(max_length=MAX_PAGE_SIZE)
    next_cursor: Annotated[StrictStr, Field(max_length=MAX_CURSOR_BYTES)] | None


class PriceAlertNotificationPayload(_ResponseModel):
    """Only the public crossing facts are projected from a stored notification payload."""

    alert_id: Annotated[StrictStr, Field(min_length=36, max_length=36, pattern=UUID_PATTERN)]
    generation: Annotated[StrictInt, Field(ge=1, le=2**63 - 1)]
    symbol: Annotated[StrictStr, Field(min_length=1, max_length=80)]
    currency: Annotated[StrictStr, Field(min_length=3, max_length=3)]
    threshold: PriceInput
    direction: Literal["above", "below"]
    price: PriceInput
    provider: Annotated[StrictStr, Field(min_length=1, max_length=80)]
    observed_at: Annotated[StrictStr, Field(min_length=1, max_length=40)]

    @field_validator("threshold", "price")
    @classmethod
    def finite_positive_price(cls, value: str) -> str:
        """Reject invalid persisted prices instead of projecting malformed state."""
        try:
            price(value)
        except MonitoringError as error:
            raise ValueError("Stored notification price is invalid.") from error
        return value


class NotificationView(_ResponseModel):
    """A safe JSON notification without address, delivery or transport state."""

    id: Annotated[StrictStr, Field(min_length=36, max_length=36, pattern=UUID_PATTERN)]
    kind: Literal["price_alert"]
    payload: PriceAlertNotificationPayload
    is_read: StrictBool
    revision: RevisionInput
    created_at: Annotated[StrictStr, Field(min_length=1, max_length=40)]


class NotificationPage(_ResponseModel):
    """A bounded owner-scoped notification page."""

    items: list[NotificationView] = Field(max_length=MAX_PAGE_SIZE)
    next_cursor: Annotated[StrictStr, Field(max_length=MAX_CURSOR_BYTES)] | None


class PreferencesView(_ResponseModel):
    """A safe preference projection that never includes address material or identifiers."""

    revision: Annotated[StrictInt, Field(ge=0, le=2**63 - 1)]
    alert_email: StrictBool
    digest_email: StrictBool
    digest_time: Annotated[StrictStr, Field(min_length=5, max_length=5)]
    digest_timezone: Annotated[StrictStr, Field(min_length=1, max_length=64)]
    address_configured: StrictBool
    updated_at: Annotated[StrictStr, Field(max_length=40)] | None


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    """Return the shared safe API error envelope without persistence details."""
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=status_code,
    )


def _alert_view(value: Mapping[str, object]) -> AlertView:
    """Remove internal owner fields and distinguish an accepted baseline from arming intent."""
    generation = value.get("arm_generation")
    snapshot_generation = value.get("arm_snapshot_generation")
    baseline_ready = (
        type(generation) is int
        and generation > 0
        and type(snapshot_generation) is int
        and snapshot_generation == generation
    )
    state = value.get("check_state")
    return AlertView.model_validate(
        {
            "id": value.get("id"),
            "revision": value.get("revision"),
            "monitor_revision": value.get("monitor_revision"),
            "enabled": bool(value.get("enabled")) and baseline_ready and state == "watching",
            "configured_enabled": value.get("configured_enabled"),
            "baseline_ready": baseline_ready,
            "config": value.get("config"),
            "arm_generation": generation,
            "arm_snapshot_generation": snapshot_generation,
            "arm_snapshot_requested_at": value.get("arm_snapshot_requested_at"),
            "arm_snapshot_received_at": value.get("arm_snapshot_received_at"),
            "last_side": value.get("last_side"),
            "ready": value.get("ready"),
            "last_observed_at": value.get("last_observed_at"),
            "last_observation": value.get("last_observation"),
            "last_check_at": value.get("last_check_at"),
            "last_success_at": value.get("last_success_at"),
            "state": state,
            "created_at": value.get("created_at"),
            "updated_at": value.get("updated_at"),
        }
    )


def _notification_view(value: Mapping[str, object]) -> NotificationView:
    """Project only the typed crossing fields and strip unrecognized stored payload keys."""
    payload = value.get("payload")
    if value.get("kind") != "price_alert" or not isinstance(payload, Mapping):
        raise MonitoringStoreError("This notification kind is not available in this API version.")
    fields = (
        "alert_id",
        "generation",
        "symbol",
        "currency",
        "threshold",
        "direction",
        "price",
        "provider",
        "observed_at",
    )
    safe_payload = {field: payload.get(field) for field in fields}
    return NotificationView.model_validate(
        {
            "id": value.get("id"),
            "kind": value.get("kind"),
            "payload": safe_payload,
            "is_read": value.get("is_read"),
            "revision": value.get("revision"),
            "created_at": value.get("created_at"),
        }
    )


def _preferences_view(value: Mapping[str, object]) -> PreferencesView:
    """Omit opaque address IDs and raw notification addresses from the HTTP response."""
    return PreferencesView.model_validate(
        {
            "revision": value.get("revision"),
            "alert_email": value.get("alert_email"),
            "digest_email": value.get("digest_email"),
            "digest_time": value.get("digest_time"),
            "digest_timezone": value.get("digest_timezone"),
            "address_configured": value.get("address_id") is not None,
            "updated_at": value.get("updated_at"),
        }
    )


def _safe_now(clock: UtcClock) -> datetime:
    """Normalize the injected application clock and reject a naive timestamp."""
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("The monitoring clock must return an aware timestamp.")
    return value.astimezone(UTC)


def _is_canonical_uuid(value: str) -> bool:
    """Recognize lowercase hyphenated UUIDs used by store idempotency contracts."""
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def create_monitoring_router(
    store: MonitoringStore,
    owner_resolver: OwnerResolver,
    clock: UtcClock | None = None,
    *,
    arm_available: Callable[[], bool] | None = None,
    email_available: Callable[[], bool] | None = None,
) -> APIRouter:
    """Create an isolated monitoring router with explicit authentication and storage seams.

    New and resumed rules wait in the persisted arming state. Only the scheduler's leased,
    generation-bound initial observation can make a rule watch for subsequent crossings.
    """
    if not isinstance(store, MonitoringStore):
        raise TypeError("store must be a MonitoringStore")
    if not callable(owner_resolver):
        raise TypeError("owner_resolver must be callable")
    selected_clock = (lambda: datetime.now(UTC)) if clock is None else clock
    can_arm: Callable[[], bool] = (lambda: False) if arm_available is None else arm_available
    can_email: Callable[[], bool] = (lambda: False) if email_available is None else email_available

    def email_is_available() -> bool:
        """Treat a broken availability probe as unavailable without blocking opt-out."""
        try:
            return can_email() is True
        except Exception:
            return False

    router = APIRouter(prefix="/api/v1", tags=["monitoring"])

    def owner_for_request(request: Request) -> int | None:
        """Trust only the owner identity returned by the injected session resolver."""
        owner = owner_resolver(request)
        return owner if type(owner) is int and owner > 0 else None

    @router.get("/alerts", response_model=AlertPage)
    def list_alerts(
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
        cursor: Annotated[str | None, Query(max_length=MAX_CURSOR_BYTES)] = None,
        owner: int | None = Depends(owner_for_request),
    ) -> AlertPage | JSONResponse:
        """List only the authenticated owner's alerts using bounded cursor pagination."""
        if owner is None:
            return _error(401, "AUTHENTICATION_REQUIRED", "Sign in to view alerts.")
        try:
            page = store.list_alerts(owner, limit=limit, cursor=cursor)
            return AlertPage(
                items=[_alert_view(item) for item in page["items"]],
                next_cursor=page["next_cursor"],
            )
        except MonitoringStoreError:
            return _error(422, "INVALID_PAGE", "The alert page request is invalid.")
        except sqlite3.Error:
            return _error(503, "MONITORING_UNAVAILABLE", "Monitoring data is unavailable.")

    @router.post("/alerts", response_model=AlertView, status_code=201)
    def create_alert(
        payload: AlertCreateRequest,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=36, max_length=36)
        ],
        request: Request,
        owner: int | None = Depends(owner_for_request),
    ) -> JSONResponse:
        """Persist the rule and its initial-snapshot job together, without triggering it."""
        if owner is None:
            return _error(401, "AUTHENTICATION_REQUIRED", "Sign in to manage alerts.")
        if not _is_canonical_uuid(idempotency_key):
            return _error(422, "INVALID_IDEMPOTENCY_KEY", "Use a canonical idempotency key.")
        try:
            saved = store.create_alert(
                owner,
                idempotency_key,
                payload.model_dump(),
                _safe_now(selected_clock),
                allow_new_creation=can_arm(),
                auth_context=_request_auth_context(request),
            )
            return JSONResponse(
                _alert_view(saved).model_dump(), status_code=200 if saved["replayed"] else 201
            )
        except AuthWriteAuthorizationError as error:
            return _error(error.status_code, error.code, error.message)
        except MonitoringConflictError:
            return _error(409, "IDEMPOTENCY_CONFLICT", "Use the original request for this key.")
        except MonitoringArmingUnavailableError:
            return _error(503, "MONITORING_ARM_UNAVAILABLE", "The alert scheduler is unavailable.")
        except MonitoringStoreError:
            return _error(422, "INVALID_ALERT", "The alert could not be created.")
        except sqlite3.Error:
            return _error(503, "MONITORING_UNAVAILABLE", "Monitoring data is unavailable.")

    @router.get("/alerts/{alert_id}", response_model=AlertView)
    def get_alert(
        alert_id: Annotated[str, Path(min_length=36, max_length=36, pattern=UUID_PATTERN)],
        owner: int | None = Depends(owner_for_request),
    ) -> AlertView | JSONResponse:
        """Return one alert only when it belongs to the authenticated owner."""
        if owner is None:
            return _error(401, "AUTHENTICATION_REQUIRED", "Sign in to view alerts.")
        try:
            return _alert_view(store.get_alert(owner, alert_id))
        except MonitoringStoreError:
            return _error(404, "ALERT_NOT_FOUND", "The alert is unavailable.")
        except sqlite3.Error:
            return _error(503, "MONITORING_UNAVAILABLE", "Monitoring data is unavailable.")

    @router.patch("/alerts/{alert_id}", response_model=AlertView)
    def edit_alert(
        payload: AlertEditRequest,
        alert_id: Annotated[str, Path(min_length=36, max_length=36, pattern=UUID_PATTERN)],
        request: Request,
        owner: int | None = Depends(owner_for_request),
    ) -> AlertView | JSONResponse:
        """CAS-edit a rule; active changes wait for a new leased initial snapshot."""
        if owner is None:
            return _error(401, "AUTHENTICATION_REQUIRED", "Sign in to manage alerts.")
        try:
            current = store.get_alert(owner, alert_id)
            if current["revision"] != payload.expected_revision:
                return _error(409, "REVISION_CONFLICT", "Reload the alert before saving it.")
            if current["check_state"] != "paused" and not can_arm():
                return _error(
                    503,
                    "MONITORING_ARM_UNAVAILABLE",
                    "The alert scheduler is unavailable; pause the alert before editing it.",
                )
            saved = store.edit_alert(
                owner,
                alert_id,
                payload.expected_revision,
                payload.model_dump(exclude={"expected_revision"}),
                _safe_now(selected_clock),
                auth_context=_request_auth_context(request),
            )
            return _alert_view(saved)
        except AuthWriteAuthorizationError as error:
            return _error(error.status_code, error.code, error.message)
        except MonitoringConflictError:
            return _error(409, "REVISION_CONFLICT", "Reload the alert before saving it.")
        except MonitoringStoreError:
            return _error(404, "ALERT_NOT_FOUND", "The alert is unavailable.")
        except sqlite3.Error:
            return _error(503, "MONITORING_UNAVAILABLE", "Monitoring data is unavailable.")

    @router.delete("/alerts/{alert_id}")
    def delete_alert(
        alert_id: Annotated[str, Path(min_length=36, max_length=36, pattern=UUID_PATTERN)],
        expected_revision: Annotated[int, Query(ge=1, le=2**63 - 1)],
        owner: int | None = Depends(owner_for_request),
    ) -> JSONResponse:
        """Keep deletion unavailable until the store can preserve immutable history."""
        if owner is None:
            return _error(401, "AUTHENTICATION_REQUIRED", "Sign in to manage alerts.")
        del alert_id, expected_revision
        return _error(
            503,
            "MONITORING_DELETE_UNAVAILABLE",
            "Alert deletion is unavailable until it can preserve monitoring history safely.",
        )

    @router.post("/alerts/{alert_id}/pause", response_model=AlertView)
    def pause_alert(
        alert_id: Annotated[str, Path(min_length=36, max_length=36, pattern=UUID_PATTERN)],
        payload: RevisionRequest,
        request: Request,
        owner: int | None = Depends(owner_for_request),
    ) -> AlertView | JSONResponse:
        """Pause an owner-scoped alert through the store's revision compare-and-swap."""
        if owner is None:
            return _error(401, "AUTHENTICATION_REQUIRED", "Sign in to manage alerts.")
        try:
            saved = store.pause_alert(
                owner,
                alert_id,
                payload.expected_revision,
                _safe_now(selected_clock),
                auth_context=_request_auth_context(request),
            )
            return _alert_view(saved)
        except AuthWriteAuthorizationError as error:
            return _error(error.status_code, error.code, error.message)
        except MonitoringConflictError:
            return _error(409, "REVISION_CONFLICT", "Reload the alert before pausing it.")
        except MonitoringStoreError:
            return _error(404, "ALERT_NOT_FOUND", "The alert is unavailable.")
        except sqlite3.Error:
            return _error(503, "MONITORING_UNAVAILABLE", "Monitoring data is unavailable.")

    @router.post("/alerts/{alert_id}/resume", response_model=AlertView)
    def resume_alert(
        alert_id: Annotated[str, Path(min_length=36, max_length=36, pattern=UUID_PATTERN)],
        payload: RevisionRequest,
        request: Request,
        owner: int | None = Depends(owner_for_request),
    ) -> AlertView | JSONResponse:
        """Queue a fresh arming generation; the previous observation cannot trigger it."""
        if owner is None:
            return _error(401, "AUTHENTICATION_REQUIRED", "Sign in to manage alerts.")
        if not can_arm():
            return _error(503, "MONITORING_ARM_UNAVAILABLE", "The alert scheduler is unavailable.")
        try:
            return _alert_view(
                store.resume_alert(
                    owner,
                    alert_id,
                    payload.expected_revision,
                    _safe_now(selected_clock),
                    auth_context=_request_auth_context(request),
                )
            )
        except AuthWriteAuthorizationError as error:
            return _error(error.status_code, error.code, error.message)
        except MonitoringConflictError:
            return _error(409, "REVISION_CONFLICT", "Reload the alert before resuming it.")
        except MonitoringStoreError:
            return _error(404, "ALERT_NOT_FOUND", "The alert is unavailable.")
        except sqlite3.Error:
            return _error(503, "MONITORING_UNAVAILABLE", "Monitoring data is unavailable.")

    @router.get("/notifications", response_model=NotificationPage)
    def list_notifications(
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
        cursor: Annotated[str | None, Query(max_length=MAX_CURSOR_BYTES)] = None,
        owner: int | None = Depends(owner_for_request),
    ) -> NotificationPage | JSONResponse:
        """List bounded owner-scoped notifications as JSON-safe typed projections."""
        if owner is None:
            return _error(401, "AUTHENTICATION_REQUIRED", "Sign in to view notifications.")
        try:
            page = store.list_notifications(owner, limit=limit, cursor=cursor)
            return NotificationPage(
                items=[_notification_view(item) for item in page["items"]],
                next_cursor=page["next_cursor"],
            )
        except MonitoringStoreError:
            return _error(422, "INVALID_NOTIFICATION_PAGE", "The notification page is invalid.")
        except sqlite3.Error:
            return _error(503, "MONITORING_UNAVAILABLE", "Notifications are unavailable.")

    @router.put("/notifications/{notification_id}/read", response_model=NotificationView)
    def set_notification_read(
        notification_id: Annotated[str, Path(min_length=36, max_length=36, pattern=UUID_PATTERN)],
        payload: NotificationReadRequest,
        request: Request,
        owner: int | None = Depends(owner_for_request),
    ) -> NotificationView | JSONResponse:
        """CAS-update notification read state without exposing transport or recipient fields."""
        if owner is None:
            return _error(401, "AUTHENTICATION_REQUIRED", "Sign in to manage notifications.")
        try:
            saved = store.set_notification_read(
                owner,
                notification_id,
                payload.expected_revision,
                payload.is_read,
                _safe_now(selected_clock),
                auth_context=_request_auth_context(request),
            )
            return _notification_view(saved)
        except AuthWriteAuthorizationError as error:
            return _error(error.status_code, error.code, error.message)
        except MonitoringConflictError:
            return _error(409, "REVISION_CONFLICT", "Reload the notification before updating it.")
        except MonitoringStoreError:
            return _error(404, "NOTIFICATION_NOT_FOUND", "The notification is unavailable.")
        except sqlite3.Error:
            return _error(503, "MONITORING_UNAVAILABLE", "Notifications are unavailable.")

    @router.get("/notification-preferences", response_model=PreferencesView)
    def get_preferences(
        owner: int | None = Depends(owner_for_request),
    ) -> PreferencesView | JSONResponse:
        """Return preference flags and address-presence only, never the address or its ID."""
        if owner is None:
            return _error(401, "AUTHENTICATION_REQUIRED", "Sign in to view notification settings.")
        try:
            return _preferences_view(store.get_notification_preferences(owner))
        except MonitoringStoreError:
            return _error(404, "PREFERENCES_UNAVAILABLE", "Notification settings are unavailable.")
        except sqlite3.Error:
            return _error(503, "MONITORING_UNAVAILABLE", "Notification settings are unavailable.")

    @router.put("/notification-preferences", response_model=PreferencesView)
    def set_preferences(
        payload: PreferencesRequest,
        request: Request,
        owner: int | None = Depends(owner_for_request),
    ) -> PreferencesView | JSONResponse:
        """Update preferences with CAS while retaining the owner-selected address server-side."""
        if owner is None:
            return _error(
                401, "AUTHENTICATION_REQUIRED", "Sign in to manage notification settings."
            )
        if payload.digest_email:
            return _error(
                422,
                "DIGEST_EMAIL_UNAVAILABLE",
                "Daily digest email is not available.",
            )
        if payload.alert_email and not email_is_available():
            return _error(
                503,
                "ALERT_EMAIL_UNAVAILABLE",
                "Alert email is not available.",
            )
        try:
            current = store.get_notification_preferences(owner)
            saved = store.set_notification_preferences(
                owner,
                payload.expected_revision,
                alert_email=payload.alert_email,
                digest_email=payload.digest_email,
                digest_time=payload.digest_time or current["digest_time"],
                digest_timezone=payload.digest_timezone or current["digest_timezone"],
                address_id=(
                    current["address_id"] if payload.alert_email or payload.digest_email else None
                ),
                now=_safe_now(selected_clock),
                auth_context=_request_auth_context(request),
            )
            return _preferences_view(saved)
        except AuthWriteAuthorizationError as error:
            return _error(error.status_code, error.code, error.message)
        except MonitoringConflictError:
            return _error(409, "REVISION_CONFLICT", "Reload notification settings before saving.")
        except MonitoringStoreError:
            return _error(422, "INVALID_PREFERENCES", "The notification settings are unavailable.")
        except sqlite3.Error:
            return _error(503, "MONITORING_UNAVAILABLE", "Notification settings are unavailable.")

    return router
