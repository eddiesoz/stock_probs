"""Standalone, dependency-injected routes for explicit notification-address verification.

The router is not registered by ``create_app``. Its default email gate is disabled, owner
identity comes only from the injected resolver, and request bodies are bounded and parsed without
echoing user input in validation responses.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from stock_probs.notification_address_store import (
    NotificationAddressConflict,
    NotificationAddressError,
    NotificationAddressRateLimited,
    NotificationAddressStore,
    NotificationAddressUnavailable,
    VerificationIssue,
    VerificationStatus,
)
from stock_probs.notification_verification import NotificationVerificationService

MAX_ADDRESS_REQUEST_BYTES = 2048
_CODE_CHARACTERS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")
OwnerResolver = Callable[[Request], int | None]
MutationGuard = Callable[[Request, int], bool]
UtcClock = Callable[[], datetime]


def create_notification_address_router(
    store: NotificationAddressStore,
    owner_resolver: OwnerResolver,
    mutation_guard: MutationGuard,
    *,
    email_enabled: bool = False,
    service: NotificationVerificationService | None = None,
    clock: UtcClock | None = None,
) -> APIRouter:
    """Build isolated routes without registering them or starting any side effect."""

    if not isinstance(store, NotificationAddressStore):
        raise TypeError("store must be a NotificationAddressStore")
    if not callable(owner_resolver) or not callable(mutation_guard):
        raise TypeError("owner_resolver and mutation_guard must be callable")
    if type(email_enabled) is not bool:
        raise TypeError("email_enabled must be a boolean")
    if service is not None and not isinstance(service, NotificationVerificationService):
        raise TypeError("service must be a NotificationVerificationService")
    selected_clock = (lambda: datetime.now(UTC)) if clock is None else clock
    if not callable(selected_clock):
        raise TypeError("clock must be callable")
    router = APIRouter(prefix="/api/v1", tags=["notification-addresses"])

    def owner_for(request: Request) -> int | None:
        try:
            owner = owner_resolver(request)
        except Exception:
            return None
        return owner if type(owner) is int and owner > 0 else None

    def mutation_allowed(request: Request, owner: int) -> bool:
        try:
            allowed = mutation_guard(request, owner)
        except Exception:
            return False
        return type(allowed) is bool and allowed

    def service_ready() -> bool:
        return email_enabled and service is not None and service.available

    @router.get("/notification-addresses")
    def list_addresses(request: Request) -> JSONResponse:
        """Return verified opaque IDs and timestamps without exposing addresses."""

        owner = owner_for(request)
        if owner is None:
            return _error(
                401, "AUTHENTICATION_REQUIRED", "Sign in to manage notification addresses."
            )
        if not mutation_allowed(request, owner):
            return _error(
                403, "NOTIFICATION_FEATURE_UNAVAILABLE", "Notification settings are unavailable."
            )
        try:
            return JSONResponse(
                {"items": store.list_verified_addresses(owner, _safe_now(selected_clock))}
            )
        except NotificationAddressUnavailable:
            return _error(503, "NOTIFICATION_UNAVAILABLE", "Notification settings are unavailable.")
        except sqlite3.Error:
            return _error(503, "NOTIFICATION_UNAVAILABLE", "Notification settings are unavailable.")

    @router.post("/notification-address-verifications")
    async def request_verification(request: Request) -> JSONResponse:
        """Create and explicitly submit a new challenge, never sending on idempotent replay."""

        owner = await run_in_threadpool(owner_for, request)
        if owner is None:
            return _error(
                401, "AUTHENTICATION_REQUIRED", "Sign in to verify a notification address."
            )
        if not await run_in_threadpool(mutation_allowed, request, owner):
            return _error(
                403, "NOTIFICATION_FEATURE_UNAVAILABLE", "Notification settings are unavailable."
            )
        if not service_ready() or service is None:
            return _error(
                503, "EMAIL_VERIFICATION_UNAVAILABLE", "Email verification is unavailable."
            )
        parsed = await _read_json(request)
        if isinstance(parsed, JSONResponse):
            return parsed
        if type(parsed) is not dict or set(parsed) != {"address"}:
            return _error(422, "INVALID_REQUEST", "Provide one valid notification address.")
        address = parsed.get("address")
        if type(address) is not str:
            return _error(422, "INVALID_REQUEST", "Provide one valid notification address.")
        key = request.headers.get("Idempotency-Key")
        if key is None or len(key) != 36:
            return _error(422, "INVALID_IDEMPOTENCY_KEY", "Use a canonical idempotency key.")
        try:
            issue = await run_in_threadpool(
                store.request_verification,
                owner,
                address,
                key,
                await run_in_threadpool(_safe_now, selected_clock),
            )
        except NotificationAddressConflict:
            return _error(409, "IDEMPOTENCY_CONFLICT", "Use the original request for this key.")
        except NotificationAddressRateLimited:
            return _error(429, "VERIFICATION_RATE_LIMITED", "Try again later.")
        except NotificationAddressError:
            return _error(422, "INVALID_REQUEST", "The verification request is invalid.")
        except sqlite3.Error:
            return _error(503, "NOTIFICATION_UNAVAILABLE", "Email verification is unavailable.")

        summary_state = issue.state
        summary_revision = issue.revision
        if issue.state == "queued" and not issue.replayed:
            result = await run_in_threadpool(service.submit, owner, issue)
            summary_state = result.state
            summary_revision = result.revision
            if result.state in {"blocked", "unavailable"}:
                return _error(
                    503, "EMAIL_VERIFICATION_UNAVAILABLE", "Email verification is unavailable."
                )
        body = _issue_view(issue, summary_state, summary_revision)
        return JSONResponse(
            body, status_code=200 if issue.replayed or issue.state == "already_verified" else 202
        )

    @router.post("/notification-address-verifications/regenerate")
    async def regenerate_verification(request: Request) -> JSONResponse:
        """Send one new code for an explicitly selected prior challenge under a new key."""

        owner = await run_in_threadpool(owner_for, request)
        if owner is None:
            return _error(401, "AUTHENTICATION_REQUIRED", "Sign in to request a replacement code.")
        if not await run_in_threadpool(mutation_allowed, request, owner):
            return _error(
                403, "NOTIFICATION_FEATURE_UNAVAILABLE", "Notification settings are unavailable."
            )
        if not service_ready() or service is None:
            return _error(
                503, "EMAIL_VERIFICATION_UNAVAILABLE", "Email verification is unavailable."
            )
        parsed = await _read_json(request)
        if isinstance(parsed, JSONResponse):
            return parsed
        if type(parsed) is not dict or set(parsed) != {
            "address",
            "verification_id",
            "expected_revision",
        }:
            return _error(422, "INVALID_REQUEST", "The replacement request is invalid.")
        address = parsed.get("address")
        previous_id = parsed.get("verification_id")
        revision = parsed.get("expected_revision")
        key = request.headers.get("Idempotency-Key")
        if (
            type(address) is not str
            or type(previous_id) is not str
            or len(previous_id) != 36
            or type(revision) is not int
            or not 1 <= revision <= 2**63 - 1
            or key is None
            or len(key) != 36
        ):
            return _error(422, "INVALID_REQUEST", "The replacement request is invalid.")
        try:
            issue = await run_in_threadpool(
                store.request_verification,
                owner,
                address,
                key,
                await run_in_threadpool(_safe_now, selected_clock),
                supersedes_verification_id=previous_id,
                expected_revision=revision,
            )
        except NotificationAddressConflict:
            return _error(
                409, "REVISION_OR_IDEMPOTENCY_CONFLICT", "Reload status and use a new key."
            )
        except NotificationAddressRateLimited:
            return _error(429, "VERIFICATION_RATE_LIMITED", "Try again later.")
        except NotificationAddressError:
            return _error(422, "INVALID_REQUEST", "The replacement request is invalid.")
        except sqlite3.Error:
            return _error(503, "NOTIFICATION_UNAVAILABLE", "Email verification is unavailable.")
        if issue.replayed:
            return _error(409, "IDEMPOTENCY_KEY_REUSED", "Use a new key for a replacement code.")
        summary_state = issue.state
        summary_revision = issue.revision
        if issue.state == "queued":
            result = await run_in_threadpool(service.submit, owner, issue)
            summary_state = result.state
            summary_revision = result.revision
            if result.state in {"blocked", "unavailable"}:
                return JSONResponse(
                    {
                        "error": {
                            "code": "EMAIL_VERIFICATION_UNAVAILABLE",
                            "message": "Email verification is unavailable.",
                        },
                        **_issue_view(issue, summary_state, summary_revision),
                    },
                    status_code=503,
                )
        return JSONResponse(_issue_view(issue, summary_state, summary_revision), status_code=202)

    @router.get("/notification-address-verifications/current")
    async def current_verification_status(request: Request) -> JSONResponse:
        """Return the latest owner-bound challenge after a lost create response."""

        owner = await run_in_threadpool(owner_for, request)
        if owner is None:
            return _error(401, "AUTHENTICATION_REQUIRED", "Sign in to view verification status.")
        if not await run_in_threadpool(mutation_allowed, request, owner):
            return _error(
                403, "NOTIFICATION_FEATURE_UNAVAILABLE", "Notification settings are unavailable."
            )
        try:
            status = await run_in_threadpool(
                store.get_current_status,
                owner,
                await run_in_threadpool(_safe_now, selected_clock),
            )
        except NotificationAddressUnavailable:
            return _error(
                404, "VERIFICATION_UNAVAILABLE", "The verification request is unavailable."
            )
        except NotificationAddressError:
            return _error(422, "INVALID_REQUEST", "The verification request is invalid.")
        except sqlite3.Error:
            return _error(
                503, "NOTIFICATION_UNAVAILABLE", "The verification request is unavailable."
            )
        if status is None:
            return _error(404, "VERIFICATION_UNAVAILABLE", "No verification request is available.")
        return JSONResponse(_status_view(status))

    @router.get("/notification-address-verifications/{verification_id}")
    async def verification_status(request: Request, verification_id: str) -> JSONResponse:
        """Expose only owner-bound challenge status for restart and lost-response recovery."""

        owner = await run_in_threadpool(owner_for, request)
        if owner is None:
            return _error(401, "AUTHENTICATION_REQUIRED", "Sign in to view verification status.")
        if not await run_in_threadpool(mutation_allowed, request, owner):
            return _error(
                403, "NOTIFICATION_FEATURE_UNAVAILABLE", "Notification settings are unavailable."
            )
        try:
            status = await run_in_threadpool(
                store.get_status,
                owner,
                verification_id,
                await run_in_threadpool(_safe_now, selected_clock),
            )
        except NotificationAddressUnavailable:
            return _error(
                404, "VERIFICATION_UNAVAILABLE", "The verification request is unavailable."
            )
        except NotificationAddressError:
            return _error(422, "INVALID_REQUEST", "The verification request is invalid.")
        except sqlite3.Error:
            return _error(
                503, "NOTIFICATION_UNAVAILABLE", "The verification request is unavailable."
            )
        return JSONResponse(_status_view(status))

    @router.post("/notification-addresses/select")
    async def select_address(request: Request) -> JSONResponse:
        """Select a verified owned address and reset both email choices to off."""

        owner = await run_in_threadpool(owner_for, request)
        if owner is None:
            return _error(
                401, "AUTHENTICATION_REQUIRED", "Sign in to select a notification address."
            )
        if not await run_in_threadpool(mutation_allowed, request, owner):
            return _error(
                403, "NOTIFICATION_FEATURE_UNAVAILABLE", "Notification settings are unavailable."
            )
        parsed = await _read_json(request)
        if isinstance(parsed, JSONResponse):
            return parsed
        if type(parsed) is not dict or set(parsed) != {"address_id", "expected_revision"}:
            return _error(422, "INVALID_REQUEST", "Select one verified notification address.")
        address_id = parsed.get("address_id")
        revision = parsed.get("expected_revision")
        if (
            type(address_id) is not str
            or len(address_id) != 36
            or type(revision) is not int
            or not 0 <= revision <= 2**63 - 1
        ):
            return _error(422, "INVALID_REQUEST", "Select one verified notification address.")
        try:
            result = await run_in_threadpool(
                store.select_verified_address,
                owner,
                address_id,
                revision,
                await run_in_threadpool(_safe_now, selected_clock),
            )
        except NotificationAddressConflict:
            return _error(
                409, "REVISION_CONFLICT", "Reload notification preferences before selecting."
            )
        except NotificationAddressUnavailable:
            return _error(
                404, "VERIFIED_ADDRESS_UNAVAILABLE", "The verified address is unavailable."
            )
        except NotificationAddressError:
            return _error(422, "INVALID_REQUEST", "The selection is invalid.")
        except sqlite3.Error:
            return _error(503, "NOTIFICATION_UNAVAILABLE", "Notification settings are unavailable.")
        return JSONResponse(result)

    @router.post("/notification-address-verifications/confirm")
    async def confirm_verification(request: Request) -> JSONResponse:
        """CAS-verify the owner's one-use code without accepting any client-selected owner."""

        owner = await run_in_threadpool(owner_for, request)
        if owner is None:
            return _error(
                401, "AUTHENTICATION_REQUIRED", "Sign in to verify a notification address."
            )
        if not await run_in_threadpool(mutation_allowed, request, owner):
            return _error(
                403, "NOTIFICATION_FEATURE_UNAVAILABLE", "Notification settings are unavailable."
            )
        parsed = await _read_json(request)
        if isinstance(parsed, JSONResponse):
            return parsed
        if type(parsed) is not dict or set(parsed) != {
            "verification_id",
            "code",
            "expected_revision",
        }:
            return _error(422, "INVALID_REQUEST", "The verification request is invalid.")
        verification_id = parsed.get("verification_id")
        code = parsed.get("code")
        revision = parsed.get("expected_revision")
        if (
            type(verification_id) is not str
            or len(verification_id) != 36
            or type(code) is not str
            or len(code) != 43
            or not code.isascii()
            or any(character not in _CODE_CHARACTERS for character in code)
            or type(revision) is not int
            or not 1 <= revision <= 2**63 - 1
        ):
            return _error(422, "INVALID_REQUEST", "The verification request is invalid.")
        try:
            result = await run_in_threadpool(
                store.verify_code,
                owner,
                verification_id,
                code,
                revision,
                await run_in_threadpool(_safe_now, selected_clock),
            )
        except NotificationAddressConflict:
            return _error(
                409, "REVISION_CONFLICT", "Reload the verification status before retrying."
            )
        except NotificationAddressUnavailable:
            return _error(
                404, "VERIFICATION_UNAVAILABLE", "The verification request is unavailable."
            )
        except NotificationAddressError:
            return _error(422, "INVALID_REQUEST", "The verification request is invalid.")
        except sqlite3.Error:
            return _error(
                503, "NOTIFICATION_UNAVAILABLE", "The verification request is unavailable."
            )
        status = 200 if result.get("verified") is True else 422
        return JSONResponse(result, status_code=status)

    return router


