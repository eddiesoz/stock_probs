"""Bounded yfinance adapter and deterministic fixture implementation."""

from __future__ import annotations

import json
import math
import time as monotonic_time
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from importlib import import_module
from importlib.resources import files
from typing import Any, Protocol, cast
from zoneinfo import ZoneInfo

from stock_probs.domain import (
    Bar,
    DomainError,
    InstrumentIdentity,
    MarketData,
    NewsData,
    NewsItem,
    normalize_lookup_query,
    normalize_symbol,
    scheduled_session_close,
)


class _YahooSearchResult(Protocol):
    quotes: object


class _YFinanceModule(Protocol):
    """Type only the two yfinance constructors this bounded adapter is allowed to use."""

    def Search(self, query: str, **kwargs: object) -> _YahooSearchResult: ...

    def Ticker(self, symbol: str) -> object: ...


# yfinance does not publish type information; keep its dynamic module behind the narrow facade.
yf = cast(_YFinanceModule, import_module("yfinance"))
curl_requests = import_module("curl_cffi.requests")

MAX_LOOKUP_RESULTS = 5
YAHOO_PROVIDER_NAME = "Yahoo Finance"
FIXTURE_PROVIDER_NAME = "deterministic fixture"
YAHOO_INTRADAY_ARCHIVE_APPROXIMATE_DAYS = 60
MAX_NEWS_RESULTS = 10
MAX_NEWS_BODY_BYTES = 256 * 1024
YAHOO_NEWS_URL = "https://query2.finance.yahoo.com/v1/finance/search"


class MarketDataProvider(Protocol):
    """Narrow provider boundary keeps deterministic tests out of transport internals."""

    def lookup(
        self, query: str, limit: int, now: datetime
    ) -> tuple[InstrumentIdentity, ...]: ...

    def fetch(self, symbol: str, asset_type: str, now: datetime) -> MarketData: ...

    def fetch_at_cutoff(
        self, symbol: str, asset_type: str, cutoff: datetime, now: datetime
    ) -> MarketData: ...

    def fetch_news(
        self, symbol: str, limit: int = 5, now: datetime | None = None
    ) -> NewsData: ...


