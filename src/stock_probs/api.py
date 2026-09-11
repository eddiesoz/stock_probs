"""FastAPI application exposes the sole browser data boundary under /api/v1."""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import sqlite3
import unicodedata
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi import Path as PathParameter
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import ClientDisconnect
from starlette.types import ASGIApp

from stock_probs.backup import MAX_BACKUP_BYTES, BackupError, BackupManager
from stock_probs.config import Settings
from stock_probs.domain import DomainError
from stock_probs.provider import FixtureProvider, MarketDataProvider, YahooProvider
from stock_probs.repository import SCHEMA_VERSION, Repository, RepositoryError
from stock_probs.schemas import (
    BackupRequest,
    CorrectionRequest,
    FreshReconstructionRequest,
    InstrumentIdentityResponse,
    InstrumentLookupResponse,
    OutcomeRequest,
    RestoreRequest,
    SearchRequest,
)
from stock_probs.service import ForecastService


class ApiResponse(BaseModel):
    """Keep generated success and error contracts concrete and closed to undocumented fields."""

    model_config = ConfigDict(extra="forbid")


class ValidationIssue(ApiResponse):
    location: list[str | int]
    message: str
    type: str


class ErrorDetail(ApiResponse):
    code: str
    message: str
    request_id: str | None = None
    details: list[ValidationIssue] | None = None


class ErrorEnvelope(ApiResponse):
    error: ErrorDetail


class HealthResponse(ApiResponse):
    status: Literal["ok"]
    service: Literal["stock-probs"]
    api_version: Literal["v1"]


class ReadinessResponse(ApiResponse):
    status: Literal["ready"]
    schema_version: int
    provider: str


class SearchEventResponse(ApiResponse):
    id: int
    request_id: str
    submitted_symbol: str
    normalized_symbol: str | None
    asset_type: str
    status: Literal["successful", "failed", "repeated"]
    is_repeat: bool
    error_code: str | None
    error_message: str | None
    submitted_at: str
    completed_at: str
    run_id: int | None
    analysis_kind: Literal["submitted_forecast", "fresh_historical_reconstruction"] | None = None
    source_event_id: int | None = None
    requested_cutoff: str | None = None
    requested_source_event_id: int | None = None

    @model_validator(mode="after")
    def exact_status_semantics(self) -> SearchEventResponse:
        """Reject inconsistent states that would make the public audit status ambiguous."""

        successful = self.status in {"successful", "repeated"}
        if successful != (self.run_id is not None):
            raise ValueError("successful and repeated events require a forecast run")
        if successful != (self.error_code is None and self.error_message is None):
            raise ValueError("only failed events may contain an error")
        if self.status == "successful" and self.is_repeat:
            raise ValueError("a first successful submission cannot be marked repeated")
        if self.status == "repeated" and not self.is_repeat:
            raise ValueError("a repeated successful submission must be marked repeated")
        return self


class CapturedBarResponse(ApiResponse):
    timestamp: str
    end: str
    close: float
    duration_seconds: int


class CalendarResponse(ApiResponse):
    name: str
    version: str
    timezone: str


class ModelIdentityResponse(ApiResponse):
    name: str
    version: str


class ModelParametersResponse(ApiResponse):
    daily_max_samples: int
    ewma_span_daily: int
    ewma_span_intraday: int
    flat_threshold: float
    return_thresholds_percent: list[float]


class StaleStateResponse(ApiResponse):
    state: Literal["current", "stale"]
    reasons: list[str]


class HistoricalAnalysisResponse(ApiResponse):
    kind: Literal["fresh_historical_reconstruction"]
    label: Literal["Fresh historical-cutoff analysis"]
    source_event_id: int
    requested_cutoff: str
    performed_at: str
    provider_content_fingerprint: str | None = None


class ProvenanceResponse(ApiResponse):
    source: str
    query: dict[str, Any]
    response_as_of: str
    content_fingerprint: str
    instrument_identity: InstrumentIdentityResponse
    identity_fingerprint: str
    model_version: str
    calendar_version: str
    analysis: HistoricalAnalysisResponse | None = None
    provider_content_fingerprint: str | None = None


class ForecastInputResponse(ApiResponse):
    id: int
    symbol: str
    canonical_symbol: str
    display_name: str
    company_name: str
    asset_type: Literal["stock", "etf"]
    quote_type: Literal["EQUITY", "STOCK", "ETF"]
    exchange: str
    exchange_timezone: str
    currency: str
    provider: str
    provider_as_of: str
    request_cutoff: str
    provider_query: dict[str, Any]
    provider_metadata: dict[str, Any]
    content_fingerprint: str
    instrument_identity: InstrumentIdentityResponse
    identity_fingerprint: str
    captured_at: str
    selected_daily_bars: list[CapturedBarResponse]
    selected_intraday_bars: list[CapturedBarResponse]
    session_rule: str
    calendar: CalendarResponse
    limitations: list[str]
    quality: Literal["current", "stale"]
    quality_reasons: list[str]
    stale_state: StaleStateResponse
    session_state_at_request: str
    model: ModelIdentityResponse
    parameters: ModelParametersResponse
    provenance: ProvenanceResponse


class DirectionDefinitionsResponse(ApiResponse):
    down: str
    flat: str
    up: str


class DirectionProbabilitiesResponse(ApiResponse):
    down: float
    flat: float
    up: float
    unit: Literal["probability"]
    definitions: DirectionDefinitionsResponse
    flat_definition: str


class ThresholdProbabilityResponse(ApiResponse):
    operator: Literal["lte", "gte"]
    threshold: float
    unit: Literal["percent_return"]
    definition: str
    probability: float


class IntervalBoundResponse(ApiResponse):
    low: float
    high: float
    unit: Literal["percent_return", "quote_currency"]


