"""SQLite migration guards for owner links and retained transaction history."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest


def test_draft_schema_owner_links_and_replace_guards():
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA recursive_triggers=OFF")
    connection.execute("CREATE TABLE users(id INTEGER PRIMARY KEY)")
    connection.executemany("INSERT INTO users VALUES (?)", [(1,), (2,)])
    connection.executescript(
        (
            Path(__file__).resolve().parents[1]
            / "src/stock_probs/migrations/015_portfolio_ledger.sql"
        ).read_text()
    )
    account, key, batch, batch_key, transaction = (str(uuid4()) for _ in range(5))
    account_values = (account, 1, key, "a" * 64, "TFSA", "tfsa", 1, 0, "2026-10-11", "2026-10-11")
    connection.execute(
        "INSERT INTO portfolio_accounts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", account_values
    )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute(
            "INSERT OR REPLACE INTO portfolio_accounts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid4()), *account_values[1:]),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute("UPDATE portfolio_accounts SET owner_user_id=2 WHERE id=?", (account,))
    connection.execute(
        "INSERT INTO portfolio_batches VALUES (?, 1, ?, ?, ?, ?, ?)",
        (batch, batch_key, str(uuid4()), "a" * 64, "{}", "2026-10-11"),
    )

    def insert(identifier, owner=1, manual="b" * 64):
        connection.execute(
            "INSERT OR REPLACE INTO portfolio_transactions "
            "(id, owner_user_id, account_id, batch_id, effective_date, payload_json, "
            "duplicate_sha256, manual_holding_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (identifier, owner, account, batch, "2026-10-11", "{}", "a" * 64, manual, "2026-10-11"),
        )

    insert(transaction)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        insert(transaction)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        insert(str(uuid4()))
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        insert(str(uuid4()), owner=2, manual=None)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("DELETE FROM portfolio_transactions")
    assert connection.execute("SELECT count(*) FROM portfolio_transactions").fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM portfolio_accounts").fetchone()[0] == 1
    connection.close()
