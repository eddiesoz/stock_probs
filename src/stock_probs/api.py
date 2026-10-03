"""FastAPI application exposes the sole browser data boundary under /api/v1."""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import ipaddress
import json
import logging
import re
import sqlite3
import threading
import time
import unicodedata
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager, suppress
from datetime import UTC, date, datetime
from functools import partial
from html.parser import HTMLParser
from inspect import signature
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from urllib.parse import ParseResult, quote, urlparse
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi import Path as PathParameter
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, model_validator
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import ClientDisconnect
from starlette.types import ASGIApp

from stock_probs.auth import (
    CSRF_COOKIE_NAME,
    OAUTH_TRANSACTION_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    AuthContext,
    AuthenticationRequired,
    AuthError,
    AuthManager,
    AuthorizationDenied,
    AuthUnavailable,
    InvitationRejected,
    OAuthStartLimited,
    PasskeyBackend,
    UserRecord,
)
from stock_probs.backup import MAX_BACKUP_BYTES, BackupError, BackupManager
from stock_probs.config import Settings
from stock_probs.domain import FORECAST_INTERVAL_HORIZONS, DomainError, normalize_symbol
from stock_probs.invitation_mail import send_invitation_email
from stock_probs.provider import FixtureProvider, MarketDataProvider, YahooProvider
from stock_probs.repository import SCHEMA_VERSION, Repository, RepositoryError
from stock_probs.schemas import (
    AuthEmailInvitationRequest,
    AuthEmailInvitationResponse,
    AuthInvitationRedeemRequest,
    AuthInvitationRequest,
    AuthInvitationResponse,
    AuthLoginResponse,
    AuthSessionResponse,
    BackupRequest,
    ChartRange,
    CorrectionRequest,
    ForecastHorizon,
    ForecastInterval,
    FreshReconstructionRequest,
    HistoryAnalysisKind,
    HistorySortField,
    HistoryStatus,
    InstrumentIdentityResponse,
    InstrumentListMutationRequest,
    InstrumentLookupResponse,
    LocalLoginRequest,
    NewsQuery,
    NewsResponse,
    OutcomeRequest,
    PasskeyOptionsResponse,
    PasskeyResponseRequest,
    RestoreRequest,
    SearchRequest,
    SortDirection,
)
from stock_probs.service import ForecastService


class ApiResponse(BaseModel):
    """Keep generated success and error contracts concrete and closed to undocumented fields."""

    model_config = ConfigDict(extra="forbid")


Probability = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
PositivePrice = Annotated[float, Field(gt=0.0, allow_inf_nan=False)]
FiniteNumber = Annotated[float, Field(allow_inf_nan=False)]
ThresholdPercent = Annotated[
    float,
    Field(
        allow_inf_nan=False,
        json_schema_extra={"enum": [-1.0, -3.0, -5.0, -10.0, 1.0, 3.0, 5.0, 10.0]},
    ),
]
IntervalLevel = Annotated[
    float, Field(ge=0.0, le=1.0, allow_inf_nan=False, json_schema_extra={"enum": [0.5, 0.8, 0.95]})
]
HistoryStatusParameter = Annotated[HistoryStatus | None, Query()]
HistoryAnalysisParameter = Annotated[HistoryAnalysisKind | None, Query()]
HistoryDateParameter = Annotated[datetime | None, Query()]
HistoryHorizonParameter = Annotated[ForecastHorizon | None, Query()]
HistorySortParameter = Annotated[HistorySortField, Query()]
SortDirectionParameter = Annotated[SortDirection, Query()]
ForecastIntervalParameter = Annotated[ForecastInterval | None, Query()]


def _safe_local_next(value: str | None, default: str = "/overview") -> str:
    """Keep redirects on this origin while preserving a valid local route."""

    if not isinstance(value, str) or not value or len(value) > 1024:
        return default
    if not value.startswith("/") or value.startswith("//"):
        return default
    if any(ord(character) < 0x20 or character in "\\\r\n" for character in value):
        return default
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or parsed.path.startswith("//"):
        return default
    return value


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


class TotpCodeRequest(ApiResponse):
    """Bounded authenticator input; recovery-code routes apply their own format check."""

    code: str = Field(min_length=6, max_length=39)


class TotpEnrollmentStartRequest(ApiResponse):
    """Optional explicit request to rotate an existing pending enrollment."""

    replace: StrictBool = False


class TotpStatusApiResponse(ApiResponse):
    """Public factor state with no secret or recovery-code material."""

    enrolled: bool
    enrollment_pending: bool
    recovery_codes_remaining: int = Field(ge=0, le=20)
    requires_totp: bool
    can_enroll: bool


class TotpEnrollmentStartApiResponse(ApiResponse):
    """Short-lived TOTP enrollment material returned exactly during setup."""

    enrollment: Literal[True]
    secret: str = Field(min_length=16, max_length=64)
    otpauth_uri: str = Field(min_length=32, max_length=512)
    expires_at: AwareDatetime


class TotpLoginApiResponse(ApiResponse):
    """Session response after an authenticator verification."""

    authenticated: Literal[True]
    user: dict[str, object]
    csrf_token: str = Field(min_length=20, max_length=256)
    expires_at: AwareDatetime
    mfa_method: Literal["totp"]


class TotpEnrollmentFinishApiResponse(TotpLoginApiResponse):
    """One-time recovery material returned after first-factor enrollment."""

    recovery_codes: list[str] = Field(min_length=1, max_length=20)


class TotpStepUpApiResponse(ApiResponse):
    """Fresh administrator proof timestamp."""

    verified: Literal[True]
    verified_at: AwareDatetime


class TotpRecoveryApiResponse(ApiResponse):
    """Restricted recovery session that can only replace the factor."""

    authenticated: Literal[True]
    user: dict[str, object]
    csrf_token: str = Field(min_length=20, max_length=256)
    expires_at: AwareDatetime
    mfa_method: Literal["recovery"]
    restricted: Literal[True]


class TotpRecoveryCodesApiResponse(ApiResponse):
    """New single-use recovery codes returned once after rotation."""

    recovery_codes: list[str] = Field(min_length=1, max_length=20)


class HealthResponse(ApiResponse):
    status: Literal["ok"]
    service: Literal["stock-probs"]
    api_version: Literal["v1"]


class ReadinessResponse(ApiResponse):
    status: Literal["ready"]
    schema_version: int
    provider: str


class QuoteItemResponse(ApiResponse):
    symbol: str = Field(min_length=1, max_length=15)
    name: str = Field(min_length=1, max_length=200)
    asset_type: Literal["stock", "etf"]
    exchange: str = Field(min_length=1, max_length=40)
    last: PositivePrice
    currency: str = Field(min_length=1, max_length=12)
    source: str = Field(min_length=1, max_length=80)
    as_of: AwareDatetime
    state: Literal["provider_reported", "delayed", "simulated"]
    delayed: bool
    delay_minutes: int | None = Field(default=None, ge=1, le=1440)
    label: str = Field(min_length=1, max_length=300)
    open: PositivePrice | None = None
    high: PositivePrice | None = None
    low: PositivePrice | None = None
    previous_close: PositivePrice | None = None
    volume: int | None = Field(default=None, ge=0, le=2**63 - 1)
    last_trade: PositivePrice | None = None
    change: FiniteNumber | None = None
    change_percent: FiniteNumber | None = None

    @model_validator(mode="after")
    def delay_is_explicit(self) -> QuoteItemResponse:
        if self.delayed != (self.delay_minutes is not None):
            raise ValueError("delayed quotes require a positive provider delay")
        if (self.state == "delayed") != self.delayed:
            raise ValueError("quote state must preserve the provider delay disclosure")
        return self


class QuotesResponse(ApiResponse):
    items: list[QuoteItemResponse] = Field(max_length=20)


class CapturedBarResponse(ApiResponse):
    timestamp: AwareDatetime
    end: AwareDatetime
    close: PositivePrice
    duration_seconds: int = Field(ge=0, le=86_400)

    @model_validator(mode="after")
    def ordered_boundaries(self) -> CapturedBarResponse:
        if self.end < self.timestamp:
            raise ValueError("bar end must not precede bar start")
        return self


class MarketBarsResponse(ApiResponse):
    symbol: str = Field(min_length=1, max_length=15)
    range: ChartRange
    interval: Literal["1d"]
    adjustment_basis: str = Field(min_length=1, max_length=160)
    source: str = Field(min_length=1, max_length=80)
    as_of: AwareDatetime
    state: Literal["provider_reported", "delayed", "simulated"]
    delayed: bool
    delay_minutes: int | None = Field(default=None, ge=1, le=1440)
    label: str = Field(min_length=1, max_length=300)
    bars: list[CapturedBarResponse] = Field(max_length=500)


class InstrumentListItemResponse(ApiResponse):
    symbol: str = Field(min_length=1, max_length=15)
    display_name: str = Field(min_length=1, max_length=200)
    provider: str = Field(min_length=1, max_length=80)
    asset_type: Literal["stock", "etf"]
    exchange: str = Field(min_length=1, max_length=40)
    quantity: FiniteNumber | None = Field(ge=0)
    added_at: AwareDatetime


class InstrumentListsResponse(ApiResponse):
    kind: Literal["watchlist", "portfolio", "all"]
    items: list[InstrumentListItemResponse] = Field(max_length=1000)


class SearchEventResponse(ApiResponse):
    id: int
    request_id: str
    submitted_symbol: str
    normalized_symbol: str | None
    asset_type: str
    status: HistoryStatus
    is_repeat: bool
    error_code: str | None
    error_message: str | None
    submitted_at: AwareDatetime
    completed_at: AwareDatetime
    run_id: int | None
    analysis_kind: Literal["submitted_forecast", "fresh_historical_reconstruction"] | None = None
    source_event_id: int | None = None
    # Failed validation attempts can intentionally retain the submitted cutoff text for audit.
    requested_cutoff: str | None = None
    requested_source_event_id: int | None = None
    canonical_symbol: str | None = None
    company_name: str | None = None
    display_name: str | None = None
    exchange: str | None = None
    quote_type: Literal["EQUITY", "STOCK", "ETF"] | None = None
    model_name: str | None = None
    model_version: str | None = None
    forecast_contract_version: str | None = None
    horizons: list[ForecastHorizon] = Field(default_factory=list, max_length=7)
    outcome_count: int = Field(default=0, ge=0)
    evaluation_statuses: list[Literal["available", "insufficient_history"]] = Field(
        default_factory=list, max_length=7
    )
    forecast_available: bool = False

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


class CalendarResponse(ApiResponse):
    name: str
    version: str
    timezone: str


class ModelIdentityResponse(ApiResponse):
    name: str
    version: str


class ModelParametersResponse(ApiResponse):
    daily_max_samples: Literal[504]
    ewma_span_daily: Literal[30]
    ewma_span_intraday: Literal[10]
    flat_threshold: Annotated[float, Field(gt=0.0, lt=1.0, allow_inf_nan=False)]
    maximum_absolute_training_return: Annotated[float, Field(gt=0.0, le=1.0, allow_inf_nan=False)]
    return_thresholds_percent: list[ThresholdPercent]
    evaluation_max_points: Literal[120]
    reliability_bin_count: Literal[5]

    @model_validator(mode="after")
    def exact_versioned_parameters(self) -> ModelParametersResponse:
        if self.flat_threshold != 0.001 or self.maximum_absolute_training_return != 0.5:
            raise ValueError("model thresholds do not match the published contract version")
        if self.return_thresholds_percent != [-1.0, -3.0, -5.0, -10.0, 1.0, 3.0, 5.0, 10.0]:
            raise ValueError("model must define every supported return threshold")
        return self


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


class ProviderSeriesQueryResponse(ApiResponse):
    """One bounded provider request, with no provider-client implementation details."""

    interval: Literal["1d", "5m"]
    prepost: Literal[False]
    auto_adjust: Literal[False]
    actions: Literal[False]
    repair: Literal[False]
    timeout_seconds: Annotated[float, Field(gt=0.0, le=120.0, allow_inf_nan=False)]
    returned_coverage: ProviderCoverageResponse
    period: Literal["2y", "5d"] | None = None
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None

    @model_validator(mode="after")
    def exact_window(self) -> ProviderSeriesQueryResponse:
        period_window = self.period is not None
        date_window = self.start is not None and self.end is not None
        if period_window == date_window:
            raise ValueError("provider query must use exactly one bounded window")
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError("provider query end must follow start")
        return self


class ProviderQueryResponse(ApiResponse):
    """Exact normalized query accepted from either the live or deterministic adapter."""

    requested_as_of: AwareDatetime
    daily: ProviderSeriesQueryResponse | Literal["1d/2y"]
    intraday: ProviderSeriesQueryResponse | Literal["5m/5d", "5m/60d"]
    mode: Literal["current", "historical_cutoff"] | None = None
    data_cutoff: AwareDatetime | None = None
    fixture: Literal["acdc.json", "spy.json"] | None = None
    analysis: HistoricalAnalysisResponse | None = None


class ProviderCoverageResponse(ApiResponse):
    first: AwareDatetime | None
    last: AwareDatetime | None
    count: int = Field(ge=0)

    @model_validator(mode="after")
    def coverage_is_ordered(self) -> ProviderCoverageResponse:
        if (self.first is None) != (self.last is None):
            raise ValueError("coverage bounds must both be present or absent")
        if self.count == 0 and self.first is not None:
            raise ValueError("empty coverage cannot have bounds")
        if self.count > 0 and self.first is None:
            raise ValueError("non-empty coverage requires bounds")
        if self.first is not None and self.last is not None and self.last < self.first:
            raise ValueError("coverage end must not precede start")
        return self


class ProviderSessionEpochResponse(ApiResponse):
    """Provider-supplied regular-session boundaries represented as Unix seconds."""

    start: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    end: Annotated[float, Field(gt=0, allow_inf_nan=False)]

    @model_validator(mode="after")
    def session_is_ordered(self) -> ProviderSessionEpochResponse:
        if self.end <= self.start:
            raise ValueError("regular-session end must follow start")
        return self


class IntradayArchiveLimitResponse(ApiResponse):
    approximate_days: Literal[60]
    statement: str = Field(min_length=1, max_length=300)


class ProviderMetadataResponse(ApiResponse):
    """Bounded public quality facts; arbitrary provider metadata is never serialized."""

    identity_source: Literal["bounded_chart_metadata", "checked_in_fixture"]
    regular_session: ProviderSessionEpochResponse
    data_granularity: Literal["5m"]
    daily_data_granularity: Literal["1d"] | None = None
    exchange_timezone: str = Field(min_length=1, max_length=80)
    session_scope: Literal["regular session only (prepost=False)"]
    intraday_archive_limit: IntradayArchiveLimitResponse
    daily_coverage: ProviderCoverageResponse
    intraday_coverage: ProviderCoverageResponse
    missing_daily_closes: int = Field(ge=0)
    missing_daily_sessions: int = Field(ge=0)
    missing_intraday_closes: int = Field(ge=0)
    missing_intraday_intervals: int = Field(ge=0)
    trailing_missing_intraday_intervals: int = Field(ge=0)
    daily_returned_rows: int | None = Field(default=None, ge=0)
    intraday_returned_rows: int | None = Field(default=None, ge=0)
    daily_normalized_rows: int | None = Field(default=None, ge=0)
    intraday_normalized_rows: int | None = Field(default=None, ge=0)
    daily_rejected_rows: int | None = Field(default=None, ge=0)
    intraday_rejected_rows: int | None = Field(default=None, ge=0)
    daily_duplicate_timestamps: int | None = Field(default=None, ge=0)
    intraday_duplicate_timestamps: int | None = Field(default=None, ge=0)
    gmtoffset: int | None = None
    fixture: Literal[True] | None = None
    fixture_contract: Literal["compact-seed-v1"] | None = None
    fixture_base_symbol: Literal["ACDC", "SPY"] | None = None


class ProvenanceResponse(ApiResponse):
    source: str
    query: ProviderQueryResponse
    response_as_of: AwareDatetime
    content_fingerprint: str
    instrument_identity: InstrumentIdentityResponse
    identity_fingerprint: str
    model_version: str
    forecast_contract_version: str
    evaluation_version: str
    model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
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
    provider_as_of: AwareDatetime
    request_cutoff: AwareDatetime
    provider_query: ProviderQueryResponse
    provider_metadata: ProviderMetadataResponse
    content_fingerprint: str
    requested_interval: ForecastInterval | None = None
    instrument_identity: InstrumentIdentityResponse
    identity_fingerprint: str
    captured_at: AwareDatetime
    selected_daily_bars: list[CapturedBarResponse]
    selected_intraday_bars: list[CapturedBarResponse]
    session_rule: str
    calendar: CalendarResponse
    limitations: list[str]
    quality: Literal["current", "stale"]
    quality_reasons: list[str]
    stale_state: StaleStateResponse
    session_state_at_request: Literal["closed_session_day", "pre_session", "open", "post_session"]
    forecast_contract_version: str
    model: ModelIdentityResponse
    model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    parameters: ModelParametersResponse
    provenance: ProvenanceResponse


class DirectionDefinitionsResponse(ApiResponse):
    down: str
    flat: str
    unchanged: str
    up: str


class ProbabilityUncertaintyResponse(ApiResponse):
    low: Probability
    high: Probability
    level: Probability
    method: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def ordered_interval(self) -> ProbabilityUncertaintyResponse:
        if self.low > self.high:
            raise ValueError("uncertainty low must not exceed high")
        return self


class DirectionEventCountsResponse(ApiResponse):
    down: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    up: int = Field(ge=0)
    sample_count: int = Field(ge=1)

    @model_validator(mode="after")
    def partition_matches_sample(self) -> DirectionEventCountsResponse:
        if self.down + self.unchanged + self.up != self.sample_count:
            raise ValueError("direction event counts must partition the sample")
        return self