async def _read_json(request: Request) -> dict[str, Any] | JSONResponse:
    """Read a small JSON object with static errors that never echo submitted values."""

    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _error(415, "JSON_REQUIRED", "Send a JSON request.")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_ADDRESS_REQUEST_BYTES:
            return _error(413, "REQUEST_TOO_LARGE", "The verification request is too large.")
        body.extend(chunk)
    try:
        value = json.loads(bytes(body), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return _error(400, "INVALID_JSON", "The verification request is invalid.")
    return (
        value
        if type(value) is dict
        else _error(422, "INVALID_REQUEST", "The verification request is invalid.")
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def _issue_view(issue: VerificationIssue, state: str, revision: int) -> dict[str, Any]:
    return {
        "verification_id": issue.verification_id,
        "address_id": issue.address_id if state == "already_verified" else None,
        "state": state,
        "revision": revision,
        "expires_at": issue.expires_at,
        "replayed": issue.replayed,
    }


def _status_view(status: VerificationStatus) -> dict[str, Any]:
    return {
        "verification_id": status.verification_id,
        "address_id": status.address_id,
        "state": status.state,
        "revision": status.revision,
        "attempts": status.attempts,
        "expires_at": status.expires_at,
        "invalidated": status.invalidated,
    }


def _safe_now(clock: UtcClock) -> datetime:
    now = clock()
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("The verification clock must return an aware timestamp.")
    return now.astimezone(UTC)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)
