"""Bounded yfinance adapter and deterministic fixture implementation."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, time, timedelta
from importlib.resources import files
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import yfinance as yf

from stock_probs.domain import Bar, DomainError, MarketData, scheduled_session_close


class MarketDataProvider(Protocol):
    """Narrow provider boundary keeps deterministic tests out of transport internals."""

    def fetch(self, symbol: str, asset_type: str, now: datetime) -> MarketData: ...


class YahooProvider:
    """Translate bounded yfinance history calls into the provider-neutral contract."""

    def __init__(self, timeout: float = 8.0, clock: Callable[[], datetime] | None = None):
        self.timeout = timeout
        self.clock = clock or (lambda: datetime.now(UTC))

    def _history(self, ticker: Any, *, period: str, interval: str) -> Any:
        try:
            # Explicit settings prohibit silent extended-session or adjusted-price input.
            return ticker.history(
                period=period,
                interval=interval,
                prepost=False,
                actions=False,
                auto_adjust=False,
                repair=False,
                timeout=self.timeout,
                raise_errors=True,
            )
        except Exception as exc:
            raise DomainError(
                "provider_unavailable",
                "Yahoo Finance did not return usable data within the configured timeout.",
                status_code=502,
            ) from exc

    @staticmethod
    def _metadata_from_bounded_history(ticker: Any, frame: Any) -> dict[str, Any]:
        """Read metadata already returned by history without starting another network request."""

        # yfinance 1.7 stores chart metadata while history(timeout=...) is running. Reading that
        # cache avoids get_history_metadata(), whose cache-miss request has no timeout argument.
        frame_metadata = getattr(frame, "attrs", {}).get("history_metadata")
        price_history = getattr(ticker, "_price_history", None)
        cached_metadata = getattr(price_history, "_history_metadata", None)
        metadata = frame_metadata if isinstance(frame_metadata, Mapping) else cached_metadata
        if not isinstance(metadata, Mapping) or not metadata:
            raise DomainError(
                "provider_metadata_unavailable",
                "Yahoo did not return session metadata with the bounded history request.",
                status_code=502,
            )
        return dict(metadata)

    @staticmethod
    def _daily_bars(frame: Any, timezone: str) -> tuple[Bar, ...]:
        zone = ZoneInfo(timezone)
        bars = []
        for timestamp, row in frame.iterrows():
            close = row.get("Close")
            if close is None or not _positive_finite(close):
                continue
            # Yahoo labels daily rows by date; the domain calendar supplies early-close time.
            raw_timestamp = timestamp.to_pydatetime()
            session_date = (
                raw_timestamp.astimezone(zone).date()
                if raw_timestamp.tzinfo
                else raw_timestamp.date()
            )
            session_close = scheduled_session_close(session_date, timezone)
            if session_close is not None:
                bars.append(Bar(session_close, float(close), 0))
        return tuple(sorted(bars, key=lambda item: item.timestamp))

    @staticmethod
    def _intraday_bars(frame: Any) -> tuple[Bar, ...]:
        bars = []
        for timestamp, row in frame.iterrows():
            close = row.get("Close")
            if close is None or not _positive_finite(close):
                continue
            raw_timestamp = timestamp.to_pydatetime()
            if raw_timestamp.tzinfo is None:
                raise DomainError(
                    "ambiguous_provider_time",
                    "Yahoo returned intraday bars without a timezone.",
                    status_code=502,
                )
            bars.append(Bar(raw_timestamp.astimezone(UTC), float(close), 300))
        return tuple(sorted(bars, key=lambda item: item.timestamp))

    def fetch(self, symbol: str, asset_type: str, now: datetime) -> MarketData:
        if now.tzinfo is None:
            raise DomainError(
                "ambiguous_provider_time", "Provider request time must include an offset."
            )
        if asset_type not in {"stock", "etf"}:
            raise DomainError("unsupported_asset", "Only stocks and ETFs are supported.")
        ticker = yf.Ticker(symbol)
        daily_frame = self._history(ticker, period="2y", interval="1d")
        intraday_frame = self._history(ticker, period="5d", interval="5m")
        if daily_frame.empty or intraday_frame.empty:
            raise DomainError(
                "symbol_not_found",
                "Yahoo Finance has no required daily and five-minute data for this symbol.",
                status_code=404,
            )
        # Metadata must come from one of the two timeout-bounded chart responses above.
        meta = self._metadata_from_bounded_history(ticker, intraday_frame)
        provider_type = str(meta.get("instrumentType", "")).lower()
        type_mapping = {"etf": "etf", "equity": "stock", "stock": "stock"}
        normalized_type = type_mapping.get(provider_type)
        if normalized_type is None:
            raise DomainError(
                "unsupported_asset",
                "Yahoo did not classify this symbol as a supported stock or ETF.",
            )
        if normalized_type != asset_type:
            raise DomainError(
                "asset_type_mismatch",
                f"Yahoo classifies {symbol} as {normalized_type}, not {asset_type}.",
            )
        timezone = str(meta.get("exchangeTimezoneName", ""))
        try:
            ZoneInfo(timezone)
        except (KeyError, ValueError) as exc:
            raise DomainError(
                "ambiguous_provider_time",
                "Yahoo did not return a recognized exchange timezone.",
                status_code=502,
            ) from exc
        regular = meta.get("currentTradingPeriod", {}).get("regular", {})
        if not isinstance(regular, dict) or not regular.get("start") or not regular.get("end"):
            raise DomainError(
                "provider_metadata_unavailable",
                "Yahoo did not return regular-session boundaries.",
                status_code=502,
            )
        if str(meta.get("dataGranularity", "")) != "5m":
            raise DomainError(
                "provider_interval_mismatch",
                "Yahoo did not return the requested five-minute interval.",
                status_code=502,
            )
        daily = self._daily_bars(daily_frame, timezone)
        intraday = self._intraday_bars(intraday_frame)
        return MarketData(
            symbol=symbol,
            asset_type=asset_type,
            exchange=str(meta.get("exchangeName", "unknown")),
            timezone=timezone,
            currency=str(meta.get("currency", "USD")),
            # Capture response completion separately from the request/cutoff timestamp.
            fetched_at=self.clock().astimezone(UTC),
            query={
                "requested_as_of": now.astimezone(UTC).isoformat(),
                "daily": {"period": "2y", "interval": "1d", "prepost": False, "auto_adjust": False},
                "intraday": {
                    "period": "5d",
                    "interval": "5m",
                    "prepost": False,
                    "auto_adjust": False,
                },
            },
            daily=daily,
            intraday=intraday,
            provider_metadata={
                "regular_session": {
                    "start": _provider_epoch(regular.get("start")),
                    "end": _provider_epoch(regular.get("end")),
                },
                "data_granularity": meta.get("dataGranularity", "5m"),
                "gmtoffset": int(meta["gmtoffset"]) if meta.get("gmtoffset") is not None else None,
                "daily_coverage": _coverage(daily),
                "intraday_coverage": _coverage(intraday),
                "daily_returned_rows": len(daily_frame.index),
                "intraday_returned_rows": len(intraday_frame.index),
                "missing_daily_closes": int(daily_frame["Close"].isna().sum()),
                "missing_daily_sessions": _missing_daily_sessions(daily, timezone),
                "missing_intraday_closes": int(intraday_frame["Close"].isna().sum()),
                "missing_intraday_intervals": _missing_intraday_intervals(intraday, timezone),
                "trailing_missing_intraday_intervals": _trailing_missing_intraday_intervals(
                    intraday, timezone, now
                ),
            },
        )


class FixtureProvider:
    """Expand compact checked-in seeds so tests exercise the real service path."""

    def fetch(self, symbol: str, asset_type: str, now: datetime) -> MarketData:
        if now.tzinfo is None:
            raise DomainError(
                "ambiguous_provider_time", "Fixture request time must include an offset."
            )
        if asset_type not in {"stock", "etf"}:
            raise DomainError("unsupported_asset", "Only stocks and ETFs are supported.")
        if symbol == "FAIL":
            raise DomainError(
                "provider_unavailable", "Deterministic provider failure.", status_code=502
            )
        fixture_name = "spy.json" if asset_type == "etf" else "acdc.json"
        payload = json.loads(files("stock_probs.fixtures").joinpath(fixture_name).read_text())
        seed = payload["daily_seed"]
        zone = ZoneInfo(payload["timezone"])
        session_date = datetime.fromisoformat(seed["start"]).astimezone(zone).date()
        daily: list[Bar] = []
        price = float(seed["price"])
        while len(daily) < int(seed["count"]):
            session_close = scheduled_session_close(session_date, payload["timezone"])
            if session_close is not None:
                price *= 1.0 + seed["step_pattern"][len(daily) % len(seed["step_pattern"])]
                daily.append(Bar(session_close, round(price, 6), 0))
            session_date += timedelta(days=1)
        intraday: list[Bar] = []
        price = float(payload["intraday_price"])
        for session_index, session in enumerate(payload["intraday_sessions"]):
            start = datetime.combine(datetime.fromisoformat(session).date(), time(9, 30), zone)
            for index in range(78):
                # Trend plus session offset yields reproducible non-degenerate samples.
                close = price * (
                    1.0 + session_index * 0.001 + index * 0.00012 + ((index % 7) - 3) * 0.00003
                )
                intraday.append(Bar(start + timedelta(minutes=5 * index), round(close, 6), 300))
        # A fixture response may contain the active bar but never bars that have not started yet.
        intraday = [bar for bar in intraday if bar.timestamp.astimezone(UTC) <= now.astimezone(UTC)]
        if symbol == "STALE":
            # Browser regressions need a deterministic stale success, not a fabricated failure.
            cutoff = datetime(2025, 1, 9, tzinfo=zone).date()
            intraday = [bar for bar in intraday if bar.timestamp.astimezone(zone).date() < cutoff]
        return MarketData(
            symbol=symbol,
            asset_type=asset_type,
            exchange=payload["exchange"],
            timezone=payload["timezone"],
            currency=payload["currency"],
            fetched_at=now.astimezone(UTC),
            query={
                "fixture": fixture_name,
                "requested_as_of": now.astimezone(UTC).isoformat(),
                "daily": "1d/2y",
                "intraday": "5m/5d",
            },
            daily=tuple(daily),
            intraday=tuple(intraday),
            provider_metadata={
                **payload["provider_metadata"],
                "fixture_contract": "compact-seed-v1",
                "daily_coverage": _coverage(tuple(daily)),
                "intraday_coverage": _coverage(tuple(intraday)),
                "missing_daily_closes": 0,
                "missing_daily_sessions": 0,
                "missing_intraday_closes": 0,
                "missing_intraday_intervals": 0,
                "trailing_missing_intraday_intervals": 0,
            },
        )


def _positive_finite(value: Any) -> bool:
    """Reject NaN and infinity before they can enter fingerprints or calculations."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number > 0 and number != float("inf") and number != float("-inf")


