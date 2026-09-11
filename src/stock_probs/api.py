"""FastAPI application exposes the sole browser data boundary under /api/v1."""

from __future__ import annotations

import csv
import io
import sqlite3
import unicodedata
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi import Path as PathParameter
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from stock_probs.backup import MAX_BACKUP_BYTES, BackupError, BackupManager
from stock_probs.config import Settings
from stock_probs.domain import DomainError
from stock_probs.provider import FixtureProvider, MarketDataProvider, YahooProvider
from stock_probs.repository import SCHEMA_VERSION, Repository
from stock_probs.schemas import BackupRequest, OutcomeRequest, RestoreRequest, SearchRequest
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
    is_repeat: int
    error_code: str | None
    error_message: str | None
    submitted_at: str
    completed_at: str
    run_id: int | None


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


class ProvenanceResponse(ApiResponse):
    source: str
    query: dict[str, Any]
    response_as_of: str
    content_fingerprint: str
    model_version: str
    calendar_version: str


class ForecastInputResponse(ApiResponse):
    id: int
    symbol: str
    asset_type: Literal["stock", "etf"]
    exchange: str
    exchange_timezone: str
    currency: str
    provider: str
    provider_as_of: str
    request_cutoff: str
    provider_query: dict[str, Any]
    provider_metadata: dict[str, Any]
    content_fingerprint: str
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


class HistoryResponse(ApiResponse):
    items: list[SearchEventResponse]
    page: int
    page_size: int
    total: int


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
    search_events: int
    forecast_runs: int
    forecast_inputs: int
    forecast_results: int
    outcomes: int


class BackupCreatedResponse(ApiResponse):
    name: str
    sha256: str
    format: Literal["stock-probs-backup"]
    format_version: int
    schema_version: int
    schema_sha256: str
    created_at: str
    database_sha256: str
    database_size: int
    counts: BackupCountsResponse
    manifest_hmac_sha256: str


class BackupStatusResponse(ApiResponse):
    status: Literal["available"]
    managed_names_only: bool
    verification_required: bool
    promotion_default: bool
    max_artifact_bytes: int


class RestoreResponse(ApiResponse):
    name: str
    verified: bool
    promoted: bool
    counts: BackupCountsResponse
    rollback_cleanup_required: bool | None = None


def _documented_errors(*status_codes: int) -> dict[int, dict[str, Any]]:
    """Reuse the real safe envelope while documenting only failures applicable to a route."""

    return {
        status_code: {"model": ErrorEnvelope, "description": "Structured local API error."}
        for status_code in status_codes
    }


class LocalSecurityMiddleware(BaseHTTPMiddleware):
    """Defend the loopback origin and attach one policy to every response type."""

    allowed_hosts = {"127.0.0.1", "localhost", "::1", "testserver"}
    browser_hosts = {"127.0.0.1", "localhost", "::1"}

    def __init__(self, app, repository: Repository, max_request_bytes: int = 16_384):
        super().__init__(app)
        self.repository = repository
        self.max_request_bytes = max_request_bytes

    def _record_bounded_rejection(
        self, error_code: str, error_message: str, submitted_symbol: str
    ) -> str:
        """Audit a rejected forecast without parsing or retaining its untrusted body."""

        request_id = str(uuid4())
        now = datetime.now(UTC)
        self.repository.record_failure(
            request_id=request_id,
            submitted_symbol=submitted_symbol,
            normalized_symbol=None,
            asset_type="invalid",
            error_code=error_code,
            error_message=error_message,
            submitted_at=now,
            completed_at=now,
        )
        return request_id

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Handle Host here instead of TrustedHostMiddleware so its rejection also uses the
        # API error envelope and receives the same headers as every other response.
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

    async def _bounded_request(self, request: Request, call_next: Callable) -> Response:
        """Reject declared oversized bodies before FastAPI allocates or validates JSON."""

        content_length = request.headers.get("content-length")
        if request.method in {"POST", "PUT", "PATCH"} and content_length is None:
            # Uvicorn accepts chunked bodies, but buffering one would defeat the local memory cap.
            request_id = (
                self._record_bounded_rejection(
                    "content_length_required",
                    "A bounded Content-Length header is required for request bodies.",
                    "<unbounded request>",
                )
                if request.method == "POST" and request.url.path == "/api/v1/forecasts"
                else None
            )
            return JSONResponse(
                status_code=411,
                content=_error(
                    "content_length_required",
                    "A bounded Content-Length header is required for request bodies.",
                    request_id=request_id,
                ),
            )
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content=_error("invalid_content_length", "Content-Length must be an integer."),
                )
            if declared_size < 0:
                return JSONResponse(
                    status_code=400,
                    content=_error("invalid_content_length", "Content-Length cannot be negative."),
                )
            oversized = declared_size > self.max_request_bytes
            if oversized:
                request_id = (
                    self._record_bounded_rejection(
                        "request_too_large",
                        "Request body exceeds the local API limit.",
                        "<oversized request>",
                    )
                    if request.method == "POST" and request.url.path == "/api/v1/forecasts"
                    else None
                )
                return JSONResponse(
                    status_code=413,
                    content=_error(
                        "request_too_large",
                        "Request body exceeds the 16 KiB local API limit.",
                        request_id=request_id,
                    ),
                )
        return await call_next(request)