class MagnitudeIntervalResponse(ApiResponse):
    level: float
    definition: str
    percent: IntervalBoundResponse
    price: IntervalBoundResponse


class OutcomeResponse(ApiResponse):
    id: int
    result_id: int
    observed_close: float | None
    observed_return: float | None
    observed_at: str
    state: Literal["observed", "unavailable", "provisional", "corrected"]
    note: str
    created_at: str
    comparison_rule: str


class ForecastResultResponse(ApiResponse):
    horizon: Literal["close_to_close", "completed_5m_to_close"]
    origin_timestamp: str
    origin_bar_end: str | None = None
    origin_price: float
    reference_timestamp: str
    reference_state: str
    target_timestamp: str
    target_state: str
    exchange_timezone: str
    session_state_at_request: str | None = None
    stale_state: Literal["current", "stale"]
    calculated_at: str
    definition: str
    target_session_rule: str | None = None
    direction_probabilities: DirectionProbabilitiesResponse
    threshold_probabilities: list[ThresholdProbabilityResponse]
    magnitude_intervals: list[MagnitudeIntervalResponse]
    sample_size: int
    distribution_definition: str


class RecordedForecastResultResponse(ForecastResultResponse):
    id: int
    recorded_at: str
    outcomes: list[OutcomeResponse]
    outcomes_truncated: bool


class OriginalForecastResultResponse(ForecastResultResponse):
    id: int
    immutable: Literal[True]


class ForecastCreationResponse(ApiResponse):
    event: SearchEventResponse
    input: ForecastInputResponse
    results: list[RecordedForecastResultResponse]
    repeated: bool
    reused: bool


class ReconstructionResponse(ApiResponse):
    event: SearchEventResponse
    input: ForecastInputResponse | None
    results: list[RecordedForecastResultResponse]


class SavedForecastResponse(ApiResponse):
    analysis_kind: Literal["saved_recorded_forecast"]
    immutable: Literal[True]
    recalculated: Literal[False]
    provider_called: Literal[False]
    event: SearchEventResponse
    input: ForecastInputResponse
    results: list[RecordedForecastResultResponse]


class FreshReconstructionResponse(ApiResponse):
    analysis_kind: Literal["fresh_historical_reconstruction"]
    label: Literal["Fresh historical-cutoff analysis"]
    source_event_id: int
    requested_cutoff: str
    provider_called: Literal[True]
    recalculated: Literal[True]
    provenance: ProvenanceResponse
    event: SearchEventResponse
    input: ForecastInputResponse
    results: list[RecordedForecastResultResponse]
    repeated: bool
    reused: bool


class HistoryResponse(ApiResponse):
    items: list[SearchEventResponse]
    page: int
    page_size: int
    total: int


class HistoryExportFiltersResponse(ApiResponse):
    query: str
    status: Literal["successful", "failed", "repeated"] | None
    asset_type: Literal["stock", "etf"] | None
    analysis_kind: Literal["submitted_forecast", "fresh_historical_reconstruction"] | None


class HistoryEventExportRecord(ApiResponse):
    record_type: Literal["event"]
    event_id: int
    run_id: int | None
    data: SearchEventResponse


class ForecastRunExportRecord(ApiResponse):
    record_type: Literal["run"]
    run_id: int
    input_id: int
    data: ForecastInputResponse


class ForecastResultExportRecord(ApiResponse):
    record_type: Literal["result"]
    run_id: int
    input_id: int
    result_id: int
    data: RecordedForecastResultResponse


class HistoryExportCountsResponse(ApiResponse):
    events: int
    runs: int
    results: int


class HistoryJsonExportResponse(ApiResponse):
    format: Literal["stock-probs-history"]
    format_version: Literal[1]
    generated_at: str
    filters: HistoryExportFiltersResponse
    total_events: int
    exported_events: int
    truncated: bool
    counts: HistoryExportCountsResponse
    records: list[
        HistoryEventExportRecord | ForecastRunExportRecord | ForecastResultExportRecord
    ]


class HistoricalPricesResponse(ApiResponse):
    event_id: int
    symbol: str
    series: Literal["daily", "intraday"]
    interval: Literal["1d", "5m"]
    currency: str
    provider_as_of: str
    quality: Literal["current", "stale"]
    items: list[CapturedBarResponse]
    total_available: int
    truncated: bool


class BackupCountsResponse(ApiResponse):
    searches: int
    forecast_analyses: int
    market_data_snapshots: int
    probability_results: int
    outcome_observations: int


class BackupCreatedResponse(ApiResponse):
    created: Literal[True]
    format: Literal["stock-probs-backup"]
    format_version: int
    created_at: datetime
    checksum_algorithm: Literal["sha256"]
    content_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    counts: BackupCountsResponse


class BackupStatusResponse(ApiResponse):
    status: Literal["available"]
    managed_names_only: bool
    verification_required: bool
    promotion_default: bool
    max_artifact_bytes: int


class RestoreResponse(ApiResponse):
    verified: bool
    promoted: bool
    counts: BackupCountsResponse


logger = logging.getLogger(__name__)


_PUBLIC_BACKUP_COUNT_FIELDS = {
    "searches": "search_events",
    "forecast_analyses": "forecast_runs",
    "market_data_snapshots": "forecast_inputs",
    "probability_results": "forecast_results",
    "outcome_observations": "outcomes",
}


def _public_backup_counts(counts: dict[str, int]) -> dict[str, int]:
    """Map integrity totals to durable product concepts at the API boundary."""

    return {
        public_name: counts[internal_name]
        for public_name, internal_name in _PUBLIC_BACKUP_COUNT_FIELDS.items()
    }


def _public_backup_result(result: dict[str, Any]) -> dict[str, Any]:
    """Translate the operational result into the storage-neutral browser contract."""

    checksum = result.get("content_checksum", result.get("sha256"))
    return {
        "created": True,
        "format": result["format"],
        "format_version": result["format_version"],
        "created_at": result["created_at"],
        "checksum_algorithm": "sha256",
        "content_checksum": checksum,
        "counts": _public_backup_counts(result["counts"]),
    }


