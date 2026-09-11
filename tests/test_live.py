"""Opt-in M03 live smoke checks exercise one Yahoo stock and one ETF without persistence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from stock_probs.domain import calculate_forecasts
from stock_probs.provider import YahooProvider


@pytest.mark.live
@pytest.mark.parametrize(("symbol", "asset_type"), [("ACDC", "stock"), ("SPY", "etf")])
def test_live_yahoo_forecasts_both_horizons(symbol, asset_type):
    now = datetime.now(UTC)
    data = YahooProvider(timeout=15).fetch(symbol, asset_type, now)
    snapshot, results = calculate_forecasts(data, now)

    assert snapshot["symbol"] == symbol
    assert {result["horizon"] for result in results} == {"close_to_close", "completed_5m_to_close"}
    # Parse offsets before comparison because Yahoo's intraday and target strings can use UTC/local.
    assert all(
        datetime.fromisoformat(result["origin_timestamp"])
        < datetime.fromisoformat(result["target_timestamp"])
        for result in results
    )