def _coverage(bars: tuple[Bar, ...]) -> dict[str, str | int | None]:
    """Record returned bounds without exposing dataframe implementation details."""

    return {
        "first": bars[0].timestamp.isoformat() if bars else None,
        "last": bars[-1].timestamp.isoformat() if bars else None,
        "count": len(bars),
    }


def _missing_intraday_intervals(bars: tuple[Bar, ...], timezone: str) -> int:
    """Count same-session five-minute gaps without treating overnight closure as missing."""

    zone = ZoneInfo(timezone)
    missing = 0
    for previous, current in zip(bars, bars[1:], strict=False):
        previous_local = previous.timestamp.astimezone(zone)
        current_local = current.timestamp.astimezone(zone)
        if previous_local.date() != current_local.date():
            continue
        seconds = (current.timestamp - previous.timestamp).total_seconds()
        if seconds > 300:
            missing += max(0, int(seconds // 300) - 1)
    return missing


def _missing_daily_sessions(bars: tuple[Bar, ...], timezone: str) -> int:
    """Count omitted scheduled closes between returned daily coverage bounds."""

    if len(bars) < 2:
        return 0
    zone = ZoneInfo(timezone)
    observed = {bar.timestamp.astimezone(zone).date() for bar in bars}
    day = min(observed)
    final_day = max(observed)
    missing = 0
    while day <= final_day:
        if scheduled_session_close(day, timezone) is not None and day not in observed:
            missing += 1
        day += timedelta(days=1)
    return missing


def _latest_scheduled_completed_end(now: datetime, timezone: str) -> datetime | None:
    """Resolve the most recent five-minute boundary eligible under the versioned calendar."""

    zone = ZoneInfo(timezone)
    local_now = now.astimezone(zone)
    day = local_now.date()
    for _ in range(15):
        close = scheduled_session_close(day, timezone)
        if close is not None:
            session_open = datetime.combine(day, time(9, 30), zone)
            if day < local_now.date():
                return close
            elapsed = (min(local_now, close) - session_open).total_seconds()
            completed_intervals = max(0, int(elapsed // 300))
            if completed_intervals:
                return session_open + timedelta(seconds=completed_intervals * 300)
        day -= timedelta(days=1)
    return None


def _trailing_missing_intraday_intervals(
    bars: tuple[Bar, ...], timezone: str, now: datetime
) -> int:
    """Count eligible regular-session bars omitted after the latest completed response bar."""

    expected_end = _latest_scheduled_completed_end(now, timezone)
    if expected_end is None:
        return 0
    zone = ZoneInfo(timezone)
    completed_regular = []
    for bar in bars:
        local = bar.timestamp.astimezone(zone)
        close = scheduled_session_close(local.date(), timezone)
        session_open = datetime.combine(local.date(), time(9, 30), zone)
        if (
            close is not None
            and session_open <= local
            and bar.end <= close
            and bar.end.astimezone(UTC) <= now.astimezone(UTC)
        ):
            completed_regular.append(bar)
    if not completed_regular:
        return 0
    latest_end = max(bar.end for bar in completed_regular)
    if latest_end.astimezone(UTC) >= expected_end.astimezone(UTC):
        return 0

    # Count only scheduled five-minute endpoints after the returned bar, never closed periods.
    missing = 0
    day = latest_end.astimezone(zone).date()
    expected_day = expected_end.astimezone(zone).date()
    while day <= expected_day:
        close = scheduled_session_close(day, timezone)
        if close is not None:
            session_open = datetime.combine(day, time(9, 30), zone)
            lower = max(session_open, latest_end) if day == latest_end.date() else session_open
            upper = min(close, expected_end) if day == expected_day else close
            if upper > lower:
                missing += int((upper - lower).total_seconds() // 300)
        day += timedelta(days=1)
    return missing


def _provider_epoch(value: Any) -> float:
    """Normalize yfinance's version-dependent integer/datetime session boundaries."""

    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise DomainError(
                "ambiguous_provider_time",
                "Yahoo returned session boundaries without a timezone.",
                status_code=502,
            )
        return value.timestamp()
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise DomainError(
            "provider_metadata_unavailable",
            "Yahoo returned invalid regular-session boundaries.",
            status_code=502,
        ) from exc