def _public_restore_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return verification effects without disclosing a managed server filename."""

    return {
        "verified": result["verified"],
        "promoted": result["promoted"],
        "counts": _public_backup_counts(result["counts"]),
    }


_FRESH_RECONSTRUCTION_PATH = re.compile(
    r"^/api/v1/history/(?P<event_id>[0-9]+)/reconstructions$"
)


def _reconstruction_source_id(path: str) -> int | None:
    matched = _FRESH_RECONSTRUCTION_PATH.fullmatch(path)
    if matched is None:
        return None
    event_id = int(matched.group("event_id"))
    return event_id if 1 <= event_id <= 2_147_483_647 else None


def _reconstruction_submission_context(
    repository: Repository, path: str
) -> tuple[str, str | None, str, int | None] | None:
    """Recover trusted source identity while retaining an unknown requested ID safely."""

    matched = _FRESH_RECONSTRUCTION_PATH.fullmatch(path)
    if matched is None:
        return None
    event_id = _reconstruction_source_id(path)
    if event_id is None:
        return "<invalid history event ID>", None, "invalid", None
    try:
        source = repository.reconstruction(event_id)
    except sqlite3.Error:
        # Framing errors still receive their safe response if local audit lookup is unavailable.
        source = None
    if source is None:
        # The repository accepts this as requested audit metadata and resolves the relationship
        # to null, so an unknown browser ID cannot violate referential integrity.
        return f"<history event {event_id}>", None, "invalid", event_id
    event = source["event"]
    snapshot = source.get("input")
    normalized = snapshot.get("symbol") if isinstance(snapshot, dict) else event.get(
        "normalized_symbol"
    )
    submitted = normalized or event.get("submitted_symbol") or "<historical reconstruction>"
    return (
        str(submitted),
        str(normalized) if normalized else None,
        str(event["asset_type"]),
        event_id,
    )


def _documented_errors(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """Reuse the real safe envelope while documenting only failures applicable to a route."""

    descriptions = {
        400: "The local host or request framing is invalid.",
        403: "The browser origin is not an allowed loopback origin.",
        404: "The requested resource or instrument was not found.",
        405: "The HTTP method is not supported by this resource.",
        409: "The requested recorded data is unavailable for this resource.",
        411: "A bounded Content-Length header is required.",
        413: "The request body exceeds the local API limit.",
        422: "The request or domain input is invalid.",
        500: "The local service could not complete the request.",
        502: "The market-data provider did not return usable data.",
        503: "A required local service or bounded provider slot is unavailable.",
    }
    return {
        status_code: {
            "model": ErrorEnvelope,
            "description": descriptions[status_code],
        }
        for status_code in status_codes
    }


class LocalSecurityMiddleware(BaseHTTPMiddleware):
    """Defend the loopback origin and attach one policy to every response type."""

    allowed_hosts = {"127.0.0.1", "localhost", "::1", "testserver"}
    browser_hosts = {"127.0.0.1", "localhost", "::1"}

    def __init__(
        self, app: ASGIApp, repository: Repository, max_request_bytes: int = 16_384
    ) -> None:
        super().__init__(app)
        self.repository = repository
        self.max_request_bytes = max_request_bytes

    def _record_bounded_rejection(
        self,
        error_code: str,
        error_message: str,
        submitted_symbol: str,
        *,
        normalized_symbol: str | None = None,
        asset_type: str = "invalid",
        analysis_kind: str = "submitted_forecast",
        source_event_id: int | None = None,
    ) -> str | None:
        """Audit a rejected forecast without parsing or retaining its untrusted body."""

        request_id = str(uuid4())
        now = datetime.now(UTC)
        # Persistence requires a cutoff marker for fresh-analysis failures. Before body parsing,
        # the receipt time is the only truthful bounded marker available; error_code records why.
        requested_cutoff = now if analysis_kind == "fresh_historical_reconstruction" else None
        try:
            self.repository.record_failure(
                request_id=request_id,
                submitted_symbol=submitted_symbol,
                normalized_symbol=normalized_symbol,
                asset_type=asset_type,
                error_code=error_code,
                error_message=error_message,
                submitted_at=now,
                completed_at=now,
                analysis_kind=analysis_kind,
                source_event_id=source_event_id,
                requested_cutoff=requested_cutoff,
            )
        except sqlite3.Error:
            # The framing rejection remains safe when local audit persistence is unavailable.
            return None
        return request_id

    def _audit_transport_rejection(
        self,
        request: Request,
        error_code: str,
        error_message: str,
        forecast_label: str,
    ) -> str | None:
        """Append one event only for application submissions, never hostile security probes."""

        reconstruction = _reconstruction_submission_context(self.repository, request.url.path)
        if request.method != "POST" or (
            request.url.path != "/api/v1/forecasts" and reconstruction is None
        ):
            return None
        submitted, normalized, asset, source_event_id = reconstruction or (
            forecast_label,
            None,
            "invalid",
            None,
        )
        return self._record_bounded_rejection(
            error_code,
            error_message,
            submitted,
            normalized_symbol=normalized,
            asset_type=asset,
            analysis_kind=(
                "fresh_historical_reconstruction"
                if reconstruction is not None
                else "submitted_forecast"
            ),
            source_event_id=source_event_id,
        )

    async def _cache_bounded_body(
        self, request: Request, declared_size: int
    ) -> tuple[int, str, str, str] | None:
        """Read at most the application cap and verify framing before FastAPI parses JSON."""

        body = bytearray()
        try:
            async for chunk in request.stream():
                if len(body) + len(chunk) > self.max_request_bytes:
                    return (
                        413,
                        "request_too_large",
                        "Request body exceeds the 16 KiB local API limit.",
                        "<oversized request>",
                    )
                body.extend(chunk)
                if len(body) > declared_size:
                    return (
                        400,
                        "invalid_body_framing",
                        "Request body framing does not match Content-Length.",
                        "<invalid request framing>",
                    )
        except (ClientDisconnect, RuntimeError):
            return (
                400,
                "invalid_body_framing",
                "Request body framing is incomplete or invalid.",
                "<invalid request framing>",
            )
        if len(body) != declared_size:
            return (
                400,
                "invalid_body_framing",
                "Request body framing does not match Content-Length.",
                "<invalid request framing>",
            )
        # BaseHTTPMiddleware's cached-request receive path will replay this bounded body once.
        request._body = bytes(body)
        return None

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Handle Host here instead of TrustedHostMiddleware so its rejection also uses the
        # API error envelope and receives the same headers as every other response. These
        # checks intentionally precede audit handling: hostile browser traffic is not a trusted
        # application submission and must not be able to grow the local event ledger.
        try:
            authority = urlparse(f"//{request.headers.get('host', '')}")
            host_is_allowed = (
                authority.hostname in self.allowed_hosts
                and authority.username is None
                and authority.password is None
                and (authority.port is None or 1 <= authority.port <= 65_535)
            )
        except ValueError:
            host_is_allowed = False
        if not host_is_allowed:
            response: Response = JSONResponse(
                status_code=400,
                content=_error("host_rejected", "Only local service hosts are allowed."),
            )
            return self._secure(response)

        origin = request.headers.get("origin")
        if origin:
            parsed_host = None
            try:
                parsed = urlparse(origin)
                target = request.url
                parsed_host = parsed.hostname
                origin_port = parsed.port
                target_port = target.port
                same_origin = (
                    parsed.scheme == target.scheme
                    and parsed_host == target.hostname
                    and parsed.username is None
                    and parsed.password is None
                    and (origin_port is None or 1 <= origin_port <= 65_535)
                    and (origin_port if origin_port is not None else _default_port(parsed.scheme))
                    == (target_port if target_port is not None else _default_port(target.scheme))
                )
            except ValueError:
                same_origin = False
            if parsed_host not in self.browser_hosts or not same_origin:
                response = JSONResponse(
                    status_code=403,
                    content={
                        "error": {
                            "code": "origin_rejected",
                            "message": "Only loopback origins are allowed.",
                        }
                    },
                )
            else:
                response = await self._bounded_request(request, call_next)
        elif request.headers.get("sec-fetch-site", "").lower() == "cross-site":
            # Modern browsers provide this header even on requests where Origin is omitted.
            response = JSONResponse(
                status_code=403,
                content=_error("origin_rejected", "Cross-site browser requests are not allowed."),
            )
        else:
            response = await self._bounded_request(request, call_next)
        return self._secure(response)

    @staticmethod
    def _secure(response: Response) -> Response:
        """Apply browser isolation even to validation, host, and mounted-asset errors."""

        # Error responses receive the same protections as successful HTML/API responses.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        return response

    async def _bounded_request(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Reject unbounded or inconsistent body framing before FastAPI parses JSON."""

        if request.method not in {"POST", "PUT", "PATCH"}:
            return await call_next(request)

        content_lengths = request.headers.getlist("content-length")
        transfer_encoding = request.headers.get("transfer-encoding")
        if transfer_encoding and content_lengths:
            message = "Content-Length and Transfer-Encoding cannot be combined."
            request_id = self._audit_transport_rejection(
                request,
                "invalid_body_framing",
                message,
                "<invalid request framing>",
            )
            return JSONResponse(
                status_code=400,
                content=_error("invalid_body_framing", message, request_id=request_id),
            )
        if not content_lengths:
            # Chunked input has no trustworthy bound, so reject it without reading any body bytes.
            message = "A bounded Content-Length header is required for request bodies."
            request_id = self._audit_transport_rejection(
                request,
                "content_length_required",
                message,
                "<unbounded request>",
            )
            return JSONResponse(
                status_code=411,
                content=_error(
                    "content_length_required",
                    message,
                    request_id=request_id,
                ),
            )

        content_length = content_lengths[0]
        if (
            len(content_lengths) != 1
            or len(content_length) > 20
            or re.fullmatch(r"[0-9]+", content_length) is None
        ):
            message = "Content-Length must contain one non-negative decimal integer."
            request_id = self._audit_transport_rejection(
                request,
                "invalid_content_length",
                message,
                "<invalid Content-Length>",
            )
            return JSONResponse(
                status_code=400,
                content=_error("invalid_content_length", message, request_id=request_id),
            )

        declared_size = int(content_length)
        if declared_size > self.max_request_bytes:
            message = "Request body exceeds the local API limit."
            request_id = self._audit_transport_rejection(
                request,
                "request_too_large",
                message,
                "<oversized request>",
            )
            return JSONResponse(
                status_code=413,
                content=_error(
                    "request_too_large",
                    "Request body exceeds the 16 KiB local API limit.",
                    request_id=request_id,
                ),
            )

        framing_error = await self._cache_bounded_body(request, declared_size)
        if framing_error is not None:
            status_code, code, message, forecast_label = framing_error
            request_id = self._audit_transport_rejection(
                request, code, message, forecast_label
            )
            return JSONResponse(
                status_code=status_code,
                content=_error(code, message, request_id=request_id),
            )
        return await call_next(request)


