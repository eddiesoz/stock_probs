"""Check fixed portfolio values, missing inputs and immutable what-if baselines."""

from copy import deepcopy
from decimal import Decimal

import pytest

from stock_probs.portfolio_ledger import LedgerError
from stock_probs.portfolio_scenarios import simulate, valuation


def test_provider_fractional_prices_and_fx_shocks_preserve_precision():
    """Provider decimal precision must not turn a valid holding into a missing quote."""
    frozen = {
        "id": "precision-fixture",
        "captured_at": "2026-10-09T20:00:00Z",
        "display_currency": "CAD",
        "book": {
            "cash": [{"account_id": "tfsa", "currency": "CAD", "amount": "1000"}],
            "positions": [
                {
                    "account_id": "tfsa",
                    "symbol": "SMALL",
                    "asset_type": "stock",
                    "currency": "USD",
                    "quantity": "0.125",
                    "book_cost": None,
                }
            ],
            "realized": [],
        },
        "quotes": [
            {
                "symbol": "SMALL",
                "asset_type": "stock",
                "currency": "USD",
                "price": "7.380000114440918",
            }
        ],
        "fx": {"USD": {"value": "1.4271", "publication_date": "2026-10-09"}},
    }
    original = deepcopy(frozen)
    assumptions = {
        "usd_cad_percent": "2.125",
        "price_shocks": [{"symbol": "SMALL", "asset_type": "stock", "percent": "1.2345"}],
        "reallocations": [
            {
                "account_id": "tfsa",
                "symbol": "SMALL",
                "asset_type": "stock",
                "amount": "125.125",
                "funding_currency": "CAD",
            }
        ],
    }
    result = simulate(frozen, assumptions)
    assert result["before"]["complete"] and result["after"]["complete"]
    assert Decimal(result["after"]["cash"][0]["amount"]) == Decimal("874.875")
    expected_before = Decimal("1000") + Decimal("0.125") * Decimal("7.380000114440918") * Decimal(
        "1.4271"
    )
    assert abs(Decimal(result["before"]["total_value"]) - expected_before) < Decimal("1e-20")
    assert frozen == original


def baseline():
    return {
        "id": "baseline-1",
        "captured_at": "2026-10-09T20:00:00Z",
        "display_currency": "CAD",
        "book": {
            "cash": [{"account_id": "tfsa", "currency": "CAD", "amount": "2400"}],
            "positions": [
                {
                    "account_id": "tfsa",
                    "symbol": "SPY",
                    "asset_type": "etf",
                    "currency": "USD",
                    "quantity": "20",
                    "book_cost": "7000",
                    "cost_known": True,
                },
                {
                    "account_id": "tfsa",
                    "symbol": "SHOP.TO",
                    "asset_type": "stock",
                    "currency": "CAD",
                    "quantity": "48",
                    "book_cost": "4800",
                    "cost_known": True,
                },
                {
                    "account_id": "tfsa",
                    "symbol": "VFV.TO",
                    "asset_type": "etf",
                    "currency": "CAD",
                    "quantity": "40",
                    "book_cost": None,
                    "cost_known": False,
                },
            ],
            "realized": [],
        },
        "quotes": [
            {"symbol": "SPY", "asset_type": "etf", "currency": "USD", "price": "400"},
            {"symbol": "SHOP.TO", "asset_type": "stock", "currency": "CAD", "price": "120"},
            {"symbol": "VFV.TO", "asset_type": "etf", "currency": "CAD", "price": "152"},
        ],
        "fx": {"USD": {"value": "1.32", "date": "2026-10-09", "provider": "Bank of Canada"}},
    }


def test_concentration_combines_the_same_instrument_across_accounts():
    frozen = baseline()
    extra = {**frozen["book"]["positions"][0], "account_id": "rrsp", "quantity": "10"}
    frozen["book"]["positions"].append(extra)
    result = valuation(frozen["book"], frozen["quotes"], frozen["fx"])
    allocations = {row["symbol"]: row for row in result["instrument_allocations"]}
    assert len(allocations) == 3 and Decimal(allocations["SPY"]["display_value"]) == Decimal(
        "15840"
    )
    expected = Decimal("15840") / Decimal("30080") * 100
    assert abs(Decimal(result["largest_position_percent"]) - expected) < Decimal("1e-20")
    assert len(result["positions"]) == 4


