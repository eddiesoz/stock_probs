"""Separate draft integration exercises real coordinated SQLite commits and owner guards."""

from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from stock_probs.portfolio_ledger import Entry, LedgerError
from stock_probs.portfolio_store import PortfolioStore, fingerprint
from stock_probs.repository import Repository

NOW = datetime(2026, 10, 11, tzinfo=UTC)
DAY = date(2026, 10, 1)


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
    return PortfolioStore(repository)


def create_account(store, owner=1):
    return store.create_account(owner, "TFSA", "tfsa", str(uuid4()), NOW)["id"]


def row(account, kind, **data):
    return Entry(str(uuid4()), account, DAY, kind, **data)


def commit(store, rows, owner=1, *, approvals=None):
    preview = store.preview(owner, rows)
    return store.commit(
        owner,
        str(uuid4()),
        str(uuid4()),
        rows,
        preview["account_revisions"],
        approvals or set(),
        NOW,
    )


def test_durable_account_and_commit_replay_conflicts_preserve_one_record(store):
    key = str(uuid4())
    account = store.create_account(1, "TFSA", "tfsa", key, NOW)
    assert store.create_account(1, "TFSA", "tfsa", key, NOW) == account
    with pytest.raises(LedgerError, match="different account"):
        store.create_account(1, "RRSP", "rrsp", key, NOW)
    rows = [row(account["id"], "opening_cash", amount="1000")]
    preview = store.preview(1, rows)
    key, preview_id = str(uuid4()), str(uuid4())
    receipt = store.commit(1, key, preview_id, rows, preview["account_revisions"], set(), NOW)
    replayed = store.commit(1, key, preview_id, rows, {}, set(), NOW)
    assert replayed["balances"] == receipt["balances"]
    assert replayed["batch_id"] == receipt["batch_id"] and replayed["replayed"]
    assert store.batch_for_key(1, key, preview_id, set()) == replayed
    assert store.batch_for_key(2, key, preview_id, set()) is None
    with pytest.raises(LedgerError, match="duplicate decision"):
        store.batch_for_key(1, key, preview_id, {rows[0].id})
    with pytest.raises(LedgerError, match="different preview"):
        store.commit(1, key, preview_id, [replace(rows[0], amount="2000")], {}, set(), NOW)
    assert store.balances(1)["cash"][0]["amount"] == "1000"
    with store.repository.connect() as connection:
        assert connection.execute("SELECT count(*) FROM portfolio_transactions").fetchone()[0] == 1


def test_preview_is_read_only_stale_commit_rejected_and_failure_rolls_back(store):
    account = create_account(store)
    rows = [row(account, "deposit", amount="100")]
    preview = store.preview(1, rows)
    assert store.balances(1)["cash"] == []
    commit(store, [row(account, "deposit", amount="50")])
    with pytest.raises(LedgerError, match="Balances changed"):
        store.commit(1, str(uuid4()), str(uuid4()), rows, preview["account_revisions"], set(), NOW)
    revisions = {row["id"]: row["revision"] for row in store.accounts(1)}
    bad = [row(account, "deposit", amount="10"), row(account, "withdrawal", amount="500")]
    with pytest.raises(LedgerError, match="Insufficient"):
        store.commit(1, str(uuid4()), str(uuid4()), bad, revisions, set(), NOW)
    assert store.balances(1)["cash"][0]["amount"] == "50"
    with store.repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM portfolio_batches").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM portfolio_transactions").fetchone()[0] == 1


def test_canonical_numeric_duplicates_need_deliberate_approval(store):
    account = create_account(store)
    original = row(account, "deposit", amount="1.25")
    commit(store, [original])
    duplicate = row(account, "deposit", amount="1.250")
    assert fingerprint(original) == fingerprint(duplicate)
    preview = store.preview(1, [duplicate])
    assert preview["duplicate_ids"] == [duplicate.id]
    with pytest.raises(LedgerError, match="duplicate"):
        store.commit(
            1, str(uuid4()), str(uuid4()), [duplicate], preview["account_revisions"], set(), NOW
        )
    commit(store, [duplicate], approvals={duplicate.id})
    assert store.balances(1)["cash"][0]["amount"] == "2.500"


def test_owner_isolation_and_revocation_block_new_financial_records(store):
    first = create_account(store)
    second = create_account(store, 2)
    commit(store, [row(first, "deposit", amount="200")])
    assert store.balances(2)["cash"] == []
    with pytest.raises(LedgerError, match="unavailable account"):
        store.preview(2, [row(first, "deposit", amount="10")])
    with pytest.raises(LedgerError, match="different account"):
        store.preview(1, [row(first, "transfer", amount="10", destination_account=second)])
    with store.repository.connect() as connection:
        connection.execute("UPDATE users SET status='disabled' WHERE id=2")
        connection.commit()
    with pytest.raises(ValueError, match="not an active"):
        commit(store, [row(second, "deposit", amount="10")], owner=2)
    assert store.balances(2)["cash"] == []


