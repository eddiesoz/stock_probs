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
    assert snapshot["canonical_symbol"] == symbol
    assert snapshot["display_name"] and snapshot["company_name"]
    assert snapshot["instrument_identity"]["quote_type"] in {"EQUITY", "STOCK", "ETF"}
    assert snapshot["instrument_identity"] == snapshot["provenance"]["instrument_identity"]
    assert {result["horizon"] for result in results} == {"close_to_close", "completed_5m_to_close"}
    # Parse offsets before comparison because Yahoo's intraday and target strings can use UTC/local.
    assert all(
        datetime.fromisoformat(result["origin_timestamp"])
        < datetime.fromisoformat(result["target_timestamp"])
        for result in results
    )


@pytest.mark.live
@pytest.mark.parametrize(
    ("query", "symbol", "asset_type"),
    [
        ("ProFrac Holding", "ACDC", "stock"),
        ("SPDR S&P 500 ETF Trust", "SPY", "etf"),
    ],
)
def test_live_yahoo_company_lookup_returns_complete_identity(query, symbol, asset_type):
    identities = YahooProvider(timeout=15).lookup(query, 5, datetime.now(UTC))
    identity = next(item for item in identities if item.canonical_symbol == symbol)

    assert identity.company_name
    assert identity.display_name
    assert identity.asset_type == asset_type
    assert identity.exchange and identity.currency and identity.timezone and identity.quote_type
