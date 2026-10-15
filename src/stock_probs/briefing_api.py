"""Owner-guarded HTTP routes for saved personal briefings.

The application factory mounts this router with authenticated owner, active-account, CSRF, feature,
and canary callbacks before exposing its routes.
"""

from __future__ import annotations

import inspect
import json
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Literal
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError
from starlette.concurrency import run_in_threadpool

from stock_probs.briefing_domain import (
    BriefingDomainError,
    BriefingSnapshot,
    BriefingWindow,
    canonical_uuid,
    parse_timestamp,
    request_fingerprint,
    timestamp_text,
    utc_instant,
    validate_threshold_bps,
)
from stock_probs.briefing_service import (
    BriefingAccessDeniedError,
    BriefingService,
    BriefingServiceError,
    BriefingSourceUnavailableError,
)
from stock_probs.briefing_store import (
    BriefingCapacityError,
    BriefingConflictError,
    BriefingNotFoundError,
    BriefingStoreError,
    BriefingUnavailableError,
    PriceThresholdPreference,
    VisitAnchor,
)
from stock_probs.domain import DomainError

MAX_BODY_BYTES = 4_096
MAX_QUERY_BYTES = 512
MAX_PAGE_SIZE = 50
MAX_REVISION = 2**63 - 1
_LOCK_STRIPES = 64

OwnerResolver = Callable[[Request], object]
OwnerGuard = Callable[[int], object]
RequestGuard = Callable[[Request], object]
Clock = Callable[[], datetime]


class _InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _BriefingCreate(_InputModel):
    window: Literal["since_last_visit", "last_24_hours", "last_7_days"]
    observed_as_of: StrictStr = Field(min_length=20, max_length=40)


class _PreferenceUpdate(_InputModel):
    threshold_bps: StrictInt = Field(ge=50, le=1_000)
    expected_revision: StrictInt = Field(ge=0, le=MAX_REVISION)


class _VisitUpdate(_InputModel):
    expected_revision: StrictInt = Field(ge=0, le=MAX_REVISION)


def _fail(code: str, message: str, status: int) -> DomainError:
    return DomainError(code, message, status_code=status)


def _error_response(error: Exception) -> DomainError:
    """Map service/store failures to fixed public messages without exposing internals."""

    if isinstance(error, DomainError):
        return error
    if isinstance(error, BriefingConflictError):
        return _fail("briefing_conflict", "The briefing changed. Reload and try again.", 409)
    if isinstance(error, BriefingNotFoundError):
        return _fail("briefing_unavailable", "The briefing is unavailable.", 404)
    if isinstance(error, BriefingCapacityError):
        return _fail("briefing_capacity", "The briefing history reached its storage limit.", 409)
    if isinstance(error, BriefingAccessDeniedError | BriefingUnavailableError):
        return _fail("owner_unavailable", "This account is not available for briefings.", 403)
    if isinstance(error, BriefingSourceUnavailableError):
        return _fail(
            "briefing_source_unavailable", "Briefing data is temporarily unavailable.", 503
        )
    if isinstance(error, BriefingServiceError):
        return _fail("briefing_invalid", "The briefing request could not be completed.", 422)
    if isinstance(error, BriefingStoreError | BriefingDomainError | ValidationError):
        return _fail("briefing_invalid", "The briefing request is invalid.", 422)
    return _fail("briefing_unavailable", "Briefing data is temporarily unavailable.", 503)


async def _invoke(callback: Callable[..., object], *args: object) -> object:
    """Run synchronous guards off-loop while also accepting async injected guards."""

    if inspect.iscoroutinefunction(callback):
        return await callback(*args)
    value = await run_in_threadpool(callback, *args)
    if inspect.isawaitable(value):
        return await value
    return value


