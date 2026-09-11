"""Pydantic transport models bound request sizes before domain or SQLite work begins."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Reject accidental fields so the local API contract stays explicit."""

    model_config = ConfigDict(extra="forbid")


class SearchRequest(StrictModel):
    # Symbol syntax is audited by the domain so validly submitted bad symbols persist as failures.
    symbol: str = Field(max_length=64)
    asset_type: Literal["stock", "etf"]


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


class BackupRequest(StrictModel):
    name: str | None = Field(default=None, min_length=10, max_length=73)


class RestoreRequest(StrictModel):
    name: str = Field(min_length=10, max_length=73)
    promote: bool = False
