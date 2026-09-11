"""Application service coordinates validation, provider work, forecasts, and audit writes."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from threading import BoundedSemaphore
from uuid import uuid4

from stock_probs.domain import DomainError, calculate_forecasts, evaluate_outcome, normalize_symbol
from stock_probs.provider import MarketDataProvider
from stock_probs.repository import Repository


class ForecastService:
    """Keep one bounded synchronous request transaction visible to the API layer."""

    def __init__(
        self,
        repository: Repository,
        provider: MarketDataProvider,
        clock: Callable[[], datetime] | None = None,
        max_provider_concurrency: int = 2,
    ):
        self.repository = repository
        self.provider = provider
        self.clock = clock or (lambda: datetime.now(UTC))
        # Yahoo calls are blocking and memory-heavy; bound them independently of HTTP workers.
        self.provider_slots = BoundedSemaphore(max_provider_concurrency)

    def search(self, submitted_symbol: str, asset_type: str) -> dict:
        request_id = str(uuid4())
        submitted_at = self.clock().astimezone(UTC)
        normalized: str | None = None
        try:
            if asset_type not in {"stock", "etf"}:
                raise DomainError("unsupported_asset", "Only stocks and ETFs are supported.")
            normalized = normalize_symbol(submitted_symbol)
            if not self.provider_slots.acquire(timeout=1.0):
                raise DomainError(
                    "provider_busy",
                    "Market data capacity is busy; try again shortly.",
                    status_code=503,
                )
            try:
                try:
                    market_data = self.provider.fetch(normalized, asset_type, submitted_at)
                except DomainError:
                    raise
                except Exception as exc:
                    # Provider implementation details must not escape or bypass failed-search audit.
                    raise DomainError(
                        "provider_unavailable",
                        "The market data provider failed unexpectedly.",
                        status_code=502,
                    ) from exc
            finally:
                self.provider_slots.release()
            try:
                snapshot, results = calculate_forecasts(market_data, submitted_at)
            except DomainError:
                raise
            except Exception as exc:
                raise DomainError(
                    "calculation_failure",
                    "The forecast calculation could not be completed.",
                    status_code=500,
                ) from exc
            completed_at = self.clock().astimezone(UTC)
            try:
                event_id, _, repeated, reused = self.repository.record_success(
                    request_id=request_id,
                    submitted_symbol=submitted_symbol,
                    asset_type=asset_type,
                    input_snapshot=snapshot,
                    results=results,
                    submitted_at=submitted_at,
                    completed_at=completed_at,
                )
            except sqlite3.Error as exc:
                # The outer classified-error path attempts one audit after the transaction rollback.
                raise DomainError(
                    "persistence_failure",
                    "The forecast could not be stored immutably.",
                    status_code=503,
                ) from exc
            reconstructed = self.repository.reconstruction(event_id)
            assert reconstructed is not None
            reconstructed["repeated"] = repeated
            reconstructed["reused"] = reused
            return reconstructed
        except DomainError as exc:
            self.repository.record_failure(
                request_id=request_id,
                submitted_symbol=submitted_symbol,
                normalized_symbol=normalized,
                asset_type=asset_type,
                error_code=exc.code,
                error_message=exc.message,
                submitted_at=submitted_at,
                completed_at=self.clock().astimezone(UTC),
            )
            exc.request_id = request_id
            raise

    def append_outcome(
        self,
        result_id: int,
        observed_close: float | None,
        observed_at: datetime,
        state: str,
        note: str,
    ) -> dict | None:
        """Keep horizon validation in the domain before appending through persistence."""

        if state not in {"observed", "unavailable", "provisional", "corrected"}:
            raise DomainError("invalid_outcome_state", "Outcome state is not supported.")
        if state == "unavailable" and observed_close is not None:
            raise DomainError(
                "invalid_outcome_price", "Unavailable outcomes cannot contain a close."
            )
        if state != "unavailable" and observed_close is None:
            raise DomainError("invalid_outcome_price", "This outcome state requires a close.")
        result = self.repository.forecast_result(result_id)
        if result is None:
            return None
        observed_return, comparison_rule = evaluate_outcome(result, observed_close, observed_at)
        return self.repository.append_outcome(
            result_id,
            observed_close,
            observed_return,
            observed_at,
            state,
            note,
            comparison_rule,
            self.clock(),
        )