class DirectionUncertaintyResponse(ApiResponse):
    down: ProbabilityUncertaintyResponse
    unchanged: ProbabilityUncertaintyResponse
    up: ProbabilityUncertaintyResponse


class DirectionProbabilitiesResponse(ApiResponse):
    down: Probability
    flat: Probability
    unchanged: Probability
    up: Probability
    unit: Literal["probability"]
    definitions: DirectionDefinitionsResponse
    flat_definition: str
    event_counts: DirectionEventCountsResponse
    uncertainty: DirectionUncertaintyResponse

    @model_validator(mode="after")
    def exact_probability_partition(self) -> DirectionProbabilitiesResponse:
        if abs(self.flat - self.unchanged) > 1e-12:
            raise ValueError("flat compatibility alias must equal unchanged")
        if abs(self.down + self.unchanged + self.up - 1.0) > 1e-9:
            raise ValueError("direction probabilities must sum to one")
        return self


class ThresholdProbabilityResponse(ApiResponse):
    operator: Literal["lte", "gte"]
    threshold: ThresholdPercent
    unit: Literal["percent_return"]
    definition: str
    probability: Probability
    event_count: int = Field(ge=0)
    sample_count: int = Field(ge=1)
    uncertainty: ProbabilityUncertaintyResponse
    rare_event: bool

    @model_validator(mode="after")
    def operator_matches_threshold(self) -> ThresholdProbabilityResponse:
        if self.event_count > self.sample_count:
            raise ValueError("threshold event count cannot exceed sample count")
        if (self.threshold < 0) != (self.operator == "lte"):
            raise ValueError("threshold sign and operator do not match")
        if self.rare_event != (self.event_count < 10):
            raise ValueError("rare-event state must follow the published sample-count rule")
        return self


class IntervalBoundResponse(ApiResponse):
    low: FiniteNumber
    high: FiniteNumber
    unit: Literal["percent_return", "quote_currency"]

    @model_validator(mode="after")
    def ordered_interval(self) -> IntervalBoundResponse:
        if self.low > self.high:
            raise ValueError("interval low must not exceed high")
        if self.unit == "quote_currency" and self.low <= 0:
            raise ValueError("price intervals must remain positive")
        return self


class MagnitudeIntervalResponse(ApiResponse):
    level: IntervalLevel
    definition: str
    percent: IntervalBoundResponse
    price: IntervalBoundResponse

    @model_validator(mode="after")
    def exact_units(self) -> MagnitudeIntervalResponse:
        if self.percent.unit != "percent_return" or self.price.unit != "quote_currency":
            raise ValueError("return and price interval units are fixed")
        return self


class ConditionalMagnitudeMetricResponse(ApiResponse):
    condition: str = Field(min_length=1, max_length=120)
    observed_count: int = Field(ge=0)
    sample_count: int = Field(ge=1)
    expected: FiniteNumber | None
    median: FiniteNumber | None
    unit: Literal["percent_return_magnitude"]
    definition: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def observed_metric_semantics(self) -> ConditionalMagnitudeMetricResponse:
        if self.observed_count > self.sample_count:
            raise ValueError("conditional count cannot exceed sample count")
        has_value = self.expected is not None and self.median is not None
        if has_value != (self.observed_count > 0):
            raise ValueError("conditional values require at least one observed event")
        if (
            self.expected is not None
            and self.median is not None
            and (self.expected <= 0 or self.median <= 0)
        ):
            raise ValueError("conditional magnitudes must be positive")
        return self


class ConditionalMagnitudesResponse(ApiResponse):
    gain: ConditionalMagnitudeMetricResponse
    loss: ConditionalMagnitudeMetricResponse


class SampleFilterResponse(ApiResponse):
    version: str = Field(min_length=1, max_length=80)
    rule: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=300)


class SampleAccountingResponse(ApiResponse):
    candidate_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    effective_count: int = Field(ge=0)
    excluded_anomaly_count: int = Field(ge=0)
    warmup_excluded_count: int = Field(ge=0)
    excluded_session_gap_count: int = Field(default=0, ge=0)
    filter: SampleFilterResponse | None = None
    transformation: Literal["none"] | None = None

    @model_validator(mode="after")
    def counts_reconcile(self) -> SampleAccountingResponse:
        if self.eligible_count + self.excluded_anomaly_count != self.candidate_count:
            raise ValueError("eligible and excluded counts must reconcile to candidates")
        if self.effective_count + self.warmup_excluded_count != self.eligible_count:
            raise ValueError("effective and warmup counts must reconcile to eligible samples")
        return self


class ReliabilityBinResponse(ApiResponse):
    low: Probability
    high: Probability
    includes_high: bool
    count: int = Field(ge=0)
    mean_predicted_probability: Probability | None
    observed_frequency: Probability | None

    @model_validator(mode="after")
    def exact_bin_semantics(self) -> ReliabilityBinResponse:
        if self.low >= self.high:
            raise ValueError("reliability bin low must be below high")
        values_present = (
            self.mean_predicted_probability is not None and self.observed_frequency is not None
        )
        if values_present != (self.count > 0):
            raise ValueError("only populated reliability bins may report values")
        return self


class DirectionReliabilityResponse(ApiResponse):
    down: list[ReliabilityBinResponse]
    unchanged: list[ReliabilityBinResponse]
    up: list[ReliabilityBinResponse]


class ThresholdReliabilityResponse(ApiResponse):
    operator: Literal["lte", "gte"]
    threshold: ThresholdPercent
    unit: Literal["percent_return"]
    bins: list[ReliabilityBinResponse]


class ReliabilityResponse(ApiResponse):
    bin_count: Literal[5]
    direction: DirectionReliabilityResponse
    thresholds: list[ThresholdReliabilityResponse]


class DirectionBrierComponentsResponse(ApiResponse):
    down: Probability
    unchanged: Probability
    up: Probability


class DirectionBrierResponse(ApiResponse):
    multiclass_mean: Annotated[float, Field(ge=0.0, le=2.0, allow_inf_nan=False)]
    components: DirectionBrierComponentsResponse
    definition: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def components_match_multiclass_score(self) -> DirectionBrierResponse:
        component_sum = self.components.down + self.components.unchanged + self.components.up
        if abs(self.multiclass_mean - component_sum) > 1e-12:
            raise ValueError("multiclass Brier score must equal its direction components")
        return self


class ThresholdBrierResponse(ApiResponse):
    operator: Literal["lte", "gte"]
    threshold: ThresholdPercent
    unit: Literal["percent_return"]
    score: Probability


class IntervalCoverageResponse(ApiResponse):
    level: IntervalLevel
    covered_count: int = Field(ge=0)
    sample_count: int = Field(ge=1)
    coverage: Probability
    definition: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def counts_match_coverage(self) -> IntervalCoverageResponse:
        if self.covered_count > self.sample_count:
            raise ValueError("covered count cannot exceed evaluation sample count")
        if abs(self.coverage - self.covered_count / self.sample_count) > 1e-12:
            raise ValueError("interval coverage must match the reported counts")
        return self


class EvaluationScoresResponse(ApiResponse):
    direction_brier: DirectionBrierResponse
    threshold_brier: list[ThresholdBrierResponse]
    reliability: ReliabilityResponse
    interval_coverage: list[IntervalCoverageResponse]

    @model_validator(mode="after")
    def complete_evaluation_matrix(self) -> EvaluationScoresResponse:
        expected_thresholds = [
            ("lte", -1.0),
            ("lte", -3.0),
            ("lte", -5.0),
            ("lte", -10.0),
            ("gte", 1.0),
            ("gte", 3.0),
            ("gte", 5.0),
            ("gte", 10.0),
        ]
        if [(item.operator, item.threshold) for item in self.threshold_brier] != (
            expected_thresholds
        ):
            raise ValueError("evaluation must report Brier scores for every threshold")
        if [(item.operator, item.threshold) for item in self.reliability.thresholds] != (
            expected_thresholds
        ):
            raise ValueError("evaluation must report reliability for every threshold")
        if [item.level for item in self.interval_coverage] != [0.5, 0.8, 0.95]:
            raise ValueError("evaluation must report coverage for every forecast interval")
        bin_groups = [
            self.reliability.direction.down,
            self.reliability.direction.unchanged,
            self.reliability.direction.up,
            *(item.bins for item in self.reliability.thresholds),
        ]
        expected_bounds = [(index / 5, (index + 1) / 5) for index in range(5)]
        if any([(item.low, item.high) for item in bins] != expected_bounds for bins in bin_groups):
            raise ValueError("reliability reports must contain the five fixed probability bins")
        return self


class ForecastModelEvaluationResponse(EvaluationScoresResponse):
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=80)


class BaselineEvaluationResponse(EvaluationScoresResponse):
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=80)
    definition: str = Field(min_length=1, max_length=300)


class EvaluationDateRangeResponse(ApiResponse):
    first_origin: AwareDatetime
    first_target: AwareDatetime
    last_origin: AwareDatetime
    last_target: AwareDatetime

    @model_validator(mode="after")
    def chronological_dates(self) -> EvaluationDateRangeResponse:
        if self.first_origin > self.first_target or self.last_origin > self.last_target:
            raise ValueError("each evaluation origin must not follow its target")
        if self.first_origin > self.last_origin or self.first_target > self.last_target:
            raise ValueError("evaluation date range must be chronological")
        return self


class TrainingSampleRangeResponse(ApiResponse):
    minimum_effective_count: int = Field(ge=1)
    maximum_effective_count: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered_counts(self) -> TrainingSampleRangeResponse:
        if self.minimum_effective_count > self.maximum_effective_count:
            raise ValueError("minimum training count must not exceed maximum")
        return self


class ForecastEvaluationResponse(ApiResponse):
    version: str = Field(min_length=1, max_length=80)
    method: str = Field(min_length=1, max_length=160)
    status: Literal["available", "insufficient_history"]
    reason: str | None = Field(default=None, min_length=1, max_length=240)
    evaluation_count: int = Field(ge=0)
    eligible_realized_count: int = Field(ge=0)
    excluded_anomaly_outcome_count: int = Field(ge=0)
    date_range: EvaluationDateRangeResponse | None
    training_sample_range: TrainingSampleRangeResponse | None
    forecast_model: ForecastModelEvaluationResponse | None
    baseline: BaselineEvaluationResponse | None
    max_evaluation_points: int = Field(ge=1)
    minimum_training_samples: int | None = Field(default=None, ge=1)
    information_rule: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def availability_is_honest(self) -> ForecastEvaluationResponse:
        reports = (
            self.date_range,
            self.training_sample_range,
            self.forecast_model,
            self.baseline,
        )
        if self.status == "available":
            if self.evaluation_count < 1 or any(item is None for item in reports):
                raise ValueError("available evaluation requires dates, scores, and baseline")
            if self.reason is not None or self.minimum_training_samples is None:
                raise ValueError("available evaluation cannot report an unavailable reason")
        elif self.evaluation_count != 0 or any(item is not None for item in reports):
            raise ValueError("insufficient evaluation cannot fabricate metrics")
        elif self.reason is None:
            raise ValueError("insufficient evaluation requires a reason")
        return self


class TargetSelectionResponse(ApiResponse):
    rule: Literal["same_open_session_close", "next_session_close_after_completed_origin_session"]
    request_session_state: Literal["closed_session_day", "pre_session", "open", "post_session"]
    origin_session_date: date
    target_session_date: date


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


class RollingSampleCountsResponse(ApiResponse):
    candidate: int = Field(ge=0)
    eligible: int = Field(ge=0)
    effective: int = Field(ge=0)
    overlap_stride: int = Field(ge=1)
    overlap_adjusted_effective: int = Field(ge=0)


class RollingProviderSnapshotResponse(ApiResponse):
    provider: str = Field(min_length=1, max_length=80)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    as_of: AwareDatetime


class RollingProvenanceResponse(ApiResponse):
    horizon: ForecastHorizon
    definition: str = Field(min_length=1, max_length=300)
    definition_version: Literal["rolling-horizons-v1"]
    origin_at: AwareDatetime
    target_at: AwareDatetime | None
    calendar: CalendarResponse
    adjustment_basis: str = Field(min_length=1, max_length=160)
    sample_counts: RollingSampleCountsResponse
    provider_snapshot: RollingProviderSnapshotResponse


class RollingSampleAccountingResponse(SampleAccountingResponse):
    overlap_stride: int = Field(ge=1)
    overlap_adjusted_effective_count: int = Field(ge=0)


class ForecastResultResponse(ApiResponse):
    horizon: Literal["close_to_close", "completed_5m_to_close"]
    origin_timestamp: AwareDatetime
    origin_bar_end: AwareDatetime | None = None
    horizon_start_timestamp: AwareDatetime
    horizon_end_timestamp: AwareDatetime
    origin_price: PositivePrice
    reference_timestamp: AwareDatetime
    reference_state: Literal["completed_session_close", "completed_five_minute_bar_close"]
    target_timestamp: AwareDatetime
    target_state: Literal["scheduled_session_close"]
    exchange_timezone: str
    session_state_at_request: (
        Literal["closed_session_day", "pre_session", "open", "post_session"] | None
    ) = None
    stale_state: Literal["current", "stale"]
    calculated_at: AwareDatetime
    definition: str
    target_session_rule: str | None = None
    target_selection: TargetSelectionResponse | None = None
    forecast_contract_version: str
    model_version: str
    model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    forecast_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    direction_probabilities: DirectionProbabilitiesResponse
    threshold_probabilities: list[ThresholdProbabilityResponse]
    conditional_magnitudes: ConditionalMagnitudesResponse
    magnitude_intervals: list[MagnitudeIntervalResponse]
    sample_size: int = Field(ge=3)
    sample_accounting: SampleAccountingResponse
    probability_estimator: str = Field(min_length=1, max_length=200)
    distribution_definition: str
    evaluation: ForecastEvaluationResponse

    @model_validator(mode="before")
    @classmethod
    def explicit_horizon_boundaries(cls, value: Any) -> Any:
        """Name the modeled window explicitly while preserving the original timestamp fields."""

        if isinstance(value, dict):
            value = dict(value)
            value.setdefault("horizon_start_timestamp", value.get("reference_timestamp"))
            value.setdefault("horizon_end_timestamp", value.get("target_timestamp"))
        return value

    @model_validator(mode="after")
    def numerical_and_time_invariants(self) -> ForecastResultResponse:
        if self.origin_timestamp > self.reference_timestamp:
            raise ValueError("origin timestamp must not follow its completed reference")
        if self.origin_bar_end is not None and self.origin_bar_end != self.reference_timestamp:
            raise ValueError("completed origin bar end must equal the reference timestamp")
        if self.horizon_start_timestamp != self.reference_timestamp:
            raise ValueError("horizon start must equal the completed reference timestamp")
        if self.horizon_end_timestamp != self.target_timestamp:
            raise ValueError("horizon end must equal the target timestamp")
        if self.reference_timestamp >= self.target_timestamp:
            raise ValueError("forecast target must follow its completed reference")
        if self.horizon == "completed_5m_to_close":
            if (
                self.origin_bar_end is None
                or self.reference_state != "completed_five_minute_bar_close"
            ):
                raise ValueError("five-minute horizon requires an exact completed bar end")
        elif self.origin_bar_end is not None or self.reference_state != "completed_session_close":
            raise ValueError("close-to-close horizon uses an instantaneous completed close")
        expected_thresholds = [
            ("lte", -1.0),
            ("lte", -3.0),
            ("lte", -5.0),
            ("lte", -10.0),
            ("gte", 1.0),
            ("gte", 3.0),
            ("gte", 5.0),
            ("gte", 10.0),
        ]
        if [(item.operator, item.threshold) for item in self.threshold_probabilities] != (
            expected_thresholds
        ):
            raise ValueError("forecast must report every supported threshold exactly once")
        if any(item.sample_count != self.sample_size for item in self.threshold_probabilities):
            raise ValueError("threshold sample counts must match the forecast sample")
        downside = [item.probability for item in self.threshold_probabilities[:4]]
        upside = [item.probability for item in self.threshold_probabilities[4:]]
        if downside != sorted(downside, reverse=True) or upside != sorted(upside, reverse=True):
            raise ValueError("more severe threshold events cannot be more probable")
        if [item.level for item in self.magnitude_intervals] != [0.5, 0.8, 0.95]:
            raise ValueError("forecast must report 50, 80, and 95 percent intervals")
        percent_lows = [item.percent.low for item in self.magnitude_intervals]
        percent_highs = [item.percent.high for item in self.magnitude_intervals]
        price_lows = [item.price.low for item in self.magnitude_intervals]
        price_highs = [item.price.high for item in self.magnitude_intervals]
        if (
            percent_lows != sorted(percent_lows, reverse=True)
            or percent_highs != sorted(percent_highs)
            or price_lows != sorted(price_lows, reverse=True)
            or price_highs != sorted(price_highs)
        ):
            raise ValueError("higher-level forecast intervals must contain lower-level intervals")
        if self.sample_accounting.effective_count != self.sample_size:
            raise ValueError("effective sample accounting must match the forecast sample")
        if self.direction_probabilities.event_counts.sample_count != self.sample_size:
            raise ValueError("direction sample count must match the forecast sample")
        for metric in (
            self.conditional_magnitudes.gain,
            self.conditional_magnitudes.loss,
        ):
            if metric.sample_count != self.sample_size:
                raise ValueError("conditional sample counts must match the forecast sample")
        if (
            self.conditional_magnitudes.gain.observed_count
            + self.conditional_magnitudes.loss.observed_count
            + self.direction_probabilities.event_counts.unchanged
            != self.sample_size
        ):
            raise ValueError("conditional direction counts must partition the forecast sample")
        return self


