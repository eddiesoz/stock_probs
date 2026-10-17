"""Acceptance tests for immutable snapshots and date-changing ledger corrections."""

import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from stock_probs.portfolio_ledger import Entry
from stock_probs.portfolio_store import PortfolioStore
from stock_probs.repository import Repository

PORTFOLIO_SNAPSHOT_SELECT_SQL = "SELECT * FROM portfolio_snapshots WHERE id = ?"
PORTFOLIO_SNAPSHOT_UPDATE_SQL = "UPDATE portfolio_snapshots SET payload_json = ? WHERE id = ?"
PORTFOLIO_SNAPSHOT_DELETE_SQL = "DELETE FROM portfolio_snapshots WHERE id = ?"
PORTFOLIO_SNAPSHOT_REPLACE_SQL = (
    "INSERT OR REPLACE INTO portfolio_snapshots SELECT * FROM portfolio_snapshots WHERE id = ?"
)
PORTFOLIO_SCENARIO_SELECT_SQL = "SELECT * FROM portfolio_scenarios WHERE id = ?"
PORTFOLIO_SCENARIO_UPDATE_SQL = "UPDATE portfolio_scenarios SET title = ? WHERE id = ?"
PORTFOLIO_SCENARIO_DELETE_SQL = "DELETE FROM portfolio_scenarios WHERE id = ?"
PORTFOLIO_SCENARIO_REPLACE_SQL = (
    "INSERT OR REPLACE INTO portfolio_scenarios SELECT * FROM portfolio_scenarios WHERE id = ?"
)

NOW = datetime(2026, 10, 11, tzinfo=UTC)


@pytest.fixture
def store(tmp_path):
    repository = Repository(tmp_path / "portfolio.db")
    repository.migrate()
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO users(id, login, display_name, role, status, created_at, updated_at) "
            "VALUES (2, 'fixture-member', 'Fixture member', 'member', 'active', ?, ?)",
            (NOW.isoformat(), NOW.isoformat()),
        )
        connection.commit()
    return PortfolioStore(repository, allow_development_noauth=True)


def add_account(store):
    return store.create_account(1, "TFSA", "tfsa", str(uuid4()), NOW)["id"]


def entry(account, effective_date, kind, **data):
    return Entry(str(uuid4()), account, effective_date, kind, **data)


def commit_rows(store, rows):
    preview = store.preview(1, rows)
    return store.commit(
        1,
        str(uuid4()),
        str(uuid4()),
        rows,
        preview["account_revisions"],
        set(),
        NOW,
    )


def test_saved_portfolio_and_scenario_rows_reject_direct_sql_mutation(store):
    account = add_account(store)
    commit_rows(
        store,
        [
            entry(account, date(2026, 10, 1), "opening_cash", amount="1000"),
            entry(
                account,
                date(2026, 10, 2),
                "opening_position",
                symbol="ABC",
                quantity="2",
                book_cost="150",
            ),
        ],
    )
    state = store.state(1)
    baseline = store.save_snapshot(
        1,
        str(uuid4()),
        "a" * 64,
        {
            "book": state["book"],
            "accounts": state["accounts"],
            "quotes": [
                {
                    "symbol": "ABC",
                    "asset_type": "stock",
                    "currency": "CAD",
                    "price": "100",
                    "as_of": NOW.isoformat(),
                    "provider": "fixture",
                }
            ],
            "fx": {"CAD": {"value": "1"}},
            "display_currency": "CAD",
            "captured_at": NOW.isoformat(),
        },
        state["account_revisions"],
        NOW,
    )
    scenario = store.save_scenario(
        1,
        str(uuid4()),
        baseline["id"],
        "Market shock",
        {
            "price_shocks": [{"symbol": "ABC", "asset_type": "stock", "percent": "-20"}],
            "usd_cad_percent": "0",
            "reallocations": [],
        },
        NOW,
    )

    records = (
        (
            baseline["id"],
            "{}",
            "portfolio baselines are immutable",
            PORTFOLIO_SNAPSHOT_SELECT_SQL,
            PORTFOLIO_SNAPSHOT_UPDATE_SQL,
            PORTFOLIO_SNAPSHOT_DELETE_SQL,
            PORTFOLIO_SNAPSHOT_REPLACE_SQL,
        ),
        (
            scenario["id"],
            "Changed scenario",
            "saved scenarios are immutable",
            PORTFOLIO_SCENARIO_SELECT_SQL,
            PORTFOLIO_SCENARIO_UPDATE_SQL,
            PORTFOLIO_SCENARIO_DELETE_SQL,
            PORTFOLIO_SCENARIO_REPLACE_SQL,
        ),
    )
    with store.repository.connect() as connection:
        for (
            identifier,
            changed_value,
            immutable_error,
            select_sql,
            update_sql,
            delete_sql,
            replace_sql,
        ) in records:
            original = tuple(connection.execute(select_sql, (identifier,)).fetchone())
            assert original

            with pytest.raises(sqlite3.IntegrityError, match=immutable_error):
                connection.execute(update_sql, (changed_value, identifier))
            connection.rollback()
            assert tuple(connection.execute(select_sql, (identifier,)).fetchone()) == original

            with pytest.raises(sqlite3.IntegrityError, match=immutable_error):
                connection.execute(delete_sql, (identifier,))
            connection.rollback()
            assert tuple(connection.execute(select_sql, (identifier,)).fetchone()) == original

            with pytest.raises(sqlite3.IntegrityError, match=immutable_error):
                connection.execute(replace_sql, (identifier,))
            connection.rollback()
            assert tuple(connection.execute(select_sql, (identifier,)).fetchone()) == original