def test_reversal_cannot_change_an_archived_transfer_destination(store):
    first = create_account(store)
    second = create_account(store)
    commit(store, [row(first, "deposit", amount="100")])
    transfer = row(first, "transfer", amount="40", destination_account=second)
    commit(store, [transfer])
    destination = next(item for item in store.accounts(1) if item["id"] == second)
    store.update_account(
        1, second, destination["revision"], "Archived destination", "tfsa", True, NOW
    )
    reversal = row(first, "reversal", replaces=transfer.id)
    before = store.balances(1)
    with pytest.raises(LedgerError, match="archived account"):
        commit(store, [reversal])
    assert store.balances(1) == before


def test_append_replacement_transfer_recalculates_both_accounts_and_keeps_audit_rows(store):
    first, second = create_account(store), create_account(store)
    commit(store, [row(first, "deposit", amount="100")])
    transfer = row(first, "transfer", amount="40", destination_account=second)
    commit(store, [transfer])
    commit(
        store,
        [row(first, "transfer", amount="30", destination_account=second, replaces=transfer.id)],
    )
    cash = {item["account_id"]: item["amount"] for item in store.balances(1)["cash"]}
    assert cash == {first: "70", second: "30"}
    revisions = {item["id"]: item["revision"] for item in store.accounts(1)}
    assert revisions == {first: 4, second: 3}
    with store.repository.connect() as connection:
        assert connection.execute("SELECT count(*) FROM portfolio_transactions").fetchone()[0] == 3


def test_storage_limit_fails_before_any_batch_or_transaction_write(store, monkeypatch):
    account = create_account(store)
    rows = [row(account, "deposit", amount="100")]

    def unavailable(*args):
        raise LedgerError("Portfolio retained storage is full.")

    monkeypatch.setattr(store, "_storage_room", unavailable)
    with pytest.raises(LedgerError, match="storage is full"):
        commit(store, rows)
    assert store.balances(1)["cash"] == []
    with store.repository.connect() as connection:
        assert connection.execute("SELECT count(*) FROM portfolio_batches").fetchone()[0] == 0


def test_saved_baselines_scenarios_replay_without_changing_actual_ledger(store):
    account = create_account(store)
    commit(
        store,
        [
            row(account, "opening_cash", amount="1000"),
            row(account, "opening_position", symbol="ABC", quantity="2", book_cost="150"),
        ],
    )
    state = store.state(1)
    data = {
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
    }
    key, request_hash = str(uuid4()), "a" * 64
    baseline = store.save_snapshot(1, key, request_hash, data, state["account_revisions"], NOW)
    assumptions = {
        "price_shocks": [{"symbol": "ABC", "asset_type": "stock", "percent": "-20"}],
        "usd_cad_percent": "0",
        "reallocations": [],
    }
    scenario_key = str(uuid4())
    saved = store.save_scenario(1, scenario_key, baseline["id"], "Market shock", assumptions, NOW)
    assert saved["result"]["value_difference"] == "-40.0"
    commit(store, [row(account, "deposit", amount="500")])
    assert store.snapshot(1, baseline["id"]) == baseline
    assert store.snapshot_for_key(1, key, request_hash) == baseline
    assert store.scenario(1, saved["id"]) == saved
    assert (
        store.save_scenario(1, scenario_key, baseline["id"], "Market shock", assumptions, NOW)
        == saved
    )
    assert store.balances(1)["cash"][0]["amount"] == "1500"
    assert store.snapshot(2, baseline["id"]) is None and store.scenario(2, saved["id"]) is None
    assert store.list_scenarios(2, 1, 20)["total"] == 0
    assert store.list_snapshots(1, 1, 20)["items"] == [baseline]
    with pytest.raises(LedgerError, match="different scenario"):
        store.save_scenario(1, scenario_key, baseline["id"], "Changed", assumptions, NOW)
    with pytest.raises(LedgerError, match="unavailable"):
        store.save_scenario(2, str(uuid4()), baseline["id"], "Other owner", assumptions, NOW)


def test_stale_snapshot_and_account_edits_are_conflicts_without_data_loss(store):
    account = create_account(store)
    state = store.state(1)
    store.update_account(1, account, 1, "My TFSA", "tfsa", False, NOW)
    with pytest.raises(LedgerError, match="changed"):
        store.update_account(1, account, 1, "Stale", "other", False, NOW)
    with pytest.raises(LedgerError, match="Balances changed"):
        store.save_snapshot(1, str(uuid4()), "a" * 64, {}, state["account_revisions"], NOW)
    assert store.list_snapshots(1, 1, 20)["total"] == 0
    store.update_account(1, account, 2, "My TFSA", "tfsa", True, NOW)
    with pytest.raises(LedgerError, match="Reopen"):
        commit(store, [row(account, "deposit", amount="10")])
    assert store.accounts(1)[0]["label"] == "My TFSA" and store.balances(1)["cash"] == []


def test_transaction_pages_retain_superseded_original_rows(store):
    account = create_account(store)
    original = row(account, "deposit", amount="100")
    commit(store, [original])
    replacement = row(account, "deposit", amount="200", replaces=original.id)
    commit(store, [replacement])
    page = store.transactions(1, 1, 1)
    assert page["total"] == 2 and page["has_next"]
    assert page["items"][0]["id"] == replacement.id
    old = store.transactions(1, 2, 1)["items"][0]
    assert old["superseded"] and old["id"] == original.id and old["data"]["amount"] == "100"
    assert store.transactions(2, 1, 100)["items"] == []
    with pytest.raises(LedgerError, match="unavailable"):
        store.transactions(2, 1, 100, account)