class RollingForecastResultResponse(ApiResponse):
    horizon: Literal["five_min_forward", "daily_1", "weekly_5", "monthly_21", "quarterly_63"]
    interval: ForecastInterval
    availability: Literal["available", "unavailable"]
    unavailable_reason: str | None = Field(default=None, min_length=1, max_length=240)
    origin_timestamp: AwareDatetime
    horizon_start_timestamp: AwareDatetime
    horizon_end_timestamp: AwareDatetime | None
    origin_price: PositivePrice
    target_timestamp: AwareDatetime | None
    target_state: Literal[
        "scheduled_five_minute_bar_close", "scheduled_session_close", "unavailable"
    ]
    exchange_timezone: str = Field(min_length=1, max_length=80)
    stale_state: Literal["current", "stale"]
    calculated_at: AwareDatetime
    definition: str = Field(min_length=1, max_length=300)
    definition_version: Literal["rolling-horizons-v1"]
    minimum_effective_samples: int = Field(ge=1)
    provenance: RollingProvenanceResponse
    model_version: str = Field(min_length=1, max_length=80)
    model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    forecast_contract_version: str = Field(min_length=1, max_length=80)
    forecast_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    direction_probabilities: DirectionProbabilitiesResponse | None = None
    threshold_probabilities: list[ThresholdProbabilityResponse] | None = None
    conditional_magnitudes: ConditionalMagnitudesResponse | None = None
    magnitude_intervals: list[MagnitudeIntervalResponse] | None = None
    sample_size: int | None = Field(default=None, ge=3)
    sample_accounting: RollingSampleAccountingResponse | None = None
    probability_estimator: str | None = Field(default=None, min_length=1, max_length=200)
    distribution_definition: str | None = Field(default=None, min_length=1, max_length=400)
    evaluation: ForecastEvaluationResponse | None = None

    @model_validator(mode="before")
    @classmethod
    def explicit_rolling_boundaries(cls, value: Any) -> Any:
        if isinstance(value, dict):
            value = dict(value)
            value.setdefault("horizon_start_timestamp", value.get("origin_timestamp"))
            value.setdefault("horizon_end_timestamp", value.get("target_timestamp"))
        return value

    @model_validator(mode="after")
    def availability_and_boundaries_are_honest(self) -> RollingForecastResultResponse:
        if self.horizon_start_timestamp != self.origin_timestamp:
            raise ValueError("rolling horizon start must equal its completed origin")
        if self.horizon_end_timestamp != self.target_timestamp:
            raise ValueError("rolling horizon end must equal its target")
        if self.interval != _HORIZON_INTERVALS[self.horizon]:
            raise ValueError("forecast interval does not match its rolling horizon")
        distribution = (
            self.direction_probabilities,
            self.threshold_probabilities,
            self.conditional_magnitudes,
            self.magnitude_intervals,
            self.sample_size,
            self.sample_accounting,
            self.probability_estimator,
            self.distribution_definition,
            self.evaluation,
        )
        if self.availability == "unavailable":
            if self.unavailable_reason is None or any(value is not None for value in distribution):
                raise ValueError("unavailable rolling forecasts cannot fabricate a distribution")
            return self
        if self.unavailable_reason is not None or self.target_timestamp is None:
            raise ValueError("available rolling forecasts require an exact future target")
        if any(value is None for value in distribution):
            raise ValueError("available rolling forecasts require the complete distribution")
        assert self.sample_size is not None
        assert self.sample_accounting is not None
        assert self.direction_probabilities is not None
        if self.sample_accounting.effective_count != self.sample_size:
            raise ValueError("rolling sample accounting must match the forecast sample")
        if self.direction_probabilities.event_counts.sample_count != self.sample_size:
            raise ValueError("rolling direction counts must match the forecast sample")
        return self


class RecordedForecastResultResponse(ForecastResultResponse):
    id: int
    recorded_at: str
    outcomes: list[OutcomeResponse]
    outcomes_truncated: bool


class RecordedRollingForecastResultResponse(RollingForecastResultResponse):
    id: int
    recorded_at: str
    outcomes: list[OutcomeResponse]
    outcomes_truncated: bool


class OriginalForecastResultResponse(ForecastResultResponse):
    id: int
    immutable: Literal[True]


class OriginalRollingForecastResultResponse(RollingForecastResultResponse):
    id: int
    immutable: Literal[True]


class ForecastCreationResponse(ApiResponse):
    event: SearchEventResponse
    input: ForecastInputResponse
    results: list[RecordedForecastResultResponse | RecordedRollingForecastResultResponse]
    repeated: bool
    reused: bool


class ReconstructionResponse(ApiResponse):
    record_kind: Literal["recorded_forecast", "failed_search"] | None = None
    immutable: Literal[True] | None = None
    forecast_available: bool | None = None
    event: SearchEventResponse
    input: ForecastInputResponse | None
    results: list[RecordedForecastResultResponse | RecordedRollingForecastResultResponse]


class SavedForecastResponse(ApiResponse):
    analysis_kind: Literal["saved_recorded_forecast"]
    immutable: Literal[True]
    recalculated: Literal[False]
    provider_called: Literal[False]
    event: SearchEventResponse
    input: ForecastInputResponse
    results: list[RecordedForecastResultResponse | RecordedRollingForecastResultResponse]


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
    results: list[RecordedForecastResultResponse | RecordedRollingForecastResultResponse]
    repeated: bool
    reused: bool


class HistoryResponse(ApiResponse):
    items: list[SearchEventResponse]
    page: int
    page_size: int
    total: int
    total_pages: int
    has_previous: bool
    has_next: bool
    filters: HistoryExportFiltersResponse
    sort: HistorySortResponse


class HistorySortResponse(ApiResponse):
    field: HistorySortField
    direction: SortDirection


class HistoryExportFiltersResponse(ApiResponse):
    query: str
    symbol: str | None
    company: str | None
    status: HistoryStatus | None
    asset_type: Literal["stock", "etf"] | None
    analysis_kind: HistoryAnalysisKind | None
    submitted_from: AwareDatetime | None
    submitted_to: AwareDatetime | None
    model: str | None
    model_version: str | None
    horizon: ForecastHorizon | None
    request_id: str | None
    event_id: int | None


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
    data: RecordedForecastResultResponse | RecordedRollingForecastResultResponse


class HistoryExportCountsResponse(ApiResponse):
    events: int
    runs: int
    results: int


class HistoryJsonExportResponse(ApiResponse):
    format: Literal["stock-probs-history"]
    format_version: Literal[1]
    generated_at: AwareDatetime
    filters: HistoryExportFiltersResponse
    sort: HistorySortResponse
    total_events: int
    exported_events: int
    truncated: bool
    counts: HistoryExportCountsResponse
    records: list[HistoryEventExportRecord | ForecastRunExportRecord | ForecastResultExportRecord]


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
    available: Literal[True] | None = None


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


class _InlineScriptHashParser(HTMLParser):
    """Parse elements so CSP authorization cannot misclassify script attributes or text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.hashes: set[str] = set()
        self._script: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        attributes = dict(attrs)
        self._script = [] if "src" not in attributes else None

    def handle_data(self, data: str) -> None:
        if self._script is not None:
            self._script.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script is not None:
            digest = hashlib.sha256("".join(self._script).encode()).digest()
            self.hashes.add(f"'sha256-{base64.b64encode(digest).decode()}'")
            self._script = None


def _static_script_csp(*html_paths: Path) -> str:
    """Authorize only local scripts and exact inline code emitted by the static export."""

    hashes: set[str] = set()
    for path in html_paths:
        parser = _InlineScriptHashParser()
        parser.feed(path.read_bytes().decode("utf-8"))
        parser.close()
        hashes.update(parser.hashes)
    script_sources = " ".join(("'self'", *sorted(hashes)))
    return (
        f"default-src 'self'; script-src {script_sources}; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'"
    )


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


_FRESH_RECONSTRUCTION_PATH = re.compile(r"^/api/v1/history/(?P<event_id>[0-9]+)/reconstructions$")


def _reconstruction_source_id(path: str) -> int | None:
    matched = _FRESH_RECONSTRUCTION_PATH.fullmatch(path)
    if matched is None:
        return None
    event_id = int(matched.group("event_id"))
    return event_id if 1 <= event_id <= 2_147_483_647 else None


def _reconstruction_submission_context(
    repository: Repository, path: str, owner_user_id: int | None = None
) -> tuple[str, str | None, str, int | None] | None:
    """Recover trusted source identity while retaining an unknown requested ID safely."""

    matched = _FRESH_RECONSTRUCTION_PATH.fullmatch(path)
    if matched is None:
        return None
    event_id = _reconstruction_source_id(path)
    if event_id is None:
        return "<invalid history event ID>", None, "invalid", None
    try:
        source = _call_with_owner(repository.reconstruction, owner_user_id, event_id)
    except sqlite3.Error:
        # Framing errors still receive their safe response if local audit lookup is unavailable.
        source = None
    if source is None:
        # The repository accepts this as requested audit metadata and resolves the relationship
        # to null, so an unknown browser ID cannot violate referential integrity.
        return f"<history event {event_id}>", None, "invalid", event_id
    event = source["event"]
    snapshot = source.get("input")
    normalized = (
        snapshot.get("symbol") if isinstance(snapshot, dict) else event.get("normalized_symbol")
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
        429: "A bounded per-caller authentication attempt limit was reached.",
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


class _RestoreRequestGate:
    """Stop new database requests and drain existing ones before promotion."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._active = 0
        self._draining = False

    def try_enter(self) -> bool:
        """Count a request unless a restore has already started draining."""

        with self._condition:
            if self._draining:
                return False
            self._active += 1
            return True

    def leave(self) -> None:
        """Release one request slot and wake a waiting promotion."""

        with self._condition:
            if self._active <= 0:
                raise RuntimeError("restore request gate underflow")
            self._active -= 1
            if self._active == 0:
                self._condition.notify_all()

    def begin_drain(self, timeout: float) -> bool:
        """Block new requests and wait for the bounded in-flight set to finish."""

        deadline = time.monotonic() + timeout
        with self._condition:
            if self._draining:
                return False
            self._draining = True
            while self._active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._draining = False
                    self._condition.notify_all()
                    return False
                self._condition.wait(remaining)
            return True

    def end_drain(self) -> None:
        """Reopen normal traffic after a failed or completed promotion."""

        with self._condition:
            self._draining = False
            self._condition.notify_all()


RESTORE_DRAIN_TIMEOUT_SECONDS = 5.0

WORKSPACE_PAGE_ROUTES = (
    "/api-docs",
    "/overview",
    "/research",
    "/tools",
    "/tools/forecast",
    "/tools/live-trading",
    "/tools/markets",
    "/sign-in",
    "/invite",
    "/passkey",
    "/authenticator",
    "/account",
    "/admin",
)


