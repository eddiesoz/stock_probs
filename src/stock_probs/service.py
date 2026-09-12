"""Application service coordinates validation, provider work, forecasts, and audit writes."""

from __future__ import annotations

import json
import sqlite3
import time as monotonic_time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import BoundedSemaphore, Lock
from typing import Any
from uuid import uuid4

from stock_probs.domain import (
    DomainError,
    NewsData,
    calculate_forecasts,
    evaluate_outcome,
    label_fresh_historical_analysis,
    normalize_lookup_query,
    normalize_symbol,
)
from stock_probs.provider import MAX_LOOKUP_RESULTS, MAX_NEWS_RESULTS, MarketDataProvider
from stock_probs.repository import Repository

NEWS_FRESH_SECONDS = 300.0
NEWS_STALE_SECONDS = 1800.0
NEWS_EMPTY_SECONDS = 60.0
NEWS_FAILURE_SECONDS = 30.0
NEWS_MAX_SYMBOLS = 32
NEWS_MAX_ENTRY_BYTES = 32 * 1024
NEWS_MAX_CACHE_BYTES = 1024 * 1024


@dataclass
class _NewsCacheEntry:
    data: NewsData | None = None
    requested_limit: int = 0
    stored_at: float = 0.0
    size: int = 0
    failed_at: float | None = None