def _error(
    code: str, message: str, request_id: str | None = None, details: object | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if request_id:
        payload["error"]["request_id"] = request_id
    if details:
        payload["error"]["details"] = details
    return payload


def _default_port(scheme: str) -> int:
    """Normalize only browser HTTP schemes for exact same-origin comparison."""

    return 443 if scheme == "https" else 80


def _safe_csv_cell(value: object) -> str:
    """Neutralize formulas hidden behind controls, Unicode spacing, or format marks."""

    text = "" if value is None else str(value)
    if text.startswith(("\t", "\r", "\n")):
        return "'" + text
    visible = text
    while visible and (
        visible[0].isspace() or unicodedata.category(visible[0]) in {"Cf", "Zl", "Zp"}
    ):
        visible = visible[1:]
    # Spreadsheet engines differ on which invisible leaders they discard before evaluation.
    return "'" + text if visible.startswith(("=", "+", "-", "@")) else text


def _bounded_history_export(
    repository: Repository,
    *,
    query: str,
    status: str | None,
    asset_type: str | None,
    analysis_kind: str | None,
) -> dict[str, Any]:
    """Build one bounded, storage-neutral event/run/result export for JSON and CSV."""

    history = repository.history(
        query=query,
        status=status,
        asset_type=asset_type,
        page=1,
        page_size=100,
        analysis_kind=analysis_kind,
        include_analysis=True,
    )
    records: list[dict[str, Any]] = []
    seen_runs: set[int] = set()
    run_count = 0
    result_count = 0
    for event in history["items"]:
        event_id = int(event["id"])
        run_id = int(event["run_id"]) if event["run_id"] is not None else None
        records.append(
            {
                "record_type": "event",
                "event_id": event_id,
                "run_id": run_id,
                "data": event,
            }
        )
        if run_id is None or run_id in seen_runs:
            continue
        detail = repository.reconstruction(event_id)
        if detail is None or detail.get("input") is None:
            # A referenced run without its immutable input is a persistence failure, not a
            # partial export that could falsely imply the event was fully preserved.
            raise sqlite3.IntegrityError("forecast run is missing its immutable input")
        seen_runs.add(run_id)
        run_count += 1
        snapshot = detail["input"]
        input_id = int(snapshot["id"])
        records.append(
            {
                "record_type": "run",
                "run_id": run_id,
                "input_id": input_id,
                "data": snapshot,
            }
        )
        for result in detail["results"]:
            result_count += 1
            records.append(
                {
                    "record_type": "result",
                    "run_id": run_id,
                    "input_id": input_id,
                    "result_id": int(result["id"]),
                    "data": result,
                }
            )
    return {
        "format": "stock-probs-history",
        "format_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "filters": {
            "query": query,
            "status": status,
            "asset_type": asset_type,
            "analysis_kind": analysis_kind,
        },
        "total_events": history["total"],
        "exported_events": len(history["items"]),
        "truncated": history["total"] > len(history["items"]),
        "counts": {
            "events": len(history["items"]),
            "runs": run_count,
            "results": result_count,
        },
        "records": records,
    }


