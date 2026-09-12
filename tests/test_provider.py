"""Provider adapter tests pin yfinance calls and normalized provenance without network access."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from stock_probs.domain import DomainError
from stock_probs.provider import MAX_NEWS_BODY_BYTES, FixtureProvider, YahooProvider


class FakeTicker:
    """Supply the minimal stable yfinance surface used by YahooProvider."""

    calls: list[dict] = []

    def __init__(self, symbol):
        self.symbol = symbol

    def history(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["interval"] == "1d":
            index = pd.date_range("2025-01-01", periods=3, freq="D", tz="America/New_York")
        else:
            index = pd.date_range("2025-01-03 09:30", periods=3, freq="5min", tz="America/New_York")
        frame = pd.DataFrame({"Close": [100.0, 101.0, 102.0]}, index=index)
        # Real yfinance history caches this same chart metadata during its timeout-bounded call.
        metadata = self.metadata()
        metadata["dataGranularity"] = kwargs["interval"]
        frame.attrs["history_metadata"] = metadata
        return frame

    def metadata(self):
        return {
            "symbol": self.symbol,
            "shortName": "SPDR S&P 500 ETF Trust",
            "longName": "SPDR S&P 500 ETF Trust",
            "instrumentType": "ETF",
            "exchangeName": "PCX",
            "exchangeTimezoneName": "America/New_York",
            "currency": "USD",
            "dataGranularity": "5m",
            # Current yfinance releases normalize these boundaries to pandas timestamps.
            "currentTradingPeriod": {
                "regular": {
                    "start": pd.Timestamp("2025-01-03 09:30", tz="America/New_York"),
                    "end": pd.Timestamp("2025-01-03 16:00", tz="America/New_York"),
                }
            },
        }

    def get_history_metadata(self):
        """Fail if the adapter regresses to yfinance's separately unbounded metadata path."""

        raise AssertionError("metadata must come from the bounded history response")


def test_yfinance_adapter_uses_exact_bounded_queries(monkeypatch):
    FakeTicker.calls = []
    monkeypatch.setattr("stock_probs.provider.yf.Ticker", FakeTicker)
    now = datetime(2025, 1, 3, 15, 0, tzinfo=UTC)

    response_at = datetime(2025, 1, 3, 15, 0, 2, tzinfo=UTC)
    data = YahooProvider(timeout=3, clock=lambda: response_at).fetch("SPY", "etf", now)

    daily_call = next(call for call in FakeTicker.calls if call["interval"] == "1d")
    intraday_call = next(call for call in FakeTicker.calls if call["interval"] == "5m")
    assert daily_call["period"] == "2y"
    assert intraday_call["start"] == now - timedelta(days=59)
    assert intraday_call["end"] == now + timedelta(days=1)
    assert all(call["prepost"] is False and call["timeout"] == 3 for call in FakeTicker.calls)
    assert data.daily[0].timestamp.hour == 16
    assert data.intraday[0].duration_seconds == 300
    assert data.provider_metadata["intraday_coverage"]["count"] == 3
    assert data.provider_metadata["intraday_archive_limit"]["approximate_days"] == 60
    assert data.provider_metadata["daily_data_granularity"] == "1d"
    assert data.query["intraday"]["start"] == (now - timedelta(days=59)).isoformat()
    assert data.query["intraday"]["end"] == (now + timedelta(days=1)).isoformat()
    assert data.query["intraday"]["returned_coverage"] == data.provider_metadata[
        "intraday_coverage"
    ]
    assert isinstance(data.provider_metadata["regular_session"]["start"], float)
    assert data.fetched_at == response_at
    assert data.query["requested_as_of"] == now.isoformat()
    assert all(bar.end <= now for bar in (*data.daily, *data.intraday))
    assert data.identity.as_dict() == {
        "canonical_symbol": "SPY",
        "display_name": "SPDR S&P 500 ETF Trust",
        "company_name": "SPDR S&P 500 ETF Trust",
        "exchange": "PCX",
        "currency": "USD",
        "timezone": "America/New_York",
        "quote_type": "ETF",
        "asset_type": "etf",
        "provider": "Yahoo Finance",
        "provider_as_of": response_at.isoformat(),
    }


