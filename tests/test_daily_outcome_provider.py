"""Offline tests for the trusted daily outcome provider capability."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from stock_probs.domain import Bar
from stock_probs.outcome_collection import (
    ADJUSTMENT_BASIS,
    CorporateActionCheck,
    DailyOutcomeSeries,
    OutcomeSourceUnavailable,
)
from stock_probs.provider import FixtureProvider, YahooProvider
from stock_probs.service import ForecastService

ORIGIN = datetime(2025, 1, 2, 21, tzinfo=UTC)
TARGET = datetime(2025, 1, 3, 21, tzinfo=UTC)
NOW = TARGET + timedelta(minutes=5)
INDEX = pd.DatetimeIndex(["2025-01-02", "2025-01-03"], tz="America/New_York")


def _metadata(
    *,
    symbol: str = "SPY",
    currency: str = "USD",
    instrument_type: str = "ETF",
    timezone: str = "America/New_York",
    granularity: str = "1d",
) -> dict[str, str]:
    return {
        "symbol": symbol,
        "instrumentType": instrument_type,
        "currency": currency,
        "exchangeTimezoneName": timezone,
        "exchangeName": "PCX",
        "shortName": "SPDR S&P 500 ETF Trust",
        "longName": "SPDR S&P 500 ETF Trust",
        "dataGranularity": granularity,
    }


def _frame(
    *,
    actions: bool,
    metadata: dict[str, str],
    index: pd.DatetimeIndex = INDEX,
    closes: tuple[float, ...] = (100.0, 101.0),
    action_values: dict[str, tuple[float, ...]] | None = None,
) -> pd.DataFrame:
    frame = pd.DataFrame(
        {"Close": closes, "Adj Close": tuple(value + 20 for value in closes)}, index=index
    )
    if actions:
        values = action_values or {}
        frame["Dividends"] = values.get("Dividends", (0.0,) * len(index))
        frame["Stock Splits"] = values.get("Stock Splits", (0.0,) * len(index))
        if metadata["instrumentType"] == "ETF":
            frame["Capital Gains"] = values.get("Capital Gains", (0.0,) * len(index))
    frame.attrs["history_metadata"] = metadata
    return frame


class FakeTicker:
    def __init__(self, symbol: str, *, frame_factory=None):
        self.symbol = symbol
        self.calls: list[dict[str, object]] = []
        self.frame_factory = frame_factory or self._default_frame
        self.provider_slots = None

    def _default_frame(self, actions: bool) -> pd.DataFrame:
        return _frame(actions=actions, metadata=_metadata(symbol=self.symbol))

    def history(self, **kwargs: object) -> pd.DataFrame:
        if self.provider_slots is not None:
            assert not self.provider_slots.acquire(blocking=False)
        self.calls.append(kwargs)
        return self.frame_factory(bool(kwargs["actions"]))


def _install_ticker(monkeypatch, ticker: FakeTicker) -> None:
    monkeypatch.setattr("stock_probs.provider.yf.Ticker", lambda symbol: ticker)


def _fetch(provider: YahooProvider | None = None) -> DailyOutcomeSeries:
    return (provider or YahooProvider(timeout=1.0, clock=lambda: NOW)).fetch_daily_outcome_series(
        "SPY", "etf", ORIGIN, TARGET, NOW
    )


def test_yahoo_reads_unadjusted_bars_and_separate_explicit_action_interval(monkeypatch):
    ticker = FakeTicker("SPY")
    _install_ticker(monkeypatch, ticker)

    series = _fetch()

    assert [call["actions"] for call in ticker.calls] == [False, True]
    assert all(call["interval"] == "1d" for call in ticker.calls)
    assert all(call["auto_adjust"] is False for call in ticker.calls)
    assert all(call["timeout"] == 1.0 for call in ticker.calls)
    assert all(call["raise_errors"] is True for call in ticker.calls)
    assert ticker.calls[0]["start"] == ticker.calls[1]["start"]
    assert ticker.calls[0]["end"] == ticker.calls[1]["end"]
    assert series.adjustment_basis == ADJUSTMENT_BASIS
    assert tuple(bar.close for bar in series.bars) == (100.0, 101.0)
    assert tuple(bar.close for bar in series.bars) != (120.0, 121.0)
    assert series.corporate_actions is not None
    assert series.corporate_actions.complete is True
    assert series.corporate_actions.events == ()


@pytest.mark.parametrize(
    ("column", "value", "event_type"),
    [
        ("Dividends", 0.5, "Dividends"),
        ("Stock Splits", 2.0, "Stock Splits"),
        ("Capital Gains", 0.25, "Capital Gains"),
    ],
)
def test_action_interval_preserves_detected_dividend_or_split(
    monkeypatch, column, value, event_type
):
    def frames(actions: bool) -> pd.DataFrame:
        values = {column: (0.0, value)}
        return _frame(actions=actions, metadata=_metadata(), action_values=values)

    ticker = FakeTicker("SPY", frame_factory=frames)
    _install_ticker(monkeypatch, ticker)

    series = _fetch()

    assert series.corporate_actions is not None
    assert series.corporate_actions.events == ({"date": "2025-01-03", "types": (event_type,)},)


def test_action_interval_requires_all_etf_columns_and_numeric_coverage(monkeypatch):
    def missing_column(actions: bool) -> pd.DataFrame:
        frame = _frame(actions=actions, metadata=_metadata())
        if actions:
            frame = frame.drop(columns=["Capital Gains"])
        return frame

    ticker = FakeTicker("SPY", frame_factory=missing_column)
    _install_ticker(monkeypatch, ticker)
    with pytest.raises(OutcomeSourceUnavailable) as missing:
        _fetch()
    assert missing.value.reason_code == "corporate_action_unknown"

    def invalid_coverage(actions: bool) -> pd.DataFrame:
        frame = _frame(actions=actions, metadata=_metadata())
        if actions:
            frame.loc[INDEX[1], "Dividends"] = float("nan")
        return frame

    ticker = FakeTicker("SPY", frame_factory=invalid_coverage)
    _install_ticker(monkeypatch, ticker)
    with pytest.raises(OutcomeSourceUnavailable) as invalid:
        _fetch()
    assert invalid.value.reason_code == "corporate_action_unknown"


def test_action_interval_rejects_string_zero_as_unverified_clear(monkeypatch):
    def frames(actions: bool) -> pd.DataFrame:
        frame = _frame(actions=actions, metadata=_metadata())
        if actions:
            frame["Dividends"] = ["0", "0"]
        return frame

    _install_ticker(monkeypatch, FakeTicker("SPY", frame_factory=frames))
    with pytest.raises(OutcomeSourceUnavailable) as failure:
        _fetch()
    assert failure.value.reason_code == "corporate_action_unknown"


@pytest.mark.parametrize(
    ("field", "value"),
    [("currency", "CAD"), ("symbol", "QQQ"), ("timezone", "America/Toronto")],
)
def test_two_reads_must_have_matching_complete_identity(monkeypatch, field, value):
    def frames(actions: bool) -> pd.DataFrame:
        kwargs = {field: value} if actions else {}
        return _frame(actions=actions, metadata=_metadata(**kwargs))

    _install_ticker(monkeypatch, FakeTicker("SPY", frame_factory=frames))
    with pytest.raises(OutcomeSourceUnavailable) as failure:
        _fetch()
    assert failure.value.reason_code == "series_incomplete"


def test_two_reads_must_match_daily_interval_and_close_values(monkeypatch):
    def wrong_interval(actions: bool) -> pd.DataFrame:
        return _frame(
            actions=actions,
            metadata=_metadata(granularity="5m" if actions else "1d"),
        )

    _install_ticker(monkeypatch, FakeTicker("SPY", frame_factory=wrong_interval))
    with pytest.raises(OutcomeSourceUnavailable):
        _fetch()

    def corrected_action_close(actions: bool) -> pd.DataFrame:
        closes = (100.0, 101.01) if actions else (100.0, 101.0)
        return _frame(actions=actions, metadata=_metadata(), closes=closes)

    _install_ticker(monkeypatch, FakeTicker("SPY", frame_factory=corrected_action_close))
    with pytest.raises(OutcomeSourceUnavailable) as mismatch:
        _fetch()
    assert mismatch.value.reason_code == "series_incomplete"


def test_recent_target_requires_publication_at_or_after_target(monkeypatch):
    ticker = FakeTicker("SPY")
    _install_ticker(monkeypatch, ticker)
    early_response = TARGET - timedelta(seconds=1)

    with pytest.raises(OutcomeSourceUnavailable) as stale:
        _fetch(YahooProvider(timeout=1.0, clock=lambda: early_response))
    assert stale.value.reason_code == "series_incomplete"
    assert len(ticker.calls) == 2

    monkeypatch.setattr(
        "stock_probs.provider.yf.Ticker",
        lambda _symbol: pytest.fail("future target must be rejected before provider access"),
    )
    with pytest.raises(OutcomeSourceUnavailable) as future:
        YahooProvider(timeout=1.0).fetch_daily_outcome_series(
            "SPY", "etf", ORIGIN, TARGET, TARGET - timedelta(seconds=1)
        )
    assert future.value.reason_code == "series_incomplete"


def test_exact_exchange_sessions_skip_holiday_and_reject_holiday_close(monkeypatch):
    origin = datetime(2026, 7, 2, 20, tzinfo=UTC)
    target = datetime(2026, 7, 6, 20, tzinfo=UTC)
    now = target + timedelta(minutes=5)
    index = pd.DatetimeIndex(["2026-07-02", "2026-07-06"], tz="America/New_York")
    ticker = FakeTicker(
        "SPY",
        frame_factory=lambda actions: _frame(
            actions=actions, metadata=_metadata(), index=index, closes=(100.0, 102.0)
        ),
    )
    _install_ticker(monkeypatch, ticker)

    series = YahooProvider(timeout=1.0, clock=lambda: now).fetch_daily_outcome_series(
        "SPY", "etf", origin, target, now
    )
    assert tuple(bar.timestamp for bar in series.bars) == (origin, target)

    holiday_close = datetime(2026, 7, 3, 20, tzinfo=UTC)
    with pytest.raises(OutcomeSourceUnavailable) as holiday:
        YahooProvider(timeout=1.0, clock=lambda: now).fetch_daily_outcome_series(
            "SPY", "etf", origin, holiday_close, now
        )
    assert holiday.value.reason_code == "series_incomplete"


def test_span_and_history_row_bounds_fail_closed_before_scoring(monkeypatch):
    monkeypatch.setattr(
        "stock_probs.provider.yf.Ticker",
        lambda _symbol: pytest.fail("oversized date span must be rejected before provider access"),
    )
    with pytest.raises(OutcomeSourceUnavailable):
        YahooProvider().fetch_daily_outcome_series(
            "SPY", "etf", ORIGIN, TARGET + timedelta(days=201), NOW + timedelta(days=201)
        )

    oversized_index = pd.date_range("2025-01-01", periods=257, freq="D", tz="America/New_York")
    ticker = FakeTicker(
        "SPY",
        frame_factory=lambda actions: _frame(
            actions=actions,
            metadata=_metadata(),
            index=oversized_index,
            closes=(100.0,) * len(oversized_index),
        ),
    )
    _install_ticker(monkeypatch, ticker)
    with pytest.raises(OutcomeSourceUnavailable) as rows:
        _fetch()
    assert rows.value.reason_code == "series_incomplete"


def _valid_series() -> DailyOutcomeSeries:
    return DailyOutcomeSeries(
        provider="Yahoo Finance",
        symbol="SPY",
        currency="USD",
        adjustment_basis=ADJUSTMENT_BASIS,
        requested_from=ORIGIN,
        requested_through=TARGET,
        as_of=NOW,
        complete=True,
        bars=(Bar(ORIGIN, 100.0, 0), Bar(TARGET, 101.0, 0)),
        corporate_actions=CorporateActionCheck(
            provider="Yahoo Finance",
            symbol="SPY",
            currency="USD",
            from_timestamp=ORIGIN,
            through_timestamp=TARGET,
            complete=True,
            events=(),
        ),
    )


def test_service_holds_one_shared_provider_slot_for_both_bounded_reads(monkeypatch):
    ticker = FakeTicker("SPY")
    _install_ticker(monkeypatch, ticker)
    service = ForecastService(
        object(), YahooProvider(timeout=1.0, clock=lambda: NOW), lambda: NOW, 1
    )  # type: ignore[arg-type]
    ticker.provider_slots = service.provider_slots

    series = service.fetch_daily_outcome_series("SPY", "etf", ORIGIN, TARGET, NOW)

    assert series.corporate_actions is not None
    assert len(ticker.calls) == 2
    assert service.provider_slots.acquire(blocking=False)
    service.provider_slots.release()


def test_service_capacity_and_fixture_capability_fail_closed():
    fixture_service = ForecastService(object(), FixtureProvider(clock=lambda: NOW), lambda: NOW, 1)  # type: ignore[arg-type]
    with pytest.raises(OutcomeSourceUnavailable) as fixture_failure:
        fixture_service.fetch_daily_outcome_series("SPY", "etf", ORIGIN, TARGET, NOW)
    assert fixture_failure.value.reason_code == "corporate_action_unknown"

    class Source:
        calls = 0

        def fetch_daily_outcome_series(self, *_args):
            self.calls += 1
            return _valid_series()

    source = Source()
    busy_service = ForecastService(object(), source, lambda: NOW, 1)  # type: ignore[arg-type]
    assert busy_service.provider_slots.acquire(blocking=False)
    try:
        with pytest.raises(OutcomeSourceUnavailable) as busy:
            busy_service.fetch_daily_outcome_series("SPY", "etf", ORIGIN, TARGET, NOW)
        assert busy.value.reason_code == "provider_unavailable"
        assert source.calls == 0
    finally:
        busy_service.provider_slots.release()