class YahooProvider:
    """Translate bounded yfinance history calls into the provider-neutral contract."""

    def __init__(
        self,
        timeout: float = 8.0,
        clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ):
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int | float)
            or not math.isfinite(timeout)
            or not 0.1 <= timeout <= 20.0
        ):
            raise ValueError("Yahoo timeout must be between 0.1 and 20 seconds")
        self.timeout = timeout
        self.clock = clock or (lambda: datetime.now(UTC))
        self.monotonic_clock = monotonic_clock or monotonic_time.monotonic

    def _response_time(self) -> datetime:
        """Require an aware completion time so lookup and forecast provenance stay comparable."""

        captured = self.clock()
        if captured.tzinfo is None:
            raise DomainError(
                "ambiguous_provider_time", "Provider response time must include an offset."
            )
        return captured.astimezone(UTC)

    def _history(
        self,
        ticker: Any,
        *,
        interval: str,
        period: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Any:
        if (period is None) == (start is None or end is None):
            raise ValueError("history requires either period or complete start/end bounds")
        bounds: dict[str, object] = (
            {"period": period} if period is not None else {"start": start, "end": end}
        )
        try:
            # Explicit settings prohibit silent extended-session or adjusted-price input.
            return ticker.history(
                **bounds,
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

    def _history_from_bounds(
        self, ticker: Any, *, interval: str, bounds: dict[str, object]
    ) -> Any:
        """Narrow dynamic query metadata before passing it to the typed provider boundary."""

        period = bounds.get("period")
        if isinstance(period, str):
            return self._history(ticker, interval=interval, period=period)
        start = bounds.get("start")
        end = bounds.get("end")
        if not isinstance(start, datetime) or not isinstance(end, datetime):
            raise ValueError("historical provider bounds require datetime start and end")
        return self._history(ticker, interval=interval, start=start, end=end)

    def fetch_news(
        self, symbol: str, limit: int = 5, now: datetime | None = None
    ) -> NewsData:
        """Fetch one bounded Yahoo search payload without yfinance's shared sessions."""

        normalized_symbol = normalize_symbol(symbol)
        _validate_news_limit(limit)
        if now is not None and now.tzinfo is None:
            raise DomainError(
                "ambiguous_provider_time", "Provider news time must include an offset."
            )
        deadline = self.monotonic_clock() + min(float(self.timeout), 10.0)
        body = bytearray()
        oversized = False
        timed_out = False

        def receive(chunk: bytes) -> int:
            """Stop libcurl while receiving, before an oversized body is buffered."""

            nonlocal oversized, timed_out
            if self.monotonic_clock() >= deadline:
                timed_out = True
                return 0
            if len(body) + len(chunk) > MAX_NEWS_BODY_BYTES:
                oversized = True
                return 0
            body.extend(chunk)
            return len(chunk)

        params = {
            "q": normalized_symbol,
            "quotesCount": 0,
            "newsCount": limit,
            "listsCount": 0,
            "recommendedCount": 0,
            "enableFuzzyQuery": "false",
            "quotesQueryId": "tss_match_phrase_query",
            "newsQueryId": "news_cie_vespa",
            "enableCb": "false",
            "enableNavLinks": "false",
            "enableResearchReports": "false",
            "enableCulturalAssets": "false",
        }
        try:
            remaining = deadline - self.monotonic_clock()
            if remaining <= 0:
                raise TimeoutError
            # A per-call session prevents cookie, connection, or option mutation from leaking.
            with curl_requests.Session() as session:
                response = session.get(
                    YAHOO_NEWS_URL,
                    params=params,
                    headers={"Accept": "application/json", "User-Agent": "stock-probs/0.1"},
                    timeout=remaining,
                    allow_redirects=False,
                    discard_cookies=True,
                    default_headers=False,
                    content_callback=receive,
                )
        except Exception as exc:
            message = (
                "Yahoo Finance news exceeded the bounded response size."
                if oversized
                else "Yahoo Finance news did not complete within the configured deadline."
                if timed_out or self.monotonic_clock() >= deadline
                else "Yahoo Finance news is currently unavailable."
            )
            raise DomainError("provider_unavailable", message, status_code=502) from exc
        if oversized or self.monotonic_clock() >= deadline:
            raise DomainError(
                "provider_unavailable",
                "Yahoo Finance news exceeded its size or time boundary.",
                status_code=502,
            )
        if response.status_code != 200:
            raise DomainError(
                "provider_unavailable",
                "Yahoo Finance news is currently unavailable.",
                status_code=502,
            )
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DomainError(
                "provider_news_invalid",
                "Yahoo Finance returned an invalid news response.",
                status_code=502,
            ) from exc
        if not isinstance(payload, Mapping) or not isinstance(payload.get("news"), list):
            raise DomainError(
                "provider_news_invalid",
                "Yahoo Finance returned an invalid news response.",
                status_code=502,
            )

        items: list[NewsItem] = []
        seen: set[str] = set()
        for raw_item in payload["news"]:
            if self.monotonic_clock() >= deadline:
                raise DomainError(
                    "provider_unavailable",
                    "Yahoo Finance news did not complete within the configured deadline.",
                    status_code=502,
                )
            if not isinstance(raw_item, Mapping):
                raise DomainError(
                    "provider_news_invalid",
                    "Yahoo Finance returned an invalid news response.",
                    status_code=502,
                )
            item_id = raw_item.get("uuid")
            published = raw_item.get("providerPublishTime")
            related = raw_item.get("relatedTickers")
            title = raw_item.get("title")
            link = raw_item.get("link")
            if (
                not isinstance(item_id, str)
                or not isinstance(title, str)
                or not isinstance(link, str)
                or (
                    published is not None
                    and (
                        isinstance(published, bool)
                        or not isinstance(published, int | float)
                        or not math.isfinite(float(published))
                    )
                )
                or (
                    related is not None
                    and (
                        not isinstance(related, list | tuple)
                        or any(not isinstance(item, str) for item in related)
                    )
                )
            ):
                raise DomainError(
                    "provider_news_invalid",
                    "Yahoo Finance returned an invalid news item.",
                    status_code=502,
                )
            try:
                published_at = (
                    datetime.fromtimestamp(float(published), UTC)
                    if published is not None
                    else None
                )
                item = NewsItem(
                    id=item_id,
                    title=title,
                    publisher=raw_item.get("publisher"),
                    published_at=published_at,
                    url=link,
                    related_symbols=tuple(related[:32]) if related is not None else None,
                )
            except (DomainError, OSError, OverflowError, ValueError) as exc:
                if isinstance(exc, DomainError):
                    raise
                raise DomainError(
                    "provider_news_invalid",
                    "Yahoo Finance returned an invalid news item.",
                    status_code=502,
                ) from exc
            if item.id not in seen and len(items) < limit:
                items.append(item)
                seen.add(item.id)
        if self.monotonic_clock() >= deadline:
            raise DomainError(
                "provider_unavailable",
                "Yahoo Finance news did not complete within the configured deadline.",
                status_code=502,
            )
        as_of = now.astimezone(UTC) if now is not None else self._response_time()
        return NewsData(normalized_symbol, YAHOO_PROVIDER_NAME, as_of, tuple(items))

    @staticmethod
    def _identity_from_metadata(
        metadata: Mapping[str, Any],
        provider_as_of: datetime,
        *,
        fallback: Mapping[str, Any] | None = None,
    ) -> InstrumentIdentity:
        """Use identity facts from bounded Yahoo responses, never guessed defaults."""

        fallback = fallback or {}
        # Search owns lookup classification; chart metadata generically labels some ETFs EQUITY.
        quote_type = _metadata_text(
            fallback.get("quoteType") or metadata.get("instrumentType"), "quote type", 24
        ).upper()
        asset_type = {"equity": "stock", "stock": "stock", "etf": "etf"}.get(
            quote_type.lower()
        )
        if asset_type is None:
            raise DomainError(
                "unsupported_asset",
                "Yahoo did not classify this symbol as a supported stock or ETF.",
            )
        raw_symbol = metadata.get("symbol") or fallback.get("symbol")
        if not isinstance(raw_symbol, str):
            raise DomainError(
                "invalid_instrument_identity",
                "Yahoo did not return a canonical instrument symbol.",
                status_code=502,
            )
        try:
            canonical_symbol = normalize_symbol(raw_symbol)
        except DomainError as exc:
            raise DomainError(
                "invalid_instrument_identity",
                "Yahoo returned an invalid canonical instrument symbol.",
                status_code=502,
            ) from exc
        long_name = metadata.get("longName") or fallback.get("longname")
        short_name = metadata.get("shortName") or fallback.get("shortname")
        display_name = _metadata_text(short_name or long_name, "display name", 200)
        company_name = _metadata_text(long_name or short_name, "company name", 200)
        return InstrumentIdentity(
            canonical_symbol=canonical_symbol,
            display_name=display_name,
            company_name=company_name,
            exchange=_metadata_text(
                metadata.get("exchangeName") or fallback.get("exchange"), "exchange", 40
            ),
            currency=_metadata_text(metadata.get("currency"), "currency", 12),
            timezone=_metadata_text(metadata.get("exchangeTimezoneName"), "timezone", 80),
            quote_type=quote_type,
            asset_type=asset_type,
            provider=YAHOO_PROVIDER_NAME,
            provider_as_of=provider_as_of,
        )

    def lookup(
        self, query: str, limit: int = MAX_LOOKUP_RESULTS, now: datetime | None = None
    ) -> tuple[InstrumentIdentity, ...]:
        """Resolve a bounded Yahoo company-name query to complete, selectable identities."""

        normalized_query = normalize_lookup_query(query)
        _validate_lookup_limit(limit)
        requested_at = now or datetime.now(UTC)
        if requested_at.tzinfo is None:
            raise DomainError(
                "ambiguous_provider_time", "Provider lookup time must include an offset."
            )
        try:
            # Search is the only company-name call. News/lists/recommendations are disabled so
            # Yahoo cannot return unrelated, unbounded payload categories.
            search = yf.Search(
                normalized_query,
                max_results=limit,
                news_count=0,
                lists_count=0,
                include_cb=False,
                include_nav_links=False,
                include_research=False,
                include_cultural_assets=False,
                enable_fuzzy_query=False,
                recommended=0,
                timeout=self.timeout,
                raise_errors=True,
            )
            quotes = search.quotes
        except Exception as exc:
            raise DomainError(
                "provider_unavailable",
                "Yahoo Finance lookup did not complete within the configured timeout.",
                status_code=502,
            ) from exc
        if not isinstance(quotes, list):
            raise DomainError(
                "provider_metadata_unavailable",
                "Yahoo Finance returned an invalid lookup response.",
                status_code=502,
            )

        identities: list[InstrumentIdentity] = []
        seen: set[str] = set()
        for quote in quotes[:limit]:
            if not isinstance(quote, Mapping):
                continue
            quote_type = str(quote.get("quoteType", "")).upper()
            if quote_type not in {"EQUITY", "STOCK", "ETF"}:
                continue
            try:
                searched_symbol = normalize_symbol(str(quote.get("symbol", "")))
            except DomainError:
                continue
            if searched_symbol in seen:
                continue
            ticker = yf.Ticker(searched_symbol)
            # Yahoo search omits currency/timezone. One timeout-bounded chart call per returned
            # candidate completes identity without using Ticker.info or metadata cache misses.
            frame = self._history(ticker, period="5d", interval="1d")
            metadata = self._metadata_from_bounded_history(ticker, frame)
            identity = self._identity_from_metadata(
                metadata, self._response_time(), fallback=quote
            )
            searched_asset_type = "etf" if quote_type == "ETF" else "stock"
            if (
                identity.canonical_symbol != searched_symbol
                or identity.asset_type != searched_asset_type
            ):
                raise DomainError(
                    "provider_identity_mismatch",
                    "Yahoo returned inconsistent instrument identity metadata.",
                    status_code=502,
                )
            identities.append(identity)
            seen.add(identity.canonical_symbol)
        return tuple(identities)

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
        """Fetch a current bounded snapshot for an ordinary submitted forecast."""

        if now.tzinfo is None:
            raise DomainError(
                "ambiguous_provider_time", "Provider request time must include an offset."
            )
        now_utc = now.astimezone(UTC)
        return self._fetch_with_bounds(
            symbol,
            asset_type,
            cutoff=now,
            requested_at=now,
            daily_bounds={"period": "2y"},
            intraday_bounds={
                "start": now_utc - timedelta(days=59),
                "end": now_utc + timedelta(days=1),
            },
            mode="current",
        )

    def fetch_at_cutoff(
        self, symbol: str, asset_type: str, cutoff: datetime, now: datetime
    ) -> MarketData:
        """Fetch only data eligible at a recent historical cutoff using explicit date bounds."""

        if cutoff.tzinfo is None or now.tzinfo is None:
            raise DomainError(
                "ambiguous_historical_cutoff", "Historical cutoff times must include an offset."
            )
        cutoff_utc = cutoff.astimezone(UTC)
        now_utc = now.astimezone(UTC)
        if cutoff_utc > now_utc:
            raise DomainError(
                "future_historical_cutoff", "Historical cutoff cannot be in the future."
            )
        cutoff_age = now_utc - cutoff_utc
        if cutoff_age > timedelta(days=49):
            raise DomainError(
                "historical_cutoff_unavailable",
                "The cutoff plus its 10-day lookback exceeds Yahoo's 60-day five-minute archive.",
            )
        # Keep the earliest requested bar inside the approximate 60-day archive. Recent cutoffs
        # receive a longer training window; the oldest supported cutoff still receives ten days.
        lookback_days = max(10, 59 - int(cutoff_age.total_seconds() // 86_400))
        # Yahoo treats end as exclusive. A one-day upper cushion includes the cutoff's session;
        # the domain still discards every row whose completion is after the exact cutoff.
        return self._fetch_with_bounds(
            symbol,
            asset_type,
            cutoff=cutoff,
            requested_at=now,
            daily_bounds={
                "start": cutoff_utc - timedelta(days=800),
                "end": cutoff_utc + timedelta(days=1),
            },
            intraday_bounds={
                "start": cutoff_utc - timedelta(days=lookback_days),
                "end": cutoff_utc + timedelta(days=1),
            },
            mode="historical_cutoff",
        )

    def _fetch_with_bounds(
        self,
        symbol: str,
        asset_type: str,
        *,
        cutoff: datetime,
        requested_at: datetime,
        daily_bounds: dict[str, object],
        intraday_bounds: dict[str, object],
        mode: str,
    ) -> MarketData:
        """Normalize current and historical Yahoo requests through one identity path."""

        if cutoff.tzinfo is None or requested_at.tzinfo is None:
            raise DomainError(
                "ambiguous_provider_time", "Provider request time must include an offset."
            )
        if asset_type not in {"stock", "etf"}:
            raise DomainError("unsupported_asset", "Only stocks and ETFs are supported.")
        requested_symbol = normalize_symbol(symbol)
        ticker = yf.Ticker(requested_symbol)
        daily_frame = self._history_from_bounds(ticker, interval="1d", bounds=daily_bounds)
        if daily_frame.empty:
            raise DomainError(
                "symbol_not_found",
                "Yahoo Finance has no required daily data for this symbol.",
                status_code=404,
            )
        # Capture the per-call cache before the next history request replaces it.
        daily_meta = self._metadata_from_bounded_history(ticker, daily_frame)
        intraday_frame = self._history_from_bounds(
            ticker, interval="5m", bounds=intraday_bounds
        )
        if intraday_frame.empty:
            raise DomainError(
                "symbol_not_found",
                "Yahoo Finance has no required five-minute data for this symbol.",
                status_code=404,
            )
        # Metadata comes from the timeout-bounded chart responses, and each response must attest
        # the requested granularity so no provider fallback can be relabelled silently.
        meta = self._metadata_from_bounded_history(ticker, intraday_frame)
        if str(daily_meta.get("dataGranularity", "")) != "1d":
            raise DomainError(
                "provider_interval_mismatch",
                "Yahoo did not return the requested daily interval.",
                status_code=502,
            )
        response_at = self._response_time()
        identity = self._identity_from_metadata(meta, response_at)
        if identity.canonical_symbol != requested_symbol:
            raise DomainError(
                "provider_identity_mismatch",
                "Yahoo returned data for a different canonical symbol.",
                status_code=502,
            )
        if identity.asset_type != asset_type:
            raise DomainError(
                "asset_type_mismatch",
                f"Yahoo classifies {requested_symbol} as {identity.asset_type}, not {asset_type}.",
            )
        timezone = identity.timezone
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
        cutoff_utc = cutoff.astimezone(UTC)
        # End is intentionally cushioned because Yahoo treats it as exclusive. The adapter, not a
        # downstream caller, enforces the exact information cutoff on every normalized bar.
        daily = tuple(
            bar
            for bar in self._daily_bars(daily_frame, timezone)
            if bar.end.astimezone(UTC) <= cutoff_utc
        )
        intraday = tuple(
            bar
            for bar in self._intraday_bars(intraday_frame)
            if bar.end.astimezone(UTC) <= cutoff_utc
        )

        def provenance_bounds(bounds: dict[str, object]) -> dict[str, object]:
            """Keep provider call datetimes explicit and JSON-fingerprintable in provenance."""

            return {
                key: value.isoformat() if isinstance(value, datetime) else value
                for key, value in bounds.items()
            }

        return MarketData(
            symbol=identity.canonical_symbol,
            display_name=identity.display_name,
            company_name=identity.company_name,
            asset_type=asset_type,
            quote_type=identity.quote_type,
            exchange=identity.exchange,
            timezone=timezone,
            currency=identity.currency,
            provider=identity.provider,
            # Capture response completion separately from the request/cutoff timestamp.
            fetched_at=response_at,
            query={
                "mode": mode,
                "requested_as_of": requested_at.astimezone(UTC).isoformat(),
                "data_cutoff": cutoff.astimezone(UTC).isoformat(),
                "daily": {
                    **provenance_bounds(daily_bounds),
                    "interval": "1d",
                    "prepost": False,
                    "actions": False,
                    "auto_adjust": False,
                    "repair": False,
                    "timeout_seconds": self.timeout,
                    "returned_coverage": _coverage(daily),
                },
                "intraday": {
                    **provenance_bounds(intraday_bounds),
                    "interval": "5m",
                    "prepost": False,
                    "actions": False,
                    "auto_adjust": False,
                    "repair": False,
                    "timeout_seconds": self.timeout,
                    "returned_coverage": _coverage(intraday),
                },
            },
            daily=daily,
            intraday=intraday,
            provider_metadata={
                "identity_source": "bounded_chart_metadata",
                "regular_session": {
                    "start": _provider_epoch(regular.get("start")),
                    "end": _provider_epoch(regular.get("end")),
                },
                "data_granularity": meta.get("dataGranularity", "5m"),
                "daily_data_granularity": daily_meta.get("dataGranularity"),
                "gmtoffset": int(meta["gmtoffset"]) if meta.get("gmtoffset") is not None else None,
                "exchange_timezone": timezone,
                "session_scope": "regular session only (prepost=False)",
                "intraday_archive_limit": {
                    "approximate_days": YAHOO_INTRADAY_ARCHIVE_APPROXIMATE_DAYS,
                    "statement": (
                        "Yahoo five-minute history is limited to approximately 60 recent days; "
                        "availability may be shorter and historical cutoffs older than 49 days "
                        "are rejected by this adapter"
                    ),
                },
                "daily_coverage": _coverage(daily),
                "intraday_coverage": _coverage(intraday),
                "daily_returned_rows": len(daily_frame.index),
                "intraday_returned_rows": len(intraday_frame.index),
                "daily_normalized_rows": len(daily),
                "intraday_normalized_rows": len(intraday),
                "daily_rejected_rows": len(daily_frame.index) - len(daily),
                "intraday_rejected_rows": len(intraday_frame.index) - len(intraday),
                "daily_duplicate_timestamps": int(daily_frame.index.duplicated().sum()),
                "intraday_duplicate_timestamps": int(intraday_frame.index.duplicated().sum()),
                "missing_daily_closes": int(daily_frame["Close"].isna().sum()),
                "missing_daily_sessions": _missing_daily_sessions(daily, timezone),
                "missing_intraday_closes": int(intraday_frame["Close"].isna().sum()),
                "missing_intraday_intervals": _missing_intraday_intervals(intraday, timezone),
                "trailing_missing_intraday_intervals": _trailing_missing_intraday_intervals(
                    intraday, timezone, cutoff
                ),
            },
        )


class FixtureProvider:
    """Expand compact checked-in seeds so tests exercise the real service path."""

    @staticmethod
    def _payloads() -> tuple[dict[str, Any], ...]:
        return tuple(
            json.loads(files("stock_probs.fixtures").joinpath(name).read_text())
            for name in ("acdc.json", "spy.json")
        )

    @staticmethod
    def _news_payload() -> dict[str, list[dict[str, Any]]]:
        payload = json.loads(files("stock_probs.fixtures").joinpath("news.json").read_text())
        return cast(
            dict[str, list[dict[str, Any]]],
            {symbol: items for symbol, items in payload.items() if not symbol.startswith("_")},
        )

    @staticmethod
    def _identity(
        payload: Mapping[str, Any], symbol: str, provider_as_of: datetime
    ) -> InstrumentIdentity:
        base_symbol = str(payload["symbol"])
        scenario = symbol != base_symbol
        display_name = str(payload["display_name"])
        company_name = str(payload["company_name"])
        if scenario:
            # Browser-only aliases are labelled as deterministic scenarios rather than asserted
            # to be real Yahoo listings. Company lookup itself returns only canonical fixtures.
            display_name = f"{display_name} ({symbol} deterministic scenario)"
            company_name = display_name
        return InstrumentIdentity(
            canonical_symbol=symbol,
            display_name=display_name,
            company_name=company_name,
            exchange=str(payload["exchange"]),
            currency=str(payload["currency"]),
            timezone=str(payload["timezone"]),
            quote_type=str(payload["quote_type"]),
            asset_type=str(payload["asset_type"]),
            provider=FIXTURE_PROVIDER_NAME,
            provider_as_of=provider_as_of.astimezone(UTC),
        )

    def lookup(
        self, query: str, limit: int = MAX_LOOKUP_RESULTS, now: datetime | None = None
    ) -> tuple[InstrumentIdentity, ...]:
        """Return stable checked-in company matches without accepting arbitrary fake symbols."""

        normalized_query = normalize_lookup_query(query)
        _validate_lookup_limit(limit)
        requested_at = now or datetime.now(UTC)
        if requested_at.tzinfo is None:
            raise DomainError(
                "ambiguous_provider_time", "Fixture lookup time must include an offset."
            )
        if normalized_query.upper() == "FAIL":
            raise DomainError(
                "provider_unavailable", "Deterministic provider failure.", status_code=502
            )
        needle = normalized_query.casefold()
        matches: list[tuple[tuple[int, str], InstrumentIdentity]] = []
        for payload in self._payloads():
            symbol = str(payload["symbol"])
            identity = self._identity(payload, symbol, requested_at)
            searchable = " ".join(
                (identity.canonical_symbol, identity.display_name, identity.company_name)
            ).casefold()
            if needle not in searchable:
                continue
            rank = (
                0
                if needle == identity.canonical_symbol.casefold()
                else 1
                if identity.company_name.casefold().startswith(needle)
                else 2
            )
            matches.append(((rank, identity.canonical_symbol), identity))
        return tuple(identity for _, identity in sorted(matches)[:limit])

    def fetch(self, symbol: str, asset_type: str, now: datetime) -> MarketData:
        if now.tzinfo is None:
            raise DomainError(
                "ambiguous_provider_time", "Fixture request time must include an offset."
            )
        if asset_type not in {"stock", "etf"}:
            raise DomainError("unsupported_asset", "Only stocks and ETFs are supported.")
        normalized_symbol = normalize_symbol(symbol)
        if normalized_symbol == "FAIL":
            raise DomainError(
                "provider_unavailable", "Deterministic provider failure.", status_code=502
            )
        fixture_symbols = {
            "ACDC": "ACDC",
            "ACDC-D": "ACDC",
            "ACDC-M": "ACDC",
            "STALE": "ACDC",
            "SPY": "SPY",
            "SPY-D": "SPY",
            "SPY-M": "SPY",
        }
        base_symbol = fixture_symbols.get(normalized_symbol)
        if base_symbol is None:
            raise DomainError(
                "symbol_not_found",
                "The deterministic fixture has no instrument with that symbol.",
                status_code=404,
            )
        payload = next(
            item for item in self._payloads() if str(item["symbol"]) == base_symbol
        )
        if payload["asset_type"] != asset_type:
            raise DomainError(
                "asset_type_mismatch",
                f"The deterministic fixture classifies {normalized_symbol} as "
                f"{payload['asset_type']}, not {asset_type}.",
            )
        fixture_name = f"{base_symbol.lower()}.json"
        identity = self._identity(payload, normalized_symbol, now)
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
        daily = [bar for bar in daily if bar.timestamp.astimezone(UTC) <= now.astimezone(UTC)]
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
        # Mirror the live adapter: a deterministic response ends at the exact completed-bar cutoff.
        intraday = [bar for bar in intraday if bar.end.astimezone(UTC) <= now.astimezone(UTC)]
        if normalized_symbol == "STALE":
            # Browser regressions need a deterministic stale success, not a fabricated failure.
            cutoff = datetime(2025, 1, 9, tzinfo=zone).date()
            intraday = [bar for bar in intraday if bar.timestamp.astimezone(zone).date() < cutoff]
        return MarketData(
            symbol=identity.canonical_symbol,
            display_name=identity.display_name,
            company_name=identity.company_name,
            asset_type=asset_type,
            quote_type=identity.quote_type,
            exchange=identity.exchange,
            timezone=identity.timezone,
            currency=identity.currency,
            provider=identity.provider,
            fetched_at=now.astimezone(UTC),
            query={
                "fixture": fixture_name,
                "requested_as_of": now.astimezone(UTC).isoformat(),
                "daily": "1d/2y",
                "intraday": "5m/60d",
                "mode": "current",
                "data_cutoff": now.astimezone(UTC).isoformat(),
            },
            daily=tuple(daily),
            intraday=tuple(intraday),
            provider_metadata={
                **payload["provider_metadata"],
                "fixture_contract": "compact-seed-v1",
                "fixture_base_symbol": base_symbol,
                "identity_source": "checked_in_fixture",
                "exchange_timezone": identity.timezone,
                "session_scope": "regular session only (prepost=False)",
                "intraday_archive_limit": {
                    "approximate_days": YAHOO_INTRADAY_ARCHIVE_APPROXIMATE_DAYS,
                    "statement": (
                        "Yahoo five-minute history is limited to approximately 60 recent days; "
                        "this deterministic fixture is smaller and makes no live coverage claim"
                    ),
                },
                "daily_coverage": _coverage(tuple(daily)),
                "intraday_coverage": _coverage(tuple(intraday)),
                "daily_returned_rows": len(daily),
                "intraday_returned_rows": len(intraday),
                "daily_normalized_rows": len(daily),
                "intraday_normalized_rows": len(intraday),
                "daily_rejected_rows": 0,
                "intraday_rejected_rows": 0,
                "daily_duplicate_timestamps": 0,
                "intraday_duplicate_timestamps": 0,
                "missing_daily_closes": 0,
                "missing_daily_sessions": 0,
                "missing_intraday_closes": 0,
                "missing_intraday_intervals": 0,
                "trailing_missing_intraday_intervals": 0,
            },
        )

    def fetch_news(
        self, symbol: str, limit: int = 5, now: datetime | None = None
    ) -> NewsData:
        """Return checked-in current headlines without touching forecast fixture data."""

        normalized_symbol = normalize_symbol(symbol)
        _validate_news_limit(limit)
        requested_at = now or datetime.now(UTC)
        if requested_at.tzinfo is None:
            raise DomainError(
                "ambiguous_provider_time", "Fixture news time must include an offset."
            )
        if normalized_symbol == "FAIL":
            raise DomainError(
                "provider_unavailable", "Deterministic news provider failure.", status_code=502
            )
        aliases = {
            "ACDC-D": "ACDC",
            "ACDC-M": "ACDC",
            "SPY-D": "SPY",
            "SPY-M": "SPY",
            "STALE": "ACDC",
        }
        fixture_symbol = aliases.get(normalized_symbol, normalized_symbol)
        payload = self._news_payload().get(fixture_symbol)
        if payload is None:
            raise DomainError(
                "provider_unavailable",
                "The deterministic fixture has no news for that symbol.",
                status_code=502,
            )
        items = tuple(
            NewsItem(
                id=item["uuid"],
                title=item["title"],
                publisher=item.get("publisher"),
                published_at=datetime.fromtimestamp(item["providerPublishTime"], UTC),
                url=item["link"],
                related_symbols=(
                    tuple(item["relatedTickers"]) if "relatedTickers" in item else None
                ),
            )
            for item in payload[:limit]
        )
        return NewsData(
            normalized_symbol,
            FIXTURE_PROVIDER_NAME,
            requested_at.astimezone(UTC),
            items,
        )

    def fetch_at_cutoff(
        self, symbol: str, asset_type: str, cutoff: datetime, now: datetime
    ) -> MarketData:
        """Recreate fixture data eligible at cutoff while recording the later retrieval time."""

        if cutoff.tzinfo is None or now.tzinfo is None:
            raise DomainError(
                "ambiguous_historical_cutoff", "Historical cutoff times must include an offset."
            )
        if cutoff.astimezone(UTC) > now.astimezone(UTC):
            raise DomainError(
                "future_historical_cutoff", "Historical cutoff cannot be in the future."
            )
        data = self.fetch(symbol, asset_type, cutoff)
        return replace(
            data,
            fetched_at=now.astimezone(UTC),
            query={
                **data.query,
                "mode": "historical_cutoff",
                "requested_as_of": now.astimezone(UTC).isoformat(),
                "data_cutoff": cutoff.astimezone(UTC).isoformat(),
            },
        )


def _validate_lookup_limit(limit: int) -> None:
    """Keep one lookup to a small, predictable number of metadata hydration calls."""

    if type(limit) is not int or not 1 <= limit <= MAX_LOOKUP_RESULTS:
        raise DomainError(
            "invalid_lookup_limit",
            f"Lookup limit must be between 1 and {MAX_LOOKUP_RESULTS}.",
        )


def _validate_news_limit(limit: int) -> None:
    if type(limit) is not int or not 1 <= limit <= MAX_NEWS_RESULTS:
        raise DomainError(
            "invalid_news_limit",
            f"News limit must be between 1 and {MAX_NEWS_RESULTS}.",
        )


def _metadata_text(value: Any, field: str, maximum: int) -> str:
    """Reject missing, oversized, or control-bearing Yahoo labels before persistence/UI use."""

    if not isinstance(value, str):
        raise DomainError(
            "provider_metadata_unavailable",
            f"Yahoo did not return a usable instrument {field}.",
            status_code=502,
        )
    text = value.strip()
    if (
        not text
        or len(text) > maximum
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise DomainError(
            "provider_metadata_unavailable",
            f"Yahoo did not return a usable instrument {field}.",
            status_code=502,
        )
    return text


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
