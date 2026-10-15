"""Collect reproducible daily forecast outcomes through a trusted provider capability."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Protocol

from stock_probs.domain import Bar
from stock_probs.outcome_collection_store import (
    DAILY_HORIZONS,
    OutcomeCollectionLeaseConflict,
    OutcomeCollectionStore,
    OutcomeForecast,
    OutcomeJobClaim,
)

ADJUSTMENT_BASIS = "unadjusted provider closes (actions=False, auto_adjust=False)"
MAX_DAILY_BARS = 520
DEFAULT_RETRY = timedelta(minutes=15)
_REASONS = frozenset({"provider_unavailable", "corporate_action_unknown", "series_incomplete"})
_HORIZON_SESSIONS = {
    "close_to_close": 1,
    "daily_1": 1,
    "weekly_5": 5,
    "monthly_21": 21,
    "quarterly_63": 63,
}


def _cancel_requested(cancelled: Callable[[], bool] | None) -> bool:
    """Fail closed if a supplied worker-cancellation check is invalid or unavailable."""
    if cancelled is None:
        return False
    try:
        return cancelled() is not False
    except Exception:
        return True


class OutcomeSourceUnavailable(RuntimeError):
    """A safe, bounded failure from the daily outcome provider adapter."""

    def __init__(self, reason_code: str):
        if reason_code not in _REASONS:
            raise ValueError("unsupported outcome source failure code")
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True)
class CorporateActionCheck:
    """Provider attestation for a complete corporate-action interval."""

    provider: str
    symbol: str
    currency: str
    from_timestamp: datetime
    through_timestamp: datetime
    complete: bool
    events: tuple[object, ...]


@dataclass(frozen=True)
class DailyOutcomeSeries:
    """Complete daily close series and action check returned by an opted-in adapter."""

    provider: str
    symbol: str
    currency: str
    adjustment_basis: str
    requested_from: datetime
    requested_through: datetime
    as_of: datetime
    complete: bool
    bars: tuple[Bar, ...]
    corporate_actions: CorporateActionCheck | None


class DailyOutcomeSource(Protocol):
    """Trusted capability required before an unadjusted daily series can be scored."""

    def fetch_daily_outcome_series(
        self,
        symbol: str,
        asset_type: str,
        origin_at: datetime,
        target_at: datetime,
        now: datetime,
    ) -> DailyOutcomeSeries: ...


@dataclass(frozen=True)
class _Collection:
    outcome_state: str
    observed_close: float | None
    evidence_state: str
    evidence_payload: Mapping[str, object]
    source_succeeded: bool


@dataclass(frozen=True)
class _CompletedCollection:
    collection: _Collection
    completed_at: datetime


class DailyOutcomeCollector:
    """Run a bounded batch of daily outcome jobs without starting background work."""

    def __init__(
        self,
        store: OutcomeCollectionStore,
        source: DailyOutcomeSource | None,
        *,
        completion_clock: Callable[[], datetime] | None = None,
    ):
        self.store = store
        self.source = source
        self.completion_clock = completion_clock

    def run_once(
        self,
        now: datetime,
        *,
        worker_id: str = "daily-outcome-collector",
        limit: int = 10,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, int]:
        """Queue and process one fair persisted batch; callers own application lifecycle."""
        request_now = _instant(now)
        counts = {"claimed": 0, "recorded": 0, "unchanged": 0, "skipped": 0}
        if _cancel_requested(cancelled):
            return counts
        self.store.enqueue_due(request_now, limit=min(limit, 50))
        if _cancel_requested(cancelled):
            return counts
        claims = self.store.claim_due(worker_id, request_now, limit=limit)
        counts["claimed"] = len(claims)
        for claim in claims:
            if _cancel_requested(cancelled):
                counts["skipped"] += 1
                break
            forecast = self.store.load_forecast(claim, request_now)
            if forecast is None:
                if _cancel_requested(cancelled):
                    counts["skipped"] += 1
                    break
                self.store.defer_claim(
                    claim,
                    request_now,
                    retry_at=request_now + DEFAULT_RETRY,
                    failure_code="forecast_unavailable",
                )
                counts["skipped"] += 1
                continue
            if forecast.latest_outcome_is_manual:
                if _cancel_requested(cancelled):
                    counts["skipped"] += 1
                    break
                self.store.preserve_manual_outcome(claim, request_now)
                counts["skipped"] += 1
                continue
            if _cancel_requested(cancelled):
                counts["skipped"] += 1
                break
            completed = self._collect(
                forecast,
                request_now,
                dispatch_guard=partial(
                    self._authorize_dispatch, claim, forecast, request_now, cancelled
                ),
            )
            if _cancel_requested(cancelled):
                counts["skipped"] += 1
                break
            collection = completed.collection
            result = self.store.record_collection(
                claim,
                forecast,
                outcome_state=collection.outcome_state,
                observed_close=collection.observed_close,
                observed_at=_target(forecast.forecast),
                evidence_state=collection.evidence_state,
                evidence_payload=collection.evidence_payload,
                now=completed.completed_at,
                source_succeeded=collection.source_succeeded,
                cancelled=cancelled,
            )
            disposition = result.get("disposition")
            if not isinstance(disposition, str) or disposition not in {
                "recorded",
                "unchanged",
                "manual_outcome_preserved",
            }:
                raise RuntimeError("the outcome store returned an unsupported disposition")
            counts[disposition] = counts.get(disposition, 0) + 1
        return counts

    def _collect(
        self,
        target: OutcomeForecast,
        now: datetime,
        *,
        dispatch_guard: Callable[[], datetime] | None = None,
    ) -> _CompletedCollection:
        """Validate data and explicit action evidence before creating scorer-compatible proof."""
        forecast = target.forecast
        horizon = _recognized_horizon(forecast.get("horizon"))
        if horizon is None:
            return self._completed(_unavailable("series_incomplete", source_succeeded=False), now)
        if forecast.get("availability", "available") != "available":
            return self._completed(_unavailable("series_incomplete", source_succeeded=False), now)
        if self.source is None:
            return self._completed(
                _unavailable("corporate_action_unknown", source_succeeded=False), now
            )
        fetch = getattr(self.source, "fetch_daily_outcome_series", None)
        if not callable(fetch):
            return self._completed(
                _unavailable("corporate_action_unknown", source_succeeded=False), now
            )
        origin_at = _parse_time(forecast.get("origin_timestamp"))
        target_at = _target(forecast)
        if now.astimezone(UTC) < target_at:
            return self._completed(_unavailable("series_incomplete", source_succeeded=False), now)
        dispatch_at = dispatch_guard() if dispatch_guard is not None else now
        try:
            series = fetch(
                target.symbol,
                target.asset_type,
                origin_at,
                target_at,
                dispatch_at,
            )
        except OutcomeSourceUnavailable as error:
            completed_at = self._completion_time(now)
            return _CompletedCollection(
                _unavailable(error.reason_code, source_succeeded=False), completed_at
            )
        except Exception:
            completed_at = self._completion_time(now)
            return _CompletedCollection(
                _unavailable("provider_unavailable", source_succeeded=False), completed_at
            )
        completed_at = self._completion_time(now)
        try:
            collection = self._validate_series(
                target, series, origin_at, target_at, horizon, completed_at
            )
        except (TypeError, ValueError, OverflowError):
            collection = _unavailable("series_incomplete", source_succeeded=True)
        return _CompletedCollection(collection, completed_at)

    def _authorize_dispatch(
        self,
        claim: OutcomeJobClaim,
        forecast: OutcomeForecast,
        request_now: datetime,
        cancelled: Callable[[], bool] | None,
    ) -> datetime:
        """Recheck live ownership, controls, and lease immediately before provider dispatch."""
        if _cancel_requested(cancelled):
            raise OutcomeCollectionLeaseConflict("The collection worker is stopping.")
        dispatch_at = self._completion_time(request_now)
        current = self.store.load_forecast(claim, dispatch_at)
        if (
            current is None
            or current.latest_outcome_is_manual
            or current.owner_user_id != forecast.owner_user_id
            or current.result_id != forecast.result_id
            or current.symbol != forecast.symbol
            or current.asset_type != forecast.asset_type
            or current.forecast != forecast.forecast
        ):
            raise OutcomeCollectionLeaseConflict(
                "The collection lease, owner authorization, or forecast changed before dispatch."
            )
        if _cancel_requested(cancelled):
            raise OutcomeCollectionLeaseConflict("The collection worker is stopping.")
        return dispatch_at

    def _completed(self, collection: _Collection, request_now: datetime) -> _CompletedCollection:
        """Bind a collection result to an aware completion time before persistence."""
        return _CompletedCollection(collection, self._completion_time(request_now))

    def _completion_time(self, request_now: datetime) -> datetime:
        """Use runtime completion time when supplied; fail closed on invalid clock readings."""
        completed_at = self.completion_clock() if self.completion_clock is not None else request_now
        normalized = _instant(completed_at)
        if normalized < request_now:
            raise ValueError("the collection completion clock moved backwards")
        return normalized

    @staticmethod
    def _validate_series(
        target: OutcomeForecast,
        series: object,
        origin_at: datetime,
        target_at: datetime,
        horizon: str,
        now: datetime,
    ) -> _Collection:
        """Require exact forecast identity, complete endpoints, and checked-clear actions."""
        if not isinstance(series, DailyOutcomeSeries):
            return _unavailable("series_incomplete", source_succeeded=True)
        expected_sessions = _HORIZON_SESSIONS.get(horizon)
        if expected_sessions is None:
            return _unavailable("series_incomplete", source_succeeded=True)
        forecast = target.forecast
        provenance = forecast.get("provenance")
        identity = provenance.get("instrument_identity") if isinstance(provenance, dict) else None
        provider = provenance.get("source") if isinstance(provenance, dict) else None
        symbol = forecast.get("canonical_symbol")
        currency = forecast.get("currency")
        if (
            not isinstance(identity, dict)
            or provider != series.provider
            or identity.get("provider") != series.provider
            or symbol != target.symbol
            or identity.get("canonical_symbol") != symbol
            or series.symbol != symbol
            or not isinstance(currency, str)
            or identity.get("currency") != currency
            or series.currency != currency
            or series.adjustment_basis != ADJUSTMENT_BASIS
            or forecast.get("adjustment_basis") != ADJUSTMENT_BASIS
            or _instant(series.requested_from) != origin_at
            or _instant(series.requested_through) != target_at
            or series.complete is not True
            or not isinstance(series.bars, tuple)
            or len(series.bars) > MAX_DAILY_BARS
            or len(series.bars) != expected_sessions + 1
            or _instant(series.as_of) > now.astimezone(UTC)
            or _instant(series.as_of) < target_at
        ):
            return _unavailable("series_incomplete", source_succeeded=True)
        action_check = series.corporate_actions
        if (
            not isinstance(action_check, CorporateActionCheck)
            or action_check.complete is not True
            or action_check.provider != series.provider
            or action_check.symbol != symbol
            or action_check.currency != currency
            or _instant(action_check.from_timestamp) != origin_at
            or _instant(action_check.through_timestamp) != target_at
            or not isinstance(action_check.events, tuple)
            or len(action_check.events) > 100
            or action_check.events
        ):
            return _unavailable("corporate_action_unknown", source_succeeded=True)

        prior: datetime | None = None
        origin_close: float | None = None
        target_close: float | None = None
        origin_price = _finite_positive(forecast.get("origin_price"))
        for bar in series.bars:
            if (
                not isinstance(bar, Bar)
                or type(bar.duration_seconds) is not int
                or bar.duration_seconds != 0
            ):
                return _unavailable("series_incomplete", source_succeeded=True)
            instant = _instant(bar.timestamp)
            close = _finite_positive(bar.close)
            if (
                instant < origin_at
                or instant > target_at
                or (prior is not None and instant <= prior)
            ):
                return _unavailable("series_incomplete", source_succeeded=True)
            prior = instant
            if instant == origin_at:
                origin_close = close
            if instant == target_at:
                target_close = close
        if (
            origin_close is None
            or target_close is None
            or not math.isclose(origin_close, origin_price, rel_tol=0, abs_tol=1e-12)
        ):
            return _unavailable("series_incomplete", source_succeeded=True)

        origin_text = origin_at.isoformat()
        target_text = target_at.isoformat()
        comparability = {
            "schema": "forecast-outcome-comparability-v1",
            "state": "comparable",
            "provider": series.provider,
            "symbol": symbol,
            "currency": currency,
            "adjustment_basis": ADJUSTMENT_BASIS,
            "origin": {"timestamp": origin_text, "close": origin_close},
            "target": {"timestamp": target_text, "close": target_close},
            "corporate_actions": {
                "state": "checked",
                "provider": series.provider,
                "symbol": symbol,
                "currency": currency,
                "from_timestamp": origin_text,
                "through_timestamp": target_text,
                "events": [],
            },
        }
        return _Collection(
            outcome_state="observed",
            observed_close=target_close,
            evidence_state="observed",
            evidence_payload={
                "method": "provider_bar",
                "provider": series.provider,
                "symbol": symbol,
                "currency": currency,
                "bar": {
                    "timestamp": target_text,
                    "end": target_text,
                    "close": target_close,
                    "duration_seconds": 0,
                },
                "comparability": comparability,
            },
            source_succeeded=True,
        )


def _unavailable(reason_code: str, *, source_succeeded: bool) -> _Collection:
    """Represent missing or unsafe source evidence without inventing a successful observation."""
    if reason_code not in _REASONS:
        reason_code = "provider_unavailable"
    return _Collection(
        outcome_state="unavailable",
        observed_close=None,
        evidence_state="unavailable",
        evidence_payload={"reason_code": reason_code},
        source_succeeded=source_succeeded,
    )


def _recognized_horizon(value: object) -> str | None:
    """Return only a nonempty daily horizon recognized by both collection contracts."""
    if not isinstance(value, str) or not value or value not in DAILY_HORIZONS:
        return None
    return value if value in _HORIZON_SESSIONS else None


def _instant(value: datetime) -> datetime:
    """Require a timezone-aware instant and normalize it for endpoint comparisons."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("provider times must be aware")
    return value.astimezone(UTC)


def _parse_time(value: object) -> datetime:
    """Parse one bounded timestamp from the immutable forecast payload."""
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("forecast time is invalid")
    return _instant(datetime.fromisoformat(value))


def _target(forecast: Mapping[str, object]) -> datetime:
    """Return the exact immutable target session timestamp."""
    return _parse_time(forecast.get("target_timestamp"))


def _finite_positive(value: object) -> float:
    """Reject booleans, malformed values, infinities, and nonpositive closes."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("a source close must be numeric")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError("a source close must be finite and positive")
    return result
