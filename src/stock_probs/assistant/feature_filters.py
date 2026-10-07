"""Typed filters shared by bounded assistant reads and confirmed browser handoffs."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation


class InvalidFeatureFilter(ValueError):
    """A bounded assistant filter or handoff payload failed its fixed contract."""


HISTORY_STATUSES = frozenset({"successful", "failed", "repeated"})
HISTORY_ANALYSIS_KINDS = frozenset({"submitted_forecast", "fresh_historical_reconstruction"})
HISTORY_HORIZONS = frozenset(
    {
        "close_to_close",
        "completed_5m_to_close",
        "five_min_forward",
        "daily_1",
        "weekly_5",
        "monthly_21",
        "quarterly_63",
    }
)
HISTORY_SORTS = frozenset(
    {"event_id:desc", "event_id:asc", "symbol:asc", "company:asc", "status:asc"}
)
HISTORY_PAGE_SIZES = frozenset({10, 20, 50})
_HISTORY_TOOL_PAGE_SIZE_VALUES = {str(size): size for size in HISTORY_PAGE_SIZES}
MARKET_RANGES = frozenset({"5d", "1mo", "3mo", "6mo", "1y"})
MARKET_REFRESH_KINDS = frozenset({"quotes", "watchlist", "chart"})
MARKET_QUOTE_FIELDS = frozenset(
    {"change_percent", "volume", "open", "high", "low", "last", "previous_close", "last_trade"}
)
MARKET_SORTS = frozenset(
    {
        "symbol:asc",
        "symbol:desc",
        "price:desc",
        "price:asc",
        "change:desc",
        "volume:desc",
        "open:desc",
        "high:desc",
        "low:desc",
        "last:desc",
        "previous_close:desc",
        "last_trade:desc",
    }
)
_HISTORY_TEXT_LIMITS = {
    "query": 30,
    "symbol": 15,
    "model": 120,
}
_HISTORY_FIELDS = frozenset(
    {
        "query",
        "symbol",
        "asset_type",
        "status",
        "analysis_kind",
        "submitted_from",
        "submitted_to",
        "model",
        "horizon",
        "sort",
        "page_size",
        "page",
    }
)
_EXPORT_FIELDS = _HISTORY_FIELDS - {"page_size", "page"}
_MARKET_FILTER_FIELDS = frozenset(
    {
        "query",
        "exchange",
        "asset_type",
        "sort",
        "min_price",
        "max_price",
        "min_change",
        "max_change",
        "min_volume",
        "quote_field",
        "quote_min",
        "quote_max",
    }
)
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9.^-]{1,15}$")
_ISO_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_DECIMAL_RE = re.compile(r"^-?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)$")


def _text(value: object, field: str, maximum: int, *, empty: bool = True) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise InvalidFeatureFilter(f"{field} is invalid")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise InvalidFeatureFilter(f"{field} contains unsupported characters")
    result = value.strip()
    if not empty and not result:
        raise InvalidFeatureFilter(f"{field} is required")
    return result


def _optional_enum(payload: Mapping[str, object], field: str, allowed: frozenset[str]) -> str:
    value = payload.get(field, "")
    if value == "":
        return ""
    if not isinstance(value, str) or value not in allowed:
        raise InvalidFeatureFilter(f"{field} is unsupported")
    return value


def _date(value: object, field: str) -> str:
    if value == "":
        return ""
    if not isinstance(value, str) or _ISO_DATE_RE.fullmatch(value) is None:
        raise InvalidFeatureFilter(f"{field} must use YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidFeatureFilter(f"{field} is not a valid calendar date") from exc
    if parsed.isoformat() != value:
        raise InvalidFeatureFilter(f"{field} must use YYYY-MM-DD")
    return value


def normalize_history_filters(
    payload: object,
    *,
    include_page_size: bool = False,
    allow_page: bool = False,
    require_query: bool = False,
) -> dict[str, object]:
    """Normalize the existing research form vocabulary without losing approved values."""

    if not isinstance(payload, Mapping):
        raise InvalidFeatureFilter("history filters must be an object")
    if allow_page:
        allowed_fields = _HISTORY_FIELDS
    elif include_page_size:
        allowed_fields = _HISTORY_FIELDS - {"page"}
    else:
        allowed_fields = _EXPORT_FIELDS
    if set(payload) - allowed_fields:
        raise InvalidFeatureFilter("history filters contain unsupported fields")
    query = _text(payload.get("query", ""), "query", _HISTORY_TEXT_LIMITS["query"])
    if require_query and "query" not in payload:
        raise InvalidFeatureFilter("query is required")
    symbol_value = payload.get("symbol", "")
    symbol = _text(symbol_value, "symbol", _HISTORY_TEXT_LIMITS["symbol"])
    if symbol and _SYMBOL_RE.fullmatch(symbol) is None:
        raise InvalidFeatureFilter("symbol is invalid")
    symbol = symbol.upper()
    asset_type = _optional_enum(payload, "asset_type", frozenset({"stock", "etf"}))
    status = _optional_enum(payload, "status", HISTORY_STATUSES)
    analysis_kind = _optional_enum(payload, "analysis_kind", HISTORY_ANALYSIS_KINDS)
    submitted_from = _date(payload.get("submitted_from", ""), "submitted_from")
    submitted_to = _date(payload.get("submitted_to", ""), "submitted_to")
    if submitted_from and submitted_to and submitted_from > submitted_to:
        raise InvalidFeatureFilter("submitted_from must not follow submitted_to")
    model = _text(payload.get("model", ""), "model", _HISTORY_TEXT_LIMITS["model"])
    horizon = _optional_enum(payload, "horizon", HISTORY_HORIZONS)
    sort_value = payload.get("sort", "event_id:desc")
    if not isinstance(sort_value, str):
        raise InvalidFeatureFilter("sort is unsupported")
    sort = sort_value
    if not sort:
        sort = "event_id:desc"
    if sort not in HISTORY_SORTS:
        raise InvalidFeatureFilter("sort is unsupported")
    result: dict[str, object] = {
        "query": query,
        "symbol": symbol,
        "asset_type": asset_type,
        "status": status,
        "analysis_kind": analysis_kind,
        "submitted_from": submitted_from,
        "submitted_to": submitted_to,
        "model": model,
        "horizon": horizon,
        "sort": sort,
    }
    if include_page_size:
        page_size = payload.get("page_size", 10)
        if type(page_size) is not int or page_size not in HISTORY_PAGE_SIZES:
            raise InvalidFeatureFilter("page_size is unsupported")
        result["page_size"] = page_size
    if allow_page:
        page = payload.get("page", 1)
        page_size = payload.get("page_size", 10)
        if type(page) is not int or not 1 <= page <= 10_000:
            raise InvalidFeatureFilter("page is unsupported")
        if type(page_size) is not int or not 1 <= page_size <= 10:
            raise InvalidFeatureFilter("page_size is unsupported")
        result["page"] = page
        result["page_size"] = page_size
    return result


def normalize_history_form_filters(payload: object) -> dict[str, object]:
    """Normalize browser filters without changing the existing form's search semantics."""

    result = normalize_history_filters(payload, include_page_size=True, require_query=True)
    if result["symbol"]:
        raise InvalidFeatureFilter("the history form cannot represent an exact symbol filter")
    result.pop("symbol")
    return result


