"""Pydantic transport models bound request sizes before domain or SQLite work begins."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    provider_as_of: datetime


class InstrumentLookupResponse(StrictModel):
    """A display name is always coupled to identity instead of returned as a loose match."""

    query: str = Field(min_length=1, max_length=80)
    items: list[InstrumentIdentityResponse]
    total: int = Field(ge=0, le=5)
    limit: int = Field(ge=1, le=5)


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