def _error(
    code: str, message: str, request_id: str | None = None, details: object | None = None
) -> dict:
    payload: dict = {"error": {"code": code, "message": message}}
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


def create_app(
    settings: Settings | None = None,
    provider: MarketDataProvider | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    """Build an injectable app so all deterministic tests use temporary SQLite files."""

    config = settings or Settings.from_env()
    config.ensure_local_dirs()
    repository = Repository(config.database_path)
    selected_provider = provider or (
        FixtureProvider()
        if config.provider == "fixture"
        else YahooProvider(config.provider_timeout)
    )
    # Browser fixtures can pin time without changing live Yahoo's real request clock.
    selected_clock = clock or ((lambda: config.fixture_now) if config.fixture_now else None)
    service = ForecastService(repository, selected_provider, selected_clock)
    backups = BackupManager(repository, config.backup_dir)
    static_dir = Path(__file__).parent / "static"

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        repository.migrate()
        yield

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
    app.add_middleware(LocalSecurityMiddleware, repository=repository)

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error(exc.code, exc.message, request_id=exc.request_id),
        )

    @app.exception_handler(BackupError)
    async def backup_error(request: Request, exc: BackupError) -> JSONResponse:
        # Restore failures are operationally distinct from backup-creation failures.
        code = "restore_failure" if request.url.path.endswith("/restores") else "backup_failure"
        return JSONResponse(status_code=422, content=_error(code, str(exc)))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic details are safe field/type facts; never include body values or local paths.
        details = [
            {"location": list(item["loc"]), "message": item["msg"], "type": item["type"]}
            for item in exc.errors()
        ]
        request_id = None
        if request.method == "POST" and request.url.path == "/api/v1/forecasts":
            # Transport-invalid forecast attempts are still append-only submitted searches.
            body = exc.body if isinstance(exc.body, dict) else {}
            raw_symbol = body.get("symbol")
            submitted_symbol = raw_symbol if isinstance(raw_symbol, str) else "<invalid request>"
            raw_asset = body.get("asset_type")
            asset_type = raw_asset if raw_asset in {"stock", "etf"} else "invalid"
            request_id = str(uuid4())
            now = datetime.now(UTC)
            repository.record_failure(
                request_id=request_id,
                submitted_symbol=submitted_symbol,
                normalized_symbol=None,
                asset_type=asset_type,
                error_code="validation_error",
                error_message="Request validation failed.",
                submitted_at=now,
                completed_at=now,
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
        code = {
            404: "not_found",
            409: "forecast_unavailable",
            405: "method_not_allowed",
            503: "service_unavailable",
        }.get(exc.status_code, "http_error")
        message = (
            str(exc.detail)
            if isinstance(exc.detail, str)
            else "The request could not be served."
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error(code, message),
            headers=exc.headers,
        )

    @app.exception_handler(sqlite3.Error)
    async def persistence_error(_: Request, __: sqlite3.Error) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content=_error("persistence_unavailable", "Local history storage is unavailable."),
        )

    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, __: Exception) -> JSONResponse:
        # Fail closed with a JSON envelope rather than exposing a traceback or provider detail.
        return JSONResponse(
            status_code=500,
            content=_error("internal_error", "The local service could not complete the request."),
        )

    @app.get(
        "/api/v1/health",
        response_model=HealthResponse,
        responses=_documented_errors(400, 403, 405, 500),
    )
    def health() -> HealthResponse:
        return {"status": "ok", "service": "stock-probs", "api_version": "v1"}

    @app.get(
        "/api/v1/readiness",
        response_model=ReadinessResponse,
        responses=_documented_errors(400, 403, 405, 500, 503),
    )
    def readiness() -> ReadinessResponse:
        # Ask through the repository boundary; transport code must not grow storage-specific SQL.
        repository.representative_counts()
        return {"status": "ready", "schema_version": SCHEMA_VERSION, "provider": config.provider}

    @app.post(
        "/api/v1/forecasts",
        status_code=201,
        response_model=ForecastCreationResponse,
        response_model_exclude_unset=True,
        responses=_documented_errors(400, 403, 405, 411, 413, 422, 500, 502, 503),
    )
    def create_forecast(payload: SearchRequest) -> ForecastCreationResponse:
        return service.search(payload.symbol, payload.asset_type)

    @app.get(
        "/api/v1/history",
        response_model=HistoryResponse,
        responses=_documented_errors(400, 403, 405, 422, 500, 503),
    )
    def history(
        q: str = Query(default="", max_length=30),
        status: str | None = Query(default=None, pattern="^(successful|failed|repeated)$"),
        asset_type: str | None = Query(default=None, pattern="^(stock|etf)$"),
        page: int = Query(default=1, ge=1, le=10_000),
        page_size: int = Query(default=20, ge=1, le=100),
    ) -> HistoryResponse:
        return repository.history(
            query=q.strip().upper(),
            status=status,
            asset_type=asset_type,
            page=page,
            page_size=page_size,
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
        status: str | None = Query(default=None, pattern="^(successful|failed|repeated)$"),
        asset_type: str | None = Query(default=None, pattern="^(stock|etf)$"),
    ) -> Response:
        # Exports are deliberately capped; users can filter rather than allocating unbounded memory.
        result = repository.history(
            query=q.strip().upper(),
            status=status,
            asset_type=asset_type,
            page=1,
            page_size=100,
        )
        output = io.StringIO()
        fieldnames = [
            "id",
            "submitted_symbol",
            "normalized_symbol",
            "asset_type",
            "status",
            "error_code",
            "submitted_at",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(
            {key: _safe_csv_cell(item.get(key)) for key in fieldnames} for item in result["items"]
        )
        return Response(
            output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="stock-probs-history.csv"'},
        )

    @app.get(
        "/api/v1/history/{event_id}",
        response_model=ReconstructionResponse,
        response_model_exclude_unset=True,
        responses=_documented_errors(400, 403, 404, 405, 422, 500, 503),
    )
    def reconstruction(
        event_id: int = PathParameter(ge=1, le=2_147_483_647),
    ) -> ReconstructionResponse:
        result = repository.reconstruction(event_id)
        if result is None:
            raise HTTPException(status_code=404, detail="history event not found")
        return result

    @app.get(
        "/api/v1/history/{event_id}/prices",
        response_model=HistoricalPricesResponse,
        responses=_documented_errors(400, 403, 404, 405, 409, 422, 500, 503),
    )
    def historical_prices(
        event_id: int = PathParameter(ge=1, le=2_147_483_647),
        series: str = Query(default="daily", pattern="^(daily|intraday)$"),
        limit: int = Query(default=120, ge=1, le=500),
    ) -> HistoricalPricesResponse:
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
    ) -> OriginalForecastResultResponse:
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
    ) -> OutcomeResponse:
        result = service.append_outcome(
            result_id, payload.observed_close, payload.observed_at, payload.state, payload.note
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
    def create_backup(payload: BackupRequest) -> BackupCreatedResponse:
        return backups.create(payload.name)

    @app.get(
        "/api/v1/operations/backups/status",
        response_model=BackupStatusResponse,
        responses=_documented_errors(400, 403, 405, 500, 503),
    )
    def backup_status() -> BackupStatusResponse:
        """Advertise bounded managed operations without disclosing server paths or filenames."""

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
    def restore_backup(payload: RestoreRequest) -> RestoreResponse:
        return backups.restore(payload.name, promote=payload.promote)

    @app.get("/api/v1/docs", include_in_schema=False)
    def api_docs() -> FileResponse:
        """Serve a CSP-compatible, dependency-free pointer to the machine-readable contract."""

        return FileResponse(static_dir / "api-docs.html")

    @app.get("/")
    def dashboard() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    app.mount("/assets", StaticFiles(directory=static_dir), name="assets")
    return app


app = create_app()