def normalize_history_action_filters(payload: object) -> dict[str, object]:
    """Normalize provider-projected page-size strings at the typed action boundary."""

    if isinstance(payload, Mapping):
        page_size = payload.get("page_size", 10)
        if type(page_size) is str:
            canonical_page_size = _HISTORY_TOOL_PAGE_SIZE_VALUES.get(page_size)
            if canonical_page_size is None:
                raise InvalidFeatureFilter("page_size is unsupported")
            normalized_payload = dict(payload)
            normalized_payload["page_size"] = canonical_page_size
            payload = normalized_payload
    return normalize_history_form_filters(payload)


def history_date_bounds(filters: dict[str, object]) -> tuple[datetime | None, datetime | None]:
    """Convert date controls to the exact inclusive UTC bounds used by the web form."""

    start_value = filters["submitted_from"]
    end_value = filters["submitted_to"]
    start = (
        datetime.combine(date.fromisoformat(str(start_value)), time.min, UTC)
        if start_value
        else None
    )
    end = (
        datetime.combine(date.fromisoformat(str(end_value)), time(23, 59, 59, 999000), UTC)
        if end_value
        else None
    )
    return start, end


def history_export_query(filters: dict[str, object]) -> dict[str, str]:
    """Map approved research form values to the existing export endpoint vocabulary."""

    query: dict[str, str] = {}
    mappings = (
        ("query", "q"),
        ("symbol", "symbol"),
        ("asset_type", "asset_type"),
        ("status", "status"),
        ("analysis_kind", "analysis_kind"),
        ("model", "model"),
        ("horizon", "horizon"),
    )
    for source, target in mappings:
        value = filters.get(source)
        if isinstance(value, str) and value:
            query[target] = value
    start = filters.get("submitted_from")
    end = filters.get("submitted_to")
    if isinstance(start, str) and start:
        query["submitted_from"] = f"{start}T00:00:00Z"
    if isinstance(end, str) and end:
        query["submitted_to"] = f"{end}T23:59:59.999Z"
    sort = str(filters.get("sort", "event_id:desc"))
    sort_by, sort_order = sort.split(":", maxsplit=1)
    query["sort_by"] = sort_by
    query["sort_order"] = sort_order
    return query


