"""Pydantic transport models bound request sizes before domain or SQLite work begins."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)

from stock_probs.domain import DomainError, normalize_symbol

ForecastHorizon: TypeAlias = Literal["close_to_close", "completed_5m_to_close"]
HistoryStatus: TypeAlias = Literal["successful", "failed", "repeated"]
HistoryAnalysisKind: TypeAlias = Literal[
    "submitted_forecast", "fresh_historical_reconstruction"
]
HistorySortField: TypeAlias = Literal[
    "event_id",
    "submitted_at",
    "completed_at",
    "symbol",
    "company",
    "asset_type",
    "status",
    "model",
    "horizon",
    "request_id",
]
SortDirection: TypeAlias = Literal["asc", "desc"]


class StrictModel(BaseModel):
    """Reject accidental fields so the local API contract stays explicit."""

    model_config = ConfigDict(extra="forbid")


class SearchRequest(StrictModel):
    # Symbol syntax is audited by the domain so validly submitted bad symbols persist as failures.
    symbol: str = Field(max_length=64)
    asset_type: Literal["stock", "etf"]


class InstrumentIdentityResponse(StrictModel):
    """Facts that together distinguish one supported Yahoo instrument."""

    canonical_symbol: str = Field(min_length=1, max_length=15)
    display_name: str = Field(min_length=1, max_length=200)
    company_name: str = Field(min_length=1, max_length=200)
    exchange: str = Field(min_length=1, max_length=40)
    currency: str = Field(min_length=1, max_length=12)
    timezone: str = Field(min_length=1, max_length=80)
    quote_type: Literal["EQUITY", "STOCK", "ETF"]
    asset_type: Literal["stock", "etf"]
    provider: str = Field(min_length=1, max_length=80)
    provider_as_of: AwareDatetime


class InstrumentLookupResponse(StrictModel):
    """A display name is always coupled to identity instead of returned as a loose match."""

    query: str = Field(min_length=1, max_length=80)
    items: list[InstrumentIdentityResponse]
    total: int = Field(ge=0, le=5)
    limit: int = Field(ge=1, le=5)


class NewsQuery(StrictModel):
    symbol: str = Field(min_length=1, max_length=15, pattern=r"^[A-Z0-9.^-]+$")
    limit: int = Field(default=5, ge=1, le=10)

    @field_validator("symbol", mode="before")
    @classmethod
    def normalized_symbol(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("symbol is not supported")
        try:
            return normalize_symbol(value)
        except DomainError:
            raise ValueError("symbol is not supported") from None

    @field_validator("limit", mode="before")
    @classmethod
    def integer_limit(cls, value: object) -> object:
        if isinstance(value, str):
            if not value.isascii() or not value.isdecimal():
                raise ValueError("limit must be an integer")
        elif type(value) is not int:
            raise ValueError("limit must be an integer")
        return value


class NewsItem(StrictModel):
    id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
    ]
    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]
    publisher: str | None = Field(max_length=200)
    url: HttpUrl = Field(max_length=2048)
    published_at: AwareDatetime | None
    related_symbols: list[str] | None = Field(max_length=32)

    @field_validator("url")
    @classmethod
    def https_url(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("news URL must use HTTPS")
        return value

    @field_validator("published_at")
    @classmethod
    def published_at_utc(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None


class NewsCoverage(StrictModel):
    returned_count: int = Field(ge=0, le=10)
    partial_metadata: bool
    refresh_failed: bool


class NewsResponse(StrictModel):
    query: NewsQuery
    provider: str = Field(min_length=1, max_length=80)
    as_of: AwareDatetime
    items: list[NewsItem] = Field(max_length=10)
    coverage: NewsCoverage
    cache_state: Literal["miss", "hit", "stale_fallback"]

    @field_validator("as_of")
    @classmethod
    def as_of_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def count_matches_items(self) -> NewsResponse:
        if self.coverage.returned_count != len(self.items) or len(self.items) > self.query.limit:
            raise ValueError("news coverage must match the bounded returned items")
        return self


class OutcomeRequest(StrictModel):
    observed_close: float | None = Field(default=None, gt=0, le=10_000_000)
    observed_at: datetime
    state: Literal["observed", "unavailable", "provisional", "corrected"]
    note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def close_required_for_observation(self) -> OutcomeRequest:
        if self.state != "unavailable" and self.observed_close is None:
            raise ValueError("observed_close is required unless state is unavailable")
        # Unavailable is an explicit missing observation, never a price-bearing correction.
        if self.state == "unavailable" and self.observed_close is not None:
            raise ValueError("observed_close must be omitted when state is unavailable")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must include a timezone offset")
        return self


class CorrectionRequest(StrictModel):
    """A correction is a new observation entry, never an edit instruction."""

    observed_close: float = Field(gt=0, le=10_000_000)
    observed_at: datetime
    note: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def timezone_required(self) -> CorrectionRequest:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must include a timezone offset")
        return self


class FreshReconstructionRequest(StrictModel):
    """Label a historical-cutoff request so it cannot be confused with saved replay."""

    analysis_kind: Literal["fresh_historical_reconstruction"] = (
        "fresh_historical_reconstruction"
    )
    cutoff: datetime

    @model_validator(mode="after")
    def bounded_aware_cutoff(self) -> FreshReconstructionRequest:
        if self.cutoff.tzinfo is None:
            raise ValueError("cutoff must include a timezone offset")
        # Pre-2000 cutoffs cannot be served by the deliberately bounded provider windows.
        if self.cutoff.astimezone(UTC) < datetime(2000, 1, 1, tzinfo=UTC):
            raise ValueError("cutoff must be on or after 2000-01-01T00:00:00Z")
        return self


class BackupRequest(StrictModel):
    name: str | None = Field(default=None, min_length=10, max_length=73)


class RestoreRequest(StrictModel):
    name: str = Field(min_length=10, max_length=73)
    promote: bool = False
