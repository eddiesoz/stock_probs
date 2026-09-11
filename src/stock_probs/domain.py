"""Provider-neutral market records and deterministic forecast calculations."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import unicodedata
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

MODEL_VERSION = "empirical-ewma-v1"
FLAT_THRESHOLD = 0.001
# Report symmetric tail magnitudes in increasing severity so monotonicity is auditable.
TAIL_MAGNITUDES = (0.01, 0.03, 0.05, 0.10)
RETURN_THRESHOLDS = tuple(-value for value in TAIL_MAGNITUDES) + TAIL_MAGNITUDES
SUPPORTED_TIMEZONE = "America/New_York"
CALENDAR_VERSION = "us-equities-rules-v1"
SUPPORTED_ASSET_TYPES = {"stock", "etf"}
QUOTE_TYPE_TO_ASSET = {"EQUITY": "stock", "STOCK": "stock", "ETF": "etf"}


class DomainError(Exception):
    """A safe, classified failure that the API may expose without provider internals."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        request_id: str | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.request_id = request_id


def normalize_lookup_query(value: str) -> str:
    """Bound a company/symbol query while retaining ordinary Unicode company names."""

    if not isinstance(value, str) or any(
        unicodedata.category(character).startswith("C") for character in value
    ):
        raise DomainError(
            "invalid_lookup_query",
            "Use 1-80 visible characters for a symbol or company name.",
        )
    query = " ".join(value.strip().split())
    if not 1 <= len(query) <= 80:
        raise DomainError(
            "invalid_lookup_query",
            "Use 1-80 visible characters for a symbol or company name.",
        )
    return query


@dataclass(frozen=True)
class InstrumentIdentity:
    """One provider-resolved identity contract shared by stocks and ETFs."""

    canonical_symbol: str
    display_name: str
    company_name: str
    exchange: str
    currency: str
    timezone: str
    quote_type: str
    asset_type: str
    provider: str
    provider_as_of: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_symbol, str) or not isinstance(self.timezone, str):
            raise DomainError(
                "invalid_instrument_identity",
                "The provider returned an incomplete or invalid instrument identity.",
                status_code=502,
            )
        try:
            normalized_symbol = normalize_symbol(self.canonical_symbol)
            ZoneInfo(self.timezone)
        except (DomainError, KeyError, ValueError) as exc:
            raise DomainError(
                "invalid_instrument_identity",
                "The provider returned an incomplete or invalid instrument identity.",
                status_code=502,
            ) from exc
        text_fields = {
            "display_name": (self.display_name, 200),
            "company_name": (self.company_name, 200),
            "exchange": (self.exchange, 40),
            "currency": (self.currency, 12),
            "provider": (self.provider, 80),
        }
        unsafe_text = any(
            not isinstance(value, str)
            or value != value.strip()
            or not value
            or len(value) > maximum
            or any(unicodedata.category(character).startswith("C") for character in value)
            for value, maximum in text_fields.values()
        )
        normalized_quote_type = (
            self.quote_type.strip().upper() if isinstance(self.quote_type, str) else ""
        )
        if (
            normalized_symbol != self.canonical_symbol
            or unsafe_text
            or self.quote_type != normalized_quote_type
            or QUOTE_TYPE_TO_ASSET.get(normalized_quote_type) != self.asset_type
            or not isinstance(self.provider_as_of, datetime)
            or self.provider_as_of.tzinfo is None
        ):
            raise DomainError(
                "invalid_instrument_identity",
                "The provider returned an incomplete or invalid instrument identity.",
                status_code=502,
            )

    def as_dict(self) -> dict[str, str]:
        """Serialize the exact identity fields used by transport and immutable provenance."""

        return {
            "canonical_symbol": self.canonical_symbol,
            "display_name": self.display_name,
            "company_name": self.company_name,
            "exchange": self.exchange,
            "currency": self.currency,
            "timezone": self.timezone,
            "quote_type": self.quote_type,
            "asset_type": self.asset_type,
            "provider": self.provider,
            "provider_as_of": self.provider_as_of.isoformat(),
        }

    def fingerprint(self) -> str:
        """Give persistence a stable identity component without database-specific fields."""

        payload = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class Bar:
    """A provider bar timestamp denotes its start; duration determines completion."""

    timestamp: datetime
    close: float
    duration_seconds: int

    @property
    def end(self) -> datetime:
        return self.timestamp + timedelta(seconds=self.duration_seconds)


