"""Fixed draft imports reject malformed or ambiguous rows before any commit."""

from decimal import Decimal

import pytest

from stock_probs.portfolio_import import csv_template, parse_import
from stock_probs.portfolio_ledger import LedgerError, replay


def test_explicit_mapping_preserves_dates_currencies_and_unknown_opening_cost():
    mapping = {
        "date": "effective_date",
        "type": "kind",
        "currency": "currency",
        "symbol": "symbol",
        "asset_type": "asset_type",
        "quantity": "quantity",
        "price": "price",
        "amount": "amount",
        "fee": "fee",
        "book_cost": "book_cost",
    }
    entries = parse_import(csv_template(), mapping, "tfsa")
    book = replay(entries, {"tfsa"})
    assert book.cash["tfsa", "CAD"] == Decimal("1000")
    assert book.positions["tfsa", "SPY", "etf", "USD"].cost is None
    assert entries[1].effective_date.isoformat() == "2026-10-01"
    assert entries[1].currency == "USD"


def test_explicit_book_cost_is_limited_to_opening_positions():
    mapping = {
        "date": "effective_date",
        "type": "kind",
        "currency": "currency",
        "symbol": "symbol",
        "asset_type": "asset_type",
        "quantity": "quantity",
        "price": "price",
        "book_cost": "book_cost",
    }
    opening = parse_import(
        "date,type,currency,symbol,asset_type,quantity,price,book_cost\n"
        "2026-10-01,opening_position,CAD,ABC,stock,2,,19.50\n",
        mapping,
        "tfsa",
    )
    assert replay(opening, {"tfsa"}).positions["tfsa", "ABC", "stock", "CAD"].cost == Decimal(
        "19.50"
    )

    with pytest.raises(LedgerError, match="Row 2: only an opening position"):
        parse_import(
            "date,type,currency,symbol,asset_type,quantity,price,book_cost\n"
            "2026-10-01,buy,CAD,ABC,stock,1,10,999\n",
            mapping,
            "tfsa",
        )


def test_invalid_later_row_rejects_the_entire_candidate_batch():
    source = (
        "date,type,currency,symbol,asset_type,quantity,price,amount,book_cost\n"
        "2026-10-01,opening_cash,CAD,,,,,1000,\n"
        "2026-10-01,buy,CAD,ABC,stock,1,10,,999\n"
    )
    mapping = {
        "date": "effective_date",
        "type": "kind",
        "currency": "currency",
        "symbol": "symbol",
        "asset_type": "asset_type",
        "quantity": "quantity",
        "price": "price",
        "amount": "amount",
        "book_cost": "book_cost",
    }
    with pytest.raises(LedgerError, match="Row 3: only an opening position"):
        parse_import(source, mapping, "tfsa")


@pytest.mark.parametrize(
    ("destination_currency", "destination_account", "error"),
    [
        ("USD", "", "only a currency exchange"),
        ("", "rrsp", "only a linked transfer"),
    ],
)
def test_destination_fields_are_rejected_for_unrelated_transaction_kinds(
    destination_currency, destination_account, error
):
    source = (
        "date,type,currency,symbol,quantity,price,destination_currency,destination_account\n"
        f"2026-10-01,buy,CAD,ABC,1,10,{destination_currency},{destination_account}\n"
    )
    mapping = {
        "date": "effective_date",
        "type": "kind",
        "currency": "currency",
        "symbol": "symbol",
        "quantity": "quantity",
        "price": "price",
        "destination_currency": "destination_currency",
        "destination_account": "destination_account",
    }

    with pytest.raises(LedgerError, match=f"Row 2: {error}"):
        parse_import(source, mapping, "tfsa")


def test_blank_destination_fields_and_valid_exchange_transfer_still_replay():
    source = (
        "date,type,currency,amount,destination_currency,destination_account,received_amount\n"
        "2026-10-01,opening_cash,CAD,200,,,\n"
        "2026-10-02,exchange,CAD,100,USD,,70\n"
        "2026-10-03,transfer,USD,20,,rrsp,\n"
    )
    mapping = {
        "date": "effective_date",
        "type": "kind",
        "currency": "currency",
        "amount": "amount",
        "destination_currency": "destination_currency",
        "destination_account": "destination_account",
        "received_amount": "received_amount",
    }

    entries = parse_import(source, mapping, "tfsa")
    book = replay(entries, {"tfsa", "rrsp"})

    assert entries[0].destination_currency is None
    assert entries[0].destination_account is None
    assert book.cash["tfsa", "CAD"] == Decimal("100")
    assert book.cash["tfsa", "USD"] == Decimal("50")
    assert book.cash["rrsp", "USD"] == Decimal("20")


@pytest.mark.parametrize(
    "source",
    [
        "date,type,amount\n10/01/2026,deposit,100\n",
        "date,type,amount\n2026-02-30,deposit,100\n",
        "date,type,amount\n2026-10-01,deposit,NaN\n",
        "date,type,amount\n2026-10-01,deposit,100\n2026-10-02,deposit,-1\n",
        "date,type,amount\n2026-10-01,deposit,100,extra\n",
        'date,type,amount\n2026-10-01,deposit,"100\n',
    ],
)
def test_bad_import_returns_no_partial_candidate_batch(source):
    with pytest.raises(LedgerError):
        parse_import(source, {"date": "effective_date", "type": "kind", "amount": "amount"}, "tfsa")


def test_mapping_cannot_accept_ownership_fields_or_duplicate_destination_columns():
    for mapping in (
        {"date": "owner_user_id", "type": "kind"},
        {"date": "effective_date", "type": "effective_date"},
    ):
        with pytest.raises(LedgerError):
            parse_import(csv_template(), mapping, "tfsa")