def test_yfinance_historical_cutoff_uses_explicit_bounded_ranges(monkeypatch):
    """Fresh reconstruction never substitutes a current rolling-period provider request."""

    FakeTicker.calls = []
    monkeypatch.setattr("stock_probs.provider.yf.Ticker", FakeTicker)
    cutoff = datetime(2025, 1, 3, 15, 0, tzinfo=UTC)
    performed = cutoff + timedelta(days=2)

    data = YahooProvider(timeout=3, clock=lambda: performed).fetch_at_cutoff(
        "SPY", "etf", cutoff, performed
    )

    assert len(FakeTicker.calls) == 2
    assert all("period" not in call for call in FakeTicker.calls)
    assert all(isinstance(call["start"], datetime) for call in FakeTicker.calls)
    assert all(isinstance(call["end"], datetime) for call in FakeTicker.calls)
    intraday_call = next(call for call in FakeTicker.calls if call["interval"] == "5m")
    assert intraday_call["start"] == cutoff - timedelta(days=57)
    assert intraday_call["end"] == cutoff + timedelta(days=1)
    assert data.query["mode"] == "historical_cutoff"
    assert data.query["data_cutoff"] == cutoff.isoformat()
    assert data.query["requested_as_of"] == performed.isoformat()
    assert data.fetched_at == performed


def test_yfinance_historical_cutoff_rejects_future_and_archive_overflow(monkeypatch):
    monkeypatch.setattr(
        "stock_probs.provider.yf.Ticker",
        lambda *args, **kwargs: pytest.fail("invalid cutoff must fail before Yahoo access"),
    )
    now = datetime(2025, 3, 10, tzinfo=UTC)

    with pytest.raises(DomainError) as future:
        YahooProvider().fetch_at_cutoff("SPY", "etf", now + timedelta(seconds=1), now)
    assert future.value.code == "future_historical_cutoff"

    with pytest.raises(DomainError) as unavailable:
        YahooProvider().fetch_at_cutoff("SPY", "etf", now - timedelta(days=50), now)
    assert unavailable.value.code == "historical_cutoff_unavailable"


def test_yfinance_accepts_an_arbitrary_equity_symbol_under_the_same_contract(monkeypatch):
    """The live adapter is symbol-driven rather than hard-coded to checked-in fixtures."""

    class StockTicker(FakeTicker):
        seen_symbols: list[str] = []

        def __init__(self, symbol):
            super().__init__(symbol)
            self.seen_symbols.append(symbol)

        def metadata(self):
            metadata = super().metadata()
            metadata["instrumentType"] = "EQUITY"
            metadata["shortName"] = "Berkshire Hathaway Inc."
            metadata["longName"] = "Berkshire Hathaway Inc."
            return metadata

    monkeypatch.setattr("stock_probs.provider.yf.Ticker", StockTicker)
    data = YahooProvider().fetch("BRK-B", "stock", datetime(2025, 1, 3, 15, 0, tzinfo=UTC))

    assert StockTicker.seen_symbols == ["BRK-B"]
    assert data.symbol == "BRK-B" and data.asset_type == "stock"
    assert data.company_name == "Berkshire Hathaway Inc."


def test_yfinance_company_lookup_uses_bounded_search_and_identity_calls(monkeypatch):
    """Lookup disables unrelated Yahoo payloads and hydrates complete identity exactly once."""

    class FakeSearch:
        calls: list[tuple[str, dict]] = []

        def __init__(self, query, **kwargs):
            self.calls.append((query, kwargs))
            self.quotes = [
                {
                    "symbol": "SPY",
                    "shortname": "SPDR S&P 500 ETF Trust",
                    "longname": "SPDR S&P 500 ETF Trust",
                    "exchange": "PCX",
                    "quoteType": "ETF",
                },
                {"symbol": "^GSPC", "quoteType": "INDEX"},
            ]

    FakeTicker.calls = []
    monkeypatch.setattr("stock_probs.provider.yf.Search", FakeSearch)
    monkeypatch.setattr("stock_probs.provider.yf.Ticker", FakeTicker)
    now = datetime(2025, 1, 3, 15, 0, tzinfo=UTC)

    identities = YahooProvider(timeout=2, clock=lambda: now).lookup("S&P 500", 2, now)

    assert len(identities) == 1
    assert identities[0].canonical_symbol == "SPY"
    assert identities[0].currency == "USD"
    query, settings = FakeSearch.calls[0]
    assert query == "S&P 500"
    assert settings["max_results"] == 2 and settings["timeout"] == 2
    assert settings["news_count"] == settings["lists_count"] == settings["recommended"] == 0
    assert [(call["period"], call["interval"]) for call in FakeTicker.calls] == [("5d", "1d")]