@dataclass(frozen=True)
class MarketData:
    """Normalized provider snapshot needed to reproduce both forecast horizons."""

    symbol: str
    display_name: str
    company_name: str
    asset_type: str
    quote_type: str
    exchange: str
    timezone: str
    currency: str
    provider: str
    fetched_at: datetime
    query: dict[str, Any]
    daily: tuple[Bar, ...]
    intraday: tuple[Bar, ...]
    provider_metadata: dict[str, Any]

    @property
    def identity(self) -> InstrumentIdentity:
        """Expose the same complete identity contract returned by provider lookup."""

        return InstrumentIdentity(
            canonical_symbol=self.symbol,
            display_name=self.display_name,
            company_name=self.company_name,
            exchange=self.exchange,
            currency=self.currency,
            timezone=self.timezone,
            quote_type=self.quote_type,
            asset_type=self.asset_type,
            provider=self.provider,
            provider_as_of=self.fetched_at,
        )

    def fingerprint(self) -> str:
        # Hash only normalized immutable content, not incidental object representation.
        payload = {
            "symbol": self.symbol,
            "display_name": self.display_name,
            "company_name": self.company_name,
            "asset_type": self.asset_type,
            "quote_type": self.quote_type,
            "exchange": self.exchange,
            "timezone": self.timezone,
            "currency": self.currency,
            "provider": self.provider,
            "fetched_at": self.fetched_at.isoformat(),
            "query": self.query,
            "daily": [
                (b.timestamp.isoformat(), b.close, b.duration_seconds) for b in self.daily
            ],
            "intraday": [
                (b.timestamp.isoformat(), b.close, b.duration_seconds) for b in self.intraday
            ],
            "metadata": self.provider_metadata,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def normalize_symbol(value: str) -> str:
    """Accept Yahoo-style symbols while excluding URL/control syntax and oversized input."""

    symbol = value.strip().upper()
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-^")
    if not 1 <= len(symbol) <= 15 or any(char not in allowed for char in symbol):
        raise DomainError("invalid_symbol", "Use 1-15 letters, numbers, '.', '-', or '^'.")
    return symbol


def _observed_holiday(day: date) -> date:
    """Apply the Saturday/Friday and Sunday/Monday US exchange observation rule."""

    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (occurrence - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    next_month = date(year + (month == 12), month % 12 + 1, 1)
    candidate = next_month - timedelta(days=1)
    return candidate - timedelta(days=(candidate.weekday() - weekday) % 7)


def _easter_sunday(year: int) -> date:
    """Use the Gregorian computus so Good Friday needs no calendar dependency."""

    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = (h + ell - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _us_exchange_holidays(year: int) -> set[date]:
    """Return scheduled full-day US equity closures around the requested year."""

    holidays: set[date] = set()
    # Include adjacent New Year's observations because they can land in December.
    for holiday_year in (year, year + 1):
        holidays.add(_observed_holiday(date(holiday_year, 1, 1)))
    holidays.update(
        {
            _nth_weekday(year, 1, 0, 3),
            _nth_weekday(year, 2, 0, 3),
            _easter_sunday(year) - timedelta(days=2),
            _last_weekday(year, 5, 0),
            _observed_holiday(date(year, 7, 4)),
            _nth_weekday(year, 9, 0, 1),
            _nth_weekday(year, 11, 3, 4),
            _observed_holiday(date(year, 12, 25)),
        }
    )
    if year >= 2022:
        holidays.add(_observed_holiday(date(year, 6, 19)))
    return holidays


def scheduled_session_close(day: date, timezone: str) -> datetime | None:
    """Resolve supported US sessions, including common scheduled 13:00 closes."""

    if timezone != SUPPORTED_TIMEZONE:
        raise DomainError(
            "unsupported_market",
            "Forecast session rules currently support America/New_York US equities only.",
        )
    if day.weekday() >= 5 or day in _us_exchange_holidays(day.year):
        return None
    thanksgiving = _nth_weekday(day.year, 11, 3, 4)
    early_close = (
        day == thanksgiving + timedelta(days=1)
        or (day.month == 7 and day.day == 3 and day.weekday() < 4)
        or (day.month == 12 and day.day == 24 and day.weekday() < 4)
    )
    return datetime.combine(day, time(13 if early_close else 16, 0), ZoneInfo(timezone))


def _next_session_close(origin: datetime, timezone: str) -> datetime:
    """Choose the next scheduled US close rather than silently targeting a holiday."""

    day = origin.astimezone(ZoneInfo(timezone)).date() + timedelta(days=1)
    for _ in range(15):
        close = scheduled_session_close(day, timezone)
        if close is not None:
            return close
        day += timedelta(days=1)
    raise DomainError("calendar_unavailable", "No supported market close was found within 15 days.")


def _provider_session_bounds(
    data: MarketData, day: date
) -> tuple[datetime, datetime] | None:
    """Use Yahoo's response-period boundaries only when both match the requested day."""

    zone = ZoneInfo(data.timezone)
    regular = data.provider_metadata.get("regular_session", {})
    try:
        provider_start = datetime.fromtimestamp(
            float(regular.get("start", 0)), UTC
        ).astimezone(zone)
        provider_end = datetime.fromtimestamp(float(regular.get("end", 0)), UTC).astimezone(zone)
    except (OSError, OverflowError, TypeError, ValueError):
        provider_start = provider_end = datetime.min.replace(tzinfo=zone)
    if provider_start.date() == day == provider_end.date() and provider_end > provider_start:
        return provider_start, provider_end
    return None


def _session_close(data: MarketData, day: date) -> datetime | None:
    """Prefer Yahoo's exact current close, then use the versioned scheduled calendar."""

    bounds = _provider_session_bounds(data, day)
    return bounds[1] if bounds is not None else scheduled_session_close(day, data.timezone)


def _session_open(data: MarketData, day: date) -> datetime | None:
    """Pair provider current-session start with a scheduled 09:30 historical fallback."""

    bounds = _provider_session_bounds(data, day)
    if bounds is not None:
        return bounds[0]
    close = scheduled_session_close(day, data.timezone)
    if close is None:
        return None
    return datetime.combine(day, time(9, 30), ZoneInfo(data.timezone))


def _request_session_state(data: MarketData, now: datetime) -> str:
    """Classify the request against explicit local regular-session boundaries."""

    local_now = now.astimezone(ZoneInfo(data.timezone))
    session_open = _session_open(data, local_now.date())
    session_close = _session_close(data, local_now.date())
    if session_open is None or session_close is None:
        return "closed_session_day"
    if local_now < session_open:
        return "pre_session"
    if local_now < session_close:
        return "open"
    return "post_session"


def _quantile(values: list[float], probability: float) -> float:
    """Linear interpolation avoids adding a numeric dependency for tiny bounded samples."""

    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _ewma_adjusted(returns: list[float], span: int = 30) -> list[float]:
    """Scale each observation using volatility known before it, preventing look-ahead leakage."""

    if len(returns) < 3:
        return returns
    alpha = 2.0 / (span + 1.0)
    variance = returns[0] ** 2
    adjusted: list[float] = []
    for value in returns[1:]:
        prior_sigma = max(math.sqrt(variance), 1e-6)
        adjusted.append(value / prior_sigma)
        variance = alpha * value**2 + (1.0 - alpha) * variance
    current_sigma = max(math.sqrt(variance), statistics.pstdev(returns), 1e-6)
    return [max(min(value * current_sigma, 0.5), -0.5) for value in adjusted]


def _distribution(samples: list[float], origin_price: float) -> dict[str, Any]:
    """Build smoothed empirical probabilities and explicit return/price intervals."""

    if len(samples) < 3:
        raise DomainError(
            "insufficient_data", "At least three historical horizon samples are required."
        )
    if not math.isfinite(origin_price) or origin_price <= 0:
        raise DomainError("invalid_market_data", "The forecast origin price must be positive.")
    if any(not math.isfinite(value) for value in samples):
        raise DomainError("invalid_market_data", "Historical returns contain non-finite values.")
    count = len(samples)

    def probability(predicate: Any) -> float:
        # Jeffreys-style smoothing prevents false certainty with small intraday samples.
        return (sum(1 for value in samples if predicate(value)) + 0.5) / (count + 1.0)

    down = probability(lambda value: value < -FLAT_THRESHOLD)
    flat = probability(lambda value: -FLAT_THRESHOLD <= value <= FLAT_THRESHOLD)
    up = probability(lambda value: value > FLAT_THRESHOLD)
    total = down + flat + up
    intervals = []
    for level, low_q, high_q in ((0.50, 0.25, 0.75), (0.80, 0.10, 0.90), (0.95, 0.025, 0.975)):
        low = _quantile(samples, low_q)
        high = _quantile(samples, high_q)
        intervals.append(
            {
                "level": level,
                "definition": f"central empirical {level:.0%} interval",
                "percent": {"low": low * 100.0, "high": high * 100.0, "unit": "percent_return"},
                "price": {
                    "low": origin_price * (1.0 + low),
                    "high": origin_price * (1.0 + high),
                    "unit": "quote_currency",
                },
            }
        )
    return {
        "direction_probabilities": {
            "down": down / total,
            "flat": flat / total,
            "up": up / total,
            "unit": "probability",
            "definitions": {
                "down": f"return < {-FLAT_THRESHOLD * 100.0:.1f}%",
                "flat": f"absolute return <= {FLAT_THRESHOLD * 100.0:.1f}%",
                "up": f"return > {FLAT_THRESHOLD * 100.0:.1f}%",
            },
            # Preserve the original field consumed by the current presentation layer.
            "flat_definition": f"absolute return <= {FLAT_THRESHOLD:.4f}",
        },
        "threshold_probabilities": [
            {
                "operator": "lte" if threshold < 0 else "gte",
                "threshold": threshold * 100.0,
                "unit": "percent_return",
                "definition": (
                    f"probability return <= {threshold * 100.0:.0f}%"
                    if threshold < 0
                    else f"probability return >= +{threshold * 100.0:.0f}%"
                ),
                "probability": probability(
                    (lambda value, t=threshold: value <= t)
                    if threshold < 0
                    else (lambda value, t=threshold: value >= t)
                ),
            }
            for threshold in RETURN_THRESHOLDS
        ],
        "magnitude_intervals": intervals,
        "sample_size": count,
        "distribution_definition": (
            "empirical historical horizon returns standardized by prior-only EWMA volatility "
            "and rescaled to volatility known at the request cutoff"
        ),
    }


def _validated_bars(
    bars: tuple[Bar, ...], *, duration_seconds: int, now: datetime, timezone: str
) -> list[Bar]:
    """Canonicalize provider rows while rejecting ambiguous timestamps and bar widths."""

    zone = ZoneInfo(timezone)
    selected: dict[datetime, Bar] = {}
    for bar in bars:
        if bar.timestamp.tzinfo is None:
            raise DomainError("ambiguous_provider_time", "Market bars must include a timezone.")
        if bar.duration_seconds != duration_seconds:
            raise DomainError(
                "provider_interval_mismatch",
                "Market bars do not match the requested interval.",
                status_code=502,
            )
        if not math.isfinite(bar.close) or bar.close <= 0:
            continue
        # UTC keys make duplicate instants deterministic even across offset representations.
        instant = bar.timestamp.astimezone(UTC)
        selected[instant] = Bar(bar.timestamp.astimezone(zone), bar.close, bar.duration_seconds)
    return sorted(
        (bar for bar in selected.values() if bar.end.astimezone(UTC) <= now),
        key=lambda item: item.timestamp,
    )


def _bar_payload(bar: Bar) -> dict[str, Any]:
    """Serialize exact bar boundaries rather than relying on JSON's datetime fallback."""

    return {
        "timestamp": bar.timestamp.isoformat(),
        "end": bar.end.isoformat(),
        "close": bar.close,
        "duration_seconds": bar.duration_seconds,
    }


def _regular_intraday_bars(data: MarketData, now: datetime) -> list[Bar]:
    """Return only completed, exact-width bars inside a supported regular session."""

    candidates = []
    for bar in _validated_bars(
        data.intraday, duration_seconds=300, now=now, timezone=data.timezone
    ):
        local = bar.timestamp
        open_at = _session_open(data, local.date())
        close = _session_close(data, local.date())
        if open_at is not None and close is not None and open_at <= local and bar.end <= close:
            candidates.append(bar)
    return candidates


def _latest_completed_intraday(data: MarketData, now: datetime) -> Bar:
    """Exclude in-progress and non-regular-session bars using exchange-local boundaries."""

    zone = ZoneInfo(data.timezone)
    local_now = now.astimezone(zone)
    if data.timezone != SUPPORTED_TIMEZONE:
        raise DomainError(
            "unsupported_market",
            "Forecast session rules currently support America/New_York US equities only.",
        )
    candidates = _regular_intraday_bars(data, now)
    if not candidates:
        raise DomainError(
            "insufficient_intraday_data", "No completed regular-session 5-minute bar is available."
        )
    latest = max(candidates, key=lambda item: item.timestamp)
    if latest.timestamp.astimezone(zone).date() < local_now.date() - timedelta(days=7):
        raise DomainError(
            "stale_data", "The latest completed intraday bar is more than seven days old."
        )
    return latest


def _missing_scheduled_daily_sessions(bars: list[Bar], timezone: str) -> int:
    """Detect omitted trading dates without treating weekends or holidays as missing data."""

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


def _latest_eligible_intraday_end(data: MarketData, now: datetime) -> datetime | None:
    """Return the latest regular-session boundary that should have a completed five-minute bar."""

    zone = ZoneInfo(data.timezone)
    local_now = now.astimezone(zone)
    day = local_now.date()
    for _ in range(15):
        session_open = _session_open(data, day)
        session_close = _session_close(data, day)
        if session_open is not None and session_close is not None:
            if day < local_now.date():
                return session_close
            # Flooring elapsed regular-session time excludes an active partial bar at the cutoff.
            elapsed = (min(local_now, session_close) - session_open).total_seconds()
            completed_intervals = max(0, int(elapsed // 300))
            if completed_intervals:
                return session_open + timedelta(seconds=completed_intervals * 300)
        day -= timedelta(days=1)
    return None


def calculate_forecasts(
    data: MarketData, now: datetime
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return one immutable shared input snapshot and two fully described results."""

    if now.tzinfo is None or data.fetched_at.tzinfo is None:
        raise DomainError(
            "ambiguous_provider_time", "Request and provider times must include offsets."
        )
    now = now.astimezone(UTC)
    if data.asset_type not in SUPPORTED_ASSET_TYPES:
        raise DomainError("unsupported_asset", "Only Yahoo Finance stocks and ETFs are supported.")
    identity = data.identity
    try:
        ZoneInfo(data.timezone)
    except (KeyError, ValueError) as exc:
        raise DomainError(
            "ambiguous_provider_time", "Provider timezone is not recognized."
        ) from exc
    # A daily row represents an instantaneous completed session close in this contract.
    completed_daily = _validated_bars(
        data.daily, duration_seconds=0, now=now, timezone=data.timezone
    )
    if len(completed_daily) < 61:
        raise DomainError(
            "insufficient_daily_data", "At least 61 completed daily closes are required."
        )
    daily_origin = completed_daily[-1]
    raw_daily = [
        current.close / previous.close - 1.0
        for previous, current in zip(completed_daily[:-1], completed_daily[1:], strict=False)
    ][-504:]
    daily_samples = _ewma_adjusted(raw_daily)

    regular_intraday = _regular_intraday_bars(data, now)
    latest = _latest_completed_intraday(data, now)
    zone = ZoneInfo(data.timezone)
    origin_local = latest.timestamp.astimezone(zone)
    origin_session_close = _session_close(data, origin_local.date())
    if origin_session_close is None:
        raise DomainError(
            "ambiguous_session", "The selected intraday bar is not in a trading session."
        )
    request_session_state = _request_session_state(data, now)
    is_open_session_horizon = (
        request_session_state == "open"
        and origin_local.date() == now.astimezone(zone).date()
        and latest.end < origin_session_close
    )
    target = (
        origin_session_close
        if is_open_session_horizon
        else _next_session_close(latest.timestamp, data.timezone)
    )
    if not is_open_session_horizon and latest.end != origin_session_close:
        # Outside an open session, a partial old session would change the horizon length.
        raise DomainError(
            "incomplete_session_data",
            "The latest available five-minute bar is not the completed session-close bar.",
        )

    # Previous sessions contribute only bars at the same or later clock time and their known close.
    sessions: dict[str, list[Bar]] = {}
    for bar in regular_intraday:
        if bar.timestamp >= latest.timestamp:
            continue
        key = bar.timestamp.astimezone(zone).date().isoformat()
        sessions.setdefault(key, []).append(bar)
    intraday_raw: list[float] = []
    for bars in sessions.values():
        ordered = sorted(bars, key=lambda item: item.timestamp)
        comparable = [
            bar for bar in ordered if bar.timestamp.astimezone(zone).time() == origin_local.time()
        ]
        session_close = _session_close(data, ordered[-1].timestamp.astimezone(zone).date())
        final_bar_start = (
            (session_close - timedelta(minutes=5)).timetz().replace(tzinfo=None)
            if session_close is not None
            else None
        )
        final_time = ordered[-1].timestamp.astimezone(zone).time()
        if comparable and final_bar_start and final_time >= final_bar_start:
            intraday_raw.append(ordered[-1].close / comparable[-1].close - 1.0)
    # Outside an open session, the completed bar is the prior close and the applicable
    # target is the next close, so close-to-close samples are the matching history.
    intraday_samples = (
        _ewma_adjusted(intraday_raw, span=10) if is_open_session_horizon else daily_samples
    )

    daily_target = _next_session_close(daily_origin.timestamp, data.timezone)
    stale_reasons = []
    # A normal weekend is not stale: data is stale only once its own next target has elapsed.
    if daily_target.astimezone(UTC) < now:
        stale_reasons.append("daily origin's next scheduled close elapsed before the request")
    if target.astimezone(UTC) < now:
        stale_reasons.append("intraday origin's applicable close elapsed before the request")
    provider_age = now - data.fetched_at.astimezone(UTC)
    if provider_age > timedelta(minutes=15):
        stale_reasons.append(
            "provider response is more than fifteen minutes older than the request"
        )
    missing_daily_closes = int(data.provider_metadata.get("missing_daily_closes", 0) or 0)
    if missing_daily_closes:
        stale_reasons.append(
            f"provider data contains {missing_daily_closes} missing daily closes"
        )
    # Recompute from selected bars so stale provider metadata cannot hide an omitted session.
    missing_daily_sessions = max(
        int(data.provider_metadata.get("missing_daily_sessions", 0) or 0),
        _missing_scheduled_daily_sessions(completed_daily, data.timezone),
    )
    if missing_daily_sessions:
        stale_reasons.append(
            f"daily history omits {missing_daily_sessions} scheduled session closes"
        )
    missing_intraday = int(data.provider_metadata.get("missing_intraday_closes", 0) or 0) + int(
        data.provider_metadata.get("missing_intraday_intervals", 0) or 0
    ) + int(data.provider_metadata.get("trailing_missing_intraday_intervals", 0) or 0)
    if missing_intraday:
        stale_reasons.append(f"provider data contains {missing_intraday} missing intraday bars")
    latest_eligible_end = _latest_eligible_intraday_end(data, now)
    if (
        latest_eligible_end is not None
        and latest.end.astimezone(UTC) < latest_eligible_end.astimezone(UTC)
    ):
        # This catches a truncated response even when no pair of returned bars exposes a gap.
        stale_reasons.append(
            "latest completed intraday bar precedes the latest eligible five-minute boundary"
        )
    quality = "stale" if stale_reasons else "current"
    common = {
        "symbol": data.symbol,
        "canonical_symbol": identity.canonical_symbol,
        "display_name": identity.display_name,
        "company_name": identity.company_name,
        "asset_type": data.asset_type,
        "quote_type": identity.quote_type,
        "exchange": data.exchange,
        "exchange_timezone": data.timezone,
        "currency": data.currency,
        "instrument_identity": identity.as_dict(),
        "identity_fingerprint": identity.fingerprint(),
        "provider": data.provider,
        "provider_as_of": data.fetched_at.isoformat(),
        "request_cutoff": now.isoformat(),
        "provider_query": data.query,
        "provider_metadata": data.provider_metadata,
        "content_fingerprint": data.fingerprint(),
        "captured_at": now.isoformat(),
        "selected_daily_bars": [_bar_payload(bar) for bar in completed_daily[-505:]],
        "selected_intraday_bars": [_bar_payload(bar) for bar in regular_intraday],
        "session_rule": (
            "America/New_York regular sessions only; a five-minute bar is completed when "
            "bar start plus 300 seconds is at or before the request cutoff"
        ),
        "calendar": {
            "name": "scheduled US equity sessions",
            "version": CALENDAR_VERSION,
            "timezone": SUPPORTED_TIMEZONE,
        },
        "limitations": [
            "Scheduled US holidays and common early closes are modeled; "
            "unscheduled closures are not.",
            "Empirical intervals describe historical sample coverage, not guaranteed confidence.",
        ],
        "quality": quality,
        "quality_reasons": stale_reasons,
        "stale_state": {"state": quality, "reasons": stale_reasons},
        "session_state_at_request": request_session_state,
        "model": {"name": "volatility-adjusted empirical distribution", "version": MODEL_VERSION},
        "parameters": {
            "daily_max_samples": 504,
            "ewma_span_daily": 30,
            "ewma_span_intraday": 10,
            "flat_threshold": FLAT_THRESHOLD,
            "return_thresholds_percent": [value * 100.0 for value in RETURN_THRESHOLDS],
        },
        "provenance": {
            "source": data.provider,
            "query": data.query,
            "response_as_of": data.fetched_at.isoformat(),
            "content_fingerprint": data.fingerprint(),
            "instrument_identity": identity.as_dict(),
            "identity_fingerprint": identity.fingerprint(),
            "model_version": MODEL_VERSION,
            "calendar_version": CALENDAR_VERSION,
        },
    }
    daily_result = {
        "horizon": "close_to_close",
        "origin_timestamp": daily_origin.timestamp.isoformat(),
        "origin_price": daily_origin.close,
        "reference_timestamp": daily_origin.timestamp.isoformat(),
        "reference_state": "completed_session_close",
        "target_timestamp": daily_target.isoformat(),
        "target_state": "scheduled_session_close",
        "exchange_timezone": data.timezone,
        "stale_state": quality,
        "calculated_at": now.isoformat(),
        "definition": "latest completed regular-session close to the next regular-session close",
        **_distribution(daily_samples, daily_origin.close),
    }
    intraday_result = {
        "horizon": "completed_5m_to_close",
        "origin_timestamp": latest.timestamp.isoformat(),
        "origin_bar_end": latest.end.isoformat(),
        "reference_timestamp": latest.end.isoformat(),
        "reference_state": "completed_five_minute_bar_close",
        "origin_price": latest.close,
        "target_timestamp": target.isoformat(),
        "target_state": "scheduled_session_close",
        "exchange_timezone": data.timezone,
        "session_state_at_request": request_session_state,
        "stale_state": quality,
        "calculated_at": now.isoformat(),
        "definition": "latest completed regular-session 5-minute bar to the applicable close",
        "target_session_rule": (
            "same-session close while the regular session is open; otherwise the next scheduled "
            "session close"
        ),
        **_distribution(intraday_samples, latest.close),
    }
    return common, [daily_result, intraday_result]


def label_fresh_historical_analysis(
    snapshot: dict[str, Any],
    results: list[dict[str, Any]],
    *,
    request_id: str,
    source_event_id: int,
    cutoff: datetime,
    performed_at: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Label a newly calculated historical cutoff without mutating calculated inputs."""

    if cutoff.tzinfo is None or performed_at.tzinfo is None:
        raise DomainError(
            "ambiguous_historical_cutoff",
            "Historical cutoff and analysis timestamps must include an offset.",
        )
    if type(source_event_id) is not int or source_event_id < 1:
        raise DomainError(
            "invalid_historical_source", "A positive saved history event is required."
        )
    labelled_snapshot = deepcopy(snapshot)
    labelled_results = deepcopy(results)
    provider_fingerprint = str(labelled_snapshot["content_fingerprint"])
    analysis: dict[str, Any] = {
        "kind": "fresh_historical_reconstruction",
        "label": "Fresh historical-cutoff analysis",
        "source_event_id": source_event_id,
        "requested_cutoff": cutoff.astimezone(UTC).isoformat(),
        "performed_at": performed_at.astimezone(UTC).isoformat(),
        "provider_content_fingerprint": provider_fingerprint,
    }
    # The request identifier makes every submitted fresh analysis an independent immutable
    # capture, while provider_content_fingerprint preserves source-data comparability.
    analysis_fingerprint = hashlib.sha256(
        f"{provider_fingerprint}\0{request_id}".encode()
    ).hexdigest()
    labelled_snapshot["content_fingerprint"] = analysis_fingerprint
    provider_query = dict(labelled_snapshot["provider_query"])
    provider_query["analysis"] = analysis
    labelled_snapshot["provider_query"] = provider_query
    provenance = dict(labelled_snapshot["provenance"])
    provenance.update(
        {
            "analysis": {
                key: value
                for key, value in analysis.items()
                if key != "provider_content_fingerprint"
            },
            "provider_content_fingerprint": provider_fingerprint,
            "content_fingerprint": analysis_fingerprint,
            "query": provider_query,
        }
    )
    labelled_snapshot["provenance"] = provenance
    return labelled_snapshot, labelled_results


def evaluate_outcome(
    result: dict[str, Any], observed_close: float | None, observed_at: datetime
) -> tuple[float | None, str]:
    """Validate a later observation against an immutable forecast horizon."""

    if observed_at.tzinfo is None:
        raise DomainError("invalid_outcome_time", "Outcome timestamps must include a timezone.")
    if observed_close is not None and (
        not math.isfinite(observed_close) or observed_close <= 0
    ):
        raise DomainError("invalid_outcome_price", "Observed closes must be positive and finite.")
    target = datetime.fromisoformat(str(result["target_timestamp"]))
    if observed_at.astimezone(UTC) < target.astimezone(UTC):
        raise DomainError(
            "outcome_before_target",
            "An outcome can be appended only after the forecast target close.",
        )
    observed_return = (
        observed_close / float(result["origin_price"]) - 1.0
        if observed_close is not None
        else None
    )
    return observed_return, "close divided by immutable origin price minus one"
