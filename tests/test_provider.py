"""Provider adapter tests pin yfinance calls and normalized provenance without network access."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from stock_probs.domain import DomainError
from stock_probs.provider import YahooProvider


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
        frame.attrs["history_metadata"] = self.metadata()
        return frame

    def metadata(self):
        return {
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

    assert [(call["period"], call["interval"]) for call in FakeTicker.calls] == [
        ("2y", "1d"),
        ("5d", "5m"),
    ]
    assert all(call["prepost"] is False and call["timeout"] == 3 for call in FakeTicker.calls)
    assert data.daily[0].timestamp.hour == 16
    assert data.intraday[0].duration_seconds == 300
    assert data.provider_metadata["intraday_coverage"]["count"] == 3
    assert isinstance(data.provider_metadata["regular_session"]["start"], float)
    assert data.fetched_at == response_at
    assert data.query["requested_as_of"] == now.isoformat()


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
            return metadata

    monkeypatch.setattr("stock_probs.provider.yf.Ticker", StockTicker)
    data = YahooProvider().fetch("BRK-B", "stock", datetime(2025, 1, 3, 15, 0, tzinfo=UTC))

    assert StockTicker.seen_symbols == ["BRK-B"]
    assert data.symbol == "BRK-B" and data.asset_type == "stock"


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
            return frame

    monkeypatch.setattr("stock_probs.provider.yf.Ticker", GappedTicker)

    data = YahooProvider().fetch("SPY", "etf", datetime(2025, 1, 3, 15, 0, tzinfo=UTC))

    assert data.provider_metadata["missing_daily_sessions"] == 1
    # At 10:00 local, 09:45, 09:50, and 09:55 are completed but absent after 09:40.
    assert data.provider_metadata["trailing_missing_intraday_intervals"] == 3