def test_backdated_replacement_replays_weighted_cost_cash_and_unknown_cost(store):
    account = add_account(store)
    opening_cash = entry(account, date(2026, 1, 1), "opening_cash", amount="1000")
    unknown_position = entry(
        account,
        date(2026, 1, 5),
        "opening_position",
        symbol="XYZ",
        quantity="3",
        book_cost=None,
    )
    original_buy = entry(
        account,
        date(2026, 1, 10),
        "buy",
        symbol="ABC",
        quantity="2",
        price="100",
    )
    later_buy = entry(
        account,
        date(2026, 1, 20),
        "buy",
        symbol="ABC",
        quantity="2",
        price="200",
    )
    sale = entry(
        account,
        date(2026, 1, 30),
        "sell",
        symbol="ABC",
        quantity="1",
        price="250",
    )
    commit_rows(store, [opening_cash, unknown_position, original_buy, later_buy, sale])

    before = store.balances(1)
    before_positions = {item["symbol"]: item for item in before["positions"]}
    assert before["cash"][0]["amount"] == "650"
    assert before_positions["ABC"]["quantity"] == "3"
    assert before_positions["ABC"]["book_cost"] == "450"
    assert Decimal(before["realized"][0]["gain"]) == Decimal("100")
    assert before_positions["XYZ"]["quantity"] == "3"
    assert before_positions["XYZ"]["book_cost"] is None
    assert not before_positions["XYZ"]["cost_known"]

    correction = entry(
        account,
        date(2026, 2, 1),
        "buy",
        symbol="ABC",
        quantity="2",
        price="120",
        replaces=original_buy.id,
    )
    first_preview = store.preview(1, [correction])
    second_preview = store.preview(1, [correction])
    assert first_preview["after"] == second_preview["after"]

    after = first_preview["after"]
    after_positions = {item["symbol"]: item for item in after["positions"]}
    assert after["cash"][0]["amount"] == "610"
    assert after_positions["ABC"]["quantity"] == "3"
    assert after_positions["ABC"]["book_cost"] == "440"
    assert Decimal(after["realized"][0]["gain"]) == Decimal("50")
    assert after_positions["XYZ"]["quantity"] == "3"
    assert after_positions["XYZ"]["book_cost"] is None
    assert not after_positions["XYZ"]["cost_known"]

    receipt = store.commit(
        1,
        str(uuid4()),
        str(uuid4()),
        [correction],
        first_preview["account_revisions"],
        set(),
        NOW,
    )
    assert receipt["balances"] == after
    assert store.balances(1) == after

    rows = store.transactions(1, 1, 100)
    by_id = {item["id"]: item for item in rows["items"]}
    assert by_id[original_buy.id]["superseded"]
    assert by_id[correction.id]["effective_date"] == "2026-02-01"
    assert not by_id[correction.id]["superseded"]