def create_app(
    settings: Settings | None = None,
    provider: MarketDataProvider | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    """Build an injectable app so all deterministic tests use temporary SQLite files."""

    config = settings or Settings.from_env()
    repository = Repository(config.database_path)
    selected_provider = provider or (
        FixtureProvider()
        if config.provider == "fixture"
        else YahooProvider(config.provider_timeout)
    )
    # Browser fixtures can pin time without changing live Yahoo's real request clock.
    fixture_now = config.fixture_now
    selected_clock = clock or (
        (lambda: fixture_now) if fixture_now is not None else (lambda: datetime.now(UTC))
    )
    service = ForecastService(repository, selected_provider, selected_clock)
    backups = BackupManager(repository, config.backup_dir)
    static_dir = Path(__file__).parent / "static"

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        config.ensure_local_dirs()
        repository.migrate()
        application.state.ready = True
        try:
            yield
        finally:
            application.state.ready = False

    app = FastAPI(
        title="Stock Probability API",
        version="1.0.0",
        # Swagger's CDN and inline bootstrap conflict with the intentionally strict local CSP.
        docs_url=None,
        openapi_url="/api/v1/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.repository = repository
    app.state.service = service
    app.state.backups = backups
    app.state.ready = False
    app.add_middleware(LocalSecurityMiddleware, repository=repository)

    def record_submitted_failure(
        *,
        submitted_symbol: str,
        normalized_symbol: str | None,
        asset_type: str,
        error_code: str,
        error_message: str,
        analysis_kind: str = "submitted_forecast",
        source_event_id: int | None = None,
        requested_cutoff: datetime | None = None,
    ) -> str:
        """Append one transport-classified event when no service call will own the audit."""

        request_id = str(uuid4())
        now = datetime.now(UTC)
        if analysis_kind == "fresh_historical_reconstruction" and requested_cutoff is None:
            # Validation can fail before a cutoff exists; preserve one labelled event using its
            # receipt time rather than retaining or reparsing an untrusted body value.
            requested_cutoff = now
        repository.record_failure(
            request_id=request_id,
            submitted_symbol=submitted_symbol,
            normalized_symbol=normalized_symbol,
            asset_type=asset_type,
            error_code=error_code,
            error_message=error_message,
            submitted_at=now,
            completed_at=now,
            analysis_kind=analysis_kind,
            source_event_id=source_event_id,
            requested_cutoff=requested_cutoff,
        )
        return request_id

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error(exc.code, exc.message, request_id=exc.request_id),
        )

    @app.exception_handler(BackupError)
    async def backup_error(request: Request, exc: BackupError) -> JSONResponse:
        request_id = str(uuid4())
        restoring = request.url.path == "/api/v1/operations/restores"
        code = "restore_failed" if restoring else "backup_creation_failed"
        message = (
            "The backup artifact could not be verified or restored."
            if restoring
            else "The backup artifact could not be created."
        )
        # Raw exception text and tracebacks can contain local names or paths. The stable
        # operation/code/type tuple remains useful for correlation without logging either.
        logger.error(
            "Backup operation failed request_id=%s operation=%s code=%s exception_type=%s",
            request_id,
            "restore" if restoring else "create",
            code,
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=422,
            content=_error(code, message, request_id=request_id),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic details are safe field/type facts; never include body values or local paths.
        details = [
            {"location": list(item["loc"]), "message": item["msg"], "type": item["type"]}
            for item in exc.errors()
        ]
        request_id = None
        if request.url.path in {
            "/api/v1/operations/backups",
            "/api/v1/operations/restores",
        }:
            # Unknown field names are attacker-controlled. Keep operational validation useful
            # without reflecting a local-looking path or implementation term into the browser.
            details = []
            request_id = str(uuid4())
        elif request.method == "POST" and request.url.path == "/api/v1/forecasts":
            # Transport-invalid forecast attempts are still append-only submitted searches.
            body = exc.body if isinstance(exc.body, dict) else {}
            raw_symbol = body.get("symbol")
            submitted_symbol = raw_symbol if isinstance(raw_symbol, str) else "<invalid request>"
            raw_asset = body.get("asset_type")
            asset_type = raw_asset if raw_asset in {"stock", "etf"} else "invalid"
            request_id = record_submitted_failure(
                submitted_symbol=submitted_symbol,
                normalized_symbol=None,
                asset_type=asset_type,
                error_code="validation_error",
                error_message="Request validation failed.",
            )
        elif request.method == "POST":
            reconstruction_context = _reconstruction_submission_context(
                repository, request.url.path
            )
            if reconstruction_context is not None:
                (
                    submitted_symbol,
                    normalized_symbol,
                    asset_type,
                    source_event_id,
                ) = reconstruction_context
                body = exc.body if isinstance(exc.body, dict) else {}
                raw_cutoff = body.get("cutoff")
                try:
                    requested_cutoff = (
                        datetime.fromisoformat(raw_cutoff)
                        if isinstance(raw_cutoff, str)
                        else None
                    )
                except ValueError:
                    requested_cutoff = None
                request_id = record_submitted_failure(
                    submitted_symbol=submitted_symbol,
                    normalized_symbol=normalized_symbol,
                    asset_type=asset_type,
                    error_code="validation_error",
                    error_message="Historical reconstruction validation failed.",
                    analysis_kind="fresh_historical_reconstruction",
                    source_event_id=source_event_id,
                    requested_cutoff=requested_cutoff,
                )
        return JSONResponse(
            status_code=422,
            content=_error(
                "validation_error",
                "Request validation failed.",
                request_id=request_id,
                details=details,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # The Starlette base class also catches router and mounted StaticFiles 404/405 errors.
        code, message = {
            404: ("not_found", "The requested resource was not found."),
            405: ("method_not_allowed", "The request method is not allowed for this resource."),
            409: ("forecast_unavailable", "The requested recorded data is unavailable."),
            503: ("service_unavailable", "The local service is not ready."),
        }.get(exc.status_code, ("http_error", "The request could not be served."))
        return JSONResponse(
            status_code=exc.status_code,
            content=_error(code, message),
            headers=exc.headers,
        )

    @app.exception_handler(RepositoryError)
    @app.exception_handler(sqlite3.Error)
    async def repository_error(request: Request, exc: sqlite3.Error) -> JSONResponse:
        request_id = str(uuid4())
        backup_operation = request.url.path.startswith("/api/v1/operations/")
        code = "operation_unavailable" if backup_operation else "persistence_unavailable"
        message = (
            "The requested backup operation is temporarily unavailable."
            if backup_operation
            else "Local history storage is unavailable."
        )
        logger.error(
            "Local operation unavailable request_id=%s operation=%s code=%s exception_type=%s",
            request_id,
            "backup" if backup_operation else "history",
            code,
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=503,
            content=_error(code, message, request_id=request_id),
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Correlate unexpected failures without logging exception text, request data, or paths.
        request_id = str(uuid4())
        operation = {
            "/api/v1/operations/backups": "backup-create",
            "/api/v1/operations/backups/status": "backup-status",
            "/api/v1/operations/restores": "restore",
        }.get(request.url.path, "application")
        logger.error(
            "Unexpected application failure request_id=%s operation=%s code=internal_error "
            "exception_type=%s",
            request_id,
            operation,
            type(exc).__name__,
        )
        # Fail closed with a JSON envelope rather than exposing a traceback or provider detail.
        return JSONResponse(
            status_code=500,
            content=_error(
                "internal_error",
                "The local service could not complete the request.",
                request_id=request_id,
            ),
        )

    @app.get(
        "/api/v1/health",
        response_model=HealthResponse,
        responses=_documented_errors(400, 403, 405, 500),
    )
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "stock-probs", "api_version": "v1"}

    @app.get(
        "/api/v1/readiness",
        response_model=ReadinessResponse,
        responses=_documented_errors(400, 403, 405, 500, 503),
    )
    def readiness() -> dict[str, Any]:
        if not app.state.ready:
            raise HTTPException(status_code=503)
        # Ask through the repository boundary; transport code must not grow storage-specific SQL.
        repository.representative_counts()
        return {"status": "ready", "schema_version": SCHEMA_VERSION, "provider": config.provider}

    @app.get(
        "/api/v1/instruments",
        response_model=InstrumentLookupResponse,
        responses=_documented_errors(400, 403, 405, 422, 500, 502, 503),
    )
    def instrument_lookup(
        query: str = Query(min_length=1, max_length=80),
        limit: int = Query(default=5, ge=1, le=5),
    ) -> dict[str, Any]:
        """Resolve a bounded company/symbol query without detaching names from identity."""

        # Resolve through app state so transport tests and runtime integrations share the
        # service's provider concurrency, normalization, and exception boundary.
        return cast(dict[str, Any], app.state.service.lookup(query, limit))

    @app.post(
        "/api/v1/forecasts",
        status_code=201,
        response_model=ForecastCreationResponse,
        response_model_exclude_unset=True,
        responses=_documented_errors(400, 403, 404, 405, 411, 413, 422, 500, 502, 503),
    )
    def create_forecast(payload: SearchRequest) -> dict[str, Any]:
        return service.search(payload.symbol, payload.asset_type)

    @app.get(
        "/api/v1/history",
        response_model=HistoryResponse,
        responses=_documented_errors(400, 403, 405, 422, 500, 503),
    )
    def history(
        q: str = Query(default="", max_length=30),
        status: Literal["successful", "failed", "repeated"] | None = Query(default=None),
        asset_type: Literal["stock", "etf"] | None = Query(default=None),
        analysis_kind: Literal[
            "submitted_forecast", "fresh_historical_reconstruction"
        ]
        | None = Query(default=None),
        page: int = Query(default=1, ge=1, le=10_000),
        page_size: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        return repository.history(
            query=q.strip().upper(),
            status=status,
            asset_type=asset_type,
            page=page,
            page_size=page_size,
            analysis_kind=analysis_kind,
            include_analysis=True,
        )

    @app.get(
        "/api/v1/history-export.csv",
        response_class=Response,
        responses={
            200: {
                "description": "Bounded CSV search-history export.",
                "content": {"text/csv": {"schema": {"type": "string"}}},
            },
            **_documented_errors(400, 403, 405, 422, 500, 503),
        },
    )
    @app.get("/api/v1/history/export.csv", include_in_schema=False)
    def history_export(
        q: str = Query(default="", max_length=30),
        status: Literal["successful", "failed", "repeated"] | None = Query(default=None),
        asset_type: Literal["stock", "etf"] | None = Query(default=None),
        analysis_kind: Literal[
            "submitted_forecast", "fresh_historical_reconstruction"
        ]
        | None = Query(default=None),
    ) -> Response:
        # Both formats share one record construction so CSV cannot silently omit audit identity.
        exported = _bounded_history_export(
            repository,
            query=q.strip().upper(),
            status=status,
            asset_type=asset_type,
            analysis_kind=analysis_kind,
        )
        output = io.StringIO()
        fieldnames = [
            "record_type",
            "event_id",
            "run_id",
            "input_id",
            "result_id",
            "request_id",
            "submitted_symbol",
            "normalized_symbol",
            "asset_type",
            "status",
            "is_repeat",
            "analysis_kind",
            "source_event_id",
            "requested_cutoff",
            "error_code",
            "company_name",
            "canonical_symbol",
            "exchange",
            "quote_type",
            "horizon",
            "submitted_at",
            "record_json",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for record in exported["records"]:
            data = record["data"]
            identity = data.get("instrument_identity", {})
            row = {
                **record,
                **data,
                "company_name": identity.get("company_name", data.get("company_name")),
                "canonical_symbol": identity.get("canonical_symbol", data.get("canonical_symbol")),
                "exchange": identity.get("exchange", data.get("exchange")),
                "quote_type": identity.get("quote_type", data.get("quote_type")),
                "record_json": json.dumps(
                    data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
            }
            writer.writerow({key: _safe_csv_cell(row.get(key)) for key in fieldnames})
        return Response(
            output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="stock-probs-history.csv"'},
        )

    @app.get(
        "/api/v1/history-export.json",
        response_model=HistoryJsonExportResponse,
        response_model_exclude_unset=True,
        responses=_documented_errors(400, 403, 405, 422, 500, 503),
    )
    @app.get("/api/v1/history/export.json", include_in_schema=False)
    def history_export_json(
        q: str = Query(default="", max_length=30),
        status: Literal["successful", "failed", "repeated"] | None = Query(default=None),
        asset_type: Literal["stock", "etf"] | None = Query(default=None),
        analysis_kind: Literal[
            "submitted_forecast", "fresh_historical_reconstruction"
        ]
        | None = Query(default=None),
    ) -> dict[str, Any]:
        """Export a bounded set of typed audit records."""

        return _bounded_history_export(
            repository,
            query=q.strip().upper(),
            status=status,
            asset_type=asset_type,
            analysis_kind=analysis_kind,
        )

    @app.get(
        "/api/v1/history/{event_id}",
        response_model=ReconstructionResponse,
        response_model_exclude_unset=True,
        responses=_documented_errors(400, 403, 404, 405, 422, 500, 503),
    )
    def reconstruction(
        event_id: int = PathParameter(ge=1, le=2_147_483_647),
    ) -> dict[str, Any]:
        result = repository.reconstruction(event_id)
        if result is None:
            raise HTTPException(status_code=404, detail="history event not found")
        return result

    @app.get(
        "/api/v1/saved-forecasts/{event_id}",
        response_model=SavedForecastResponse,
        response_model_exclude_unset=True,
        responses=_documented_errors(400, 403, 404, 405, 409, 422, 500, 503),
    )
    def saved_forecast(
        event_id: int = PathParameter(ge=1, le=2_147_483_647),
    ) -> dict[str, Any]:
        """Reopen an immutable recorded forecast without recalculation or provider access."""

        recorded = repository.reconstruction(event_id)
        if recorded is None:
            raise HTTPException(status_code=404, detail="history event not found")
        if recorded.get("input") is None:
            raise HTTPException(status_code=409, detail="failed searches have no saved forecast")
        return {
            "analysis_kind": "saved_recorded_forecast",
            "immutable": True,
            "recalculated": False,
            "provider_called": False,
            **recorded,
        }

    @app.post(
        "/api/v1/history/{event_id}/reconstructions",
        status_code=201,
        response_model=FreshReconstructionResponse,
        response_model_exclude_unset=True,
        responses=_documented_errors(400, 403, 404, 405, 409, 411, 413, 422, 500, 502, 503),
    )
    def fresh_historical_reconstruction(
        payload: FreshReconstructionRequest,
        event_id: int = PathParameter(ge=1, le=2_147_483_647),
    ) -> dict[str, Any]:
        """Run a newly audited analysis at a cutoff, never relabel a saved result as fresh."""

        generated = cast(
            dict[str, Any],
            # This one service call owns both the new event and its success/failure status.
            service.fresh_historical_reconstruction(event_id, payload.cutoff),
        )
        provenance = dict(generated["input"]["provenance"])
        analysis = provenance.get("analysis")
        if not isinstance(analysis, dict):
            query = provenance.get("query", {})
            analysis = query.get("analysis") if isinstance(query, dict) else None
        if isinstance(analysis, dict):
            # Promote the fresh-analysis marker to a stable transport field while retaining the
            # exact provider query that forms part of immutable persistence provenance.
            provenance["analysis"] = analysis
            provenance["provider_content_fingerprint"] = analysis.get(
                "provider_content_fingerprint"
            )
        return {
            **generated,
            "source_event_id": event_id,
            "requested_cutoff": payload.cutoff.astimezone(UTC).isoformat(),
            "provider_called": True,
            "recalculated": True,
            "provenance": provenance,
        }

    @app.get(
        "/api/v1/history/{event_id}/prices",
        response_model=HistoricalPricesResponse,
        responses=_documented_errors(400, 403, 404, 405, 409, 422, 500, 503),
    )
    def historical_prices(
        event_id: int = PathParameter(ge=1, le=2_147_483_647),
        series: str = Query(default="daily", pattern="^(daily|intraday)$"),
        limit: int = Query(default=120, ge=1, le=500),
    ) -> dict[str, Any]:
        """Expose bounded captured prices, never a fresh provider or browser-side query."""

        reconstruction = repository.reconstruction(event_id)
        if reconstruction is None:
            raise HTTPException(status_code=404, detail="history event not found")
        snapshot = reconstruction.get("input")
        if snapshot is None:
            raise HTTPException(status_code=409, detail="failed searches have no captured prices")
        key = "selected_daily_bars" if series == "daily" else "selected_intraday_bars"
        available = snapshot.get(key, [])
        items = available[-limit:]
        return {
            "event_id": event_id,
            "symbol": snapshot["symbol"],
            "series": series,
            "interval": "1d" if series == "daily" else "5m",
            "currency": snapshot["currency"],
            "provider_as_of": snapshot["provider_as_of"],
            "quality": snapshot["quality"],
            "items": items,
            "total_available": len(available),
            "truncated": len(items) < len(available),
        }

    @app.get(
        "/api/v1/forecasts/{result_id}",
        response_model=OriginalForecastResultResponse,
        response_model_exclude_unset=True,
        responses=_documented_errors(400, 403, 404, 405, 422, 500, 503),
    )
    def original_forecast_result(
        result_id: int = PathParameter(ge=1, le=2_147_483_647),
    ) -> dict[str, Any]:
        """Return the immutable recorded result without folding later outcomes into it."""

        result = repository.forecast_result(result_id)
        if result is None:
            raise HTTPException(status_code=404, detail="forecast result not found")
        return {"id": result_id, "immutable": True, **result}

    @app.post(
        "/api/v1/forecasts/{result_id}/outcomes",
        status_code=201,
        response_model=OutcomeResponse,
        responses=_documented_errors(400, 403, 404, 405, 411, 413, 422, 500, 503),
    )
    def append_outcome(
        payload: OutcomeRequest,
        result_id: int = PathParameter(ge=1, le=2_147_483_647),
    ) -> dict[str, Any]:
        result = service.append_outcome(
            result_id, payload.observed_close, payload.observed_at, payload.state, payload.note
        )
        if result is None:
            raise HTTPException(status_code=404, detail="forecast result not found")
        return result

    @app.post(
        "/api/v1/forecasts/{result_id}/corrections",
        status_code=201,
        response_model=OutcomeResponse,
        responses=_documented_errors(400, 403, 404, 405, 411, 413, 422, 500, 503),
    )
    def append_correction(
        payload: CorrectionRequest,
        result_id: int = PathParameter(ge=1, le=2_147_483_647),
    ) -> dict[str, Any]:
        """Make correction append semantics explicit instead of offering an update verb."""

        result = service.append_outcome(
            result_id,
            payload.observed_close,
            payload.observed_at,
            "corrected",
            payload.note,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="forecast result not found")
        return result

    @app.post(
        "/api/v1/operations/backups",
        status_code=201,
        response_model=BackupCreatedResponse,
        responses=_documented_errors(400, 403, 405, 411, 413, 422, 500, 503),
    )
    def create_backup(payload: BackupRequest) -> dict[str, Any]:
        return _public_backup_result(backups.create(payload.name))

    @app.get(
        "/api/v1/operations/backups/status",
        response_model=BackupStatusResponse,
        responses=_documented_errors(400, 403, 405, 500, 503),
    )
    def backup_status() -> dict[str, Any]:
        """Report bounded managed backup capabilities."""

        repository.representative_counts()
        return {
            "status": "available",
            "managed_names_only": True,
            "verification_required": True,
            "promotion_default": False,
            "max_artifact_bytes": MAX_BACKUP_BYTES,
        }

    @app.post(
        "/api/v1/operations/restores",
        response_model=RestoreResponse,
        response_model_exclude_unset=True,
        responses=_documented_errors(400, 403, 405, 411, 413, 422, 500, 503),
    )
    def restore_backup(payload: RestoreRequest) -> dict[str, Any]:
        return _public_restore_result(backups.restore(payload.name, promote=payload.promote))

    @app.get("/api/v1/docs", include_in_schema=False)
    def api_docs() -> FileResponse:
        """Serve a CSP-compatible, dependency-free pointer to the machine-readable contract."""

        return FileResponse(static_dir / "api-docs.html")

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    app.mount("/assets", StaticFiles(directory=static_dir), name="assets")
    return app


app = create_app()
