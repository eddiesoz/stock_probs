"""Provider-neutral market records and deterministic forecast calculations."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import statistics
import unicodedata
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

MODEL_VERSION = "empirical-ewma-v2"
FORECAST_CONTRACT_VERSION = "forecast-contract-v2"
EVALUATION_VERSION = "chronological-walk-forward-v1"
FLAT_THRESHOLD = 0.001
# Report symmetric tail magnitudes in increasing severity so monotonicity is auditable.
TAIL_MAGNITUDES = (0.01, 0.03, 0.05, 0.10)
RETURN_THRESHOLDS = tuple(-value for value in TAIL_MAGNITUDES) + TAIL_MAGNITUDES
SUPPORTED_TIMEZONE = "America/New_York"
CALENDAR_VERSION = "us-equities-rules-v1"
SUPPORTED_ASSET_TYPES = {"stock", "etf"}
QUOTE_TYPE_TO_ASSET = {"EQUITY": "stock", "STOCK": "stock", "ETF": "etf"}
MAX_ABSOLUTE_RETURN = 0.50
EVALUATION_MAX_POINTS = 120
RELIABILITY_BIN_COUNT = 5
HISTORY_SEMANTICS = {"success", "failure", "repeat", "fresh", "saved"}


@dataclass(frozen=True)
class HistoryFilters:
    """Storage-neutral, bounded filters shared by history list and export reads."""

    query: str = ""
    symbol: str | None = None
    company: str | None = None
    asset_type: str | None = None
    status: str | None = None
    semantics: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    model: str | None = None
    model_version: str | None = None
    request_id: str | None = None
    analysis_kind: str | None = None
    event_id: int | None = None

    def __post_init__(self) -> None:
        """Reject expensive or ambiguous filters before a query reaches an adapter."""

        limits = {
            "query": (self.query, 30, True),
            "company": (self.company, 200, False),
            "model": (self.model, 120, False),
            "model_version": (self.model_version, 80, False),
            "request_id": (self.request_id, 128, False),
        }
        for name, (value, maximum, empty_allowed) in limits.items():
            if value is None:
                continue
            if not isinstance(value, str) or len(value) > maximum:
                raise ValueError(f"history {name} must not exceed {maximum} characters")
            if not empty_allowed and not value.strip():
                raise ValueError(f"history {name} must not be empty")
            if any(unicodedata.category(character).startswith("C") for character in value):
                raise ValueError(f"history {name} contains unsupported control characters")
        if self.symbol is not None:
            if not isinstance(self.symbol, str):
                raise ValueError("history symbol is not supported")
            try:
                normalized = normalize_symbol(self.symbol)
            except DomainError as exc:
                raise ValueError("history symbol is not supported") from exc
            object.__setattr__(self, "symbol", normalized)
        for name in ("company", "model", "model_version", "request_id"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, value.strip())
        if self.asset_type not in {None, "stock", "etf"}:
            raise ValueError("history asset_type is not supported")
        if self.status not in {None, "successful", "failed", "repeated"}:
            raise ValueError("history status is not supported")
        if self.semantics not in {None, *HISTORY_SEMANTICS}:
            raise ValueError("history semantics is not supported")
        if self.analysis_kind not in {
            None,
            "submitted_forecast",
            "fresh_historical_reconstruction",
        }:
            raise ValueError("history analysis_kind is not supported")
        if self.event_id is not None and (
            type(self.event_id) is not int or not 1 <= self.event_id <= 2_147_483_647
        ):
            raise ValueError("history event_id is not supported")
        for name, timestamp in (("date_from", self.date_from), ("date_to", self.date_to)):
            if timestamp is not None and (
                not isinstance(timestamp, datetime) or timestamp.tzinfo is None
            ):
                raise ValueError(f"history {name} must include a timezone offset")
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_from.astimezone(UTC) > self.date_to.astimezone(UTC)
        ):
            raise ValueError("history date_from must not follow date_to")


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


def _safe_news_text(
    value: object, field: str, maximum: int, *, optional: bool = False
) -> str | None:
    """Reject control-bearing or unbounded provider text without inventing missing metadata."""

    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise DomainError(
            "provider_news_invalid",
            f"Yahoo Finance returned an invalid news {field}.",
            status_code=502,
        )
    text = value.strip()
    if (
        not text
        or len(text) > maximum
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise DomainError(
            "provider_news_invalid",
            f"Yahoo Finance returned an invalid news {field}.",
            status_code=502,
        )
    return text


def safe_news_url(value: object) -> str:
    """Allow display-only public HTTPS article links and reject local/userinfo destinations."""

    url = _safe_news_text(value, "URL", 2048)
    assert url is not None
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise DomainError(
            "provider_news_invalid",
            "Yahoo Finance returned an unsafe news URL.",
            status_code=502,
        ) from exc
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or host.casefold() == "localhost"
        or host.casefold().endswith(
            (".localhost", ".local", ".internal", ".lan", ".home", ".home.arpa")
        )
        or "." not in host
    ):
        raise DomainError(
            "provider_news_invalid",
            "Yahoo Finance returned an unsafe news URL.",
            status_code=502,
        )
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise DomainError(
                "provider_news_invalid",
                "Yahoo Finance returned an unsafe news URL.",
                status_code=502,
            )
    return url


@dataclass(frozen=True)
class NewsItem:
    """One provider-neutral headline; unavailable optional metadata remains absent."""

    id: str
    title: str
    publisher: str | None
    published_at: datetime | None
    url: str
    related_symbols: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        item_id = _safe_news_text(self.id, "identifier", 128)
        title = _safe_news_text(self.title, "headline", 500)
        publisher = _safe_news_text(self.publisher, "source", 200, optional=True)
        if self.published_at is not None and (
            not isinstance(self.published_at, datetime) or self.published_at.tzinfo is None
        ):
            raise DomainError(
                "provider_news_invalid",
                "Yahoo Finance returned an invalid news publication time.",
                status_code=502,
            )
        if self.related_symbols is not None and (
            not isinstance(self.related_symbols, tuple) or len(self.related_symbols) > 32
        ):
            raise DomainError(
                "provider_news_invalid",
                "Yahoo Finance returned invalid related news symbols.",
                status_code=502,
            )
        try:
            normalized_related = []
            for item in self.related_symbols or ():
                text = _safe_news_text(item, "related symbol", 32)
                assert text is not None
                normalized_related.append(text)
            related = (
                tuple(dict.fromkeys(normalized_related))
                if self.related_symbols is not None
                else None
            )
        except (DomainError, TypeError) as exc:
            raise DomainError(
                "provider_news_invalid",
                "Yahoo Finance returned invalid related news symbols.",
                status_code=502,
            ) from exc
        object.__setattr__(self, "id", item_id)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "publisher", publisher)
        object.__setattr__(
            self,
            "published_at",
            self.published_at.astimezone(UTC) if self.published_at is not None else None,
        )
        object.__setattr__(self, "url", safe_news_url(self.url))
        object.__setattr__(self, "related_symbols", related)

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "publisher": self.publisher,
            "published_at": (
                self.published_at.isoformat() if self.published_at is not None else None
            ),
            "url": self.url,
            "related_symbols": (
                list(self.related_symbols) if self.related_symbols is not None else None
            ),
        }


@dataclass(frozen=True)
class NewsData:
    """A bounded news response kept separate from forecast inputs and persistence."""

    symbol: str
    provider: str
    as_of: datetime
    items: tuple[NewsItem, ...]

    def __post_init__(self) -> None:
        symbol = normalize_symbol(self.symbol)
        provider = _safe_news_text(self.provider, "provider", 80)
        if (
            symbol != self.symbol
            or not isinstance(self.as_of, datetime)
            or self.as_of.tzinfo is None
            or not isinstance(self.items, tuple)
            or len(self.items) > 10
            or any(not isinstance(item, NewsItem) for item in self.items)
        ):
            raise DomainError(
                "provider_news_invalid",
                "Yahoo Finance returned an invalid news response.",
                status_code=502,
            )
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "as_of", self.as_of.astimezone(UTC))

    def as_dict(self, *, limit: int, cache_state: str) -> dict[str, object]:
        selected = self.items[:limit]
        return {
            "query": {"symbol": self.symbol, "limit": limit},
            "provider": self.provider,
            "as_of": self.as_of.isoformat(),
            "cache_state": cache_state,
            "items": [item.as_dict() for item in selected],
            "coverage": {
                "returned_count": len(selected),
                "partial_metadata": any(
                    item.publisher is None
                    or item.published_at is None
                    or item.related_symbols is None
                    for item in selected
                ),
                "refresh_failed": cache_state == "stale_fallback",
            },
        }


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
        return hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()


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

    if len(returns) <= 3:
        # Three observations is the explicit small-sample fallback. Estimating prior volatility
        # from fewer values would discard too much of Yahoo's bounded intraday history.
        return list(returns)
    alpha = 2.0 / (span + 1.0)
    variance = returns[0] ** 2
    adjusted: list[float] = []
    for value in returns[1:]:
        prior_sigma = max(math.sqrt(variance), 1e-6)
        adjusted.append(value / prior_sigma)
        variance = alpha * value**2 + (1.0 - alpha) * variance
    current_sigma = max(math.sqrt(variance), statistics.pstdev(returns), 1e-6)
    return [max(min(value * current_sigma, 0.5), -0.5) for value in adjusted]


def _prepare_model_samples(
    returns: list[float], *, span: int
) -> tuple[list[float], dict[str, Any]]:
    """Apply the versioned anomaly filter and prior-only volatility transformation."""

    if any(not math.isfinite(value) or value <= -1.0 for value in returns):
        raise DomainError("invalid_market_data", "Historical returns contain invalid values.")
    filtered = [value for value in returns if abs(value) < MAX_ABSOLUTE_RETURN]
    excluded = len(returns) - len(filtered)
    adjusted = _ewma_adjusted(filtered, span=span)
    return adjusted, {
        "candidate_count": len(returns),
        "eligible_count": len(filtered),
        "effective_count": len(adjusted),
        "excluded_anomaly_count": excluded,
        "warmup_excluded_count": len(filtered) - len(adjusted),
        "filter": {
            "version": "absolute-return-filter-v1",
            "rule": f"exclude absolute close return at least {MAX_ABSOLUTE_RETURN:.0%}",
            "purpose": (
                "avoid treating split, corporate-action, currency, or unit discontinuities "
                "as ordinary returns"
            ),
        },
    }


def _wilson_interval(successes: int, count: int) -> dict[str, float | str]:
    """Return a dependency-free 95% Wilson interval for an observed binary event rate."""

    if count < 1:
        return {"low": 0.0, "high": 1.0, "level": 0.95, "method": "Wilson score"}
    z = 1.959963984540054
    proportion = successes / count
    denominator = 1.0 + z * z / count
    center = (proportion + z * z / (2.0 * count)) / denominator
    radius = z * math.sqrt(
        proportion * (1.0 - proportion) / count + z * z / (4.0 * count * count)
    ) / denominator
    return {
        "low": max(0.0, center - radius),
        "high": min(1.0, center + radius),
        "level": 0.95,
        "method": "Wilson score for the unsmoothed empirical event rate",
    }


def _distribution(
    samples: list[float], origin_price: float, *, sample_accounting: dict[str, Any] | None = None
) -> dict[str, Any]:
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

    def event_summary(predicate: Any) -> dict[str, Any]:
        # Jeffreys-style smoothing prevents false certainty with small intraday samples.
        event_count = sum(1 for value in samples if predicate(value))
        return {
            "probability": (event_count + 0.5) / (count + 1.0),
            "event_count": event_count,
            "sample_count": count,
            "uncertainty": _wilson_interval(event_count, count),
        }

    down_summary = event_summary(lambda value: value < -FLAT_THRESHOLD)
    flat_summary = event_summary(lambda value: -FLAT_THRESHOLD <= value <= FLAT_THRESHOLD)
    up_summary = event_summary(lambda value: value > FLAT_THRESHOLD)
    down = float(down_summary["probability"])
    flat = float(flat_summary["probability"])
    up = float(up_summary["probability"])
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
    direction_probabilities = {
        "down": down / total,
        "flat": flat / total,
        # "flat" remains an API-compatible alias; unchanged is the canonical contract term.
        "unchanged": flat / total,
        "up": up / total,
        "unit": "probability",
        "definitions": {
            "down": f"return < {-FLAT_THRESHOLD * 100.0:.1f}%",
            "flat": f"absolute return <= {FLAT_THRESHOLD * 100.0:.1f}%",
            "unchanged": f"absolute return <= {FLAT_THRESHOLD * 100.0:.1f}%",
            "up": f"return > {FLAT_THRESHOLD * 100.0:.1f}%",
        },
        "event_counts": {
            "down": down_summary["event_count"],
            "unchanged": flat_summary["event_count"],
            "up": up_summary["event_count"],
            "sample_count": count,
        },
        "uncertainty": {
            "down": down_summary["uncertainty"],
            "unchanged": flat_summary["uncertainty"],
            "up": up_summary["uncertainty"],
        },
        # Preserve the original field consumed by the current presentation layer.
        "flat_definition": f"absolute return <= {FLAT_THRESHOLD:.4f}",
    }
    threshold_probabilities = []
    for threshold in RETURN_THRESHOLDS:
        summary = event_summary(
            (lambda value, t=threshold: value <= t)
            if threshold < 0
            else (lambda value, t=threshold: value >= t)
        )
        threshold_probabilities.append(
            {
                "operator": "lte" if threshold < 0 else "gte",
                "threshold": threshold * 100.0,
                "unit": "percent_return",
                "definition": (
                    f"probability return <= {threshold * 100.0:.0f}%"
                    if threshold < 0
                    else f"probability return >= +{threshold * 100.0:.0f}%"
                ),
                **summary,
                "rare_event": int(summary["event_count"]) < 10,
            }
        )

    gains = [value for value in samples if value > FLAT_THRESHOLD]
    losses = [-value for value in samples if value < -FLAT_THRESHOLD]

    def conditional(values: list[float], label: str) -> dict[str, Any]:
        return {
            "condition": label,
            "observed_count": len(values),
            "sample_count": count,
            "expected": statistics.fmean(values) * 100.0 if values else None,
            "median": statistics.median(values) * 100.0 if values else None,
            "unit": "percent_return_magnitude",
            "definition": "positive return magnitude conditional on the stated direction",
        }

    return {
        "direction_probabilities": direction_probabilities,
        "threshold_probabilities": threshold_probabilities,
        "conditional_magnitudes": {
            "gain": conditional(gains, f"return > {FLAT_THRESHOLD * 100.0:.1f}%"),
            "loss": conditional(losses, f"return < {-FLAT_THRESHOLD * 100.0:.1f}%"),
        },
        "magnitude_intervals": intervals,
        "sample_size": count,
        "sample_accounting": sample_accounting
        or {
            "candidate_count": count,
            "eligible_count": count,
            "effective_count": count,
            "excluded_anomaly_count": 0,
            "warmup_excluded_count": 0,
        },
        "probability_estimator": "Jeffreys add-one smoothing: (events + 0.5) / (samples + 1)",
        "distribution_definition": (
            "filtered historical horizon returns standardized by prior-only EWMA volatility "
            "and rescaled to volatility known at the request cutoff; interval endpoints are "
            "empirical interpolated quantiles of that effective sample"
        ),
    }


@dataclass(frozen=True)
class _HorizonObservation:
    """One realized horizon whose target outcome has an unambiguous availability time."""

    origin_at: datetime
    target_at: datetime
    origin_price: float
    return_value: float
    comparison_key: str


def _direction(value: float) -> str:
    if value < -FLAT_THRESHOLD:
        return "down"
    if value > FLAT_THRESHOLD:
        return "up"
    return "unchanged"


def _threshold_key(item: dict[str, Any]) -> str:
    return f"{item['operator']}:{float(item['threshold']):g}"


def _reliability_bins(pairs: list[tuple[float, int]]) -> list[dict[str, Any]]:
    """Aggregate fixed-width bins, retaining empty bins so reports have a stable schema."""

    bins = []
    for index in range(RELIABILITY_BIN_COUNT):
        low = index / RELIABILITY_BIN_COUNT
        high = (index + 1) / RELIABILITY_BIN_COUNT
        selected = [
            (probability, observed)
            for probability, observed in pairs
            if low <= probability <= high
            and (probability < high or index == RELIABILITY_BIN_COUNT - 1)
        ]
        bins.append(
            {
                "low": low,
                "high": high,
                "includes_high": index == RELIABILITY_BIN_COUNT - 1,
                "count": len(selected),
                "mean_predicted_probability": (
                    statistics.fmean(item[0] for item in selected) if selected else None
                ),
                "observed_frequency": (
                    statistics.fmean(item[1] for item in selected) if selected else None
                ),
            }
        )
    return bins


def _score_predictions(
    predictions: list[tuple[dict[str, Any], float]],
) -> dict[str, Any]:
    """Score direction, every threshold tail, reliability, and central interval coverage."""

    direction_pairs: dict[str, list[tuple[float, int]]] = {
        key: [] for key in ("down", "unchanged", "up")
    }
    threshold_pairs: dict[str, list[tuple[float, int]]] = {
        f"{'lte' if threshold < 0 else 'gte'}:{threshold * 100.0:g}": []
        for threshold in RETURN_THRESHOLDS
    }
    coverage: dict[float, list[bool]] = {0.50: [], 0.80: [], 0.95: []}
    for distribution, observed_return in predictions:
        observed_direction = _direction(observed_return)
        for direction in direction_pairs:
            direction_pairs[direction].append(
                (
                    float(distribution["direction_probabilities"][direction]),
                    int(direction == observed_direction),
                )
            )
        for item in distribution["threshold_probabilities"]:
            threshold = float(item["threshold"]) / 100.0
            observed = (
                observed_return <= threshold
                if item["operator"] == "lte"
                else observed_return >= threshold
            )
            threshold_pairs[_threshold_key(item)].append(
                (float(item["probability"]), int(observed))
            )
        for interval in distribution["magnitude_intervals"]:
            level = float(interval["level"])
            low = float(interval["percent"]["low"]) / 100.0
            high = float(interval["percent"]["high"]) / 100.0
            coverage[level].append(low <= observed_return <= high)

    direction_components = {
        direction: statistics.fmean(
            (probability - observed) ** 2 for probability, observed in pairs
        )
        for direction, pairs in direction_pairs.items()
    }
    return {
        "direction_brier": {
            "multiclass_mean": sum(direction_components.values()),
            "components": direction_components,
            "definition": "mean sum of squared probability errors across down/unchanged/up",
        },
        "threshold_brier": [
            {
                "operator": key.split(":", 1)[0],
                "threshold": float(key.split(":", 1)[1]),
                "unit": "percent_return",
                "score": statistics.fmean(
                    (probability - observed) ** 2 for probability, observed in pairs
                ),
            }
            for key, pairs in threshold_pairs.items()
        ],
        "reliability": {
            "bin_count": RELIABILITY_BIN_COUNT,
            "direction": {
                direction: _reliability_bins(pairs)
                for direction, pairs in direction_pairs.items()
            },
            "thresholds": [
                {
                    "operator": key.split(":", 1)[0],
                    "threshold": float(key.split(":", 1)[1]),
                    "unit": "percent_return",
                    "bins": _reliability_bins(pairs),
                }
                for key, pairs in threshold_pairs.items()
            ],
        },
        "interval_coverage": [
            {
                "level": level,
                "covered_count": sum(values),
                "sample_count": len(values),
                "coverage": statistics.fmean(values),
                "definition": "fraction of realized returns inside the forecast interval",
            }
            for level, values in coverage.items()
        ],
    }


def _empty_evaluation(reason: str, eligible_count: int) -> dict[str, Any]:
    """Keep unavailable evaluation explicit instead of inventing zero-valued scores."""

    return {
        "version": EVALUATION_VERSION,
        "method": "bounded chronological expanding-window walk-forward",
        "status": "insufficient_history",
        "reason": reason,
        "evaluation_count": 0,
        "eligible_realized_count": eligible_count,
        "excluded_anomaly_outcome_count": 0,
        "date_range": None,
        "training_sample_range": None,
        "forecast_model": None,
        "baseline": None,
        "max_evaluation_points": EVALUATION_MAX_POINTS,
        "information_rule": (
            "each fit uses only outcomes whose target was completed at or before its origin"
        ),
    }


def _walk_forward_evaluation(
    observations: list[_HorizonObservation],
    *,
    cutoff: datetime,
    span: int,
    minimum_training: int,
) -> dict[str, Any]:
    """Evaluate a bounded tail chronologically without making future outcomes fit inputs."""

    cutoff_utc = cutoff.astimezone(UTC)
    eligible = sorted(
        (
            item
            for item in observations
            if item.target_at.astimezone(UTC) <= cutoff_utc
        ),
        key=lambda item: (item.target_at.astimezone(UTC), item.origin_at.astimezone(UTC)),
    )
    candidates = eligible[-EVALUATION_MAX_POINTS:]
    scored: list[
        tuple[_HorizonObservation, int, dict[str, Any], dict[str, Any]]
    ] = []
    excluded_outcomes = 0
    for candidate in candidates:
        # Intraday comparison keys enforce equal clock-time horizons. Daily observations all use
        # one key. A target at the candidate origin is known; any later target is future leakage.
        prior = [
            item.return_value
            for item in eligible
            if item.comparison_key == candidate.comparison_key
            and item.target_at.astimezone(UTC) <= candidate.origin_at.astimezone(UTC)
        ]
        filtered_prior = [value for value in prior if abs(value) < MAX_ABSOLUTE_RETURN]
        if len(filtered_prior) < minimum_training:
            continue
        if abs(candidate.return_value) >= MAX_ABSOLUTE_RETURN:
            excluded_outcomes += 1
            continue
        model_samples, accounting = _prepare_model_samples(prior, span=span)
        if len(model_samples) < 3:
            continue
        model = _distribution(model_samples, candidate.origin_price, sample_accounting=accounting)
        baseline_accounting = {
            **accounting,
            "effective_count": len(filtered_prior),
            "warmup_excluded_count": 0,
            "transformation": "none",
        }
        baseline = _distribution(
            filtered_prior, candidate.origin_price, sample_accounting=baseline_accounting
        )
        scored.append((candidate, len(model_samples), model, baseline))

    if not scored:
        return _empty_evaluation(
            f"fewer than {minimum_training} prior comparable realized samples per point",
            len(eligible),
        )
    model_predictions = [(model, item.return_value) for item, _, model, _ in scored]
    baseline_predictions = [(baseline, item.return_value) for item, _, _, baseline in scored]
    first = scored[0][0]
    last = scored[-1][0]
    training_counts = [training_count for _, training_count, _, _ in scored]
    return {
        "version": EVALUATION_VERSION,
        "method": "bounded chronological expanding-window walk-forward",
        "status": "available",
        "evaluation_count": len(scored),
        "eligible_realized_count": len(eligible),
        "excluded_anomaly_outcome_count": excluded_outcomes,
        "date_range": {
            "first_origin": first.origin_at.isoformat(),
            "first_target": first.target_at.isoformat(),
            "last_origin": last.origin_at.isoformat(),
            "last_target": last.target_at.isoformat(),
        },
        "training_sample_range": {
            "minimum_effective_count": min(training_counts),
            "maximum_effective_count": max(training_counts),
        },
        "forecast_model": {
            "name": "volatility-adjusted empirical distribution",
            "version": MODEL_VERSION,
            **_score_predictions(model_predictions),
        },
        "baseline": {
            "name": "prior-only empirical climatology",
            "version": "empirical-climatology-v1",
            "definition": (
                "the same expanding prior outcomes, anomaly filter, quantiles, and smoothing "
                "without EWMA volatility standardization"
            ),
            **_score_predictions(baseline_predictions),
        },
        "max_evaluation_points": EVALUATION_MAX_POINTS,
        "minimum_training_samples": minimum_training,
        "information_rule": (
            "each fit uses only outcomes whose target was completed at or before its origin"
        ),
    }


def _daily_observations(bars: list[Bar], timezone: str) -> list[_HorizonObservation]:
    return [
        _HorizonObservation(
            origin_at=previous.timestamp,
            target_at=current.timestamp,
            origin_price=previous.close,
            return_value=current.close / previous.close - 1.0,
            comparison_key="close_to_next_close",
        )
        for previous, current in zip(bars[:-1], bars[1:], strict=False)
        if _next_session_close(previous.timestamp, timezone).astimezone(UTC)
        == current.timestamp.astimezone(UTC)
    ]


def _intraday_observations(
    data: MarketData, bars: list[Bar]
) -> list[_HorizonObservation]:
    """Build realized same-clock-time-to-close outcomes from complete historical sessions."""

    zone = ZoneInfo(data.timezone)
    sessions: dict[date, list[Bar]] = {}
    for bar in bars:
        sessions.setdefault(bar.timestamp.astimezone(zone).date(), []).append(bar)
    observations = []
    for day, session_bars in sessions.items():
        ordered = sorted(session_bars, key=lambda item: item.timestamp)
        close = _session_close(data, day)
        if close is None or not ordered or ordered[-1].end != close:
            continue
        final_price = ordered[-1].close
        for bar in ordered[:-1]:
            observations.append(
                _HorizonObservation(
                    origin_at=bar.end,
                    target_at=close,
                    origin_price=bar.close,
                    return_value=final_price / bar.close - 1.0,
                    comparison_key=bar.timestamp.astimezone(zone).strftime("%H:%M"),
                )
            )
    return observations


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
            raise DomainError(
                "invalid_market_data", "Market bars must contain positive finite close prices."
            )
        # UTC keys make duplicate instants deterministic even across offset representations.
        instant = bar.timestamp.astimezone(UTC)
        existing = selected.get(instant)
        if existing is not None and existing.close != bar.close:
            raise DomainError(
                "conflicting_provider_bar",
                "The provider returned conflicting closes for one market timestamp.",
                status_code=502,
            )
        selected[instant] = Bar(bar.timestamp.astimezone(zone), bar.close, bar.duration_seconds)
    return sorted(
        (bar for bar in selected.values() if bar.end.astimezone(UTC) <= now),
        key=lambda item: item.timestamp,
    )


def _completed_daily_bars(data: MarketData, now: datetime) -> list[Bar]:
    """Require every daily row to identify an actual completed scheduled session close."""

    bars = _validated_bars(data.daily, duration_seconds=0, now=now, timezone=data.timezone)
    for bar in bars:
        expected = _session_close(data, bar.timestamp.astimezone(ZoneInfo(data.timezone)).date())
        if expected is None or bar.timestamp.astimezone(UTC) != expected.astimezone(UTC):
            raise DomainError(
                "invalid_daily_session_close",
                "A daily bar does not identify its completed regular-session close.",
                status_code=502,
            )
    return bars


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


def _missing_internal_intraday_intervals(
    data: MarketData, bars: list[Bar]
) -> tuple[int, int]:
    """Count absent calendar-aligned bars only between observed bars in one session."""

    zone = ZoneInfo(data.timezone)
    sessions: dict[date, set[int]] = {}
    for bar in bars:
        local = bar.timestamp.astimezone(zone)
        session_open = _session_open(data, local.date())
        session_close = _session_close(data, local.date())
        if session_open is None or session_close is None:
            continue
        elapsed_seconds = (local - session_open).total_seconds()
        # Only scheduled five-minute slots establish coverage. This avoids interpreting an
        # off-grid provider timestamp or a closed-period boundary as one or more absent bars.
        if elapsed_seconds < 0 or elapsed_seconds % 300 or bar.end > session_close:
            continue
        sessions.setdefault(local.date(), set()).add(int(elapsed_seconds // 300))

    missing = 0
    affected_sessions = 0
    for observed_slots in sessions.values():
        if len(observed_slots) < 2:
            continue
        first_slot = min(observed_slots)
        last_slot = max(observed_slots)
        session_missing = last_slot - first_slot + 1 - len(observed_slots)
        if session_missing:
            missing += session_missing
            affected_sessions += 1
    return missing, affected_sessions


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
    completed_daily = _completed_daily_bars(data, now)
    if len(completed_daily) < 61:
        raise DomainError(
            "insufficient_daily_data", "At least 61 completed daily closes are required."
        )
    daily_origin = completed_daily[-1]
    bounded_daily_bars = completed_daily[-505:]
    daily_observations = _daily_observations(bounded_daily_bars, data.timezone)
    raw_daily = [item.return_value for item in daily_observations][-504:]
    daily_samples, daily_accounting = _prepare_model_samples(raw_daily, span=30)

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
    if is_open_session_horizon:
        intraday_samples, intraday_accounting = _prepare_model_samples(intraday_raw, span=10)
    else:
        intraday_samples, intraday_accounting = daily_samples, daily_accounting

    daily_evaluation = _walk_forward_evaluation(
        daily_observations,
        cutoff=now,
        span=30,
        minimum_training=20,
    )
    intraday_evaluation = (
        _walk_forward_evaluation(
            _intraday_observations(data, regular_intraday),
            cutoff=now,
            span=10,
            minimum_training=3,
        )
        if is_open_session_horizon
        else daily_evaluation
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
    internal_missing, affected_sessions = _missing_internal_intraday_intervals(
        data, regular_intraday
    )
    if internal_missing:
        bar_label = "bar" if internal_missing == 1 else "bars"
        session_label = "session" if affected_sessions == 1 else "sessions"
        stale_reasons.append(
            f"intraday history omits {internal_missing} completed internal five-minute "
            f"{bar_label} within {affected_sessions} regular {session_label}"
        )
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
    common: dict[str, Any] = {
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
        "forecast_contract_version": FORECAST_CONTRACT_VERSION,
        "model": {"name": "volatility-adjusted empirical distribution", "version": MODEL_VERSION},
        "parameters": {
            "daily_max_samples": 504,
            "ewma_span_daily": 30,
            "ewma_span_intraday": 10,
            "flat_threshold": FLAT_THRESHOLD,
            "maximum_absolute_training_return": MAX_ABSOLUTE_RETURN,
            "return_thresholds_percent": [value * 100.0 for value in RETURN_THRESHOLDS],
            "evaluation_max_points": EVALUATION_MAX_POINTS,
            "reliability_bin_count": RELIABILITY_BIN_COUNT,
        },
        "provenance": {
            "source": data.provider,
            "query": data.query,
            "response_as_of": data.fetched_at.isoformat(),
            "content_fingerprint": data.fingerprint(),
            "instrument_identity": identity.as_dict(),
            "identity_fingerprint": identity.fingerprint(),
            "model_version": MODEL_VERSION,
            "forecast_contract_version": FORECAST_CONTRACT_VERSION,
            "evaluation_version": EVALUATION_VERSION,
            "calendar_version": CALENDAR_VERSION,
        },
    }
    model_fingerprint_payload = {
        "contract_version": FORECAST_CONTRACT_VERSION,
        "model": common["model"],
        "parameters": common["parameters"],
        "calendar": common["calendar"],
    }
    model_fingerprint = hashlib.sha256(
        json.dumps(model_fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    common["model_fingerprint"] = model_fingerprint
    common["provenance"]["model_fingerprint"] = model_fingerprint
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
        "target_session_rule": (
            "the next scheduled regular-session close after the completed origin close"
        ),
        "evaluation": daily_evaluation,
        **_distribution(
            daily_samples, daily_origin.close, sample_accounting=daily_accounting
        ),
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
        "target_selection": {
            "rule": (
                "same_open_session_close"
                if is_open_session_horizon
                else "next_session_close_after_completed_origin_session"
            ),
            "request_session_state": request_session_state,
            "origin_session_date": origin_local.date().isoformat(),
            "target_session_date": target.astimezone(zone).date().isoformat(),
        },
        "evaluation": intraday_evaluation,
        **_distribution(
            intraday_samples, latest.close, sample_accounting=intraday_accounting
        ),
    }
    for result in (daily_result, intraday_result):
        result["model_version"] = MODEL_VERSION
        result["forecast_contract_version"] = FORECAST_CONTRACT_VERSION
        result["model_fingerprint"] = model_fingerprint
        result["forecast_fingerprint"] = hashlib.sha256(
            json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
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