def test_approved_fixed_portfolio_and_what_if_arithmetic():
    original = baseline()
    result = simulate(
        original, {"price_shocks": [{"symbol": "SHOP.TO", "asset_type": "stock", "percent": "-20"}]}
    )
    assert Decimal(result["before"]["total_value"]) == Decimal("24800")
    assert Decimal(result["after"]["total_value"]) == Decimal("23648")
    assert Decimal(result["value_difference"]) == Decimal("-1152")
    assert result["after"]["unknown_cost_count"] == 1
    assert result["label"] == "Simulation only"
    assert original == baseline()
    assert result["baseline_id"] == "baseline-1"


def test_partial_inputs_never_publish_a_complete_total_or_allocation():
    frozen = baseline()
    partial = valuation(frozen["book"], frozen["quotes"][1:], frozen["fx"])
    assert not partial["complete"]
    assert partial["total_value"] is None
    assert Decimal(partial["known_subtotal"]) == Decimal("14240")
    assert all(row["allocation_percent"] is None for row in partial["positions"])
    missing_fx = valuation(frozen["book"], frozen["quotes"], {})
    assert missing_fx["total_value"] is None
    assert missing_fx["missing_inputs"] == [{"symbol": "SPY", "reason": "fx_unavailable"}]


def test_missing_fx_for_nonzero_cash_keeps_total_and_allocations_unavailable():
    book = {
        "cash": [
            {"account_id": "tfsa", "currency": "CAD", "amount": "100"},
            {"account_id": "tfsa", "currency": "USD", "amount": "25"},
        ],
        "positions": [],
        "realized": [],
    }

    result = valuation(book, [], {})

    assert not result["complete"]
    assert result["total_value"] is None
    assert Decimal(result["known_subtotal"]) == Decimal("100")
    assert result["cash_value"] is None
    assert result["missing_inputs"] == [{"symbol": "USD", "reason": "fx_unavailable"}]
    assert all(row["allocation_percent"] is None for row in result["cash"])


def test_zero_cash_without_fx_is_known_zero_and_preserves_cash_subtotal():
    """An exact zero needs no exchange rate, but nonzero foreign cash still does."""
    book = {
        "cash": [
            {"account_id": "tfsa", "currency": "CAD", "amount": "100"},
            {"account_id": "tfsa", "currency": "USD", "amount": "0"},
        ],
        "positions": [],
        "realized": [],
    }

    result = valuation(book, [], {})

    assert result["complete"]
    assert result["total_value"] == "100"
    assert result["known_subtotal"] == "100"
    assert result["cash_value"] == "100"
    assert result["missing_inputs"] == []
    assert [(row["currency"], row["amount"]) for row in result["cash"]] == [
        ("CAD", "100"),
        ("USD", "0"),
    ]
    assert [row["display_value"] for row in result["cash"]] == ["100", "0"]
    assert [row["allocation_percent"] for row in result["cash"]] == ["100", "0"]


def test_cash_funded_reallocation_retains_value_before_shocks():
    frozen = baseline()
    result = simulate(
        frozen,
        {
            "reallocations": [
                {"account_id": "tfsa", "symbol": "SHOP.TO", "asset_type": "stock", "quantity": "5"}
            ]
        },
    )
    assert Decimal(result["value_difference"]) == 0
    assert Decimal(result["after"]["cash"][0]["amount"]) == 1800
    assert Decimal(result["after"]["positions"][1]["quantity"]) == 53
    assert frozen == baseline()
    with pytest.raises(LedgerError, match="existing selected-currency cash"):
        simulate(
            frozen,
            {
                "reallocations": [
                    {"account_id": "tfsa", "symbol": "SPY", "asset_type": "etf", "quantity": "1"}
                ]
            },
        )