async def _bounded_json(request: Request) -> object:
    """Read one strictly framed, small JSON body and reject duplicate object keys."""

    lengths = request.headers.getlist("content-length")
    transfer = request.headers.get("transfer-encoding")
    if transfer and lengths:
        raise _fail("invalid_body_framing", "The request body framing is invalid.", 400)
    if transfer:
        raise _fail("bounded_body_required", "A bounded request body is required.", 411)
    if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdecimal():
        raise _fail("bounded_body_required", "A bounded request body is required.", 411)
    length_text = lengths[0]
    if len(length_text) > 12:
        raise _fail("body_too_large", "The request body exceeds its size limit.", 413)
    declared = int(length_text)
    if declared > MAX_BODY_BYTES:
        raise _fail("body_too_large", "The request body exceeds its size limit.", 413)
    content_type = request.headers.get("content-type", "").split(";", maxsplit=1)[0].strip().lower()
    if content_type != "application/json":
        raise _fail("json_required", "Send a JSON request body.", 415)

    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > MAX_BODY_BYTES or received > declared:
            raise _fail("body_too_large", "The request body exceeds its size limit.", 413)
        chunks.append(chunk)
    if received != declared:
        raise _fail("invalid_body_framing", "The request body length is invalid.", 400)

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        return json.loads(
            b"".join(chunks).decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("invalid number")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise _fail("invalid_json", "The request body is not valid JSON.", 400) from None


def _validate_body(model: type[BaseModel], value: object) -> BaseModel:
    try:
        return model.model_validate(value)
    except ValidationError:
        raise _fail("briefing_invalid", "The request fields are invalid.", 422) from None


def _preference_payload(value: PriceThresholdPreference) -> dict[str, object]:
    return {
        "revision": value.revision,
        "threshold_bps": value.threshold_bps,
        "updated_at": timestamp_text(value.updated_at) if value.updated_at else None,
    }


def _anchor_payload(value: VisitAnchor) -> dict[str, object]:
    return {
        "revision": value.revision,
        "baseline_at": timestamp_text(value.baseline_at) if value.baseline_at else None,
        "snapshot_id": value.snapshot_id,
        "visited_at": timestamp_text(value.visited_at) if value.visited_at else None,
    }


def _snapshot_payload(value: BriefingSnapshot) -> dict[str, object]:
    """Project only the reviewed public snapshot fields; omit owner and idempotency material."""

    payload = value.payload()
    if not isinstance(payload, dict):
        raise _fail("briefing_unavailable", "The saved briefing is unavailable.", 503)
    required_payload = {
        "version",
        "window",
        "baseline_at",
        "observed_as_of",
        "threshold_bps",
        "price_changes",
        "outcome_changes",
        "triggered_alerts",
        "due_thesis_reviews",
    }
    if set(payload) != required_payload:
        raise _fail("briefing_unavailable", "The saved briefing is unavailable.", 503)
    try:
        result: dict[str, object] = dict(payload)
        result.update(
            {
                "id": canonical_uuid(value.snapshot_id, "snapshot_id"),
                "generated_at": timestamp_text(utc_instant(value.generated_at, "generated_at")),
                "baseline_anchor_revision": value.baseline_anchor_revision,
                "preference_revision": value.preference_revision,
            }
        )
    except (BriefingDomainError, TypeError, ValueError):
        raise _fail("briefing_unavailable", "The saved briefing is unavailable.", 503) from None
    for field in ("baseline_anchor_revision", "preference_revision"):
        revision = result[field]
        if type(revision) is not int or revision < 0 or revision > MAX_REVISION:
            raise _fail("briefing_unavailable", "The saved briefing is unavailable.", 503)
    return result


def _page_query(request: Request) -> tuple[int, str | None]:
    raw = request.scope.get("query_string", b"")
    if not isinstance(raw, bytes) or len(raw) > MAX_QUERY_BYTES:
        raise _fail("briefing_query_invalid", "The briefing query is too long.", 422)
    try:
        text = raw.decode("ascii")
        pairs = parse_qsl(text, keep_blank_values=True, strict_parsing=True, max_num_fields=2)
    except (UnicodeDecodeError, ValueError):
        raise _fail("briefing_query_invalid", "The briefing query is invalid.", 422) from None
    values: dict[str, str] = {}
    for key, value in pairs:
        if key not in {"limit", "cursor"} or key in values or len(value) > 36:
            raise _fail("briefing_query_invalid", "The briefing query is invalid.", 422)
        values[key] = value
    raw_limit = values.get("limit", "20")
    if not raw_limit.isascii() or not raw_limit.isdecimal() or len(raw_limit) > 2:
        raise _fail("briefing_query_invalid", "The briefing page size is invalid.", 422)
    limit = int(raw_limit)
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise _fail("briefing_query_invalid", "The briefing page size is invalid.", 422)
    cursor = values.get("cursor")
    if cursor is not None:
        try:
            cursor = canonical_uuid(cursor, "cursor")
        except BriefingDomainError:
            raise _fail("briefing_query_invalid", "The briefing cursor is invalid.", 422) from None
    return limit, cursor


def create_briefing_router(
    service: BriefingService,
    *,
    owner_for_request: OwnerResolver,
    active_owner: OwnerGuard,
    csrf_guard: RequestGuard,
    feature_enabled: RequestGuard,
    canary_allowed: RequestGuard,
    clock: Clock | None = None,
) -> APIRouter:
    """Create routes requiring explicit application-owned identity and write guards.

    Guards must return the literal boolean ``True`` to grant access. Read-only state remains
    available to an authenticated active owner while the release/canary gates are off; all
    snapshot, preference, and visit actions fail closed until both gates grant access.
    """

    if not isinstance(service, BriefingService):
        raise TypeError("service must be a BriefingService")
    callbacks: tuple[tuple[str, object], ...] = (
        ("owner_for_request", owner_for_request),
        ("active_owner", active_owner),
        ("csrf_guard", csrf_guard),
        ("feature_enabled", feature_enabled),
        ("canary_allowed", canary_allowed),
    )
    if any(not callable(callback) for _name, callback in callbacks):
        raise TypeError("all briefing identity and feature guards are required")
    if clock is not None and not callable(clock):
        raise TypeError("clock must be callable")
    selected_clock = clock or service.clock
    idempotency_locks = tuple(threading.Lock() for _ in range(_LOCK_STRIPES))
    router = APIRouter()

    async def resolve_owner(request: Request) -> int:
        try:
            owner = await _invoke(owner_for_request, request)
        except DomainError:
            raise
        except Exception:
            raise _fail("authentication_required", "Sign in to view briefings.", 401) from None
        if type(owner) is not int or owner < 1:
            raise _fail("authentication_required", "Sign in to view briefings.", 401)
        try:
            active = await _invoke(active_owner, owner)
        except DomainError:
            raise
        except Exception:
            raise _fail("owner_unavailable", "This account is not available.", 503) from None
        if active is not True:
            raise _fail("owner_unavailable", "This account is not available.", 403)
        return owner

    async def ensure_enabled(request: Request) -> None:
        try:
            enabled = await _invoke(feature_enabled, request)
            if enabled is not True:
                raise _fail("briefing_disabled", "Briefings are not enabled for this account.", 503)
            canary = await _invoke(canary_allowed, request)
        except DomainError:
            raise
        except Exception:
            raise _fail("briefing_disabled", "Briefings are not available.", 503) from None
        if canary is not True:
            raise _fail("briefing_disabled", "Briefings are not enabled for this account.", 503)

    async def ensure_csrf(request: Request) -> None:
        try:
            allowed = await _invoke(csrf_guard, request)
        except DomainError:
            raise
        except Exception:
            raise _fail("csrf_rejected", "The request could not be verified.", 403) from None
        if allowed is not True:
            raise _fail("csrf_rejected", "The request could not be verified.", 403)

    def now_text() -> str:
        try:
            now = utc_instant(selected_clock(), "server_time")
            return timestamp_text(now)
        except (BriefingDomainError, TypeError, ValueError):
            raise _fail(
                "briefing_unavailable", "Briefing data is temporarily unavailable.", 503
            ) from None

    def no_store(response: Response) -> None:
        response.headers["Cache-Control"] = "no-store"

    @router.get("/api/v1/briefing-state")
    async def briefing_state(request: Request, response: Response) -> dict[str, object]:
        owner = await resolve_owner(request)
        try:
            preference, anchor = await run_in_threadpool(
                lambda: (service.get_preference(owner), service.store.get_visit_anchor(owner))
            )
            features_enabled = await _invoke(feature_enabled, request)
            if features_enabled is True:
                canary = await _invoke(canary_allowed, request)
                enabled = canary is True
            else:
                enabled = False
        except DomainError:
            raise
        except Exception:
            raise _fail(
                "briefing_unavailable", "Briefing data is temporarily unavailable.", 503
            ) from None
        no_store(response)
        return {
            "features": {
                "enabled": enabled,
                "headlines_available": False,
                "digest_available": False,
                "assistant_available": False,
            },
            "server_time": now_text(),
            "preference": _preference_payload(preference),
            "visit_anchor": _anchor_payload(anchor),
        }

    @router.get("/api/v1/briefings")
    async def list_briefings(request: Request, response: Response) -> dict[str, object]:
        owner = await resolve_owner(request)
        await ensure_enabled(request)
        limit, cursor = _page_query(request)
        try:
            page = await run_in_threadpool(
                lambda: service.list_snapshots(owner, limit=limit, cursor=cursor)
            )
            items = [_snapshot_payload(item) for item in page.items]
        except Exception as error:
            raise _error_response(error) from None
        no_store(response)
        return {"items": items, "next_cursor": page.next_cursor}

    @router.get("/api/v1/briefings/{snapshot_id}")
    async def get_briefing(
        snapshot_id: str, request: Request, response: Response
    ) -> dict[str, object]:
        owner = await resolve_owner(request)
        await ensure_enabled(request)
        if len(snapshot_id) != 36:
            raise _fail("briefing_unavailable", "The briefing is unavailable.", 404)
        try:
            selected_id = canonical_uuid(snapshot_id, "snapshot_id")
        except BriefingDomainError:
            raise _fail("briefing_unavailable", "The briefing is unavailable.", 404) from None
        try:
            snapshot = await run_in_threadpool(service.get_snapshot, owner, selected_id)
            result = _snapshot_payload(snapshot)
        except Exception as error:
            raise _error_response(error) from None
        no_store(response)
        return result

    @router.post("/api/v1/briefings")
    async def create_briefing(request: Request, response: Response) -> dict[str, object]:
        owner = await resolve_owner(request)
        await ensure_enabled(request)
        await ensure_csrf(request)
        value = _validate_body(_BriefingCreate, await _bounded_json(request))
        if not isinstance(value, _BriefingCreate):
            raise _fail("briefing_invalid", "The request fields are invalid.", 422)
        keys = request.headers.getlist("idempotency-key")
        if len(keys) != 1:
            raise _fail("idempotency_required", "A canonical Idempotency-Key is required.", 400)
        try:
            key = canonical_uuid(keys[0], "idempotency_key")
            window = BriefingWindow(value.window)
            observed_as_of = parse_timestamp(value.observed_as_of, "observed_as_of")
            request_hash = request_fingerprint(window, observed_as_of)
        except (BriefingDomainError, ValueError):
            raise _fail("briefing_invalid", "The briefing request is invalid.", 422) from None

        lock = idempotency_locks[hash((owner, key)) % _LOCK_STRIPES]
        try:

            def create_or_replay() -> tuple[BriefingSnapshot, bool]:
                with lock:
                    existing = service.store.get_snapshot_by_idempotency(owner, key, request_hash)
                    if existing is not None:
                        return existing, False
                    result = service.generate(
                        owner,
                        idempotency_key=key,
                        window=window,
                        observed_as_of=observed_as_of,
                    )
                    return result, True

            snapshot, created = await run_in_threadpool(create_or_replay)
            result = _snapshot_payload(snapshot)
        except Exception as error:
            raise _error_response(error) from None
        no_store(response)
        response.status_code = 201 if created else 200
        response.headers["Location"] = f"/api/v1/briefings/{result['id']}"
        return result

    @router.patch("/api/v1/briefing-preference")
    async def update_preference(request: Request, response: Response) -> dict[str, object]:
        owner = await resolve_owner(request)
        await ensure_enabled(request)
        await ensure_csrf(request)
        value = _validate_body(_PreferenceUpdate, await _bounded_json(request))
        if not isinstance(value, _PreferenceUpdate):
            raise _fail("briefing_invalid", "The request fields are invalid.", 422)
        try:
            threshold = validate_threshold_bps(value.threshold_bps)
            updated = await run_in_threadpool(
                service.update_preference,
                owner,
                threshold,
                expected_revision=value.expected_revision,
            )
            result = _preference_payload(updated)
        except Exception as error:
            raise _error_response(error) from None
        no_store(response)
        return result

    @router.post("/api/v1/briefings/{snapshot_id}/visits")
    async def record_briefing_visit(
        snapshot_id: str, request: Request, response: Response
    ) -> dict[str, object]:
        owner = await resolve_owner(request)
        await ensure_enabled(request)
        await ensure_csrf(request)
        if len(snapshot_id) != 36:
            raise _fail("briefing_unavailable", "The briefing is unavailable.", 404)
        try:
            selected_id = canonical_uuid(snapshot_id, "snapshot_id")
        except BriefingDomainError:
            raise _fail("briefing_unavailable", "The briefing is unavailable.", 404) from None
        value = _validate_body(_VisitUpdate, await _bounded_json(request))
        if not isinstance(value, _VisitUpdate):
            raise _fail("briefing_invalid", "The request fields are invalid.", 422)
        try:
            anchor = await run_in_threadpool(
                service.record_visit,
                owner,
                selected_id,
                expected_revision=value.expected_revision,
            )
            result = _anchor_payload(anchor)
        except Exception as error:
            raise _error_response(error) from None
        no_store(response)
        return result

    return router