class ForecastService:
    """Keep one bounded synchronous request transaction visible to the API layer."""

    def __init__(
        self,
        repository: Repository,
        provider: MarketDataProvider,
        clock: Callable[[], datetime] | None = None,
        max_provider_concurrency: int = 2,
        monotonic_clock: Callable[[], float] | None = None,
    ):
        self.repository = repository
        self.provider = provider
        self.clock = clock or (lambda: datetime.now(UTC))
        # Yahoo calls are blocking and memory-heavy; bound them independently of HTTP workers.
        self.provider_slots = BoundedSemaphore(max_provider_concurrency)
        self.monotonic_clock = monotonic_clock or monotonic_time.monotonic
        self.news_slot = BoundedSemaphore(1)
        self._news_lock = Lock()
        self._news_cache: OrderedDict[str, _NewsCacheEntry] = OrderedDict()

    @staticmethod
    def _news_response(data: NewsData, limit: int, cache_state: str) -> dict[str, object]:
        return data.as_dict(limit=limit, cache_state=cache_state)

    @staticmethod
    def _news_data_is_stale_eligible(
        entry: _NewsCacheEntry, now: float, limit: int
    ) -> bool:
        return bool(
            entry.data is not None
            and entry.data.items
            and limit <= entry.requested_limit
            and max(0.0, now - entry.stored_at) <= NEWS_STALE_SECONDS
            and entry.size <= NEWS_MAX_ENTRY_BYTES
        )

    def _news_failure(
        self, symbol: str, now: float, limit: int
    ) -> dict[str, object] | None:
        """Record suppression and return an eligible stale response in one locked step."""

        with self._news_lock:
            entry = self._news_cache.get(symbol) or _NewsCacheEntry()
            entry.failed_at = now
            self._news_cache[symbol] = entry
            self._news_cache.move_to_end(symbol)
            while len(self._news_cache) > NEWS_MAX_SYMBOLS:
                self._news_cache.popitem(last=False)
            if self._news_data_is_stale_eligible(entry, now, limit):
                assert entry.data is not None
                return self._news_response(entry.data, limit, "stale_fallback")
            return None

    def _store_news(self, symbol: str, data: NewsData, limit: int, now: float) -> None:
        serialized = json.dumps(
            data.as_dict(limit=limit, cache_state="miss"),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        if len(serialized) > NEWS_MAX_ENTRY_BYTES:
            raise DomainError(
                "provider_news_invalid",
                "The news provider response exceeds the safe response size.",
                status_code=502,
            )
        with self._news_lock:
            self._news_cache[symbol] = _NewsCacheEntry(
                data=data,
                requested_limit=limit,
                stored_at=now,
                size=len(serialized),
            )
            self._news_cache.move_to_end(symbol)
            while len(self._news_cache) > NEWS_MAX_SYMBOLS or sum(
                entry.size for entry in self._news_cache.values()
            ) > NEWS_MAX_CACHE_BYTES:
                self._news_cache.popitem(last=False)

    def news(self, symbol: str, limit: int = 5) -> dict[str, object]:
        """Return bounded current headlines without reading or writing forecast persistence."""

        normalized_symbol = normalize_symbol(symbol)
        if type(limit) is not int or not 1 <= limit <= MAX_NEWS_RESULTS:
            raise DomainError(
                "invalid_news_limit",
                f"News limit must be between 1 and {MAX_NEWS_RESULTS}.",
            )
        now = self.monotonic_clock()
        with self._news_lock:
            entry = self._news_cache.get(normalized_symbol)
            if entry is not None:
                age = max(0.0, now - entry.stored_at)
                within_requested_limit = limit <= entry.requested_limit
                if entry.data is not None and within_requested_limit:
                    if entry.data.items and age < NEWS_FRESH_SECONDS:
                        self._news_cache.move_to_end(normalized_symbol)
                        return self._news_response(entry.data, limit, "hit")
                    if not entry.data.items and age < NEWS_EMPTY_SECONDS:
                        self._news_cache.move_to_end(normalized_symbol)
                        return self._news_response(entry.data, limit, "hit")
                empty_expired = (
                    entry.data is not None
                    and not entry.data.items
                    and age >= NEWS_EMPTY_SECONDS
                )
                stale_expired = (
                    entry.data is not None
                    and bool(entry.data.items)
                    and age > NEWS_STALE_SECONDS
                )
                if empty_expired or stale_expired:
                    entry.data = None
                    entry.size = 0
                    entry.requested_limit = 0
                suppressed = (
                    entry.failed_at is not None
                    and max(0.0, now - entry.failed_at) < NEWS_FAILURE_SECONDS
                )
                if suppressed:
                    if self._news_data_is_stale_eligible(entry, now, limit):
                        assert entry.data is not None
                        return self._news_response(entry.data, limit, "stale_fallback")
                    raise DomainError(
                        "provider_unavailable",
                        "The news provider is temporarily unavailable.",
                        status_code=502,
                    )

        if not self.news_slot.acquire(blocking=False):
            raise DomainError(
                "provider_busy",
                "News retrieval capacity is busy; try again shortly.",
                status_code=503,
            )
        try:
            try:
                requested_at = self.clock()
                if requested_at.tzinfo is None:
                    raise DomainError(
                        "ambiguous_provider_time", "News request time must include an offset."
                    )
                data = self.provider.fetch_news(
                    normalized_symbol, limit, requested_at.astimezone(UTC)
                )
                if data.symbol != normalized_symbol or len(data.items) > limit:
                    raise DomainError(
                        "provider_news_invalid",
                        "The news provider returned data outside the requested bounds.",
                        status_code=502,
                    )
                completed = self.monotonic_clock()
                self._store_news(normalized_symbol, data, limit, completed)
                return self._news_response(data, limit, "miss")
            except Exception as exc:
                failed = self.monotonic_clock()
                stale = self._news_failure(normalized_symbol, failed, limit)
                if stale is not None:
                    return stale
                if isinstance(exc, DomainError):
                    raise
                raise DomainError(
                    "provider_unavailable",
                    "The news provider failed unexpectedly.",
                    status_code=502,
                ) from exc
        finally:
            self.news_slot.release()

    def lookup(self, query: str, limit: int = 5) -> dict[str, object]:
        """Expose one transport-ready company/symbol lookup without leaking provider objects."""

        normalized_query = normalize_lookup_query(query)
        if type(limit) is not int or not 1 <= limit <= MAX_LOOKUP_RESULTS:
            raise DomainError(
                "invalid_lookup_limit",
                f"Lookup limit must be between 1 and {MAX_LOOKUP_RESULTS}.",
            )
        requested_at = self.clock().astimezone(UTC)
        if not self.provider_slots.acquire(timeout=1.0):
            raise DomainError(
                "provider_busy",
                "Market data capacity is busy; try again shortly.",
                status_code=503,
            )
        try:
            try:
                identities = self.provider.lookup(normalized_query, limit, requested_at)
            except DomainError:
                raise
            except Exception as exc:
                # Search responses receive the same safe provider boundary as market history.
                raise DomainError(
                    "provider_unavailable",
                    "The instrument lookup provider failed unexpectedly.",
                    status_code=502,
                ) from exc
        finally:
            self.provider_slots.release()
        bounded_identities = identities[:limit]
        return {
            "query": normalized_query,
            "limit": limit,
            "items": [identity.as_dict() for identity in bounded_identities],
            "total": len(bounded_identities),
        }

    def history(
        self,
        *,
        query: str = "",
        symbol: str | None = None,
        company: str | None = None,
        asset_type: str | None = None,
        status: str | None = None,
        semantics: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        model: str | None = None,
        model_version: str | None = None,
        request_id: str | None = None,
        analysis_kind: str | None = None,
        event_id: int | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """Serve rich history facets while keeping persistence and transport separable."""

        return self.repository.history(
            query=query,
            symbol=symbol,
            company=company,
            asset_type=asset_type,
            status=status,
            semantics=semantics,
            date_from=date_from,
            date_to=date_to,
            model=model,
            model_version=model_version,
            request_id=request_id,
            analysis_kind=analysis_kind,
            event_id=event_id,
            page=page,
            page_size=page_size,
            include_analysis=True,
            include_facets=True,
        )

    def history_detail(self, event_id: int) -> dict[str, Any] | None:
        """Return recorded chart, calibration, and outcome data without provider access."""

        return self.repository.reconstruction(event_id)

    def saved_forecast(self, event_id: int) -> dict[str, Any] | None:
        """Label exact replay explicitly; this method never invokes a provider or calculator."""

        recorded = self.repository.reconstruction(event_id)
        if recorded is None or recorded.get("input") is None:
            return None
        return {
            "analysis_kind": "saved_recorded_forecast",
            "immutable": True,
            "recalculated": False,
            "provider_called": False,
            **recorded,
        }

    def history_export(
        self,
        *,
        query: str = "",
        symbol: str | None = None,
        company: str | None = None,
        asset_type: str | None = None,
        status: str | None = None,
        semantics: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        model: str | None = None,
        model_version: str | None = None,
        request_id: str | None = None,
        analysis_kind: str | None = None,
        event_id: int | None = None,
        max_events: int = 100,
    ) -> dict[str, Any]:
        """Use one UTC generation time for a bounded JSON/CSV source record stream."""

        return self.repository.history_export(
            generated_at=self.clock().astimezone(UTC),
            query=query,
            symbol=symbol,
            company=company,
            asset_type=asset_type,
            status=status,
            semantics=semantics,
            date_from=date_from,
            date_to=date_to,
            model=model,
            model_version=model_version,
            request_id=request_id,
            analysis_kind=analysis_kind,
            event_id=event_id,
            max_events=max_events,
        )

    def historical_series(
        self, event_id: int, *, series: str = "daily", limit: int = 120
    ) -> dict[str, Any] | None:
        """Expose the same immutable bounded price source to chart and text consumers."""

        return self.repository.historical_series(event_id, series=series, limit=limit)

    def search(self, submitted_symbol: str, asset_type: str) -> dict[str, object]:
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

    def fresh_historical_reconstruction(
        self, source_event_id: int, cutoff: datetime
    ) -> dict[str, object]:
        """Submit and audit a fresh cutoff analysis, never a saved-result recalculation."""

        request_id = str(uuid4())
        submitted_at = self.clock().astimezone(UTC)
        source = self.repository.reconstruction(source_event_id)
        source_input = source.get("input") if source is not None else None
        submitted_symbol = (
            str(source_input["symbol"])
            if isinstance(source_input, dict) and "symbol" in source_input
            else f"<history event {source_event_id}>"
        )
        asset_type = (
            str(source_input["asset_type"])
            if isinstance(source_input, dict) and "asset_type" in source_input
            else "invalid"
        )
        normalized: str | None = None
        try:
            if source is None or not isinstance(source_input, dict):
                raise DomainError(
                    "historical_source_unavailable",
                    "Fresh analysis requires a saved successful forecast event.",
                    status_code=404 if source is None else 409,
                )
            if cutoff.tzinfo is None:
                raise DomainError(
                    "ambiguous_historical_cutoff",
                    "Historical cutoff must include a timezone offset.",
                )
            cutoff = cutoff.astimezone(UTC)
            if cutoff > submitted_at:
                raise DomainError(
                    "future_historical_cutoff", "Historical cutoff cannot be in the future."
                )
            normalized = normalize_symbol(submitted_symbol)
            if asset_type not in {"stock", "etf"}:
                raise DomainError("unsupported_asset", "Only stocks and ETFs are supported.")
            if not self.provider_slots.acquire(timeout=1.0):
                raise DomainError(
                    "provider_busy",
                    "Market data capacity is busy; try again shortly.",
                    status_code=503,
                )
            try:
                try:
                    # Fetching is deliberately complete before BEGIN IMMEDIATE in persistence.
                    market_data = self.provider.fetch_at_cutoff(
                        normalized, asset_type, cutoff, submitted_at
                    )
                except DomainError:
                    raise
                except Exception as exc:
                    raise DomainError(
                        "provider_unavailable",
                        "The historical market data provider failed unexpectedly.",
                        status_code=502,
                    ) from exc
            finally:
                self.provider_slots.release()
            try:
                snapshot, results = calculate_forecasts(market_data, cutoff)
            except DomainError:
                raise
            except Exception as exc:
                raise DomainError(
                    "calculation_failure",
                    "The historical forecast calculation could not be completed.",
                    status_code=500,
                ) from exc
            snapshot, results = label_fresh_historical_analysis(
                snapshot,
                results,
                request_id=request_id,
                source_event_id=source_event_id,
                cutoff=cutoff,
                performed_at=submitted_at,
            )
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
                    analysis_kind="fresh_historical_reconstruction",
                    source_event_id=source_event_id,
                    requested_cutoff=cutoff,
                    reuse_exact_input=False,
                )
            except sqlite3.Error as exc:
                raise DomainError(
                    "persistence_failure",
                    "The fresh historical analysis could not be stored immutably.",
                    status_code=503,
                ) from exc
            reconstructed = self.repository.reconstruction(event_id)
            assert reconstructed is not None
            reconstructed["analysis_kind"] = "fresh_historical_reconstruction"
            reconstructed["label"] = "Fresh historical-cutoff analysis"
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
                analysis_kind="fresh_historical_reconstruction",
                # Persistence resolves this requested ID to an FK only for a real successful
                # source, so an unknown history ID remains useful context without fabrication.
                source_event_id=source_event_id,
                requested_cutoff=cutoff,
            )
            exc.request_id = request_id
            raise

    # Keep the application-layer handoff concise for A while retaining the explicit public name.
    reconstruct_at_cutoff = fresh_historical_reconstruction

    def append_outcome(
        self,
        result_id: int,
        observed_close: float | None,
        observed_at: datetime,
        state: str,
        note: str,
    ) -> dict[str, object] | None:
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
