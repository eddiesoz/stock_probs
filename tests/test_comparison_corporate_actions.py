"""Protect comparison metrics from provider-reported split discontinuities."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from stock_probs.domain import DomainError
from stock_probs.provider import YahooProvider
from stock_probs.repository import Repository
from stock_probs.research import ResearchStore, compare_series

NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
AS_OF = "2026-10-17T14:00:00+00:00"
DATES = ("2026-10-01", "2026-10-02", "2026-10-03")
_MISSING = object()


def series(
    symbol: str,
    closes: tuple[float, ...] = (100.0, 102.0, 104.0),
    *,
    dates: tuple[str, ...] = DATES,
    events: object = _MISSING,
    available_fields: list[str] | None = None,
) -> dict[str, object]:
    item: dict[str, object] = {
        "symbol": symbol,
        "identity": {"currency": "USD", "display_name": symbol, "asset_type": "stock"},
        "source": "Yahoo Finance",
        "as_of": AS_OF,
        "adjustment_basis": "unadjusted closes (actions=True, auto_adjust=False)",
        "label": "Provider-reported historical data.",
        "range": "1mo",
        "bars": [
            {"timestamp": f"{day}T16:00:00+00:00", "close": close}
            for day, close in zip(dates, closes, strict=True)
        ],
    }
    if events is not _MISSING:
        item["action_evidence"] = {
            "status": "provider_events_returned" if events else "no_reported_action_evidence",
            "provider": "Yahoo Finance",
            "canonical_symbol": symbol,
            "requested_range": "1mo",
            "series_as_of": AS_OF,
            "available_fields": (
                ["Dividends", "Stock Splits"] if available_fields is None else available_fields
            ),
            "events": events,
        }
    return item


def split_event(day: str, ratio: float) -> dict[str, object]:
    return {"kind": "split", "date": day, "new_shares_per_old_share": ratio}


def test_three_for_two_split_suppresses_metrics_and_keeps_raw_chart():
    item = series("ABC", (150.0, 100.0, 105.0), events=[split_event(DATES[1], 1.5)])

    result = compare_series([item, series("SPY")])
    compared = {entry["symbol"]: entry for entry in result["instruments"]}
    affected = compared["ABC"]

    assert affected["quality"] == "corporate_action_detected"
    assert affected["price_change"] is None
    assert affected["volatility"] is None
    assert affected["max_drawdown"] is None
    assert affected["raw_bars"] == item["bars"]
    assert affected["normalized"][1]["value"] == pytest.approx(100 * 100 / 150)
    assert "1.5 new shares per old share" in affected["metric_suppression_reason"]
    assert compared["SPY"]["price_change"] == pytest.approx(0.04)
    assert compared["SPY"]["volatility"] is not None


def test_reverse_split_preserves_provider_ratio_without_inventing_original_fraction():
    item = series("REV", (1000.0, 100.0, 105.0), events=[split_event(DATES[1], 0.1)])

    affected = compare_series([item, series("SPY")])["instruments"][0]

    assert affected["action_evidence"]["events"][0]["new_shares_per_old_share"] == 0.1
    assert "0.1 new shares per old share" in affected["metric_suppression_reason"]
    assert "old shares per new share" not in affected["metric_suppression_reason"]
    assert affected["raw_bars"][0]["close"] == 1000.0


@pytest.mark.parametrize("event_day", [DATES[0], "2026-10-04"])
def test_split_at_normalization_baseline_or_outside_common_window_does_not_suppress(event_day):
    item = series("ABC", (100.0, 101.0, 102.0), events=[split_event(event_day, 1.5)])

    affected = compare_series([item, series("SPY")])["instruments"][0]

    assert affected["quality"] == "unadjusted_price_only"
    assert affected["price_change"] is not None
    assert affected["volatility"] is not None
    assert affected["max_drawdown"] is not None


def test_one_to_one_split_report_does_not_suppress_metrics():
    item = series("ABC", events=[split_event(DATES[1], 1.0)])

    affected = compare_series([item, series("SPY")])["instruments"][0]

    assert affected["quality"] == "unadjusted_price_only"
    assert affected["price_change"] is not None
    assert affected["metric_suppression_reason"] is None


def test_missing_action_evidence_is_not_a_completeness_claim_and_jump_guard_remains():
    item = series("ABC", (100.0, 45.0, 48.0))

    affected = compare_series([item, series("SPY")])["instruments"][0]

    assert affected["action_evidence"]["status"] == "no_reported_action_evidence"
    assert affected["action_evidence"]["completeness"] == "not_established"
    assert affected["quality"] == "discontinuity_detected"
    assert affected["price_change"] is None
    assert "inferred from unadjusted closes" in affected["metric_suppression_reason"]


def test_empty_action_events_are_reported_as_unknown_completeness():
    item = series("ABC", events=[], available_fields=["Dividends", "Stock Splits"])

    affected = compare_series([item, series("SPY")])["instruments"][0]

    assert affected["action_evidence"]["status"] == "no_reported_action_evidence"
    assert affected["action_evidence"]["events"] == []
    assert affected["action_evidence"]["completeness"] == "not_established"
    assert affected["price_change"] is not None


def test_dividend_keeps_currency_unknown_even_when_instrument_has_currency():
    item = series(
        "ABC",
        events=[{"kind": "dividend", "date": DATES[1], "amount": 0.42, "currency": None}],
        available_fields=["Dividends"],
    )

    affected = compare_series([item, series("SPY")])["instruments"][0]

    assert affected["currency"] == "USD"
    assert affected["action_evidence"]["events"][0]["currency"] is None


@pytest.mark.parametrize(
    ("event", "fields"),
    [
        (split_event(DATES[1], 0.0), ["Stock Splits"]),
        (split_event(DATES[1], float("nan")), ["Stock Splits"]),
        (
            {"kind": "split", "date": "2026-02-30", "new_shares_per_old_share": 1.5},
            ["Stock Splits"],
        ),
        (split_event(DATES[1], 1.5), []),
        ({"kind": "split", "date": DATES[1]}, ["Stock Splits"]),
        ("malformed populated event", ["Stock Splits"]),
    ],
)
def test_malformed_populated_action_evidence_fails_closed(event, fields):
    item = series("ABC", events=[event], available_fields=fields)

    with pytest.raises(DomainError) as caught:
        compare_series([item, series("SPY")])

    assert caught.value.status_code == 502


def test_comparison_snapshot_reopens_with_action_evidence_and_suppression_reason(settings):
    repo = Repository(settings.database_path)
    repo.migrate()
    payload = compare_series(
        [
            series("ABC", (150.0, 100.0, 105.0), events=[split_event(DATES[1], 1.5)]),
            series("SPY"),
        ]
    )
    payload["captured_at"] = NOW.isoformat()
    store = ResearchStore(repo)
    saved = store.save_comparison(1, str(uuid4()), payload, NOW)

    reopened = ResearchStore(Repository(settings.database_path)).get(1, "comparisons", saved["id"])

    assert reopened == saved
    affected = {entry["symbol"]: entry for entry in reopened["data"]["instruments"]}["ABC"]
    assert affected["action_evidence"]["events"] == [split_event(DATES[1], 1.5)]
    assert (
        affected["metric_suppression_reason"]
        == payload["instruments"][0]["metric_suppression_reason"]
    )


class _Timestamp:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def to_pydatetime(self) -> datetime:
        return self.value


class _Frame:
    columns = ("Close", "Dividends", "Stock Splits")

    def __init__(self, rows: list[tuple[datetime, dict[str, object]]]) -> None:
        self.rows = rows

    def iterrows(self):
        return ((_Timestamp(timestamp), values) for timestamp, values in self.rows)


def test_yahoo_comparison_requests_actions_and_unadjusted_bars(monkeypatch):
    provider = YahooProvider(clock=lambda: NOW)
    timestamps = [datetime(2026, 10, day, 16, tzinfo=UTC) for day in (1, 2)]
    frame = _Frame(
        [
            (timestamps[0], {"Close": 150.0, "Dividends": 0.0, "Stock Splits": 0.0}),
            (timestamps[1], {"Close": 100.0, "Dividends": 0.42, "Stock Splits": 1.5}),
        ]
    )
    identity = SimpleNamespace(
        canonical_symbol="ABC",
        timezone="America/New_York",
        provider="Yahoo Finance",
    )
    calls: list[dict[str, object]] = []

    def capability_history(symbol, asset_type, *, period, interval, actions=False):
        calls.append(
            {
                "symbol": symbol,
                "asset_type": asset_type,
                "period": period,
                "interval": interval,
                "actions": actions,
            }
        )
        return frame, {}, identity, NOW

    monkeypatch.setattr(provider, "_capability_history", capability_history)

    result = provider.historical_comparison("ABC", "stock", NOW, range="1mo")

    assert calls == [
        {
            "symbol": "ABC",
            "asset_type": "stock",
            "period": "1mo",
            "interval": "1d",
            "actions": True,
        }
    ]
    assert result["series"]["adjustment_basis"] == (
        "unadjusted closes (actions=True, auto_adjust=False)"
    )
    evidence = result["action_evidence"]
    assert evidence["events"] == [
        {"kind": "dividend", "date": "2026-10-02", "amount": 0.42, "currency": None},
        {"kind": "split", "date": "2026-10-02", "new_shares_per_old_share": 1.5},
    ]


def test_yahoo_history_flags_actions_without_adjusting_or_repairing():
    class Ticker:
        kwargs: dict[str, object]

        def history(self, **kwargs):
            self.kwargs = kwargs
            return object()

    ticker = Ticker()
    provider = YahooProvider()

    provider._history(ticker, period="1mo", interval="1d", actions=True)

    assert ticker.kwargs["actions"] is True
    assert ticker.kwargs["auto_adjust"] is False
    assert ticker.kwargs["repair"] is False


def test_yahoo_malformed_populated_action_fails_closed():
    frame = _Frame(
        [
            (
                datetime(2026, 10, 2, 16, tzinfo=UTC),
                {"Close": 100.0, "Dividends": 0.0, "Stock Splits": "unknown"},
            )
        ]
    )

    with pytest.raises(DomainError, match="Corporate-action values") as caught:
        YahooProvider._comparison_action_evidence(
            frame,
            "America/New_York",
            "Yahoo Finance",
            "ABC",
            "1mo",
            NOW,
        )

    assert caught.value.status_code == 502
