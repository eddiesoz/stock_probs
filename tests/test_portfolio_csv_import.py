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