def test_yfinance_lookup_rejects_unbounded_limit_before_network(monkeypatch):
    monkeypatch.setattr(
        "stock_probs.provider.yf.Search",
        lambda *args, **kwargs: pytest.fail("invalid bounds must fail before Yahoo access"),
    )

    with pytest.raises(DomainError) as failure:
        YahooProvider().lookup("SPY", 6, datetime.now(UTC))
    assert failure.value.code == "invalid_lookup_limit"


@pytest.mark.parametrize(
    ("query", "symbol", "asset_type", "quote_type"),
    [
        ("ProFrac Holding", "ACDC", "stock", "EQUITY"),
        ("s&p 500", "SPY", "etf", "ETF"),
    ],
)
def test_fixture_lookup_is_deterministic_and_returns_real_fixture_identity(
    query, symbol, asset_type, quote_type
):
    now = datetime(2025, 1, 3, 15, 0, tzinfo=UTC)

    first = FixtureProvider().lookup(query, 5, now)
    second = FixtureProvider().lookup(query, 5, now)

    assert first == second
    assert [(item.canonical_symbol, item.asset_type, item.quote_type) for item in first] == [
        (symbol, asset_type, quote_type)
    ]
    assert first[0].display_name and first[0].company_name


def test_fixture_rejects_unknown_symbols_instead_of_fabricating_identity():
    with pytest.raises(DomainError) as failure:
        FixtureProvider().fetch("MSFT", "stock", datetime.now(UTC))
    assert failure.value.code == "symbol_not_found"


def test_daily_rows_use_the_scheduled_early_close_and_ignore_non_sessions():
    """Daily labels become actual close instants, including the post-Thanksgiving close."""

    index = pd.DatetimeIndex(
        [
            pd.Timestamp("2024-11-28", tz="America/New_York"),
            pd.Timestamp("2024-11-29", tz="America/New_York"),
        ]
    )
    frame = pd.DataFrame({"Close": [100.0, 101.0]}, index=index)

    bars = YahooProvider._daily_bars(frame, "America/New_York")

    assert len(bars) == 1
    assert bars[0].timestamp.isoformat() == "2024-11-29T13:00:00-05:00"


def test_non_finite_provider_prices_are_not_normalized_as_market_bars():
    """NaN and infinity cannot enter immutable provider fingerprints."""

    index = pd.date_range("2025-01-02", periods=3, freq="D", tz="America/New_York")
    frame = pd.DataFrame({"Close": [100.0, float("nan"), float("inf")]}, index=index)

    bars = YahooProvider._daily_bars(frame, "America/New_York")

    assert len(bars) == 1 and bars[0].close == 100.0


def test_yfinance_asset_type_mismatch_is_classified(monkeypatch):
    monkeypatch.setattr("stock_probs.provider.yf.Ticker", FakeTicker)
    with pytest.raises(DomainError) as failure:
        YahooProvider().fetch("SPY", "stock", datetime.now(UTC))
    assert failure.value.code == "asset_type_mismatch"


def test_yfinance_requires_unambiguous_asset_and_session_metadata(monkeypatch):
    class AmbiguousTicker(FakeTicker):
        """Return bars but omit facts that the forecast must never guess."""

        def metadata(self):
            return {"instrumentType": "INDEX", "exchangeTimezoneName": ""}

    monkeypatch.setattr("stock_probs.provider.yf.Ticker", AmbiguousTicker)
    with pytest.raises(DomainError) as failure:
        YahooProvider().fetch("SPY", "etf", datetime.now(UTC))
    assert failure.value.code == "unsupported_asset"


@pytest.mark.parametrize(("requested", "reported"), [("1d", "1wk"), ("5m", "15m")])
def test_yfinance_rejects_silent_interval_substitution(monkeypatch, requested, reported):
    """Bars are never relabelled as daily or five-minute when Yahoo reports another interval."""

    class SubstitutedTicker(FakeTicker):
        def history(self, **kwargs):
            frame = super().history(**kwargs)
            if kwargs["interval"] == requested:
                frame.attrs["history_metadata"]["dataGranularity"] = reported
            return frame

    monkeypatch.setattr("stock_probs.provider.yf.Ticker", SubstitutedTicker)

    with pytest.raises(DomainError) as failure:
        YahooProvider().fetch("SPY", "etf", datetime(2025, 1, 3, 15, 0, tzinfo=UTC))
    assert failure.value.code == "provider_interval_mismatch"