def test_multiple_reallocations_cannot_overspend_shared_cash():
    frozen = baseline()
    original = deepcopy(frozen)
    reallocations = [
        {
            "account_id": "tfsa",
            "symbol": "SHOP.TO",
            "asset_type": "stock",
            "amount": "1300",
            "funding_currency": "CAD",
        },
        {
            "account_id": "tfsa",
            "symbol": "SHOP.TO",
            "asset_type": "stock",
            "amount": "1300",
            "funding_currency": "CAD",
        },
    ]

    with pytest.raises(LedgerError, match="existing selected-currency cash"):
        simulate(frozen, {"reallocations": reallocations})

    assert frozen == original


def test_cad_cash_can_fund_usd_instrument_at_frozen_indicative_fx_then_shocks():
    frozen = baseline()
    allocation = {
        "account_id": "tfsa",
        "symbol": "SPY",
        "asset_type": "etf",
        "funding_currency": "CAD",
        "amount": "1000",
    }
    result = simulate(frozen, {"reallocations": [allocation]})
    assert Decimal(result["value_difference"]).quantize(Decimal("0.01")) == 0
    assert Decimal(result["after"]["cash"][0]["amount"]) == 1400
    assert Decimal(result["after"]["positions"][0]["display_value"]).quantize(
        Decimal("0.01")
    ) == Decimal("11560")
    shocked = simulate(frozen, {"reallocations": [allocation], "usd_cad_percent": "10"})
    assert Decimal(shocked["value_difference"]).quantize(Decimal("0.01")) == Decimal("1156")
    assert frozen == baseline()
    with pytest.raises(LedgerError, match="existing selected-currency cash"):
        simulate(frozen, {"reallocations": [{**allocation, "amount": "2401"}]})
    with pytest.raises(LedgerError, match="not both"):
        simulate(frozen, {"reallocations": [{**allocation, "quantity": "1"}]})
    without_fx = {**frozen, "fx": {}}
    with pytest.raises(LedgerError, match="frozen indicative FX"):
        simulate(without_fx, {"reallocations": [allocation]})


def test_fx_shock_changes_foreign_values_and_keeps_native_values():
    frozen = baseline()
    result = simulate(frozen, {"usd_cad_percent": "10"})
    assert Decimal(result["value_difference"]) == Decimal("1056")
    assert (
        result["after"]["positions"][0]["native_value"]
        == result["before"]["positions"][0]["native_value"]
    )
    usd = valuation(frozen["book"], frozen["quotes"], frozen["fx"], "USD")
    assert Decimal(usd["total_value"]).quantize(Decimal("0.01")) == Decimal("18787.88")


def test_complete_loss_is_zero_value_not_missing_quote():
    frozen = baseline()
    assumptions = {
        "price_shocks": [{"symbol": "SHOP.TO", "asset_type": "stock", "percent": "-100"}]
    }
    result = simulate(frozen, assumptions)
    assert result["after"]["complete"]
    assert Decimal(result["value_difference"]) == Decimal("-5760")
    assert Decimal(result["after"]["positions"][1]["native_value"]) == 0
    assert frozen == baseline()


def test_invalid_or_repeated_shocks_fail_and_preserve_baseline():
    frozen = baseline()
    item = {"symbol": "SPY", "asset_type": "etf", "percent": "-10"}
    for assumptions in (
        {"price_shocks": [item, item]},
        {"usd_cad_percent": "-100"},
        {"price_shocks": [{**item, "percent": "NaN"}]},
        {"price_shocks": [{**item, "percent": "-101"}]},
    ):
        saved = deepcopy(frozen)
        with pytest.raises(LedgerError):
            simulate(frozen, assumptions)
        assert frozen == saved


def test_reallocation_rejects_existing_position_quote_currency_mismatch():
    """Simulation cannot add quote-currency cost to a different native book currency."""
    frozen = baseline()
    original = deepcopy(frozen)
    frozen["quotes"][0]["currency"] = "CAD"
    before = deepcopy(frozen)
    with pytest.raises(LedgerError, match="different currency"):
        simulate(
            frozen,
            {
                "reallocations": [
                    {
                        "account_id": "tfsa",
                        "symbol": "SPY",
                        "asset_type": "etf",
                        "amount": "100",
                        "funding_currency": "CAD",
                    }
                ]
            },
        )
    assert frozen == before
    assert frozen["book"] == original["book"]
