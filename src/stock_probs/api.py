"""FastAPI application exposes the sole browser data boundary under /api/v1."""

from __future__ import annotations

import base64
import csv
import io
import json
import logging
import re
import sqlite3
import unicodedata
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi import Path as PathParameter
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
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
    ForecastHorizon,
    FreshReconstructionRequest,
    HistoryAnalysisKind,
    HistorySortField,
    HistoryStatus,
    InstrumentIdentityResponse,
    InstrumentLookupResponse,
    NewsQuery,
    NewsResponse,
    OutcomeRequest,
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
    horizons: list[ForecastHorizon] = Field(default_factory=list, max_length=2)
    outcome_count: int = Field(default=0, ge=0)
    evaluation_statuses: list[Literal["available", "insufficient_history"]] = Field(
        default_factory=list, max_length=2
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
    maximum_absolute_training_return: Annotated[
        float, Field(gt=0.0, le=1.0, allow_inf_nan=False)
    ]
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
    session_state_at_request: Literal[
        "closed_session_day", "pre_session", "open", "post_session"
    ]
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
        if any(
            [(item.low, item.high) for item in bins] != expected_bounds for bins in bin_groups
        ):
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
    rule: Literal[
        "same_open_session_close", "next_session_close_after_completed_origin_session"
    ]
    request_session_state: Literal[
        "closed_session_day", "pre_session", "open", "post_session"
    ]
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
    session_state_at_request: Literal[
        "closed_session_day", "pre_session", "open", "post_session"
    ] | None = None
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
        if downside != sorted(downside, reverse=True) or upside != sorted(
            upside, reverse=True
        ):
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
    record_kind: Literal["recorded_forecast", "failed_search"] | None = None
    immutable: Literal[True] | None = None
    forecast_available: bool | None = None
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
    data: RecordedForecastResultResponse


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


_HISTORY_SCAN_LIMIT = 10_000


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


def _validate_history_dates(
    submitted_from: datetime | None, submitted_to: datetime | None
) -> None:
    """Require explicit offsets and an ordered inclusive submission window."""

    if any(value is not None and value.tzinfo is None for value in (submitted_from, submitted_to)):
        raise DomainError(
            "invalid_history_date",
            "History dates must include a timezone offset.",
            status_code=422,
        )
    if (
        submitted_from is not None
        and submitted_to is not None
        and submitted_from > submitted_to
    ):
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
        item["forecast_available"] = True
        return item
    detail = detail or service.history_detail(int(item["id"]))
    snapshot = detail.get("input") if detail else None
    results = detail.get("results", []) if detail else []
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
    if filters["symbol"] and str(
        item.get("normalized_symbol") or item.get("submitted_symbol")
    ).upper() != filters["symbol"]:
        return False
    if filters["company"] and filters["company"].casefold() not in str(
        item.get("company_name") or ""
    ).casefold():
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
) -> dict[str, Any]:
    """Return an exact bounded page using only the established history interface."""

    post_processed = any(
        filters[name] is not None
        for name in (
            "horizon",
            "event_id",
        )
    ) or sort_by != "event_id" or sort_order != "desc"

    def indexed_page(index: int, size: int) -> dict[str, Any]:
        try:
            return service.history(
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
            _history_event_view(service, item, hydrate_results=False)
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
            _history_event_view(service, item, hydrate_results=False)
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
) -> dict[str, Any]:
    """Adapt the service's fixed-query bulk stream once for both download formats."""

    try:
        # Every successful run owns both required horizons, so either horizon has this exact
        # indexed persistence-side meaning and needs no per-event reconstruction.
        source = service.repository.history_export(
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
                datetime.fromisoformat(filters["submitted_to"])
                if filters["submitted_to"]
                else None
            ),
            model=filters["model"],
            model_version=filters["model_version"],
            request_id=filters["request_id"],
            event_id=filters["event_id"],
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
            results_by_run.setdefault(int(record["run_id"]), []).append(record)

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
        enriched = _history_event_view(service, event, detail)
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

    def record_malformed_forecast_response(
        generated: object, *, submitted_symbol: str, asset_type: str
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
            repository.record_failure(
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
    def create_forecast(payload: SearchRequest, response: Response) -> ForecastCreationResponse:
        generated = service.search(payload.symbol, payload.asset_type)
        try:
            # Validate before FastAPI's response serializer so a malformed service handoff can be
            # correlated with exactly one failed search rather than escaping as an unaudited 500.
            validated = ForecastCreationResponse.model_validate(generated)
            response.headers["Location"] = (
                f"/api/v1/saved-forecasts/{validated.event.id}"
            )
            response.headers["X-Request-ID"] = validated.event.request_id
            return validated
        except Exception:
            request_id = record_malformed_forecast_response(
                generated,
                submitted_symbol=payload.symbol,
                asset_type=payload.asset_type,
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
        response.headers["Content-Disposition"] = (
            'attachment; filename="stock-probs-history.json"'
        )
        response.headers["X-Export-Filters"] = _safe_metadata_header(filters)
        response.headers["X-Export-Sort"] = _safe_metadata_header(
            {"field": sort_by, "direction": sort_order}
        )
        return _bounded_history_export(
            service,
            filters=filters,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    @app.get(
        "/api/v1/history/{event_id:int}",
        response_model=ReconstructionResponse,
        response_model_exclude_unset=True,
        responses=_documented_errors(400, 403, 404, 405, 422, 500, 503),
    )
    def reconstruction(
        event_id: int = PathParameter(ge=1, le=2_147_483_647),
    ) -> dict[str, Any]:
        # Constrain matching at the router boundary so unrelated history paths remain genuine 404s;
        # the typed parameter still owns numeric bounds and their public validation response.
        result = service.history_detail(event_id)
        if result is None:
            raise HTTPException(status_code=404, detail="history event not found")
        available = result.get("input") is not None
        return {
            "record_kind": "recorded_forecast" if available else "failed_search",
            "immutable": True,
            "forecast_available": available,
            **result,
        }

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

        recorded = service.history_detail(event_id)
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
        responses={
            201: {
                "description": "Fresh cutoff analysis completed as a distinct saved result.",
                "headers": {
                    "Location": {"schema": {"type": "string"}},
                    "X-Request-ID": {"schema": {"type": "string"}},
                },
            },
            **_documented_errors(
                400, 403, 404, 405, 409, 411, 413, 422, 500, 502, 503
            ),
        },
    )
    def fresh_historical_reconstruction(
        payload: FreshReconstructionRequest,
        response: Response,
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
        created = {
            **generated,
            "source_event_id": event_id,
            "requested_cutoff": payload.cutoff.astimezone(UTC).isoformat(),
            "provider_called": True,
            "recalculated": True,
            "provenance": provenance,
        }
        response.headers["Location"] = (
            f"/api/v1/saved-forecasts/{generated['event']['id']}"
        )
        response.headers["X-Request-ID"] = str(generated["event"]["request_id"])
        return created

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

        historical = service.historical_series(event_id, series=series, limit=limit)
        if historical is None:
            raise HTTPException(status_code=404, detail="history event not found")
        if historical.get("available") is False:
            raise HTTPException(status_code=409, detail="failed searches have no captured prices")
        return historical

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
