"""Quote and chart provider capabilities remain bounded and honestly labelled."""

from datetime import UTC, datetime

import pandas as pd
import pytest

from stock_probs.domain import DomainError
from stock_probs.provider import FixtureProvider, YahooProvider
from stock_probs.service import ForecastService

NOW = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)


class QuoteTicker:
    """Provide the one timeout-bounded chart surface used by capability tests."""

    calls: list[dict[str, object]] = []

    def __init__(self, symbol: str):
        self.symbol = symbol

    def history(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(kwargs)
        interval = str(kwargs["interval"])
        frequency = {"1m": "1min", "5m": "5min", "1h": "1h", "1d": "1D"}[interval]
        index = pd.date_range("2025-01-10 09:30", periods=3, freq=frequency, tz="America/New_York")
        frame = pd.DataFrame(
            {
                "Open": [99.5, 100.0, 100.5],
                "High": [100.25, 100.75, 101.25],
                "Low": [99.25, 99.75, 100.25],
                "Close": [100.0, 100.5, 101.0],
                "Volume": [10, 20, 30],
            },
            index=index,
        )
        frame.attrs["history_metadata"] = {
            "symbol": self.symbol,
            "shortName": "SPDR S&P 500 ETF Trust",
            "longName": "SPDR S&P 500 ETF Trust",
            "instrumentType": "ETF",
            "exchangeName": "PCX",
            "exchangeTimezoneName": "America/New_York",
            "currency": "USD",
            "dataGranularity": interval,
            "exchangeDataDelayedBy": 15,
            "chartPreviousClose": 99.0,
        }
        return frame


class BoundaryQuoteTicker:
    """Return a completed bar immediately before now and an in-progress next bar."""

    starts = ("2025-01-10 12:02", "2025-01-10 12:03")
    closes = (100.5, 101.0)

    def __init__(self, symbol: str):
        self.symbol = symbol

    def history(self, **kwargs: object) -> pd.DataFrame:
        index = pd.DatetimeIndex(self.starts, tz="America/New_York")
        frame = pd.DataFrame(
            {
                "Open": self.closes,
                "High": self.closes,
                "Low": self.closes,
                "Close": self.closes,
                "Volume": list(range(20, 20 + 10 * len(self.closes), 10)),
            },
            index=index,
        )
        frame.attrs["history_metadata"] = {
            "symbol": self.symbol,
            "shortName": "SPDR S&P 500 ETF Trust",
            "longName": "SPDR S&P 500 ETF Trust",
            "instrumentType": "ETF",
            "exchangeName": "PCX",
            "exchangeTimezoneName": "America/New_York",
            "currency": "USD",
            "dataGranularity": str(kwargs["interval"]),
            "exchangeDataDelayedBy": 15,
            "chartPreviousClose": 99.0,
        }
        return frame


def test_fixture_clock_quote_chart_and_service_handoffs_are_deterministic():
    provider = FixtureProvider(clock=lambda: NOW)
    quote = provider.quote_snapshot("SPY", "etf")
    chart = provider.historical_bars("SPY", "etf")

    assert quote == provider.quote_snapshot("SPY", "etf")
    assert quote.label == "Deterministic simulated fixture quote; not live market data."
    assert quote.last_trade == quote.price
    assert quote.open is not None and quote.low is not None and quote.high is not None
    assert quote.previous_close is not None
    assert quote.change == pytest.approx(quote.last_trade - quote.previous_close)
    assert quote.change_percent == pytest.approx(quote.change / quote.previous_close * 100)
    assert quote.volume is None
    assert chart.range == "1mo" and chart.interval == "1d" and chart.bars
    assert quote.delayed is False

    service = ForecastService(object(), provider, lambda: NOW)  # type: ignore[arg-type]
    assert service.quote_snapshot("SPY", "etf")["as_of"] == quote.as_of.isoformat()
    assert service.historical_bars("SPY", "etf")["range"] == "1mo"


def test_yahoo_quote_is_delay_labelled(monkeypatch):
    QuoteTicker.calls = []
    monkeypatch.setattr("stock_probs.provider.yf.Ticker", QuoteTicker)
    provider = YahooProvider(timeout=2, clock=lambda: NOW)

    quote = provider.quote_snapshot("SPY", "etf", NOW)
    chart = provider.historical_bars("SPY", "etf", now=NOW)

    assert quote.price == 101.0
    assert quote.as_of == datetime(2025, 1, 10, 14, 33, tzinfo=UTC)
    assert quote.as_of.tzinfo == UTC
    assert quote.delayed is True and quote.delay_minutes == 15
    assert "approximately 15 minute delay" in quote.label
    assert quote.open == 99.5
    assert quote.high == 101.25
    assert quote.low == 99.25
    assert quote.previous_close == 99.0
    assert quote.volume == 60
    assert quote.last_trade == 101.0
    assert quote.change == 2.0
    assert quote.change_percent == pytest.approx(2.0202020202)
    assert chart.range == "1mo" and chart.interval == "1d"
    assert QuoteTicker.calls[-1]["period"] == "1mo"
    assert QuoteTicker.calls[-1]["interval"] == "1d"
    assert all(call["timeout"] == 2 and call["auto_adjust"] is False for call in QuoteTicker.calls)


def test_yahoo_quote_excludes_the_minute_starting_at_the_reference_boundary(monkeypatch):
    monkeypatch.setattr("stock_probs.provider.yf.Ticker", BoundaryQuoteTicker)
    provider = YahooProvider(timeout=2, clock=lambda: NOW)

    quote = provider.quote_snapshot("SPY", "etf", NOW)

    assert quote.price == 100.5
    assert quote.as_of == NOW
    assert quote.as_of <= NOW


def test_yahoo_quote_without_a_completed_minute_is_provider_unavailable(monkeypatch):
    monkeypatch.setattr("stock_probs.provider.yf.Ticker", BoundaryQuoteTicker)
    monkeypatch.setattr(BoundaryQuoteTicker, "starts", ("2025-01-10 12:03",))
    monkeypatch.setattr(BoundaryQuoteTicker, "closes", (101.0,))

    with pytest.raises(DomainError) as failure:
        YahooProvider(timeout=2, clock=lambda: NOW).quote_snapshot("SPY", "etf", NOW)

    assert failure.value.code == "provider_market_data_invalid"
    assert failure.value.status_code == 502
    assert failure.value.message == "Yahoo Finance returned no usable quote price."


def test_yahoo_chart_passes_requested_range_to_daily_history(monkeypatch):
    QuoteTicker.calls = []
    monkeypatch.setattr("stock_probs.provider.yf.Ticker", QuoteTicker)

    chart = YahooProvider(timeout=2, clock=lambda: NOW).historical_bars(
        "SPY", "etf", now=NOW, range="3mo"
    )

    assert chart.range == "3mo"
    assert chart.interval == "1d"
    assert QuoteTicker.calls[-1]["period"] == "3mo"
    assert QuoteTicker.calls[-1]["interval"] == "1d"


@pytest.mark.parametrize("requested_range", ["5d", "1mo", "3mo", "6mo", "1y"])
def test_fixture_chart_preserves_each_bounded_range(requested_range):
    chart = FixtureProvider(clock=lambda: NOW).historical_bars(
        "SHOP.TO", "stock", range=requested_range
    )

    assert chart.range == requested_range
    assert chart.interval == "1d"
    assert chart.bars
    assert all(bar.end <= NOW for bar in chart.bars)


def test_chart_range_rejects_values_outside_the_provider_allowlist():
    with pytest.raises(DomainError) as failure:
        FixtureProvider(clock=lambda: NOW).historical_bars("SPY", "etf", range="2y")

    assert failure.value.code == "invalid_chart_range"
    assert failure.value.status_code == 422


def test_market_depth_is_not_a_provider_or_service_capability():
    assert not hasattr(YahooProvider, "market_depth")
    assert not hasattr(FixtureProvider, "market_depth")
    assert not hasattr(ForecastService, "market_depth")


def test_yahoo_missing_delay_metadata_never_becomes_a_live_or_fifteen_minute_claim(
    monkeypatch,
):
    monkeypatch.setattr("stock_probs.provider.yf.Ticker", QuoteTicker)
    original = QuoteTicker.history

    def history_without_delay(self, **kwargs):
        frame = original(self, **kwargs)
        del frame.attrs["history_metadata"]["exchangeDataDelayedBy"]
        return frame

    monkeypatch.setattr(QuoteTicker, "history", history_without_delay)
    quote = YahooProvider(timeout=2, clock=lambda: NOW).quote_snapshot("SPY", "etf", NOW)

    assert quote.delayed is False and quote.delay_minutes is None
    assert quote.label == (
        "Yahoo Finance quote; provider delay is unavailable and real-time is not claimed."
    )


def test_yahoo_missing_optional_quote_values_remain_unavailable(monkeypatch):
    monkeypatch.setattr("stock_probs.provider.yf.Ticker", QuoteTicker)
    original = QuoteTicker.history

    def history_without_optional_values(self, **kwargs):
        frame = original(self, **kwargs)[["Close"]]
        frame.attrs["history_metadata"].pop("chartPreviousClose")
        return frame

    monkeypatch.setattr(QuoteTicker, "history", history_without_optional_values)
    quote = YahooProvider(timeout=2, clock=lambda: NOW).quote_snapshot("SPY", "etf", NOW)

    assert quote.last_trade == quote.price == 101.0
    assert quote.open is quote.high is quote.low is None
    assert quote.previous_close is quote.volume is None
    assert quote.change is quote.change_percent is None


def test_market_capabilities_reject_naive_fixture_clock():
    provider = FixtureProvider(clock=lambda: datetime(2025, 1, 10))

    with pytest.raises(DomainError) as ambiguous:
        provider.quote_snapshot("SPY", "etf")
    assert ambiguous.value.code == "ambiguous_provider_time"


@pytest.mark.parametrize(
    ("method", "arguments", "message"),
    [
        ("quote_snapshot", ("SPY", "etf"), "The quote provider failed unexpectedly."),
        ("historical_bars", ("SPY", "etf"), "The chart provider failed unexpectedly."),
    ],
)
def test_service_capabilities_share_exception_mapping_and_release_slots(
    monkeypatch, method, arguments, message
):
    provider = FixtureProvider(clock=lambda: NOW)

    def fail(*_args):
        raise RuntimeError("provider detail")

    monkeypatch.setattr(provider, method, fail)
    service = ForecastService(
        object(), provider, lambda: NOW, max_provider_concurrency=1
    )  # type: ignore[arg-type]

    with pytest.raises(DomainError) as failure:
        getattr(service, method)(*arguments)

    assert failure.value.code == "provider_unavailable"
    assert failure.value.status_code == 502
    assert failure.value.message == message
    assert service.provider_slots.acquire(blocking=False)
    service.provider_slots.release()
