"""Fixed arithmetic fixtures for the separate, unintegrated Release 2 draft."""

from datetime import date
from decimal import Decimal

import pytest

from stock_probs.portfolio_ledger import Entry, LedgerError, decimal, replay

DAY = date(2026, 10, 1)


def entry(identifier, kind, **values):
    return Entry(identifier, "tfsa", DAY, kind, **values)


def test_fractional_buys_fees_and_partial_sales_use_weighted_book_cost():
    records = [
        entry("1", "deposit", amount="1000"),
        entry("2", "buy", symbol="ABC", quantity="2.5", price="100", fee="2"),
        entry("3", "buy", symbol="ABC", quantity="2.5", price="120", fee="3"),
        entry("4", "sell", symbol="ABC", quantity="1.25", price="150", fee="1"),
    ]
    book = replay(records, {"tfsa"})
    assert book.cash["tfsa", "CAD"] == Decimal("631.50")
    position = book.positions["tfsa", "ABC", "stock", "CAD"]
    assert position.quantity == Decimal("3.75")
    assert position.cost == Decimal("416.25")
    assert Decimal(book.realized[0]["gain"]) == Decimal("47.75")


def test_unknown_opening_cost_stays_unknown_then_resets_after_full_sale():
    records = [
        entry("1", "opening_position", symbol="ABC", quantity="2"),
        entry("2", "deposit", amount="1000"),
        entry("3", "buy", symbol="ABC", quantity="1", price="100"),
        entry("4", "sell", symbol="ABC", quantity="1", price="150"),
    ]
    assert replay(records, {"tfsa"}).as_dict()["positions"][0]["book_cost"] is None
    records += [
        entry("5", "sell", symbol="ABC", quantity="2", price="150"),
        entry("6", "buy", symbol="ABC", quantity="1", price="120"),
    ]
    book = replay(records, {"tfsa"})
    assert book.realized[0]["gain"] is None
    assert book.positions["tfsa", "ABC", "stock", "CAD"].cost == Decimal("120")


def test_splits_and_linked_security_transfers_preserve_total_cost():
    records = [
        entry("1", "opening_position", symbol="ABC", quantity="3", book_cost="90"),
        entry("2", "split", symbol="ABC", split_ratio="2"),
        entry("3", "transfer", symbol="ABC", quantity="2", destination_account="rrsp"),
    ]
    book = replay(records, {"tfsa", "rrsp"})
    assert book.positions["tfsa", "ABC", "stock", "CAD"].cost == Decimal("60")
    assert book.positions["rrsp", "ABC", "stock", "CAD"].cost == Decimal("30")
    assert book.realized == []


def test_cash_transfers_exchanges_and_income_keep_native_currencies():
    records = [
        entry("1", "opening_cash", amount="1000"),
        entry(
            "2",
            "exchange",
            amount="300",
            received_amount="200",
            destination_currency="USD",
            fee="2",
        ),
        entry("3", "transfer", amount="100", currency="USD", destination_account="rrsp"),
        Entry("4", "rrsp", DAY, "dividend", currency="USD", amount="5.25"),
        Entry("5", "rrsp", DAY, "interest", currency="USD", amount="0.5"),
        Entry("6", "rrsp", DAY, "fee", currency="USD", amount="1"),
    ]
    book = replay(records, {"tfsa", "rrsp"})
    assert book.cash == {
        ("tfsa", "CAD"): Decimal("698"),
        ("tfsa", "USD"): Decimal("100"),
        ("rrsp", "USD"): Decimal("104.75"),
    }


def test_replacement_and_reversal_append_without_double_counting():
    records = [
        entry("1", "deposit", amount="1000"),
        entry("2", "buy", symbol="ABC", quantity="2", price="100"),
        entry("3", "buy", symbol="ABC", quantity="3", price="100", replaces="2"),
    ]
    book = replay(records, {"tfsa"})
    assert book.cash["tfsa", "CAD"] == Decimal("700")
    records.append(entry("4", "reversal", replaces="3"))
    book = replay(records, {"tfsa"})
    assert book.cash["tfsa", "CAD"] == Decimal("1000")
    assert book.as_dict()["positions"] == []


def test_backdating_cannot_borrow_future_cash_or_create_short_positions():
    records = [
        entry("1", "deposit", amount="1000"),
        Entry("2", "tfsa", date(2026, 9, 1), "buy", symbol="ABC", quantity="1", price="1"),
    ]
    with pytest.raises(LedgerError, match="Insufficient"):
        replay(records, {"tfsa"})
    with pytest.raises(LedgerError, match="short"):
        replay([entry("1", "sell", symbol="ABC", quantity="1", price="100")], {"tfsa"})
    with pytest.raises(LedgerError, match="different account"):
        replay([entry("1", "transfer", amount="1", destination_account="other")], {"tfsa"})


@pytest.mark.parametrize("amount", [1.5, True, "NaN", "Infinity", "-1", "1000000000001", "1e-13"])
def test_decimal_inputs_reject_floats_nonfinite_negative_and_unbounded(amount):
    with pytest.raises(LedgerError):
        decimal(amount)
