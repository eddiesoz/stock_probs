"""Authenticated HTTP routes for recorded forecast report cards and manual reviews."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from stock_probs.auth import AuthContext
from stock_probs.auth_write_guard import AuthWriteAuthorizationError
from stock_probs.report_store import ReportCardStore, ReportStoreError
from stock_probs.repository import RepositoryError

OwnerResolver = Callable[[Request], int | None]
FeaturePredicate = bool | Callable[[], bool]
Clock = Callable[[], datetime]


class ManualOutcomeReviewRequest(BaseModel):
    """Bounded append-only review request; identity and timestamp come from the server."""

    model_config = ConfigDict(extra="forbid", strict=True)

    expected_revision: int = Field(ge=0, le=2**63 - 2)
    state: Literal["confirmed", "disputed"]
    note: str = Field(default="", max_length=2048)


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def _request_auth_context(request: Request) -> AuthContext | None:
    """Use only the trusted authentication snapshot attached before body parsing."""
    context = getattr(request.state, "auth_context", None)
    return context if isinstance(context, AuthContext) else None


def create_report_router(
    store: ReportCardStore,
    owner_resolver: OwnerResolver,
    *,
    enabled: FeaturePredicate,
    clock: Clock | None = None,
) -> APIRouter:
    """Build report-card routes around the caller's authenticated owner boundary.

    The resolver must use the active application session. This router never trusts request data
    for identity, starts provider or assistant work, or adds to forecasts/outcomes.
    """
    router = APIRouter(prefix="/api/v1/report-cards", tags=["report-cards"])
    current_time = clock or (lambda: datetime.now(UTC))

    def owner_or_error(request: Request) -> int | JSONResponse:
        owner_id = owner_resolver(request)
        if type(owner_id) is not int or owner_id < 1:
            return _error(401, "AUTHENTICATION_REQUIRED", "Sign in to view report cards.")
        return owner_id

    def feature_enabled() -> bool:
        return enabled() if callable(enabled) else enabled

    def unavailable_if_disabled() -> JSONResponse | None:
        if not feature_enabled():
            return _error(
                503, "REPORT_CARDS_UNAVAILABLE", "Report cards are temporarily unavailable."
            )
        return None

    def store_error(error: ReportStoreError) -> JSONResponse:
        return _error(error.status_code, error.code, error.message)

    @router.get("", response_model=None)
    def list_report_cards(
        request: Request,
        page: int = Query(default=1, ge=1, le=10_000),
        page_size: int = Query(default=20, ge=1, le=100),
        symbol: str | None = Query(default=None, min_length=1, max_length=80),
        horizon: str | None = Query(default=None, min_length=1, max_length=80),
    ) -> JSONResponse | dict[str, object]:
        """Return the authenticated owner's current bounded report page."""
        owner = owner_or_error(request)
        if isinstance(owner, JSONResponse):
            return owner
        disabled = unavailable_if_disabled()
        if disabled is not None:
            return disabled
        try:
            return store.list_report(
                owner,
                current_time(),
                page=page,
                page_size=page_size,
                symbol=symbol,
                horizon=horizon,
            )
        except ReportStoreError as error:
            return store_error(error)
        except (RepositoryError, sqlite3.Error):
            return _error(
                503, "REPORT_CARDS_UNAVAILABLE", "Report cards are temporarily unavailable."
            )

    @router.get("/{result_id}/reviews", response_model=None)
    def list_reviews(
        result_id: int,
        request: Request,
        page: int = Query(default=1, ge=1, le=10_000),
        page_size: int = Query(default=20, ge=1, le=100),
    ) -> JSONResponse | dict[str, object]:
        """Return one owner's bounded immutable review history for a saved result."""
        owner = owner_or_error(request)
        if isinstance(owner, JSONResponse):
            return owner
        disabled = unavailable_if_disabled()
        if disabled is not None:
            return disabled
        try:
            payload = store.review_history(
                owner,
                result_id,
                current_time(),
                page=page,
                page_size=page_size,
            )
            if payload is None:
                return _error(404, "REPORT_NOT_FOUND", "The report card was not found.")
            return payload
        except ReportStoreError as error:
            return store_error(error)
        except (RepositoryError, sqlite3.Error):
            return _error(
                503, "REPORT_CARDS_UNAVAILABLE", "Report cards are temporarily unavailable."
            )

    @router.post("/{result_id}/reviews", status_code=201, response_model=None)
    def append_review(
        result_id: int,
        payload: ManualOutcomeReviewRequest,
        request: Request,
    ) -> JSONResponse | dict[str, object]:
        """Append a confirmed or disputed review after the explicit user action."""
        owner = owner_or_error(request)
        if isinstance(owner, JSONResponse):
            return owner
        disabled = unavailable_if_disabled()
        if disabled is not None:
            return disabled
        try:
            result = store.append_manual_review(
                owner,
                result_id,
                payload.expected_revision,
                payload.state,
                payload.note,
                current_time(),
                auth_context=_request_auth_context(request),
            )
            return JSONResponse(status_code=201, content=result)
        except AuthWriteAuthorizationError as error:
            return _error(error.status_code, error.code, error.message)
        except ReportStoreError as error:
            return store_error(error)
        except (RepositoryError, sqlite3.Error):
            return _error(
                503, "REPORT_CARDS_UNAVAILABLE", "Report cards are temporarily unavailable."
            )

    return router