def _numeric_filter(
    value: object,
    *,
    field: str,
    allow_negative: bool,
    maximum: Decimal,
    integral: bool = False,
    max_fraction_digits: int | None = None,
) -> str:
    if not isinstance(value, str) or len(value) > 32:
        raise InvalidFeatureFilter(f"{field} is invalid")
    candidate = value.strip()
    if not candidate:
        return ""
    if _DECIMAL_RE.fullmatch(candidate) is None:
        raise InvalidFeatureFilter(f"{field} is invalid")
    try:
        number = Decimal(candidate)
    except InvalidOperation as exc:
        raise InvalidFeatureFilter(f"{field} is invalid") from exc
    if not number.is_finite() or (not allow_negative and number < 0) or abs(number) > maximum:
        raise InvalidFeatureFilter(f"{field} is outside the supported range")
    if integral and number != number.to_integral_value():
        raise InvalidFeatureFilter(f"{field} must be an integer")
    fractional_digits = max(0, -number.as_tuple().exponent)
    if max_fraction_digits is not None and fractional_digits > max_fraction_digits:
        raise InvalidFeatureFilter(f"{field} has too many decimal places")
    if number == 0:
        return "0"
    normalized = format(number, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized


def normalize_market_filters(payload: object) -> dict[str, object]:
    """Validate every existing Markets filter without converting browser values to floats."""

    if not isinstance(payload, Mapping) or set(payload) != _MARKET_FILTER_FIELDS:
        raise InvalidFeatureFilter("market filters must include exactly the current controls")
    query = _text(payload.get("query"), "query", 80)
    exchange = _text(payload.get("exchange"), "exchange", 40)
    if exchange and re.fullmatch(r"[A-Za-z0-9 ._-]+", exchange) is None:
        raise InvalidFeatureFilter("exchange is invalid")
    asset_type = _optional_enum(payload, "asset_type", frozenset({"stock", "etf"}))
    sort = payload.get("sort")
    if not isinstance(sort, str) or sort not in MARKET_SORTS:
        raise InvalidFeatureFilter("sort is unsupported")
    min_price = _numeric_filter(
        payload.get("min_price"),
        field="min_price",
        allow_negative=False,
        maximum=Decimal("1000000000"),
        max_fraction_digits=2,
    )
    max_price = _numeric_filter(
        payload.get("max_price"),
        field="max_price",
        allow_negative=False,
        maximum=Decimal("1000000000"),
        max_fraction_digits=2,
    )
    min_change = _numeric_filter(
        payload.get("min_change"),
        field="min_change",
        allow_negative=True,
        maximum=Decimal("1000000"),
        max_fraction_digits=2,
    )
    max_change = _numeric_filter(
        payload.get("max_change"),
        field="max_change",
        allow_negative=True,
        maximum=Decimal("1000000"),
        max_fraction_digits=2,
    )
    min_volume = _numeric_filter(
        payload.get("min_volume"),
        field="min_volume",
        allow_negative=False,
        maximum=Decimal("1000000000000000"),
        integral=True,
    )
    quote_field = _optional_enum(payload, "quote_field", MARKET_QUOTE_FIELDS)
    quote_integral = quote_field == "volume"
    quote_negative = quote_field == "change_percent"
    quote_maximum = (
        Decimal("1000000000000000")
        if quote_integral
        else Decimal("1000000")
        if quote_negative
        else Decimal("1000000000")
    )
    quote_min = _numeric_filter(
        payload.get("quote_min"),
        field="quote_min",
        allow_negative=quote_negative,
        maximum=quote_maximum,
        integral=quote_integral,
    )
    quote_max = _numeric_filter(
        payload.get("quote_max"),
        field="quote_max",
        allow_negative=quote_negative,
        maximum=quote_maximum,
        integral=quote_integral,
    )
    if not quote_field and (quote_min or quote_max):
        raise InvalidFeatureFilter("quote_field is required for metric bounds")
    for low, high, label in (
        (min_price, max_price, "price"),
        (min_change, max_change, "change"),
        (quote_min, quote_max, "quote metric"),
    ):
        if low and high and Decimal(low) > Decimal(high):
            raise InvalidFeatureFilter(f"minimum {label} must not exceed maximum {label}")
    return {
        "query": query,
        "exchange": exchange,
        "asset_type": asset_type,
        "sort": sort,
        "min_price": min_price,
        "max_price": max_price,
        "min_change": min_change,
        "max_change": max_change,
        "min_volume": min_volume,
        "quote_field": quote_field,
        "quote_min": quote_min,
        "quote_max": quote_max,
    }


def normalize_market_chart_range(payload: object) -> dict[str, object]:
    """Validate a chart range against its exact current Markets instrument identity."""

    if not isinstance(payload, Mapping) or set(payload) != {
        "symbol",
        "asset_type",
        "provider",
        "exchange",
        "range",
    }:
        raise InvalidFeatureFilter("chart range requires one exact instrument")
    symbol = _text(payload.get("symbol"), "symbol", 15, empty=False).upper()
    if _SYMBOL_RE.fullmatch(symbol) is None:
        raise InvalidFeatureFilter("symbol is invalid")
    asset_type = _optional_enum(payload, "asset_type", frozenset({"stock", "etf"}))
    if not asset_type:
        raise InvalidFeatureFilter("asset_type is required")
    provider = _text(payload.get("provider"), "provider", 80, empty=False)
    exchange = _text(payload.get("exchange"), "exchange", 40, empty=False)
    if re.fullmatch(r"[A-Za-z0-9 ._-]+", provider) is None:
        raise InvalidFeatureFilter("provider is invalid")
    if re.fullmatch(r"[A-Za-z0-9 ._-]+", exchange) is None:
        raise InvalidFeatureFilter("exchange is invalid")
    chart_range = payload.get("range")
    if not isinstance(chart_range, str) or chart_range not in MARKET_RANGES:
        raise InvalidFeatureFilter("range is unsupported")
    return {
        "symbol": symbol,
        "asset_type": asset_type,
        "provider": provider,
        "exchange": exchange,
        "range": chart_range,
    }


def normalize_market_columns(payload: object) -> dict[str, object]:
    """Validate the one boolean Markets column-display handoff."""

    if (
        not isinstance(payload, Mapping)
        or set(payload) != {"show_all_columns"}
        or type(payload.get("show_all_columns")) is not bool
    ):
        raise InvalidFeatureFilter("column preference must be a boolean")
    return {"show_all_columns": payload["show_all_columns"]}


def normalize_market_refresh(payload: object) -> dict[str, object]:
    """Validate the Markets refresh target without accepting a new operation kind."""

    if not isinstance(payload, Mapping) or set(payload) != {"kind"}:
        raise InvalidFeatureFilter("refresh requires one target")
    kind = payload.get("kind")
    if not isinstance(kind, str) or kind not in MARKET_REFRESH_KINDS:
        raise InvalidFeatureFilter("refresh target is unsupported")
    return {"kind": kind}