def test_yfinance_rejects_control_bearing_identity_metadata(monkeypatch):
    class UnsafeNameTicker(FakeTicker):
        def metadata(self):
            metadata = super().metadata()
            metadata["shortName"] = "unsafe\nname"
            return metadata

    monkeypatch.setattr("stock_probs.provider.yf.Ticker", UnsafeNameTicker)
    with pytest.raises(DomainError) as failure:
        YahooProvider().fetch("SPY", "etf", datetime.now(UTC))
    assert failure.value.code == "provider_metadata_unavailable"


def test_yfinance_history_failure_is_safely_classified(monkeypatch):
    class FailingTicker(FakeTicker):
        """Simulate yfinance transport internals without allowing their message to escape."""

        def history(self, **kwargs):
            raise RuntimeError("credential-like internal detail")

    monkeypatch.setattr("stock_probs.provider.yf.Ticker", FailingTicker)
    with pytest.raises(DomainError) as failure:
        YahooProvider().fetch("SPY", "etf", datetime.now(UTC))
    assert failure.value.code == "provider_unavailable"
    assert "internal" not in failure.value.message


def test_yfinance_metadata_is_reused_from_timeout_bounded_history(monkeypatch):
    """R-M05-3 eliminates the network-capable get_history_metadata call entirely."""

    monkeypatch.setattr("stock_probs.provider.yf.Ticker", FakeTicker)

    data = YahooProvider(timeout=0.25).fetch(
        "SPY", "etf", datetime(2025, 1, 3, 15, 0, tzinfo=UTC)
    )

    assert data.provider_metadata["data_granularity"] == "5m"


def test_provider_reports_omitted_daily_session_and_trailing_completed_bars(monkeypatch):
    """R-M03 provider provenance records holes that missing-value counts cannot reveal."""

    class GappedTicker(FakeTicker):
        def history(self, **kwargs):
            frame = super().history(**kwargs)
            if kwargs["interval"] == "1d":
                # January 3 is an eligible session between the two returned dates.
                frame = frame.iloc[[1, 2]].copy()
                frame.index = pd.DatetimeIndex(
                    [
                        pd.Timestamp("2025-01-02", tz="America/New_York"),
                        pd.Timestamp("2025-01-06", tz="America/New_York"),
                    ]
                )
            else:
                frame.index = pd.date_range(
                    "2025-01-07 09:30",
                    periods=3,
                    freq="5min",
                    tz="America/New_York",
                )
            return frame

    monkeypatch.setattr("stock_probs.provider.yf.Ticker", GappedTicker)

    data = YahooProvider().fetch("SPY", "etf", datetime(2025, 1, 7, 15, 0, tzinfo=UTC))

    assert data.provider_metadata["missing_daily_sessions"] == 1
    # At 10:00 local, 09:45, 09:50, and 09:55 are completed but absent after 09:40.
    assert data.provider_metadata["trailing_missing_intraday_intervals"] == 3


def _news_payload(news):
    return json.dumps({"news": news}).encode()


def _news_item(identifier="news-1", **changes):
    return {
        "uuid": identifier,
        "title": "Markets finish mixed",
        "publisher": "Example News",
        "providerPublishTime": 1736503200,
        "link": "https://finance.yahoo.com/news/markets-finish-mixed.html",
        "relatedTickers": ["SPY"],
        **changes,
    }


def fake_curl_session(handler):
    class Response:
        status_code = 200

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url, **kwargs):
            handler(self, url, kwargs)
            return Response()

    return Session