class LocalSecurityMiddleware(BaseHTTPMiddleware):
    """Defend the configured origin and attach one policy to every response type."""

    allowed_hosts = {"127.0.0.1", "localhost", "::1", "testserver"}
    browser_hosts = {"127.0.0.1", "localhost", "::1"}
    html_navigation_paths = frozenset({"/", "/api/v1/docs", *WORKSPACE_PAGE_ROUTES})

    @staticmethod
    def _host_authority(raw: str) -> ParseResult | None:
        """Accept only an HTTP Host authority, never URL path/query/fragment syntax.

        Starlette can derive request.url.path from Host. A malformed Host containing a path
        must not change the path used by authentication or maintenance decisions.
        """

        if (
            not raw
            or len(raw) > 253
            or any(char in raw for char in "/\\?#@%")
            or any(ord(char) < 33 or ord(char) > 126 for char in raw)
        ):
            return None
        try:
            authority = urlparse(f"//{raw}")
            if (
                authority.netloc != raw
                or authority.path
                or authority.params
                or authority.query
                or authority.fragment
                or authority.hostname is None
                or authority.username is not None
                or authority.password is not None
                or (authority.port is not None and not 1 <= authority.port <= 65_535)
            ):
                return None
        except ValueError:
            return None
        return authority

    def __init__(
        self,
        app: ASGIApp,
        repository: Repository,
        content_security_policy: str,
        content_security_policies: Mapping[str, str] | None = None,
        auth_manager: AuthManager | None = None,
        public_origin: str | None = None,
        trusted_proxy_hosts: tuple[str, ...] = (),
        maintenance_event: threading.Event | None = None,
        request_gate: _RestoreRequestGate | None = None,
        max_request_bytes: int = 16_384,
    ) -> None:
        super().__init__(app)
        self.repository = repository
        self.content_security_policy = content_security_policy
        self.content_security_policies = dict(content_security_policies or {})
        self.auth_manager = auth_manager
        self.public_origin = public_origin.rstrip("/") if public_origin else None
        self.trusted_proxy_hosts = set(trusted_proxy_hosts)
        self.maintenance_event = maintenance_event or threading.Event()
        self.request_gate = request_gate or _RestoreRequestGate()
        self.max_request_bytes = max_request_bytes

    @property
    def public_hostname(self) -> str | None:
        """Return the configured public hostname without trusting request headers."""

        if self.public_origin is None:
            return None
        try:
            return urlparse(self.public_origin).hostname
        except ValueError:
            return None

    def _trusted_proxy(self, request: Request) -> bool:
        client = request.client.host if request.client is not None else None
        return client is not None and client.lower() in self.trusted_proxy_hosts

    def _effective_origin(self, request: Request, authority: str) -> str:
        """Build the request origin, accepting forwarded values only from the connector."""

        if self._trusted_proxy(request):
            forwarded_host = request.headers.get("x-forwarded-host")
            forwarded_proto = request.headers.get("x-forwarded-proto")
            if (
                forwarded_host
                and forwarded_proto in {"http", "https"}
                and self._host_authority(forwarded_host) is not None
            ):
                return f"{forwarded_proto}://{forwarded_host}"
        scheme = request.url.scheme
        return f"{scheme}://{authority}"

    def _allowed_origin(self, request: Request, authority: str) -> str | None:
        """Return the one origin against which a browser request may be compared."""

        public_hostname = self.public_hostname
        parsed_authority = self._host_authority(authority)
        host = parsed_authority.hostname if parsed_authority is not None else None
        if self.public_origin and (host == public_hostname or self._trusted_proxy(request)):
            return self.public_origin
        return self._effective_origin(request, authority)

    def _requires_authentication(self, request: Request) -> bool:
        """Keep health, sign-in, and machine contract discovery available anonymously."""

        if self.auth_manager is None or not self.auth_manager.enabled:
            return False
        path = request.scope["path"]
        if path in {
            "/api/v1/health",
            "/api/v1/readiness",
            "/api/v1/openapi.json",
            "/api/v1/auth/status",
            "/api/v1/auth/session",
            "/api/v1/auth/local/login",
            "/api/v1/auth/github/start",
            "/api/v1/auth/github/callback",
            "/api/v1/auth/invites/redeem",
        }:
            return False
        if path.startswith("/api/v1/auth/passkeys/") or path.startswith("/api/v1/auth/totp/"):
            return False
        return path.startswith("/api/v1/") or path in {
            "/",
            "/overview",
            "/research",
            "/tools",
            "/tools/forecast",
            "/tools/live-trading",
            "/tools/markets",
            "/account",
            "/admin",
        }

    def _auth_rejection(self, error: AuthError) -> JSONResponse:
        headers = (
            {"Retry-After": str(error.retry_after_seconds)}
            if isinstance(error, OAuthStartLimited)
            else None
        )
        return JSONResponse(
            status_code=error.status_code,
            content=_error(error.code, error.public_message),
            headers=headers,
        )

    def _authenticate_request(self, request: Request) -> Response | None:
        """Attach the validated context before any protected handler executes."""

        if not self._requires_authentication(request):
            return None
        if self.auth_manager is None:
            return JSONResponse(
                status_code=503,
                content=_error(
                    "authentication_unavailable", "Authentication is temporarily unavailable."
                ),
            )
        try:
            context = self.auth_manager.authenticate(
                request.cookies.get(SESSION_COOKIE_NAME), datetime.now(UTC)
            )
            # Factor pages and endpoints must remain reachable by the provisional session so the
            # browser can complete enrollment before the workspace gate is applied.
            is_logout = request.scope["path"] == "/api/v1/auth/logout"
            factor_path = request.scope["path"].startswith(
                ("/api/v1/auth/passkeys/", "/api/v1/auth/totp/")
            ) or request.scope["path"] in {"/passkey", "/authenticator"}
            if (
                not is_logout
                and not factor_path
                and self.auth_manager.settings.mode == "github"
                and context.mfa_method != "totp"
            ):
                if not request.scope["path"].startswith("/api/v1/"):
                    return RedirectResponse(
                        "/authenticator?mode="
                        + ("enroll" if not context.user.totp_enrolled else "verify")
                        + "&next="
                        + quote(request.scope["path"], safe="/"),
                        status_code=303,
                    )
                return JSONResponse(
                    status_code=403,
                    content=_error(
                        "totp_required",
                        "Verify your authenticator code before using this application.",
                    ),
                )
            request.state.auth_context = context
            return None
        except AuthError as exc:
            if (
                not request.scope["path"].startswith("/api/v1/")
                and exc.code == "authentication_required"
            ):
                return RedirectResponse(
                    "/sign-in?next=" + quote(request.scope["path"], safe="/"), status_code=303
                )
            return self._auth_rejection(exc)

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
        owner_user_id: int | None = None,
    ) -> str | None:
        """Audit a rejected forecast without parsing or retaining its untrusted body."""

        request_id = str(uuid4())
        now = datetime.now(UTC)
        # Persistence requires a cutoff marker for fresh-analysis failures. Before body parsing,
        # the receipt time is the only truthful bounded marker available; error_code records why.
        requested_cutoff = now if analysis_kind == "fresh_historical_reconstruction" else None
        try:
            _call_with_owner(
                self.repository.record_failure,
                owner_user_id,
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

        owner_user_id = (
            request.state.auth_context.user.id
            if isinstance(getattr(request.state, "auth_context", None), AuthContext)
            else None
        )
        if owner_user_id is None and (self.auth_manager is None or not self.auth_manager.enabled):
            try:
                owner_user_id = self.repository.legacy_owner_id()
            except (sqlite3.Error, ValueError, AttributeError):
                return None
        reconstruction = _reconstruction_submission_context(
            self.repository, request.scope["path"], owner_user_id
        )
        if request.method != "POST" or (
            request.scope["path"] != "/api/v1/forecasts" and reconstruction is None
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
            owner_user_id=owner_user_id,
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

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Handle Host here instead of TrustedHostMiddleware so its rejection also uses the
        # API error envelope and receives the same headers as every other response. These
        # checks intentionally precede audit handling: hostile browser traffic is not a trusted
        # application submission and must not be able to grow the local event ledger.
        host_values = request.headers.getlist("host")
        host_header = host_values[0] if len(host_values) == 1 else ""
        authority = self._host_authority(host_header)
        public_authority = urlparse(self.public_origin).netloc if self.public_origin else None
        host_is_allowed = authority is not None and (
            authority.hostname in self.allowed_hosts
            or (
                public_authority is not None
                and authority.netloc.lower() == public_authority.lower()
            )
        )
        if not host_is_allowed:
            response: Response = JSONResponse(
                status_code=400,
                content=_error("host_rejected", "The requested host is not configured."),
            )
            return self._secure(response, request)

        request_gate_exempt = request.scope["path"] in {
            "/api/v1/health",
            "/api/v1/readiness",
            "/api/v1/operations/restores",
        }
        gate_entered = False
        if not request_gate_exempt:
            if not self.request_gate.try_enter():
                response = JSONResponse(
                    status_code=503,
                    content=_error(
                        "maintenance_mode",
                        "The application is temporarily unavailable during a verified restore.",
                    ),
                )
                return self._secure(response, request)
            gate_entered = True
        try:
            if self.maintenance_event.is_set() and request.scope["path"] not in {
                "/api/v1/health",
                "/api/v1/readiness",
                "/api/v1/operations/restores",
            }:
                response = JSONResponse(
                    status_code=503,
                    content=_error(
                        "maintenance_mode",
                        "The application is temporarily unavailable during a verified restore.",
                    ),
                )
                return self._secure(response, request)

            history_suffix = request.scope["path"].removeprefix("/api/v1/history/")
            history_id = history_suffix.split("/", 1)[0]
            if (
                history_suffix != request.scope["path"]
                and len(history_id) > 10
                and history_id.isascii()
                and history_id.isdecimal()
            ):
                return self._secure(
                    JSONResponse(
                        status_code=422,
                        content=_error("validation_error", "Request validation failed."),
                    ),
                    request,
                )

            origin = request.headers.get("origin")
            if origin:
                parsed_host = None
                try:
                    parsed = urlparse(origin)
                    parsed_host = parsed.hostname
                    origin_port = parsed.port
                    expected = self._allowed_origin(request, host_header)
                    expected_parsed = urlparse(expected) if expected else None
                    same_origin = (
                        expected_parsed is not None
                        and (origin_port is None or 1 <= origin_port <= 65_535)
                        and parsed.scheme == expected_parsed.scheme
                        and parsed_host == expected_parsed.hostname
                        and parsed.username is None
                        and parsed.password is None
                        and (
                            origin_port if origin_port is not None else _default_port(parsed.scheme)
                        )
                        == (
                            expected_parsed.port
                            if expected_parsed.port is not None
                            else _default_port(expected_parsed.scheme)
                        )
                    )
                except ValueError:
                    same_origin = False
                allowed_browser_hosts = set(self.browser_hosts)
                if self.public_hostname:
                    allowed_browser_hosts.add(self.public_hostname)
                if parsed_host not in allowed_browser_hosts or not same_origin:
                    response = JSONResponse(
                        status_code=403,
                        content=_error("origin_rejected", "The browser origin is not allowed."),
                    )
                else:
                    auth_response = self._authenticate_request(request)
                    response = auth_response or await self._bounded_request(request, call_next)
            elif (
                request.headers.get("sec-fetch-site", "").lower() == "cross-site"
                and not (
                    request.method == "GET"
                    and request.scope["path"] == "/api/v1/auth/github/callback"
                )
                and not (
                    request.method == "GET"
                    and request.scope["path"] in self.html_navigation_paths
                    and request.headers.get("sec-fetch-mode", "").lower() == "navigate"
                    and request.headers.get("sec-fetch-dest", "").lower() == "document"
                )
            ):
                # Modern browsers provide this header even on requests where Origin is omitted.
                # A top-level navigation to an HTML page may come from an email or another
                # site. Keep the exception confined to named pages; authentication still runs.
                response = JSONResponse(
                    status_code=403,
                    content=_error(
                        "origin_rejected", "Cross-site browser requests are not allowed."
                    ),
                )
            else:
                auth_response = self._authenticate_request(request)
                response = auth_response or await self._bounded_request(request, call_next)
            return self._secure(response, request)

        finally:
            if gate_entered:
                self.request_gate.leave()

    def _secure(self, response: Response, request: Request) -> Response:
        """Apply browser isolation even to validation, host, and mounted-asset errors."""

        # Error responses receive the same protections as successful HTML/API responses.
        response.headers["Content-Security-Policy"] = self.content_security_policies.get(
            request.scope["path"], self.content_security_policy
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        if self.public_origin and self.public_origin.startswith("https://"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
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
            request_id = self._audit_transport_rejection(request, code, message, forecast_label)
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


def _oauth_caller_identity(request: Request, trusted_proxy_hosts: tuple[str, ...]) -> str:
    """Return the socket IP, using Cloudflare's client IP only from the trusted connector."""

    client = request.client
    if client is None or not isinstance(client.host, str) or not client.host:
        raise AuthUnavailable("GitHub sign-in is temporarily unavailable.")
    peer = client.host.strip()
    if not peer or len(peer) > 253:
        raise AuthUnavailable("GitHub sign-in is temporarily unavailable.")

    if peer.lower() in {host.lower() for host in trusted_proxy_hosts}:
        cloudflare_ip = request.headers.get("cf-connecting-ip", "").strip()
        if 1 <= len(cloudflare_ip) <= 64:
            try:
                return str(ipaddress.ip_address(cloudflare_ip))
            except ValueError:
                # An invalid connector header falls back to the transport peer, never another
                # forwarded header whose value may still be supplied by the remote browser.
                pass
    try:
        return str(ipaddress.ip_address(peer))
    except ValueError:
        # In-process ASGI transports can use a named peer such as "testclient". Production
        # Uvicorn peers are socket addresses, and the value remains bounded above.
        return peer.lower()


def _call_with_owner(
    callable_value: Callable[..., Any], owner_user_id: int | None, *args: Any, **kwargs: Any
) -> Any:
    """Pass ownership explicitly and fail closed when a private method lacks the boundary."""

    if owner_user_id is not None:
        try:
            parameters = signature(callable_value).parameters
        except (TypeError, ValueError) as exc:
            raise AuthUnavailable("Private data ownership could not be verified.") from exc
        if "owner_user_id" not in parameters:
            raise AuthUnavailable("Private data ownership is not enforced by this operation.")
        owner_parameter = parameters["owner_user_id"]
        if owner_parameter.kind in {
            owner_parameter.POSITIONAL_ONLY,
            owner_parameter.POSITIONAL_OR_KEYWORD,
        }:
            # Persistence uses positional owner IDs for simple record lookups and keyword-only
            # ownership for larger writes. Put the ID in the declared slot so a following
            # event/result ID is not accidentally bound twice.
            args = (owner_user_id, *args)
        else:
            kwargs["owner_user_id"] = owner_user_id
    return callable_value(*args, **kwargs)


_RESTORE_SECURITY_TABLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "users",
        (
            "id",
            "github_user_id",
            "login",
            "email",
            "display_name",
            "password_hash",
            "role",
            "status",
            "legacy_owner_claimed_at",
        ),
    ),
    (
        "invitations",
        (
            "id",
            "github_user_id",
            "github_login",
            "token_hash",
            "invited_by_user_id",
            "expires_at",
            "used_at",
            "created_at",
        ),
    ),
    (
        "passkeys",
        (
            "id",
            "user_id",
            "credential_id",
            "public_key",
            "sign_count",
            "transports",
            "revoked_at",
        ),
    ),
    (
        "oauth_states",
        (
            "id",
            "state_hash",
            "code_verifier",
            "redirect_uri",
            "invitation_code_hash",
            "created_at",
            "expires_at",
            "consumed_at",
        ),
    ),
    (
        "totp_factors",
        (
            "id",
            "user_id",
            "secret_ciphertext",
            "created_at",
            "confirmed_at",
            "last_accepted_step",
            "updated_at",
        ),
    ),
    (
        "totp_enrollments",
        (
            "id",
            "user_id",
            "secret_ciphertext",
            "created_at",
            "expires_at",
            "expected_factor_id",
            "origin_token_hash",
        ),
    ),
    (
        "recovery_codes",
        (
            "id",
            "user_id",
            "code_hash",
            "created_at",
            "consumed_at",
            "revoked_at",
        ),
    ),
    (
        "totp_attempt_throttles",
        (
            "user_id",
            "window_started_at",
            "attempt_count",
            "last_attempt_at",
            "locked_until",
        ),
    ),
)


def _restore_security_digest(path: Path) -> str:
    """Fingerprint account and authenticator state without exposing its secret values."""

    try:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only = ON")
            state: list[tuple[str, list[tuple[object, ...]]]] = []
            for table, columns in _RESTORE_SECURITY_TABLES:
                quoted_columns = ", ".join(columns)
                order_column = "user_id" if table == "totp_attempt_throttles" else "id"
                rows = connection.execute(
                    f"SELECT {quoted_columns} FROM {table} ORDER BY {order_column}"  # noqa: S608
                ).fetchall()
                state.append((table, [tuple(row[column] for column in columns) for row in rows]))
        finally:
            connection.close()
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise AuthUnavailable("Account security state could not be verified.") from exc
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _revoke_every_session(repository: Repository, revoked_at: datetime) -> None:
    """Invalidate sessions in the promoted database before the route returns."""

    timestamp = revoked_at.astimezone(UTC).isoformat()
    try:
        with repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE sessions SET revoked_at = ?, revocation_reason = ? "
                "WHERE revoked_at IS NULL",
                (timestamp, "restore_promotion"),
            )
            connection.commit()
    except (OSError, sqlite3.Error) as exc:
        raise AuthUnavailable("Promoted restore could not revoke existing sessions.") from exc


def _clear_pending_oauth_states(repository: Repository) -> None:
    """Discard transient OAuth/PKCE transactions after a database promotion."""

    try:
        with repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM oauth_states")
            connection.commit()
    except (OSError, sqlite3.Error) as exc:
        raise AuthUnavailable("Promoted restore could not clear OAuth transactions.") from exc


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


_HISTORY_SCAN_LIMIT = 10_000
_HORIZON_INTERVALS: dict[str, ForecastInterval] = {
    horizon: cast(ForecastInterval, interval)
    for interval, horizon in FORECAST_INTERVAL_HORIZONS.items()
}
_LEGACY_HORIZONS = {"close_to_close", "completed_5m_to_close"}
_ALL_HORIZONS = _LEGACY_HORIZONS | set(_HORIZON_INTERVALS)


def _forecast_response_view(
    generated: dict[str, Any], interval: ForecastInterval | None = None
) -> dict[str, Any]:
    """Project the requested persisted contract while retaining legacy reopen behavior."""

    snapshot = generated.get("input")
    recorded_interval = snapshot.get("requested_interval") if isinstance(snapshot, dict) else None
    if interval is not None and isinstance(snapshot, dict) and recorded_interval != interval:
        # A saved run is immutable: a different requested interval is a conflict, not an empty
        # successful forecast. Starlette's existing 409 handler supplies the public error shape.
        raise HTTPException(status_code=409)
    effective_interval = interval or recorded_interval
    selected = (
        _LEGACY_HORIZONS
        if effective_interval is None
        else {FORECAST_INTERVAL_HORIZONS[effective_interval]}
    )
    results = []
    for source in generated.get("results", []):
        if source.get("horizon") not in selected:
            continue
        result = dict(source)
        rolling_interval = _HORIZON_INTERVALS.get(str(result.get("horizon")))
        if rolling_interval is not None:
            result["interval"] = rolling_interval
            result.setdefault("horizon_start_timestamp", result.get("origin_timestamp"))
            result.setdefault("horizon_end_timestamp", result.get("target_timestamp"))
        results.append(result)
    return {**generated, "results": results}


def _iso_or_none(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _safe_metadata_header(value: dict[str, Any]) -> str:
    """Encode bounded download metadata with an HTTP-header-safe alphabet."""

    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _history_filters(
    *,
    query: str,
    symbol: str | None,
    company: str | None,
    status: str | None,
    asset_type: str | None,
    analysis_kind: str | None,
    submitted_from: datetime | None,
    submitted_to: datetime | None,
    model: str | None,
    model_version: str | None,
    horizon: str | None,
    request_id: str | None,
    event_id: int | None,
) -> dict[str, Any]:
    """Normalize one public filter set for list and download responses."""

    text_values = (query, symbol, company, model, model_version, request_id)
    if any(
        value is not None
        and any(unicodedata.category(character).startswith("C") for character in value)
        for value in text_values
    ):
        raise DomainError(
            "invalid_history_filter",
            "History filters contain unsupported characters.",
            status_code=422,
        )
    return {
        "query": query.strip(),
        "symbol": symbol.strip().upper() if symbol else None,
        "company": company.strip() if company else None,
        "status": status,
        "asset_type": asset_type,
        "analysis_kind": analysis_kind,
        "submitted_from": _iso_or_none(submitted_from),
        "submitted_to": _iso_or_none(submitted_to),
        "model": model.strip() if model else None,
        "model_version": model_version.strip() if model_version else None,
        "horizon": horizon,
        "request_id": request_id.strip() if request_id else None,
        "event_id": event_id,
    }


def _validate_history_dates(submitted_from: datetime | None, submitted_to: datetime | None) -> None:
    """Require explicit offsets and an ordered inclusive submission window."""

    if any(value is not None and value.tzinfo is None for value in (submitted_from, submitted_to)):
        raise DomainError(
            "invalid_history_date",
            "History dates must include a timezone offset.",
            status_code=422,
        )
    if submitted_from is not None and submitted_to is not None and submitted_from > submitted_to:
        raise DomainError(
            "invalid_history_date_range",
            "History start date must not follow its end date.",
            status_code=422,
        )


def _history_event_view(
    service: ForecastService,
    event: dict[str, Any],
    detail: dict[str, Any] | None = None,
    *,
    hydrate_results: bool = True,
    visible_horizon: str | None = None,
    owner_user_id: int | None = None,
) -> dict[str, Any]:
    """Add bounded display facts while keeping a failed request result-free."""

    item = dict(event)
    if item.get("run_id") is None:
        item.update(
            {
                "canonical_symbol": item.get("normalized_symbol"),
                "company_name": None,
                "display_name": None,
                "exchange": None,
                "quote_type": None,
                "model_name": None,
                "model_version": None,
                "horizons": [],
                "outcome_count": 0,
                "evaluation_statuses": [],
                "forecast_available": False,
            }
        )
        return item

    if not hydrate_results:
        horizons = list(item.get("horizons", []))
        statuses = list(item.get("evaluation_statuses", []))
        visible = (
            _ALL_HORIZONS
            if visible_horizon is None
            else {visible_horizon}
            if visible_horizon in _HORIZON_INTERVALS
            else _LEGACY_HORIZONS
        )
        item["horizons"] = [horizon for horizon in horizons if horizon in visible]
        item["evaluation_statuses"] = [
            status
            for horizon, status in zip(horizons, statuses, strict=False)
            if horizon in visible
        ]
        item["forecast_available"] = True
        return item
    detail = detail or _call_with_owner(service.history_detail, owner_user_id, int(item["id"]))
    snapshot = detail.get("input") if detail else None
    recorded_interval = snapshot.get("requested_interval") if isinstance(snapshot, dict) else None
    visible = (
        {visible_horizon}
        if visible_horizon in _ALL_HORIZONS
        else (
            {FORECAST_INTERVAL_HORIZONS[recorded_interval]}
            if recorded_interval in FORECAST_INTERVAL_HORIZONS
            else _ALL_HORIZONS
        )
    )
    results = [
        result
        for result in (detail.get("results", []) if detail else [])
        if result.get("horizon") in visible
    ]
    if not isinstance(snapshot, dict):
        # Do not make a partial run look reopenable when its recorded input is unavailable.
        item.update(
            {
                "horizons": [],
                "outcome_count": 0,
                "evaluation_statuses": [],
                "forecast_available": False,
            }
        )
        return item
    identity = snapshot.get("instrument_identity")
    identity = identity if isinstance(identity, dict) else snapshot
    model_identity = snapshot.get("model")
    model_identity = model_identity if isinstance(model_identity, dict) else {}
    item.update(
        {
            "canonical_symbol": identity.get("canonical_symbol"),
            "company_name": identity.get("company_name"),
            "display_name": identity.get("display_name"),
            "exchange": identity.get("exchange"),
            "quote_type": identity.get("quote_type"),
            "model_name": model_identity.get("name"),
            "model_version": model_identity.get("version"),
            "forecast_contract_version": snapshot.get("forecast_contract_version"),
            "horizons": [result.get("horizon") for result in results],
            "outcome_count": sum(len(result.get("outcomes", [])) for result in results),
            "evaluation_statuses": [
                result.get("evaluation", {}).get("status") for result in results
            ],
            "forecast_available": True,
        }
    )
    return item


def _matches_history_filters(item: dict[str, Any], filters: dict[str, Any]) -> bool:
    """Apply the exact browser filter meanings to one enriched event."""

    query = str(filters["query"]).casefold()
    searchable = (
        item.get("submitted_symbol"),
        item.get("normalized_symbol"),
        item.get("company_name"),
        item.get("display_name"),
        item.get("request_id"),
    )
    if query and not any(query in str(value).casefold() for value in searchable if value):
        return False
    if (
        filters["symbol"]
        and str(item.get("normalized_symbol") or item.get("submitted_symbol")).upper()
        != filters["symbol"]
    ):
        return False
    if (
        filters["company"]
        and filters["company"].casefold() not in str(item.get("company_name") or "").casefold()
    ):
        return False
    for name in ("status", "asset_type", "analysis_kind", "request_id"):
        if filters[name] is not None and item.get(name) != filters[name]:
            return False
    if filters["event_id"] is not None and item.get("id") != filters["event_id"]:
        return False
    submitted_at = datetime.fromisoformat(str(item["submitted_at"]))
    if filters["submitted_from"] and submitted_at < datetime.fromisoformat(
        filters["submitted_from"]
    ):
        return False
    if filters["submitted_to"] and submitted_at > datetime.fromisoformat(filters["submitted_to"]):
        return False
    if filters["model"]:
        needle = filters["model"].casefold()
        if not any(
            needle in str(item.get(field) or "").casefold()
            for field in ("model_name", "model_version")
        ):
            return False
    return not filters["horizon"] or filters["horizon"] in item.get("horizons", [])


def _history_sort_value(item: dict[str, Any], field: str) -> tuple[bool, Any]:
    mapped = {
        "event_id": item.get("id"),
        "symbol": item.get("normalized_symbol") or item.get("submitted_symbol"),
        "company": item.get("company_name"),
        "model": item.get("model_version") or item.get("model_name"),
        "horizon": ",".join(item.get("horizons", [])),
    }.get(field, item.get(field))
    if isinstance(mapped, str):
        mapped = mapped.casefold()
    return mapped is None, mapped


def _query_history(
    service: ForecastService,
    *,
    filters: dict[str, Any],
    sort_by: str,
    sort_order: str,
    page: int,
    page_size: int,
    owner_user_id: int | None = None,
) -> dict[str, Any]:
    """Return an exact bounded page using only the established history interface."""

    post_processed = (
        any(
            filters[name] is not None
            for name in (
                "horizon",
                "event_id",
            )
        )
        or sort_by != "event_id"
        or sort_order != "desc"
    )

    def indexed_page(index: int, size: int) -> dict[str, Any]:
        try:
            return _call_with_owner(
                service.history,
                owner_user_id,
                query=filters["query"],
                symbol=filters["symbol"],
                company=filters["company"],
                status=filters["status"],
                asset_type=filters["asset_type"],
                analysis_kind=filters["analysis_kind"],
                date_from=(
                    datetime.fromisoformat(filters["submitted_from"])
                    if filters["submitted_from"]
                    else None
                ),
                date_to=(
                    datetime.fromisoformat(filters["submitted_to"])
                    if filters["submitted_to"]
                    else None
                ),
                model=filters["model"],
                model_version=filters["model_version"],
                request_id=filters["request_id"],
                page=index,
                page_size=size,
            )
        except ValueError:
            raise DomainError(
                "invalid_history_filter",
                "One or more history filters are invalid.",
                status_code=422,
            ) from None

    if not post_processed:
        result = indexed_page(page, page_size)
        result["items"] = [
            _history_event_view(
                service,
                item,
                hydrate_results=False,
                visible_horizon=filters["horizon"],
                owner_user_id=owner_user_id,
            )
            for item in result["items"]
        ]
    else:
        first = indexed_page(1, 100)
        if first["total"] > _HISTORY_SCAN_LIMIT:
            raise DomainError(
                "history_filter_too_broad",
                "Add an asset, status, or analysis filter to keep this history request bounded.",
                status_code=422,
            )
        raw_items = list(first["items"])
        for next_page in range(2, (first["total"] + 99) // 100 + 1):
            raw_items.extend(indexed_page(next_page, 100)["items"])
        enriched = [
            _history_event_view(
                service,
                item,
                hydrate_results=False,
                visible_horizon=filters["horizon"],
                owner_user_id=owner_user_id,
            )
            for item in raw_items
        ]
        matched = [item for item in enriched if _matches_history_filters(item, filters)]
        # ID is the deterministic tie-breaker regardless of the selected display field.
        matched.sort(key=lambda item: int(item["id"]))
        matched.sort(
            key=lambda item: _history_sort_value(item, sort_by),
            reverse=sort_order == "desc",
        )
        # Missing display facets (notably failed requests) stay last in either direction.
        matched.sort(key=lambda item: _history_sort_value(item, sort_by)[0])
        offset = (page - 1) * page_size
        result = {
            "items": matched[offset : offset + page_size],
            "page": page,
            "page_size": page_size,
            "total": len(matched),
        }
    total_pages = (result["total"] + page_size - 1) // page_size
    return {
        **result,
        "total_pages": total_pages,
        "has_previous": page > 1,
        "has_next": page < total_pages,
        "filters": filters,
        "sort": {"field": sort_by, "direction": sort_order},
    }


def _bounded_history_export(
    service: ForecastService,
    *,
    filters: dict[str, Any],
    sort_by: str,
    sort_order: str,
    owner_user_id: int | None = None,
) -> dict[str, Any]:
    """Adapt the service's fixed-query bulk stream once for both download formats."""

    try:
        # Every successful run owns both required horizons, so either horizon has this exact
        # indexed persistence-side meaning and needs no per-event reconstruction.
        source = _call_with_owner(
            service.repository.history_export,
            owner_user_id,
            generated_at=service.clock().astimezone(UTC),
            query=filters["query"],
            symbol=filters["symbol"],
            company=filters["company"],
            status=filters["status"],
            asset_type=filters["asset_type"],
            analysis_kind=filters["analysis_kind"],
            semantics="success" if filters["horizon"] else None,
            date_from=(
                datetime.fromisoformat(filters["submitted_from"])
                if filters["submitted_from"]
                else None
            ),
            date_to=(
                datetime.fromisoformat(filters["submitted_to"]) if filters["submitted_to"] else None
            ),
            model=filters["model"],
            model_version=filters["model_version"],
            request_id=filters["request_id"],
            event_id=filters["event_id"],
            horizon=filters["horizon"],
            max_events=100,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except ValueError:
        raise DomainError(
            "invalid_history_filter",
            "One or more history filters are invalid.",
            status_code=422,
        ) from None

    run_records: dict[int, dict[str, Any]] = {}
    results_by_run: dict[int, list[dict[str, Any]]] = {}
    raw_events: list[dict[str, Any]] = []
    for record in source["records"]:
        if record["record_type"] == "event":
            raw_events.append(record)
        elif record["record_type"] == "run":
            run_records[int(record["run_id"])] = record
        elif record["record_type"] == "result":
            horizon = record["data"].get("horizon")
            visible = (
                _ALL_HORIZONS
                if filters["horizon"] is None
                else {filters["horizon"]}
                if filters["horizon"] in _HORIZON_INTERVALS
                else _LEGACY_HORIZONS
            )
            if horizon in visible:
                projected = _forecast_response_view(
                    {"results": [record["data"]]}, _HORIZON_INTERVALS.get(horizon)
                )["results"]
                if projected:
                    results_by_run.setdefault(int(record["run_id"]), []).append(
                        {**record, "data": projected[0]}
                    )

    enriched_events: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for record in raw_events:
        event = record["data"]
        run_id = int(record["run_id"]) if record["run_id"] is not None else None
        detail = None
        if run_id is not None:
            run_record = run_records.get(run_id)
            if run_record is None:
                raise sqlite3.IntegrityError("forecast run is missing its immutable input")
            detail = {
                "input": run_record["data"],
                "results": [item["data"] for item in results_by_run.get(run_id, [])],
            }
        enriched = _history_event_view(
            service,
            event,
            detail,
            visible_horizon=filters["horizon"],
        )
        if _matches_history_filters(enriched, filters):
            enriched_events.append((record, enriched))

    selected = enriched_events[:100]

    records: list[dict[str, Any]] = []
    seen_runs: set[int] = set()
    result_count = 0
    for event_record, event in selected:
        run_id = int(event_record["run_id"]) if event_record["run_id"] is not None else None
        records.append({**event_record, "data": event})
        if run_id is None or run_id in seen_runs:
            continue
        seen_runs.add(run_id)
        records.append(run_records[run_id])
        run_results = results_by_run.get(run_id, [])
        records.extend(run_results)
        result_count += len(run_results)

    payload = {
        "format": source["format"],
        "format_version": source["format_version"],
        "generated_at": source["generated_at"],
        "filters": filters,
        "sort": {"field": sort_by, "direction": sort_order},
        "total_events": source["total_events"],
        "exported_events": len(selected),
        "truncated": source["truncated"],
        "counts": {
            "events": len(selected),
            "runs": len(seen_runs),
            "results": result_count,
        },
        "records": records,
    }
    # Normalize timestamps and discriminated records before CSV serializes the same contract.
    return HistoryJsonExportResponse.model_validate(payload).model_dump(
        mode="json", exclude_unset=True
    )


def create_app(
    settings: Settings | None = None,
    provider: MarketDataProvider | None = None,
    clock: Callable[[], datetime] | None = None,
    *,
    auth_store: object | None = None,
    passkey_backend: PasskeyBackend | None = None,
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
    auth_manager = AuthManager(
        auth_store if auth_store is not None else repository,
        config.auth_settings(),
        passkey_backend=passkey_backend,
    )
    static_dir = Path(__file__).parent / "static"
    next_dir = static_dir / "next"
    workspace_pages = {
        "/": next_dir / "index.html",
        "/api-docs": next_dir / "api-docs.html",
        "/api/v1/docs": next_dir / "api-docs.html",
        "/overview": next_dir / "overview.html",
        "/research": next_dir / "research.html",
        "/tools": next_dir / "tools.html",
        "/tools/forecast": next_dir / "tools" / "forecast.html",
        "/tools/live-trading": next_dir / "tools" / "live-trading.html",
        "/tools/markets": next_dir / "tools" / "markets.html",
        "/sign-in": next_dir / "sign-in.html",
        "/invite": next_dir / "invite.html",
        "/passkey": next_dir / "passkey.html",
        "/authenticator": next_dir / "authenticator.html",
        "/account": next_dir / "account.html",
        "/admin": next_dir / "admin.html",
    }
    legacy_page_paths = tuple(
        workspace_pages[route]
        for route in (
            "/",
            "/api-docs",
            "/api/v1/docs",
            "/overview",
            "/research",
            "/tools",
            "/tools/forecast",
            "/tools/live-trading",
            "/tools/markets",
        )
        if workspace_pages[route].is_file()
    )
    content_security_policy = _static_script_csp(*legacy_page_paths)
    # Keep the legacy dashboard/docs contract stable while granting each auth shell only the
    # inline hashes emitted by that page. A single union policy would authorize unrelated auth
    # bootstraps on every public document.
    auth_content_security_policies = {
        route: _static_script_csp(workspace_pages[route])
        for route in (
            "/sign-in",
            "/invite",
            "/passkey",
            "/authenticator",
            "/account",
            "/admin",
        )
        if workspace_pages[route].is_file()
    }
    restore_lock = threading.Lock()
    maintenance_event = threading.Event()
    request_gate = _RestoreRequestGate()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        config.ensure_local_dirs()
        repository.migrate()
        if (
            auth_manager.settings.mode == "local"
            and config.bootstrap_username
            and config.bootstrap_password
        ):
            auth_manager.ensure_local_bootstrap(
                config.bootstrap_username,
                config.bootstrap_password,
                datetime.now(UTC),
            )
        if (
            auth_manager.settings.mode == "local"
            and config.bootstrap_member_username
            and config.bootstrap_member_password
        ):
            auth_manager.ensure_local_bootstrap(
                config.bootstrap_member_username,
                config.bootstrap_member_password,
                datetime.now(UTC),
                role="member",
            )
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
    app.state.auth = auth_manager
    app.state.ready = False
    app.add_middleware(
        LocalSecurityMiddleware,
        repository=repository,
        content_security_policy=content_security_policy,
        content_security_policies=auth_content_security_policies,
        auth_manager=auth_manager,
        public_origin=config.auth_public_origin,
        trusted_proxy_hosts=config.trusted_proxy_hosts,
        maintenance_event=maintenance_event,
        request_gate=request_gate,
    )

    def _public_user(user: UserRecord) -> dict[str, object]:
        """Serialize account identity without password, token, or provider secrets."""

        # The legacy login/session response model predates the authenticator capability field;
        # setup state is exposed by /api/v1/auth/totp/status instead.
        result = user.public_dict()
        result.pop("totp_enrolled", None)
        return result

    def _auth_context(
        request: Request, *, role: str | None = None, step_up: bool = False
    ) -> AuthContext:
        """Resolve middleware identity and enforce role, CSRF, and admin step-up rules."""

        if not auth_manager.enabled:
            raise AuthenticationRequired()
        context = getattr(request.state, "auth_context", None)
        if not isinstance(context, AuthContext):
            context = auth_manager.authenticate(
                request.cookies.get(SESSION_COOKIE_NAME), datetime.now(UTC)
            )
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            auth_manager.require_csrf(context, request.headers.get("x-csrf-token"))
        if role == "admin":
            auth_manager.require_role(context, "admin")
        if step_up and not auth_manager.has_recent_step_up(context, datetime.now(UTC)):
            raise AuthorizationDenied("A fresh authenticator code is required for this operation.")
        return context

    def _owner_user_id(request: Request) -> int | None:
        """Return the authenticated owner or the designated legacy owner in disabled mode."""

        if not auth_manager.enabled:
            return repository.legacy_owner_id()
        return _auth_context(request).user.id

    def _set_auth_cookies(
        response: Response, session_token: str, csrf_token: str, expires_at: datetime
    ) -> None:
        """Set one HttpOnly session cookie and one non-secret CSRF token cookie."""

        common = {
            "path": "/",
            "secure": config.auth_cookie_secure,
            "httponly": False,
            "samesite": "lax",
            "domain": config.auth_cookie_domain,
            "expires": expires_at,
        }
        response.set_cookie(
            SESSION_COOKIE_NAME,
            session_token,
            **{**common, "httponly": True},
        )
        response.set_cookie(CSRF_COOKIE_NAME, csrf_token, **common)

    def _set_oauth_transaction_cookie(response: Response, state: str) -> None:
        """Bind the OAuth redirect to this host's initiating browser transaction."""

        response.set_cookie(
            OAUTH_TRANSACTION_COOKIE_NAME,
            state,
            max_age=auth_manager.settings.oauth_state_ttl_seconds,
            path="/",
            secure=config.auth_cookie_secure,
            httponly=True,
            samesite="lax",
        )

    def _clear_oauth_transaction_cookie(response: Response) -> None:
        """Expire the one-time OAuth transaction after callback success or rejection."""

        response.delete_cookie(OAUTH_TRANSACTION_COOKIE_NAME, path="/")

    def _clear_auth_cookies(response: Response) -> None:
        """Expire both browser cookies after logout or a rejected session."""

        response.delete_cookie(SESSION_COOKIE_NAME, path="/", domain=config.auth_cookie_domain)
        response.delete_cookie(CSRF_COOKIE_NAME, path="/", domain=config.auth_cookie_domain)

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
        owner_user_id: int | None = None,
    ) -> str:
        """Append one transport-classified event when no service call will own the audit."""

        request_id = str(uuid4())
        now = datetime.now(UTC)
        if analysis_kind == "fresh_historical_reconstruction" and requested_cutoff is None:
            # Validation can fail before a cutoff exists; preserve one labelled event using its
            # receipt time rather than retaining or reparsing an untrusted body value.
            requested_cutoff = now
        _call_with_owner(
            repository.record_failure,
            owner_user_id,
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

    def record_malformed_forecast_response(
        generated: object,
        *,
        submitted_symbol: str,
        asset_type: str,
        owner_user_id: int | None = None,
    ) -> str:
        """Audit a broken service handoff once, reusing its correlation identity when present."""

        request_id: str | None = None
        if isinstance(generated, dict):
            event = generated.get("event")
            candidate = event.get("request_id") if isinstance(event, dict) else None
            # request_id is the existing public correlation field. Preserve it while excluding
            # every other malformed response value from both persistence and the error envelope.
            if isinstance(candidate, str) and candidate:
                request_id = candidate
        request_id = request_id or str(uuid4())
        now = datetime.now(UTC)
        # request_id is unique and all other inserted fields are controlled below. An atomic
        # conflict means the service already committed this request's audit event; a separate
        # read-before-write check would race with that commit under concurrent requests.
        with suppress(sqlite3.IntegrityError):
            _call_with_owner(
                repository.record_failure,
                owner_user_id,
                request_id=request_id,
                submitted_symbol=submitted_symbol,
                normalized_symbol=None,
                asset_type=asset_type,
                error_code="internal_error",
                error_message="The local service could not complete the request.",
                submitted_at=now,
                completed_at=now,
            )
        return request_id

    @app.exception_handler(AuthError)
    async def auth_error(_: Request, exc: AuthError) -> JSONResponse:
        """Return stable auth errors without revealing account or provider internals."""

        headers = (
            {"Retry-After": str(exc.retry_after_seconds)}
            if isinstance(exc, OAuthStartLimited)
            else None
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error(exc.code, exc.public_message),
            headers=headers,
        )

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error(exc.code, exc.message, request_id=exc.request_id),
        )

    @app.exception_handler(BackupError)
    async def backup_error(request: Request, exc: BackupError) -> JSONResponse:
        request_id = str(uuid4())
        restoring = request.scope["path"] == "/api/v1/operations/restores"
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
        if request.scope["path"] == "/api/v1/auth/invites/redeem":
            # Invitation redemption is intentionally anonymous. Do not enter the generic POST
            # audit path here: resolving its owner would turn malformed invite input into a
            # misleading authentication failure before the invitation recovery message is shown.
            return JSONResponse(
                status_code=InvitationRejected.status_code,
                content=_error(InvitationRejected.code, InvitationRejected.message),
            )
        request_id = None
        if request.scope["path"] in {
            "/api/v1/operations/backups",
            "/api/v1/operations/restores",
        }:
            # Unknown field names are attacker-controlled. Keep operational validation useful
            # without reflecting a local-looking path or implementation term into the browser.
            details = []
            request_id = str(uuid4())
        elif request.method == "POST" and request.scope["path"] == "/api/v1/forecasts":
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
                owner_user_id=_owner_user_id(request),
            )
        elif request.method == "POST":
            validation_owner_id = _owner_user_id(request)
            reconstruction_context = _reconstruction_submission_context(
                repository, request.scope["path"], validation_owner_id
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
                        datetime.fromisoformat(raw_cutoff) if isinstance(raw_cutoff, str) else None
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
                    owner_user_id=validation_owner_id,
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
        backup_operation = request.scope["path"].startswith("/api/v1/operations/")
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
        }.get(request.scope["path"], "application")
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
        "/api/v1/auth/status",
        response_model=None,
        responses=_documented_errors(400, 403, 405, 500),
    )
    def auth_status() -> dict[str, object]:
        """Expose only the enabled sign-in mode and public origin to the sign-in screen."""

        return {
            "status": auth_manager.settings.mode,
            "public_origin": config.auth_public_origin,
            "passkey_required": False,
            "totp_required": auth_manager.settings.mode == "github",
        }

    @app.get(
        "/api/v1/auth/session",
        response_model=None,
        responses=_documented_errors(400, 403, 405, 500, 503),
    )
    def auth_session(request: Request) -> dict[str, object]:
        """Return the current account without reflecting an invalid cookie as a server error."""

        if not auth_manager.enabled:
            return {"authenticated": False, "user": None, "requires_passkey": False}
        try:
            context = auth_manager.authenticate(
                request.cookies.get(SESSION_COOKIE_NAME), datetime.now(UTC)
            )
        except AuthError:
            return {"authenticated": False, "user": None, "requires_passkey": False}
        record = auth_manager.store.auth_get_session(context.token_hash)
        expires_at = record.get("expires_at") if record else None
        requires_totp = auth_manager.settings.mode == "github" and context.mfa_method != "totp"
        return {
            "authenticated": True,
            "user": _public_user(context.user),
            "csrf_token": request.cookies.get(CSRF_COOKIE_NAME),
            "requires_passkey": False,
            "requires_totp": requires_totp,
            "mfa_method": context.mfa_method,
            "expires_at": expires_at,
            "role": context.user.role,
            "local_login_enabled": auth_manager.settings.mode == "local",
        }

    @app.get(
        "/api/v1/auth/totp/status",
        response_model=TotpStatusApiResponse,
        responses=_documented_errors(400, 403, 405, 500, 503),
    )
    def totp_status(request: Request) -> dict[str, object]:
        """Return authenticator setup state without returning factor secrets."""

        context = _auth_context(request)
        return auth_manager.totp_status(context, datetime.now(UTC))

    @app.post(
        "/api/v1/auth/totp/enroll/start",
        response_model=TotpEnrollmentStartApiResponse,
        responses=_documented_errors(400, 403, 405, 411, 413, 422, 429, 500, 503),
    )
    def totp_enrollment_start(
        request: Request,
        response: Response,
        payload: TotpEnrollmentStartRequest | None = None,
    ) -> dict[str, object]:
        """Start one short-lived authenticator enrollment transaction."""

        context = _auth_context(request)
        result = auth_manager.begin_totp_enrollment(
            context, datetime.now(UTC), replace=payload.replace if payload is not None else False
        )
        response.headers["Cache-Control"] = "no-store"
        return result

    @app.post(
        "/api/v1/auth/totp/enroll/finish",
        response_model=TotpEnrollmentFinishApiResponse,
        responses=_documented_errors(400, 403, 405, 411, 413, 422, 429, 500, 503),
    )
    def totp_enrollment_finish(
        request: Request, payload: TotpCodeRequest, response: Response
    ) -> dict[str, object]:
        """Confirm a code, activate TOTP, and rotate the account's sessions."""

        context = _auth_context(request)
        issue, recovery_codes = auth_manager.finish_totp_enrollment(
            context, payload.code, datetime.now(UTC)
        )
        _set_auth_cookies(response, issue.session_token, issue.csrf_token, issue.expires_at)
        response.headers["Cache-Control"] = "no-store"
        return {
            "authenticated": True,
            "user": _public_user(issue.context.user),
            "csrf_token": issue.csrf_token,
            "expires_at": issue.expires_at,
            "mfa_method": "totp",
            "recovery_codes": recovery_codes,
        }

    @app.post(
        "/api/v1/auth/totp/verify",
        response_model=TotpLoginApiResponse,
        responses=_documented_errors(400, 403, 405, 411, 413, 422, 429, 500, 503),
    )
    def totp_verify(
        request: Request, payload: TotpCodeRequest, response: Response
    ) -> dict[str, object]:
        """Verify an authenticator code after GitHub sign-in and issue a workspace session."""

        context = _auth_context(request)
        issue = auth_manager.verify_totp(context, payload.code, datetime.now(UTC))
        _set_auth_cookies(response, issue.session_token, issue.csrf_token, issue.expires_at)
        return {
            "authenticated": True,
            "user": _public_user(issue.context.user),
            "csrf_token": issue.csrf_token,
            "expires_at": issue.expires_at,
            "mfa_method": "totp",
        }

    @app.post(
        "/api/v1/auth/totp/step-up",
        response_model=TotpStepUpApiResponse,
        responses=_documented_errors(400, 403, 405, 411, 413, 422, 429, 500, 503),
    )
    def totp_step_up(request: Request, payload: TotpCodeRequest) -> dict[str, object]:
        """Record fresh five-minute TOTP proof for an administrator operation."""

        context = _auth_context(request)
        verified_at = auth_manager.step_up_totp(context, payload.code, datetime.now(UTC))
        return {"verified": True, "verified_at": verified_at}

    @app.post(
        "/api/v1/auth/totp/recover",
        response_model=TotpRecoveryApiResponse,
        responses=_documented_errors(400, 403, 405, 411, 413, 422, 429, 500, 503),
    )
    def totp_recover(
        request: Request, payload: TotpCodeRequest, response: Response
    ) -> dict[str, object]:
        """Consume one recovery code and issue a factor-replacement-only session."""

        context = _auth_context(request)
        issue = auth_manager.recover_with_code(context, payload.code, datetime.now(UTC))
        _set_auth_cookies(response, issue.session_token, issue.csrf_token, issue.expires_at)
        return {
            "authenticated": True,
            "user": _public_user(issue.context.user),
            "csrf_token": issue.csrf_token,
            "expires_at": issue.expires_at,
            "mfa_method": "recovery",
            "restricted": True,
        }

    @app.post(
        "/api/v1/auth/totp/recovery-codes/rotate",
        response_model=TotpRecoveryCodesApiResponse,
        responses=_documented_errors(400, 403, 405, 411, 413, 422, 429, 500, 503),
    )
    def totp_recovery_codes_rotate(
        request: Request, payload: TotpCodeRequest, response: Response
    ) -> dict[str, object]:
        """Replace recovery codes after a fresh TOTP verification."""

        context = _auth_context(request)
        recovery_codes = auth_manager.rotate_recovery_codes(
            context, payload.code, datetime.now(UTC)
        )
        response.headers["Cache-Control"] = "no-store"
        return {"recovery_codes": recovery_codes}

    @app.get(
        "/api/v1/auth/sessions",
        responses=_documented_errors(400, 403, 405, 500, 503),
    )
    def list_auth_sessions(request: Request) -> dict[str, object]:
        """List safe session metadata for the current account only."""

        context = _auth_context(request)
        records = auth_manager.store.auth_list_sessions(context.user.id)
        return {
            "sessions": [
                {
                    "id": item.get("session_id"),
                    "created_at": item.get("created_at"),
                    "last_seen_at": item.get("last_seen_at"),
                    "expires_at": item.get("expires_at"),
                    "current": item.get("session_id") == context.session_id,
                    "user_agent": item.get("user_agent"),
                }
                for item in records
                if isinstance(item.get("session_id"), str) and item.get("revoked_at") is None
            ]
        }

    @app.delete(
        "/api/v1/auth/sessions/{session_id}",
        status_code=204,
        response_class=Response,
        responses=_documented_errors(400, 403, 404, 405, 422, 500, 503),
    )
    def revoke_auth_session(request: Request, session_id: str) -> Response:
        """Revoke one sibling session after validating account ownership."""

        context = _auth_context(request)
        if not 8 <= len(session_id) <= 128 or not session_id.isascii():
            raise HTTPException(status_code=404)
        records = auth_manager.store.auth_list_sessions(context.user.id)
        if not any(item.get("session_id") == session_id for item in records):
            raise HTTPException(status_code=404)
        auth_manager.store.auth_revoke_session_by_id(
            context.user.id, session_id, datetime.now(UTC).isoformat()
        )
        return Response(status_code=204)

    @app.post(
        "/api/v1/auth/local/login",
        response_model=AuthLoginResponse,
        responses=_documented_errors(400, 403, 405, 411, 413, 422, 500, 503),
    )
    def local_login(payload: LocalLoginRequest, response: Response) -> dict[str, object]:
        """Authenticate only when development local mode is explicitly enabled."""

        issue = auth_manager.local_login(payload.username, payload.password, datetime.now(UTC))
        _set_auth_cookies(response, issue.session_token, issue.csrf_token, issue.expires_at)
        return {
            "authenticated": True,
            "user": _public_user(issue.context.user),
            "csrf_token": issue.csrf_token,
            "requires_passkey": issue.context.user.passkey_required
            and not issue.context.user.passkey_enrolled,
            "expires_at": issue.expires_at,
        }

    @app.post(
        "/api/v1/auth/logout",
        status_code=204,
        response_class=Response,
        responses=_documented_errors(400, 403, 405, 500, 503),
    )
    def logout(request: Request) -> Response:
        """Revoke the current session and expire both browser cookies."""

        context = _auth_context(request)
        auth_manager.logout(context, datetime.now(UTC))
        logged_out = Response(status_code=204)
        _clear_auth_cookies(logged_out)
        return logged_out

    @app.get(
        "/api/v1/auth/github/start",
        include_in_schema=False,
        responses={
            302: {"description": "Redirect to GitHub authorization."},
            **_documented_errors(400, 403, 405, 429, 503),
        },
    )
    def github_start(
        request: Request,
        invite: str | None = Query(default=None, min_length=20, max_length=128),
    ) -> RedirectResponse:
        """Start a server-side GitHub OAuth authorization-code transaction."""

        authorization = auth_manager.begin_github(
            datetime.now(UTC),
            caller_identity=_oauth_caller_identity(request, config.trusted_proxy_hosts),
            invitation_code=invite,
        )
        redirect = RedirectResponse(authorization.url, status_code=302)
        _set_oauth_transaction_cookie(redirect, authorization.state)
        return redirect

    @app.get(
        "/api/v1/auth/github/callback",
        response_model=AuthLoginResponse,
        responses=_documented_errors(400, 403, 405, 422, 500, 503),
    )
    def github_callback(
        request: Request,
        code: str = Query(min_length=8, max_length=512),
        state: str = Query(min_length=16, max_length=256),
    ) -> Response:
        """Finish browser-bound GitHub OAuth and issue a provisional session."""

        try:
            identity = auth_manager.finish_github(
                code,
                state,
                datetime.now(UTC),
                browser_transaction=request.cookies.get(OAUTH_TRANSACTION_COOKIE_NAME),
            )
            user_record = auth_manager.store.auth_get_user_by_github_id(identity.github_id)
            if identity.invitation_code_hash is not None:
                invitation = auth_manager.inspect_invitation_hash(
                    identity.invitation_code_hash, datetime.now(UTC)
                )
                invited_github_id = invitation.get("github_id", invitation.get("github_user_id"))
                if invited_github_id != identity.github_id:
                    raise InvitationRejected()
                auth_manager.consume_invitation_hash(
                    identity.invitation_code_hash, datetime.now(UTC)
                )
            elif user_record is None:
                if auth_manager.settings.owner_github_id != identity.github_id:
                    # A first-time member must arrive through an administrator invitation. The
                    # configured owner is the one exception and atomically claims legacy data.
                    raise InvitationRejected()
                user_record = auth_manager.store.auth_claim_legacy_owner(
                    {
                        "login": identity.login,
                        "display_name": identity.login,
                        "claimed_at": datetime.now(UTC).isoformat(),
                        "github_user_id": identity.github_id,
                        "email": identity.email,
                        "password_hash": None,
                    }
                )
                if user_record is None:
                    raise AuthUnavailable("The owner account could not be provisioned safely.")
            if user_record is None:
                user_record = auth_manager.store.auth_create_user(
                    {
                        "github_id": identity.github_id,
                        "github_login": identity.login,
                        "email": identity.email,
                        "role": "member",
                        "status": "active",
                        # Production sign-in uses GitHub plus an authenticator app. Keep the
                        # legacy columns false so old clients cannot advertise a passkey step.
                        "passkey_required": False,
                        "passkey_enrolled": False,
                        "created_at": datetime.now(UTC).isoformat(),
                    }
                )
            user = auth_manager.user_from_record(user_record)
            issue = auth_manager.issue_session(user, datetime.now(UTC), "github")
            if auth_manager.has_totp_factor(user.id):
                target = "/authenticator?mode=verify&next=/overview"
            else:
                target = "/authenticator?mode=enroll&next=/overview"
            redirect = RedirectResponse(target, status_code=303)
            _set_auth_cookies(redirect, issue.session_token, issue.csrf_token, issue.expires_at)
            _clear_oauth_transaction_cookie(redirect)
            return redirect
        except AuthError as exc:
            rejected = JSONResponse(
                status_code=exc.status_code,
                content=_error(exc.code, exc.public_message),
            )
            _clear_oauth_transaction_cookie(rejected)
            return rejected
        except Exception as exc:
            logger.error(
                "GitHub callback failed code=internal_error exception_type=%s",
                type(exc).__name__,
            )
            rejected = JSONResponse(
                status_code=500,
                content=_error(
                    "internal_error", "The local service could not complete the request."
                ),
            )
            _clear_oauth_transaction_cookie(rejected)
            return rejected

    @app.post(
        "/api/v1/auth/invitations",
        status_code=201,
        response_model=AuthInvitationResponse,
        include_in_schema=False,
    )
    @app.post(
        "/api/v1/auth/invites",
        status_code=201,
        response_model=AuthInvitationResponse,
        responses=_documented_errors(400, 403, 405, 411, 413, 422, 500, 503),
    )
    def create_invitation(request: Request, payload: AuthInvitationRequest) -> dict[str, object]:
        """Create a single-use GitHub invitation for an administrator."""

        context = _auth_context(request, role="admin")
        code, result = auth_manager.create_invitation(
            payload.github_id,
            context.user.id,
            datetime.now(UTC),
            github_login=payload.github_login,
        )
        return {
            "code": code,
            "github_id": result.get("github_id", payload.github_id),
            "github_login": result.get("github_login", payload.github_login),
            "expires_at": result["expires_at"],
        }

    @app.post(
        "/api/v1/auth/invites/email",
        status_code=201,
        response_model=AuthEmailInvitationResponse,
        responses=_documented_errors(400, 403, 405, 411, 413, 422, 500, 502, 503),
    )
    def create_email_invitation(
        request: Request, payload: AuthEmailInvitationRequest, response: Response
    ) -> dict[str, object]:
        """Create a GitHub-bound invite and submit it to the configured SMTP server."""

        context = _auth_context(request, role="admin")
        mail_settings = config.invitation_mail
        if mail_settings is None or config.auth_public_origin is None:
            raise AuthUnavailable("Email invitations are not configured.")
        code, result = auth_manager.create_invitation(
            payload.github_id,
            context.user.id,
            datetime.now(UTC),
            github_login=payload.github_login,
        )
        raw_expires_at = result.get("expires_at")
        expires_at: datetime | None
        if isinstance(raw_expires_at, datetime):
            expires_at = raw_expires_at
        elif isinstance(raw_expires_at, str):
            try:
                expires_at = datetime.fromisoformat(raw_expires_at.replace("Z", "+00:00"))
            except ValueError:
                expires_at = None
        else:
            expires_at = None
        if expires_at is None or expires_at.tzinfo is None:
            raise AuthUnavailable()
        expires_at = expires_at.astimezone(UTC)
        submission = send_invitation_email(
            mail_settings,
            public_origin=config.auth_public_origin,
            recipient=payload.email,
            github_id=payload.github_id,
            github_login=payload.github_login,
            code=code,
            expires_at=expires_at,
        )
        response.headers["Cache-Control"] = "no-store"
        return {
            "submission_status": "smtp_accepted",
            "submission_id": submission.submission_id,
            "submitted_at": submission.submitted_at,
            "github_id": payload.github_id,
            "github_login": payload.github_login,
            "expires_at": expires_at,
            "invite_url": f"{config.auth_public_origin.rstrip('/')}/invite",
        }

    @app.get(
        "/api/v1/auth/invites",
        responses=_documented_errors(400, 403, 405, 500, 503),
    )
    def list_invitations(request: Request) -> dict[str, object]:
        """List bounded invitation metadata for the current administrator."""

        _auth_context(request, role="admin")
        method = getattr(auth_manager.store, "auth_list_invitations", None)
        if not callable(method):
            method = getattr(repository, "list_invitations", None)
        records = method() if callable(method) else []
        return {
            "invitations": [dict(item) for item in records if isinstance(item, Mapping)],
            "email_invites_enabled": config.email_invites_enabled,
        }

    @app.post(
        "/api/v1/auth/invites/redeem",
        response_model=AuthSessionResponse,
        responses=_documented_errors(400, 403, 405, 411, 413, 422, 429, 500, 503),
    )
    def redeem_invitation(
        request: Request, payload: AuthInvitationRedeemRequest, response: Response
    ) -> dict[str, object]:
        """Validate an invitation and return a server-bound GitHub OAuth URL."""

        if auth_manager.settings.mode != "github":
            raise AuthUnavailable("Invitation sign-in is not enabled.")
        invitation = auth_manager.inspect_invitation(payload.code, datetime.now(UTC))
        authorization = auth_manager.begin_github(
            datetime.now(UTC),
            caller_identity=_oauth_caller_identity(request, config.trusted_proxy_hosts),
            invitation_code=payload.code,
        )
        _set_oauth_transaction_cookie(response, authorization.state)
        # The raw code is never persisted in a cookie.  The client must continue through the
        # GitHub authorization route with this code so OAuth state can bind the invitation.
        return {
            "authenticated": False,
            "user": None,
            "requires_passkey": False,
            "role": None,
            "local_login_enabled": False,
            "invitation_github_id": invitation.get("github_id", invitation.get("github_user_id")),
            "github_required": True,
            "authorization_url": authorization.url,
            "message": (
                "Invitation accepted. Continue with GitHub sign-in to prove the invited identity."
            ),
        }

    @app.post(
        "/api/v1/auth/passkeys/registration/options",
        response_model=PasskeyOptionsResponse,
        include_in_schema=False,
    )
    @app.post(
        "/api/v1/auth/passkeys/register/options",
        response_model=PasskeyOptionsResponse,
        responses=_documented_errors(400, 403, 405, 500, 503),
    )
    def passkey_registration_options(request: Request) -> dict[str, object]:
        """Reject WebAuthn enrollment after the authenticator-only production cutover."""

        context = _auth_context(request)
        if auth_manager.settings.mode == "github":
            raise AuthorizationDenied("Passkeys are retired; use your authenticator code.")
        rp_id = urlparse(config.auth_public_origin or "http://127.0.0.1").hostname or "127.0.0.1"
        options = auth_manager.begin_passkey_registration(
            context.user, rp_id, config.auth_public_origin or "http://127.0.0.1"
        )
        return {"public_key": options.get("publicKey", options.get("public_key", {}))}

    @app.post(
        "/api/v1/auth/passkeys/registration/finish",
        response_model=AuthLoginResponse,
        include_in_schema=False,
    )
    @app.post(
        "/api/v1/auth/passkeys/register",
        response_model=AuthLoginResponse,
        responses=_documented_errors(400, 403, 405, 411, 413, 422, 500, 503),
    )
    def passkey_registration_finish(
        request: Request, payload: PasskeyResponseRequest, response: Response
    ) -> dict[str, object]:
        """Reject the retired WebAuthn enrollment ceremony in production."""

        context = _auth_context(request)
        if auth_manager.settings.mode == "github":
            raise AuthorizationDenied("Passkeys are retired; use your authenticator code.")
        rp_id = urlparse(config.auth_public_origin or "http://127.0.0.1").hostname or "127.0.0.1"
        auth_manager.finish_passkey_registration(
            context.user,
            {
                "response": payload.response,
                "id": payload.id,
                "rawId": payload.raw_id,
                "type": payload.type,
            },
            rp_id,
            config.auth_public_origin or "http://127.0.0.1",
        )
        updated = auth_manager.store.auth_get_user_by_id(context.user.id)
        if updated is None:
            raise AuthUnavailable("Account security state is invalid.")
        user = auth_manager.user_from_record(updated)
        auth_method: Literal["local", "github"] = (
            "github" if auth_manager.settings.mode == "github" else "local"
        )
        issue = auth_manager.issue_session(
            user, datetime.now(UTC), auth_method, mfa_method="passkey"
        )
        _set_auth_cookies(response, issue.session_token, issue.csrf_token, issue.expires_at)
        return {
            "authenticated": True,
            "user": _public_user(issue.context.user),
            "csrf_token": issue.csrf_token,
            "requires_passkey": False,
            "expires_at": issue.expires_at,
        }

    @app.post(
        "/api/v1/auth/passkeys/assertion/options",
        response_model=PasskeyOptionsResponse,
        include_in_schema=False,
    )
    @app.post(
        "/api/v1/auth/passkeys/authenticate/options",
        response_model=PasskeyOptionsResponse,
        responses=_documented_errors(400, 403, 405, 500, 503),
    )
    def passkey_assertion_options(request: Request) -> dict[str, object]:
        """Reject the retired WebAuthn assertion ceremony in production."""

        context = _auth_context(request)
        rp_id = urlparse(config.auth_public_origin or "http://127.0.0.1").hostname or "127.0.0.1"
        options = auth_manager.begin_passkey_assertion(context.user, rp_id)
        return {"public_key": options.get("publicKey", options.get("public_key", {}))}

    @app.post(
        "/api/v1/auth/passkeys/assertion/finish",
        response_model=None,
        include_in_schema=False,
    )
    @app.post(
        "/api/v1/auth/passkeys/authenticate",
        response_model=None,
        responses=_documented_errors(400, 403, 405, 411, 413, 422, 500, 503),
    )
    def passkey_assertion_finish(
        request: Request, payload: PasskeyResponseRequest, response: Response
    ) -> dict[str, object]:
        """Reject the retired WebAuthn assertion ceremony in production."""

        context = _auth_context(request)
        rp_id = urlparse(config.auth_public_origin or "http://127.0.0.1").hostname or "127.0.0.1"
        issue = auth_manager.finish_passkey_assertion(
            context.user,
            {
                "response": payload.response,
                "id": payload.id,
                "rawId": payload.raw_id,
                "type": payload.type,
            },
            rp_id,
            config.auth_public_origin or "http://127.0.0.1",
            datetime.now(UTC),
        )
        _set_auth_cookies(response, issue.session_token, issue.csrf_token, issue.expires_at)
        return {
            "authenticated": True,
            "user": _public_user(issue.context.user),
            "csrf_token": issue.csrf_token,
            # This endpoint is retained only for local compatibility; production rejects the
            # assertion before reaching this response after the authenticator-only cutover.
            "requires_passkey": False,
            "requires_totp": True,
            "mfa_method": issue.context.mfa_method,
            "expires_at": issue.expires_at,
        }

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
        if not app.state.ready or maintenance_event.is_set():
            raise HTTPException(status_code=503)
        # Ask through the repository boundary; transport code must not grow storage-specific SQL.
        repository.representative_counts()
        return {"status": "ready", "schema_version": SCHEMA_VERSION, "provider": config.provider}

    def market_identity(symbol: str, asset_type: str | None = None) -> dict[str, Any]:
        """Resolve one exact provider identity before requesting or persisting market data."""

        normalized = normalize_symbol(symbol)
        lookup = cast(dict[str, Any], app.state.service.lookup(normalized, 1))
        identity = next(
            (item for item in lookup["items"] if item.get("canonical_symbol") == normalized),
            None,
        )
        if identity is None:
            raise DomainError(
                "instrument_not_found", "The instrument was not found.", status_code=404
            )
        if asset_type is not None and identity.get("asset_type") != asset_type:
            raise DomainError(
                "asset_type_mismatch",
                "The selected asset type does not match the provider identity.",
                status_code=422,
            )
        return cast(dict[str, Any], identity)

    def flattened_list_items(
        kind: str | None, owner_user_id: int | None = None
    ) -> list[dict[str, Any]]:
        return [
            {
                "symbol": item["canonical_symbol"],
                "display_name": item["display_name"],
                "provider": item["provider"],
                "asset_type": item["asset_type"],
                "exchange": item["exchange"],
                "quantity": item["quantity"],
                "added_at": item["added_at"],
            }
            for item in _call_with_owner(repository.instrument_list_items, owner_user_id, kind)
        ]

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

    @app.get(
        "/api/v1/quotes",
        response_model=QuotesResponse,
        responses=_documented_errors(400, 403, 404, 405, 422, 500, 502, 503),
    )
    def quotes(
        request: Request,
        symbols: str = Query(min_length=1, max_length=319),
    ) -> dict[str, Any]:
        """Return up to twenty provider-labelled observations without real-time claims."""

        if (
            set(request.query_params) != {"symbols"}
            or len(request.query_params.getlist("symbols")) != 1
        ):
            raise DomainError("validation_error", "Request validation failed.")
        parts = symbols.split(",")
        if not 1 <= len(parts) <= 20 or any(not part.strip() for part in parts):
            raise DomainError("validation_error", "Request validation failed.")
        normalized = list(dict.fromkeys(normalize_symbol(part) for part in parts))
        items = []
        for symbol in normalized:
            identity = market_identity(symbol)
            quote = cast(
                dict[str, Any],
                app.state.service.quote_snapshot(symbol, identity["asset_type"]),
            )
            simulated = quote["provider"] == "deterministic fixture"
            items.append(
                {
                    "symbol": quote["symbol"],
                    "name": identity["display_name"],
                    "asset_type": identity["asset_type"],
                    "exchange": identity["exchange"],
                    "last": quote["price"],
                    "currency": quote["currency"],
                    "source": quote["provider"],
                    "as_of": quote["as_of"],
                    "state": (
                        "simulated"
                        if simulated
                        else "delayed"
                        if quote["delayed"]
                        else "provider_reported"
                    ),
                    "delayed": quote["delayed"],
                    "delay_minutes": quote["delay_minutes"],
                    "label": quote["label"],
                    **{
                        key: quote[key]
                        for key in (
                            "open",
                            "high",
                            "low",
                            "previous_close",
                            "volume",
                            "last_trade",
                            "change",
                            "change_percent",
                        )
                    },
                }
            )
        return {"items": items}

    @app.get(
        "/api/v1/bars",
        response_model=MarketBarsResponse,
        responses=_documented_errors(400, 403, 404, 405, 422, 500, 502, 503),
    )
    def market_bars(
        symbol: str = Query(min_length=1, max_length=15),
        asset_type: Literal["stock", "etf"] | None = Query(default=None),
        chart_range: ChartRange = Query(default="1mo", alias="range"),  # noqa: B008
    ) -> dict[str, Any]:
        """Return a bounded daily chart for the requested provider-supported range."""

        identity = market_identity(symbol, asset_type)
        series = cast(
            dict[str, Any],
            # ForecastService owns provider slots and exception classification. Its existing
            # convenience method is fixed at the default range, so use the same private boundary
            # with the explicit chart range rather than bypassing capacity/error handling.
            service._provider_capability(  # noqa: SLF001
                lambda requested_at: service.provider.historical_bars(
                    identity["canonical_symbol"],
                    identity["asset_type"],
                    requested_at,
                    range=chart_range,
                ).as_dict(),
                "The chart provider failed unexpectedly.",
            ),
        )
        simulated = series["provider"] == "deterministic fixture"
        return {
            **{key: series[key] for key in ("symbol", "range", "interval", "adjustment_basis")},
            "source": series["provider"],
            "as_of": series["as_of"],
            "state": (
                "simulated"
                if simulated
                else "delayed"
                if series["delayed"]
                else "provider_reported"
            ),
            "delayed": series["delayed"],
            "delay_minutes": series["delay_minutes"],
            "label": series["label"],
            "bars": series["bars"],
        }

    @app.get(
        "/api/v1/lists",
        response_model=InstrumentListsResponse,
        responses=_documented_errors(400, 403, 405, 422, 500, 503),
    )
    def instrument_lists(
        request: Request,
        kind: Literal["watchlist", "portfolio"] | None = Query(default=None),
    ) -> dict[str, Any]:
        owner_user_id = _owner_user_id(request)
        return {
            "kind": kind or "all",
            "items": flattened_list_items(kind, owner_user_id),
        }

    @app.post(
        "/api/v1/lists",
        status_code=201,
        response_model=InstrumentListsResponse,
        responses=_documented_errors(400, 403, 404, 405, 409, 411, 413, 422, 500, 502, 503),
    )
    def add_instrument_list_item(
        request: Request, payload: InstrumentListMutationRequest, response: Response
    ) -> dict[str, Any]:
        owner_user_id = _owner_user_id(request)
        identity = market_identity(payload.item.symbol, payload.item.asset_type)
        items = _call_with_owner(repository.instrument_list_items, owner_user_id, payload.kind)
        now = selected_clock().astimezone(UTC)
        try:
            existing = next(
                (
                    item
                    for item in items
                    if item["canonical_symbol"] == identity["canonical_symbol"]
                    and item["asset_type"] == identity["asset_type"]
                ),
                None,
            )
            if existing is None:
                _call_with_owner(
                    repository.add_instrument_list_item,
                    owner_user_id,
                    payload.kind,
                    provider=identity["provider"],
                    canonical_symbol=identity["canonical_symbol"],
                    asset_type=identity["asset_type"],
                    exchange=identity["exchange"],
                    display_name=identity["display_name"],
                    quantity=payload.item.quantity,
                    added_at=now,
                )
            elif payload.kind == "portfolio":
                _call_with_owner(
                    repository.set_instrument_list_item_holding,
                    owner_user_id,
                    payload.kind,
                    provider=existing["provider"],
                    canonical_symbol=existing["canonical_symbol"],
                    asset_type=existing["asset_type"],
                    quantity=payload.item.quantity,
                )
        except ValueError as exc:
            raise DomainError(
                "instrument_list_conflict",
                "The instrument list update conflicts with its current bounded state.",
                status_code=409,
            ) from exc
        response.headers["Location"] = f"/api/v1/lists?kind={payload.kind}"
        return {
            "kind": payload.kind,
            "items": flattened_list_items(payload.kind, owner_user_id),
        }

    @app.delete(
        "/api/v1/lists",
        status_code=204,
        response_class=Response,
        responses=_documented_errors(400, 403, 404, 405, 422, 500, 503),
    )
    def remove_instrument_list_item(
        request: Request,
        kind: Literal["watchlist", "portfolio"] = Query(),
        symbol: str = Query(min_length=1, max_length=15),
    ) -> Response:
        owner_user_id = _owner_user_id(request)
        normalized = normalize_symbol(symbol)
        item = next(
            (
                candidate
                for candidate in _call_with_owner(
                    repository.instrument_list_items, owner_user_id, kind
                )
                if candidate["canonical_symbol"] == normalized
            ),
            None,
        )
        if item is not None:
            _call_with_owner(
                repository.remove_instrument_list_item,
                owner_user_id,
                kind,
                provider=item["provider"],
                canonical_symbol=item["canonical_symbol"],
                asset_type=item["asset_type"],
            )
            return Response(status_code=204)
        raise HTTPException(status_code=404)

    @app.get(
        "/api/v1/news",
        response_model=NewsResponse,
        responses=_documented_errors(400, 403, 405, 422, 500, 502, 503),
    )
    def news(request: Request, query: Annotated[NewsQuery, Query()]) -> dict[str, Any]:
        """Return current bounded headlines separately from immutable forecast records."""

        if any(len(request.query_params.getlist(name)) > 1 for name in request.query_params):
            raise DomainError("validation_error", "Request validation failed.")
        try:
            return cast(dict[str, Any], app.state.service.news(query.symbol, limit=query.limit))
        except DomainError as exc:
            public_error = {
                422: ("validation_error", "Request validation failed."),
                502: ("provider_unavailable", "The news provider is temporarily unavailable."),
                503: ("provider_busy", "News retrieval capacity is busy; try again shortly."),
            }.get(exc.status_code)
            if public_error is None:
                raise
            raise DomainError(*public_error, status_code=exc.status_code) from None

    @app.post(
        "/api/v1/forecasts",
        status_code=201,
        response_model=ForecastCreationResponse,
        response_model_exclude_unset=True,
        responses={
            201: {
                "description": "Forecast completed and available at its immutable saved URL.",
                "headers": {
                    "Location": {"schema": {"type": "string"}},
                    "X-Request-ID": {"schema": {"type": "string"}},
                },
            },
            **_documented_errors(400, 403, 404, 405, 411, 413, 422, 500, 502, 503),
        },
    )
    def create_forecast(
        request: Request, payload: SearchRequest, response: Response
    ) -> ForecastCreationResponse:
        owner_user_id = _owner_user_id(request)
        generated = _call_with_owner(
            service.search,
            owner_user_id,
            payload.symbol,
            payload.asset_type,
            payload.interval,
        )
        try:
            # Validate before FastAPI's response serializer so a malformed service handoff can be
            # correlated with exactly one failed search rather than escaping as an unaudited 500.
            visible = _forecast_response_view(cast(dict[str, Any], generated), payload.interval)
            validated = ForecastCreationResponse.model_validate(visible)
            response.headers["Location"] = f"/api/v1/saved-forecasts/{validated.event.id}"
            if payload.interval is not None:
                response.headers["Location"] += f"?interval={payload.interval}"
            response.headers["X-Request-ID"] = validated.event.request_id
            return validated
        except Exception:
            request_id = record_malformed_forecast_response(
                generated,
                submitted_symbol=payload.symbol,
                asset_type=payload.asset_type,
                owner_user_id=owner_user_id,
            )
            raise DomainError(
                "internal_error",
                "The local service could not complete the request.",
                status_code=500,
                request_id=request_id,
            ) from None

    @app.get(
        "/api/v1/history",
        response_model=HistoryResponse,
        response_model_exclude_unset=True,
        responses=_documented_errors(400, 403, 405, 422, 500, 503),
    )
    def history(
        request: Request,
        q: str = Query(default="", max_length=30),
        symbol: str | None = Query(default=None, min_length=1, max_length=15),
        company: str | None = Query(default=None, min_length=1, max_length=200),
        status: HistoryStatusParameter = None,
        asset_type: Literal["stock", "etf"] | None = Query(default=None),
        analysis_kind: HistoryAnalysisParameter = None,
        submitted_from: HistoryDateParameter = None,
        submitted_to: HistoryDateParameter = None,
        model: str | None = Query(default=None, min_length=1, max_length=120),
        model_version: str | None = Query(default=None, min_length=1, max_length=80),
        horizon: HistoryHorizonParameter = None,
        request_id: str | None = Query(default=None, min_length=1, max_length=128),
        event_id: int | None = Query(default=None, ge=1, le=2_147_483_647),
        sort_by: HistorySortParameter = "event_id",
        sort_order: SortDirectionParameter = "desc",
        page: int = Query(default=1, ge=1, le=10_000),
        page_size: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        """Search complete display identities and audit facts with stable bounded paging."""

        _validate_history_dates(submitted_from, submitted_to)
        filters = _history_filters(
            query=q,
            symbol=symbol,
            company=company,
            status=status,
            asset_type=asset_type,
            analysis_kind=analysis_kind,
            submitted_from=submitted_from,
            submitted_to=submitted_to,
            model=model,
            model_version=model_version,
            horizon=horizon,
            request_id=request_id,
            event_id=event_id,
        )
        return _query_history(
            service,
            filters=filters,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            page_size=page_size,
            owner_user_id=_owner_user_id(request),
        )

    @app.get(
        "/api/v1/history-export.csv",
        response_class=Response,
        responses={
            200: {
                "description": "Bounded CSV search-history export.",
                "content": {"text/csv": {"schema": {"type": "string"}}},
                "headers": {
                    "Content-Disposition": {"schema": {"type": "string"}},
                    "X-Export-Filters": {"schema": {"type": "string"}},
                    "X-Export-Sort": {"schema": {"type": "string"}},
                },
            },
            **_documented_errors(400, 403, 405, 422, 500, 503),
        },
    )
    def history_export(
        request: Request,
        q: str = Query(default="", max_length=30),
        symbol: str | None = Query(default=None, min_length=1, max_length=15),
        company: str | None = Query(default=None, min_length=1, max_length=200),
        status: HistoryStatusParameter = None,
        asset_type: Literal["stock", "etf"] | None = Query(default=None),
        analysis_kind: HistoryAnalysisParameter = None,
        submitted_from: HistoryDateParameter = None,
        submitted_to: HistoryDateParameter = None,
        model: str | None = Query(default=None, min_length=1, max_length=120),
        model_version: str | None = Query(default=None, min_length=1, max_length=80),
        horizon: HistoryHorizonParameter = None,
        request_id: str | None = Query(default=None, min_length=1, max_length=128),
        event_id: int | None = Query(default=None, ge=1, le=2_147_483_647),
        sort_by: HistorySortParameter = "event_id",
        sort_order: SortDirectionParameter = "desc",
    ) -> Response:
        # Both formats share one record construction so CSV cannot silently omit audit identity.
        _validate_history_dates(submitted_from, submitted_to)
        filters = _history_filters(
            query=q,
            symbol=symbol,
            company=company,
            status=status,
            asset_type=asset_type,
            analysis_kind=analysis_kind,
            submitted_from=submitted_from,
            submitted_to=submitted_to,
            model=model,
            model_version=model_version,
            horizon=horizon,
            request_id=request_id,
            event_id=event_id,
        )
        exported = _bounded_history_export(
            service,
            filters=filters,
            sort_by=sort_by,
            sort_order=sort_order,
            owner_user_id=_owner_user_id(request),
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
            "error_message",
            "company_name",
            "canonical_symbol",
            "exchange",
            "quote_type",
            "horizon",
            "submitted_at",
            "export_generated_at",
            "export_filters",
            "export_sort",
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
                "export_generated_at": exported["generated_at"],
                "export_filters": json.dumps(
                    exported["filters"], ensure_ascii=True, sort_keys=True, separators=(",", ":")
                ),
                "export_sort": json.dumps(
                    exported["sort"], ensure_ascii=True, sort_keys=True, separators=(",", ":")
                ),
                "record_json": json.dumps(
                    data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
            }
            writer.writerow({key: _safe_csv_cell(row.get(key)) for key in fieldnames})
        return Response(
            output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="stock-probs-history.csv"',
                "X-Export-Filters": _safe_metadata_header(filters),
                "X-Export-Sort": _safe_metadata_header(exported["sort"]),
            },
        )

    @app.get(
        "/api/v1/history-export.json",
        response_model=HistoryJsonExportResponse,
        response_model_exclude_unset=True,
        responses={
            200: {
                "description": "Bounded JSON search-history export.",
                "headers": {
                    "Content-Disposition": {"schema": {"type": "string"}},
                    "X-Export-Filters": {"schema": {"type": "string"}},
                    "X-Export-Sort": {"schema": {"type": "string"}},
                },
            },
            **_documented_errors(400, 403, 405, 422, 500, 503),
        },
    )
    def history_export_json(
        request: Request,
        response: Response,
        q: str = Query(default="", max_length=30),
        symbol: str | None = Query(default=None, min_length=1, max_length=15),
        company: str | None = Query(default=None, min_length=1, max_length=200),
        status: HistoryStatusParameter = None,
        asset_type: Literal["stock", "etf"] | None = Query(default=None),
        analysis_kind: HistoryAnalysisParameter = None,
        submitted_from: HistoryDateParameter = None,
        submitted_to: HistoryDateParameter = None,
        model: str | None = Query(default=None, min_length=1, max_length=120),
        model_version: str | None = Query(default=None, min_length=1, max_length=80),
        horizon: HistoryHorizonParameter = None,
        request_id: str | None = Query(default=None, min_length=1, max_length=128),
        event_id: int | None = Query(default=None, ge=1, le=2_147_483_647),
        sort_by: HistorySortParameter = "event_id",
        sort_order: SortDirectionParameter = "desc",
    ) -> dict[str, Any]:
        """Export a bounded set of typed audit records."""

        _validate_history_dates(submitted_from, submitted_to)
        filters = _history_filters(
            query=q,
            symbol=symbol,
            company=company,
            status=status,
            asset_type=asset_type,
            analysis_kind=analysis_kind,
            submitted_from=submitted_from,
            submitted_to=submitted_to,
            model=model,
            model_version=model_version,
            horizon=horizon,
            request_id=request_id,
            event_id=event_id,
        )
        response.headers["Content-Disposition"] = 'attachment; filename="stock-probs-history.json"'
        response.headers["X-Export-Filters"] = _safe_metadata_header(filters)
        response.headers["X-Export-Sort"] = _safe_metadata_header(
            {"field": sort_by, "direction": sort_order}
        )
        return _bounded_history_export(
            service,
            filters=filters,
            sort_by=sort_by,
            sort_order=sort_order,
            owner_user_id=_owner_user_id(request),
        )

    @app.get(
        "/api/v1/history/{event_id:int}",
        response_model=ReconstructionResponse,
        response_model_exclude_unset=True,
        responses=_documented_errors(400, 403, 404, 405, 422, 500, 503),
    )
    def reconstruction(
        request: Request,
        event_id: int = PathParameter(ge=1, le=2_147_483_647),
        interval: ForecastIntervalParameter = None,
    ) -> dict[str, Any]:
        # Constrain matching at the router boundary so unrelated history paths remain genuine 404s;
        # the typed parameter still owns numeric bounds and their public validation response.
        result = _call_with_owner(service.history_detail, _owner_user_id(request), event_id)
        if result is None:
            raise HTTPException(status_code=404, detail="history event not found")
        available = result.get("input") is not None
        return _forecast_response_view(
            {
                "record_kind": "recorded_forecast" if available else "failed_search",
                "immutable": True,
                "forecast_available": available,
                **result,
            },
            interval,
        )

    @app.get(
        "/api/v1/saved-forecasts/{event_id}",
        response_model=SavedForecastResponse,
        response_model_exclude_unset=True,
        responses=_documented_errors(400, 403, 404, 405, 409, 422, 500, 503),
    )
    def saved_forecast(
        request: Request,
        event_id: int = PathParameter(ge=1, le=2_147_483_647),
        interval: ForecastIntervalParameter = None,
    ) -> dict[str, Any]:
        """Reopen an immutable recorded forecast without recalculation or provider access."""

        recorded = _call_with_owner(service.history_detail, _owner_user_id(request), event_id)
        if recorded is None:
            raise HTTPException(status_code=404, detail="history event not found")
        if recorded.get("input") is None:
            raise HTTPException(status_code=409, detail="failed searches have no saved forecast")
        return _forecast_response_view(
            {
                "analysis_kind": "saved_recorded_forecast",
                "immutable": True,
                "recalculated": False,
                "provider_called": False,
                **recorded,
            },
            interval,
        )

    @app.post(
        "/api/v1/history/{event_id}/reconstructions",
        status_code=201,
        response_model=FreshReconstructionResponse,
        response_model_exclude_unset=True,
        responses={
            201: {
                "description": "Fresh cutoff analysis completed as a distinct saved result.",
                "headers": {
                    "Location": {"schema": {"type": "string"}},
                    "X-Request-ID": {"schema": {"type": "string"}},
                },
            },
            **_documented_errors(400, 403, 404, 405, 409, 411, 413, 422, 500, 502, 503),
        },
    )
    def fresh_historical_reconstruction(
        request: Request,
        payload: FreshReconstructionRequest,
        response: Response,
        event_id: int = PathParameter(ge=1, le=2_147_483_647),
    ) -> dict[str, Any]:
        """Run a newly audited analysis at a cutoff, never relabel a saved result as fresh."""

        generated = cast(
            dict[str, Any],
            # This one service call owns both the new event and its success/failure status.
            _call_with_owner(
                service.fresh_historical_reconstruction,
                _owner_user_id(request),
                event_id,
                payload.cutoff,
            ),
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
        created = _forecast_response_view(
            {
                **generated,
                "source_event_id": event_id,
                "requested_cutoff": payload.cutoff.astimezone(UTC).isoformat(),
                "provider_called": True,
                "recalculated": True,
                "provenance": provenance,
            }
        )
        response.headers["Location"] = f"/api/v1/saved-forecasts/{generated['event']['id']}"
        requested_interval = generated["input"].get("requested_interval")
        if requested_interval is not None:
            response.headers["Location"] += f"?interval={requested_interval}"
        response.headers["X-Request-ID"] = str(generated["event"]["request_id"])
        return created

    @app.get(
        "/api/v1/history/{event_id}/prices",
        response_model=HistoricalPricesResponse,
        responses=_documented_errors(400, 403, 404, 405, 409, 422, 500, 503),
    )
    def historical_prices(
        request: Request,
        event_id: int = PathParameter(ge=1, le=2_147_483_647),
        series: str = Query(default="daily", pattern="^(daily|intraday)$"),
        limit: int = Query(default=120, ge=1, le=500),
    ) -> dict[str, Any]:
        """Expose bounded captured prices, never a fresh provider or browser-side query."""

        historical = _call_with_owner(
            service.historical_series,
            _owner_user_id(request),
            event_id,
            series=series,
            limit=limit,
        )
        if historical is None:
            raise HTTPException(status_code=404, detail="history event not found")
        if historical.get("available") is False:
            raise HTTPException(status_code=409, detail="failed searches have no captured prices")
        return historical

    @app.get(
        "/api/v1/forecasts/{result_id}",
        response_model=OriginalForecastResultResponse | OriginalRollingForecastResultResponse,
        response_model_exclude_unset=True,
        responses=_documented_errors(400, 403, 404, 405, 422, 500, 503),
    )
    def original_forecast_result(
        request: Request,
        result_id: int = PathParameter(ge=1, le=2_147_483_647),
    ) -> dict[str, Any]:
        """Return the immutable recorded result without folding later outcomes into it."""

        result = _call_with_owner(repository.forecast_result, _owner_user_id(request), result_id)
        if result is None:
            raise HTTPException(status_code=404, detail="forecast result not found")
        horizon = result.get("horizon")
        interval = _HORIZON_INTERVALS.get(horizon) if isinstance(horizon, str) else None
        visible = _forecast_response_view({"results": [result]}, interval)
        return {"id": result_id, "immutable": True, **visible["results"][0]}

    @app.post(
        "/api/v1/forecasts/{result_id}/outcomes",
        status_code=201,
        response_model=OutcomeResponse,
        responses=_documented_errors(400, 403, 404, 405, 411, 413, 422, 500, 503),
    )
    def append_outcome(
        request: Request,
        payload: OutcomeRequest,
        result_id: int = PathParameter(ge=1, le=2_147_483_647),
    ) -> dict[str, Any]:
        result = _call_with_owner(
            service.append_outcome,
            _owner_user_id(request),
            result_id,
            payload.observed_close,
            payload.observed_at,
            payload.state,
            payload.note,
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
        request: Request,
        payload: CorrectionRequest,
        result_id: int = PathParameter(ge=1, le=2_147_483_647),
    ) -> dict[str, Any]:
        """Make correction append semantics explicit instead of offering an update verb."""

        result = _call_with_owner(
            service.append_outcome,
            _owner_user_id(request),
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
    def create_backup(request: Request, payload: BackupRequest) -> dict[str, Any]:
        # The legacy local mode remains available for deterministic development fixtures; any
        # enabled auth mode requires an authenticated administrator with recent passkey proof.
        if auth_manager.enabled:
            _auth_context(request, role="admin", step_up=True)
        return _public_backup_result(backups.create(payload.name))

    @app.get(
        "/api/v1/operations/backups/status",
        response_model=BackupStatusResponse,
        responses=_documented_errors(400, 403, 405, 500, 503),
    )
    def backup_status(request: Request) -> dict[str, Any]:
        """Report bounded managed backup capabilities."""

        if auth_manager.enabled:
            _auth_context(request, role="admin")
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
    def restore_backup(
        request: Request, payload: RestoreRequest, response: Response
    ) -> dict[str, Any]:
        if auth_manager.enabled:
            context = _auth_context(request, role="admin", step_up=True)
            if payload.promote:
                # Promotion is a short, serialized maintenance operation. The pre-restore
                # artifact and target are independently verified before BackupManager touches
                # the active database, and account/authenticator rows must match exactly.
                if not restore_lock.acquire(blocking=False):
                    raise AuthorizationDenied("Another restore operation is in progress.")
                if not request_gate.begin_drain(RESTORE_DRAIN_TIMEOUT_SECONDS):
                    restore_lock.release()
                    raise AuthUnavailable(
                        "Active requests did not drain before the restore deadline."
                    )
                maintenance_event.set()
                restore_started = False
                cleanup_complete = False
                try:
                    pre_restore = backups.create()
                    pre_restore_name = pre_restore.get("name")
                    if not isinstance(pre_restore_name, str):
                        raise AuthUnavailable("The pre-restore backup could not be verified.")
                    pre_manifest, _, pre_staging = backups.verify(pre_restore_name)
                    try:
                        if pre_manifest.get("schema_version") != SCHEMA_VERSION:
                            raise AuthUnavailable("The pre-restore backup schema is incompatible.")
                    finally:
                        pre_staging.cleanup()

                    target_manifest, target_database, target_staging = backups.verify(payload.name)
                    try:
                        if target_manifest.get("schema_version") != SCHEMA_VERSION:
                            raise AuthorizationDenied(
                                "The restore artifact schema is incompatible."
                            )
                        active_digest = _restore_security_digest(repository.database_path)
                        target_digest = _restore_security_digest(target_database)
                        if not hmac.compare_digest(active_digest, target_digest):
                            raise AuthorizationDenied(
                                "The restore artifact account-security state does not match "
                                "the active account state."
                            )
                    finally:
                        target_staging.cleanup()
                    restore_started = True
                    result = backups.restore(payload.name, promote=True)
                    revoked_at = datetime.now(UTC)
                    _revoke_every_session(repository, revoked_at)
                    # Keep injected/test stores consistent with the promoted repository. The
                    # production adapter points at the same database, while this also closes
                    # the current in-memory session used by deterministic API checks.
                    auth_manager.store.auth_revoke_all_sessions(
                        context.user.id, revoked_at.isoformat()
                    )
                    _clear_pending_oauth_states(repository)
                    auth_manager.clear_pending_challenges()
                    cleanup_complete = True
                    # The current cookie is now revoked along with every other session.
                    _clear_auth_cookies(response)
                    return _public_restore_result(result)
                finally:
                    # If the database swap succeeded but security cleanup failed, leave the
                    # maintenance barrier closed. Operators must inspect/restart rather than
                    # serving the restored database with an uncertain session state.
                    if not restore_started or cleanup_complete:
                        maintenance_event.clear()
                    request_gate.end_drain()
                    restore_lock.release()
        return _public_restore_result(backups.restore(payload.name, promote=payload.promote))

    @app.get("/api/v1/docs", include_in_schema=False)
    def api_docs() -> FileResponse:
        """Serve a CSP-compatible, dependency-free pointer to the machine-readable contract."""

        return FileResponse(workspace_pages["/api/v1/docs"])

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(workspace_pages["/"])

    def workspace_page(route: str, request: Request) -> Response:
        if route == "/passkey":
            # Keep old bookmarks useful while ensuring the retired WebAuthn ceremony is never
            # rendered. Only a same-origin absolute path may survive the redirect.
            next_path = _safe_local_next(request.query_params.get("next"))
            return RedirectResponse(
                "/authenticator?mode=enroll&next=" + quote(next_path, safe=""),
                status_code=303,
            )
        page = workspace_pages[route]
        if not page.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(page)

    for route in WORKSPACE_PAGE_ROUTES:
        app.add_api_route(
            route,
            partial(workspace_page, route),
            methods=["GET", "HEAD"],
            include_in_schema=False,
            name=f"workspace-{route.strip('/').replace('/', '-')}",
        )

    @app.api_route(
        "/assets/{path:path}",
        methods=["GET", "HEAD"],
        include_in_schema=False,
        name="assets",
    )
    def static_asset(path: str) -> FileResponse:
        """Serve authored assets without aliasing the generated export beneath /assets."""

        if path not in ("app.css", "app.js", "theme.js", "favicon.svg"):
            raise HTTPException(status_code=404)
        return FileResponse(static_dir / path)

    app.mount("/_next", StaticFiles(directory=next_dir / "_next"), name="next-assets")
    return app


app = create_app()