def test_yahoo_news_uses_one_request_local_exact_bounded_get(monkeypatch):
    calls = []
    sessions = []

    def handler(session, url, kwargs):
        sessions.append(session)
        calls.append((url, kwargs))
        payload = _news_payload(
            [
                _news_item(),
                _news_item("news-1", title="duplicate"),
                {
                    key: value
                    for key, value in _news_item(
                        "news-2", title="Second headline", publisher=None
                    ).items()
                    if key != "relatedTickers"
                },
            ]
        )
        assert kwargs["content_callback"](payload) == len(payload)

    monkeypatch.setattr(
        "stock_probs.provider.curl_requests.Session", fake_curl_session(handler)
    )
    as_of = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)

    result = YahooProvider(timeout=20, monotonic_clock=lambda: 100.0).fetch_news(
        " spy ", 2, as_of
    )

    assert len(sessions) == len(calls) == 1
    url, options = calls[0]
    assert url == "https://query2.finance.yahoo.com/v1/finance/search"
    assert options["params"] == {
        "q": "SPY",
        "quotesCount": 0,
        "newsCount": 2,
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
    assert options["timeout"] == 10
    assert options["allow_redirects"] is False
    assert options["discard_cookies"] is True
    assert result.as_of == as_of
    assert [item.id for item in result.items] == ["news-1", "news-2"]
    assert result.items[0].published_at.tzinfo is UTC
    assert result.items[1].publisher is None and result.items[1].related_symbols is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"news": None},
        {"news": [{}]},
        {"news": [_news_item(link="http://example.com/story")]},
        {"news": [_news_item(link="https://127.0.0.1/story")]},
        {"news": [_news_item(providerPublishTime="yesterday")]},
    ],
)
def test_yahoo_news_rejects_malformed_or_unsafe_payloads(monkeypatch, payload):
    def handler(_session, _url, kwargs):
        raw = json.dumps(payload).encode()
        kwargs["content_callback"](raw)

    monkeypatch.setattr(
        "stock_probs.provider.curl_requests.Session", fake_curl_session(handler)
    )

    with pytest.raises(DomainError) as failure:
        YahooProvider(monotonic_clock=lambda: 0.0).fetch_news("SPY")
    assert failure.value.status_code == 502


def test_yahoo_news_enforces_body_cap_during_receipt(monkeypatch):
    def handler(_session, _url, kwargs):
        accepted = kwargs["content_callback"](b"x" * (MAX_NEWS_BODY_BYTES + 1))
        assert accepted == 0
        raise RuntimeError("curl write aborted")

    monkeypatch.setattr(
        "stock_probs.provider.curl_requests.Session", fake_curl_session(handler)
    )

    with pytest.raises(DomainError, match="response size") as failure:
        YahooProvider(monotonic_clock=lambda: 0.0).fetch_news("SPY")
    assert failure.value.code == "provider_unavailable"


def test_yahoo_news_deadline_covers_processing_after_receipt(monkeypatch):
    class Clock:
        value = 0.0

        def __call__(self):
            return self.value

    clock = Clock()

    def handler(_session, _url, kwargs):
        payload = _news_payload([_news_item()])
        assert kwargs["content_callback"](payload) == len(payload)
        clock.value = 0.1

    monkeypatch.setattr(
        "stock_probs.provider.curl_requests.Session", fake_curl_session(handler)
    )

    with pytest.raises(DomainError, match="time boundary") as failure:
        YahooProvider(timeout=0.1, monotonic_clock=clock).fetch_news("SPY")
    assert failure.value.code == "provider_unavailable"


def test_fixture_news_is_deterministic_bounded_and_partial_metadata_is_honest():
    now = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)
    result = FixtureProvider().fetch_news("ACDC", 10, now)

    assert result == FixtureProvider().fetch_news("ACDC", 10, now)
    assert len(result.items) == 2
    assert result.items[1].publisher is None
    assert FixtureProvider().fetch_news("EMPTY", now=now).items == ()


def test_fixture_news_loader_ignores_metadata_and_keeps_symbol_entries():
    payload = FixtureProvider._news_payload()

    assert set(payload) == {"ACDC", "SPY", "EMPTY"}
    assert [item["uuid"] for item in payload["ACDC"]] == [
        "fixture-acdc-1",
        "fixture-acdc-2",
    ]


def test_yahoo_news_bounds_optional_related_symbols(monkeypatch):
    def handler(_session, _url, kwargs):
        payload = _news_payload(
            [_news_item(relatedTickers=[f"S{index}" for index in range(40)])]
        )
        kwargs["content_callback"](payload)

    monkeypatch.setattr(
        "stock_probs.provider.curl_requests.Session", fake_curl_session(handler)
    )

    result = YahooProvider(monotonic_clock=lambda: 0.0).fetch_news("SPY")
    assert result.items[0].related_symbols == tuple(f"S{index}" for index in range(32))
