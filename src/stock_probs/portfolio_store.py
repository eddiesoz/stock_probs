"""Owner-safe atomic ledger storage; previews do not write financial records."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date, datetime
from typing import Any, cast
from uuid import uuid4

from stock_probs.portfolio_ledger import Entry, LedgerError, decimal, replay
from stock_probs.portfolio_scenarios import simulate
from stock_probs.repository import Repository


def encoded(value: object) -> str:
    """Stable financial input fingerprints exclude generated row identities."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(entry: Entry) -> str:
    """Detect repeat imported financial inputs while preserving legitimate confirmed duplicates."""
    body = asdict(entry)
    body.pop("id")
    body.pop("replaces")
    body["effective_date"] = entry.effective_date.isoformat()
    for field in (
        "quantity",
        "price",
        "amount",
        "fee",
        "book_cost",
        "split_ratio",
        "received_amount",
    ):
        if body[field] is not None:
            body[field] = format(decimal(body[field]).normalize(), "f")
    return hashlib.sha256(encoded(body).encode()).hexdigest()


def from_row(row: Any) -> Entry:
    """Only canonical server-created payload fields reconstruct the accounting input."""
    data = json.loads(row["payload_json"])
    return Entry(
        id=row["id"],
        account=row["account_id"],
        effective_date=date.fromisoformat(row["effective_date"]),
        **data,
    )


class PortfolioStore:
    """Use the same repository connection and write-owner guards as the application."""

    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def accounts(self, owner: int) -> list[dict[str, Any]]:
        """Return at most the bounded twenty accounts belonging to this owner."""
        with self.repository.connect() as connection:
            return self._accounts(connection, owner)

    def balances(self, owner: int) -> dict[str, Any]:
        """Replay original records without quote, FX, or provider requests."""
        return cast(dict[str, Any], self.state(owner)["book"])

    def state(self, owner: int) -> dict[str, Any]:
        """Bind account revisions and replayed balances to the same SQLite read snapshot."""
        with self.repository.connect() as connection:
            connection.execute("BEGIN")
            accounts = self._accounts(connection, owner)
            book = replay(
                self._entries(connection, owner), {row["id"] for row in accounts}
            ).as_dict()
        return {
            "accounts": accounts,
            "book": book,
            "account_revisions": {row["id"]: row["revision"] for row in accounts},
        }

    @staticmethod
    def _storage_room(connection: Any, owner: int, extra: int) -> None:
        """Bound all retained portfolio payloads, including immutable snapshots and scenarios."""
        totals = connection.execute(
            "SELECT COALESCE(SUM(size),0), COALESCE(SUM(CASE WHEN "
            "owner_user_id=? THEN size ELSE 0 END),0) "
            "FROM (SELECT owner_user_id, length(CAST(payload_json AS BLOB)) "
            "AS size FROM portfolio_transactions "
            "UNION ALL SELECT owner_user_id, length(CAST(receipt_json AS "
            "BLOB)) FROM portfolio_batches "
            "UNION ALL SELECT owner_user_id, length(CAST(payload_json AS "
            "BLOB)) FROM portfolio_snapshots "
            "UNION ALL SELECT owner_user_id, length(CAST(assumptions_json AS "
            "BLOB))+length(CAST(result_json AS BLOB)) "
            "FROM portfolio_scenarios)",
            (owner,),
        ).fetchone()
        if totals[0] + extra > 20 * 1024 * 1024 or totals[1] + extra > 5 * 1024 * 1024:
            raise LedgerError("Portfolio retained storage is full.")

    @staticmethod
    def _accounts(connection: Any, owner: int) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT id, label, account_type, revision, archived, created_at, updated_at "
            "FROM portfolio_accounts WHERE owner_user_id=? ORDER BY created_at, id LIMIT 20",
            (owner,),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _entries(connection: Any, owner: int) -> list[Entry]:
        rows = connection.execute(
            "SELECT * FROM portfolio_transactions WHERE owner_user_id=? ORDER "
            "BY sequence LIMIT 5001",
            (owner,),
        ).fetchall()
        if len(rows) > 5000:
            raise LedgerError("Transaction storage is full.")
        return [from_row(row) for row in rows]

    def create_account(
        self, owner: int, label: str, account_type: str, key: str, now: datetime
    ) -> dict[str, Any]:
        """A durable account request key replays without network or generated-field comparison."""
        label = label.strip()
        if not 1 <= len(label) <= 80 or account_type not in {"tfsa", "rrsp", "taxable", "other"}:
            raise LedgerError("Choose an account label and supported account type.")
        request_hash = hashlib.sha256(encoded([label, account_type]).encode()).hexdigest()
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.repository._ensure_owner_can_write(connection, owner)
            existing = connection.execute(
                "SELECT id, request_sha256 FROM portfolio_accounts "
                "WHERE owner_user_id=? AND idempotency_key=?",
                (owner, key),
            ).fetchone()
            if existing:
                if existing["request_sha256"] != request_hash:
                    raise LedgerError("This request key belongs to a different account.")
                return next(
                    row for row in self._accounts(connection, owner) if row["id"] == existing["id"]
                )
            if len(self._accounts(connection, owner)) >= 20:
                raise LedgerError("The twenty-account limit has been reached.")
            identifier = str(uuid4())
            connection.execute(
                "INSERT INTO portfolio_accounts VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?)",
                (
                    identifier,
                    owner,
                    key,
                    request_hash,
                    label,
                    account_type,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            result = next(
                row for row in self._accounts(connection, owner) if row["id"] == identifier
            )
            connection.commit()
            return result

    def update_account(
        self,
        owner: int,
        account_id: str,
        revision: int,
        label: str,
        account_type: str,
        archived: bool,
        now: datetime,
    ) -> dict[str, Any]:
        """Labels and archive state change only after reviewing the current account revision."""
        label = label.strip()
        if not 1 <= len(label) <= 80 or account_type not in {"tfsa", "rrsp", "taxable", "other"}:
            raise LedgerError("Choose an account label and supported account type.")
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.repository._ensure_owner_can_write(connection, owner)
            previous = connection.execute(
                "SELECT revision FROM portfolio_accounts WHERE id=? AND owner_user_id=?",
                (account_id, owner),
            ).fetchone()
            if previous is None:
                raise LedgerError("This account is unavailable.")
            if previous[0] != revision:
                raise LedgerError("This account changed. Reload it before saving.")
            connection.execute(
                "UPDATE portfolio_accounts SET label=?, account_type=?, "
                "archived=?, revision=revision+1, "
                "updated_at=? WHERE id=? AND owner_user_id=?",
                (label, account_type, int(archived), now.isoformat(), account_id, owner),
            )
            result = next(
                row for row in self._accounts(connection, owner) if row["id"] == account_id
            )
            connection.commit()
        return result

    def transactions(
        self, owner: int, page: int, page_size: int, account_id: str | None = None
    ) -> dict[str, Any]:
        """Page immutable original rows and expose replacement state without deleting history."""
        if page < 1 or not 1 <= page_size <= 100:
            raise LedgerError("Invalid transaction page.")
        with self.repository.connect() as connection:
            connection.execute("BEGIN")
            if account_id is not None and account_id not in {
                row["id"] for row in self._accounts(connection, owner)
            }:
                raise LedgerError("This account is unavailable.")
            total = connection.execute(
                "SELECT COUNT(*) FROM portfolio_transactions WHERE "
                "owner_user_id=? AND (? IS NULL OR account_id=?)",
                (owner, account_id, account_id),
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT row.*, EXISTS(SELECT 1 FROM portfolio_transactions replacement WHERE "
                "replacement.replaces_id=row.id AND "
                "replacement.owner_user_id=row.owner_user_id) AS superseded "
                "FROM portfolio_transactions row WHERE row.owner_user_id=? AND (? "
                "IS NULL OR row.account_id=?) "
                "ORDER BY row.effective_date DESC, row.sequence DESC LIMIT ? OFFSET ?",
                (owner, account_id, account_id, page_size, (page - 1) * page_size),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            for field in ("owner_user_id", "duplicate_sha256"):
                item.pop(field)
            item["data"] = json.loads(item.pop("payload_json"))
            item["superseded"] = bool(item["superseded"])
            items.append(item)
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_next": page * page_size < total,
        }

    @staticmethod
    def _snapshot_item(row: Any) -> dict[str, Any]:
        item = dict(row)
        for field in ("owner_user_id", "idempotency_key", "request_sha256"):
            item.pop(field)
        item["data"] = json.loads(item.pop("payload_json"))
        return item

    def snapshot_for_key(self, owner: int, key: str, request_sha256: str) -> dict[str, Any] | None:
        """Creation retries reopen the original baseline before any quote/FX request."""
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT * FROM portfolio_snapshots WHERE owner_user_id=? AND idempotency_key=?",
                (owner, key),
            ).fetchone()
        if row is None:
            return None
        if row["request_sha256"] != request_sha256:
            raise LedgerError("This request key belongs to a different baseline.")
        return self._snapshot_item(row)

    def snapshot(self, owner: int, identifier: str) -> dict[str, Any] | None:
        """A frozen baseline has no provider or live portfolio dependencies when reopened."""
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT * FROM portfolio_snapshots WHERE id=? AND owner_user_id=?",
                (identifier, owner),
            ).fetchone()
        return self._snapshot_item(row) if row else None

    def save_snapshot(
        self,
        owner: int,
        key: str,
        request_sha256: str,
        data: dict[str, Any],
        account_revisions: dict[str, int],
        now: datetime,
    ) -> dict[str, Any]:
        """Reject balances changed during quote collection and retain frozen provenance."""
        payload = encoded(data)
        if len(payload.encode()) > 262144:
            raise LedgerError("The portfolio baseline is too large.")
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.repository._ensure_owner_can_write(connection, owner)
            previous = connection.execute(
                "SELECT * FROM portfolio_snapshots WHERE owner_user_id=? AND idempotency_key=?",
                (owner, key),
            ).fetchone()
            if previous:
                if previous["request_sha256"] != request_sha256:
                    raise LedgerError("This request key belongs to a different baseline.")
                return self._snapshot_item(previous)
            if {
                row["id"]: row["revision"] for row in self._accounts(connection, owner)
            } != account_revisions:
                raise LedgerError("Balances changed while prices loaded. Request a new baseline.")
            if (
                connection.execute(
                    "SELECT count(*) FROM portfolio_snapshots WHERE owner_user_id=?", (owner,)
                ).fetchone()[0]
                >= 100
            ):
                raise LedgerError("The hundred-baseline storage limit has been reached.")
            self._storage_room(connection, owner, len(payload.encode()))
            identifier = str(uuid4())
            connection.execute(
                "INSERT INTO portfolio_snapshots VALUES (?, ?, ?, ?, ?, ?)",
                (identifier, owner, key, request_sha256, payload, now.isoformat()),
            )
            connection.commit()
        return self.snapshot(owner, identifier) or {}

    @staticmethod
    def _scenario_item(row: Any) -> dict[str, Any]:
        item = dict(row)
        for field in ("owner_user_id", "idempotency_key", "request_sha256"):
            item.pop(field)
        item["assumptions"] = json.loads(item.pop("assumptions_json"))
        item["result"] = json.loads(item.pop("result_json"))
        return item

    def scenario(self, owner: int, identifier: str) -> dict[str, Any] | None:
        """Return the unchanged simulation and original assumptions, never refresh its baseline."""
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT * FROM portfolio_scenarios WHERE id=? AND owner_user_id=?",
                (identifier, owner),
            ).fetchone()
        return self._scenario_item(row) if row else None

    def save_scenario(
        self,
        owner: int,
        key: str,
        baseline_id: str,
        title: str,
        assumptions: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        """Simulate only the owned frozen baseline; a scenario save cannot call ledger commit."""
        title = title.strip()
        if not 1 <= len(title) <= 120:
            raise LedgerError("Use a scenario title of at most 120 characters.")
        assumptions_json = encoded(assumptions)
        if len(assumptions_json.encode()) > 32768:
            raise LedgerError("The assumptions are too large.")
        request_hash = hashlib.sha256(
            encoded([baseline_id, title, assumptions]).encode()
        ).hexdigest()
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.repository._ensure_owner_can_write(connection, owner)
            existing = connection.execute(
                "SELECT * FROM portfolio_scenarios WHERE owner_user_id=? AND idempotency_key=?",
                (owner, key),
            ).fetchone()
            if existing:
                if existing["request_sha256"] != request_hash:
                    raise LedgerError("This request key belongs to a different scenario.")
                return self._scenario_item(existing)
            baseline = connection.execute(
                "SELECT * FROM portfolio_snapshots WHERE id=? AND owner_user_id=?",
                (baseline_id, owner),
            ).fetchone()
            if baseline is None:
                raise LedgerError("This baseline is unavailable.")
            data = json.loads(baseline["payload_json"])
            result = simulate({**data, "id": baseline_id}, assumptions)
            result_json = encoded(result)
            if len(result_json.encode()) > 262144:
                raise LedgerError("The scenario result is too large.")
            if (
                connection.execute(
                    "SELECT count(*) FROM portfolio_scenarios WHERE owner_user_id=?", (owner,)
                ).fetchone()[0]
                >= 100
            ):
                raise LedgerError("The hundred-scenario storage limit has been reached.")
            self._storage_room(
                connection, owner, len(result_json.encode()) + len(assumptions_json.encode())
            )
            identifier = str(uuid4())
            connection.execute(
                "INSERT INTO portfolio_scenarios VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier,
                    owner,
                    baseline_id,
                    key,
                    request_hash,
                    title,
                    assumptions_json,
                    result_json,
                    now.isoformat(),
                ),
            )
            connection.commit()
        return self.scenario(owner, identifier) or {}

    def list_snapshots(self, owner: int, page: int, page_size: int) -> dict[str, Any]:
        """Expose one bounded page of existing baselines without collecting new prices."""
        with self.repository.connect() as connection:
            total = connection.execute(
                "SELECT count(*) FROM portfolio_snapshots WHERE owner_user_id=?", (owner,)
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM portfolio_snapshots WHERE owner_user_id=? ORDER BY "
                "created_at DESC, id DESC LIMIT ? OFFSET ?",
                (owner, page_size, (page - 1) * page_size),
            ).fetchall()
        return {
            "items": [self._snapshot_item(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_next": page * page_size < total,
        }

    def list_scenarios(self, owner: int, page: int, page_size: int) -> dict[str, Any]:
        """Saved scenarios always include their original identified baseline and assumptions."""
        with self.repository.connect() as connection:
            total = connection.execute(
                "SELECT count(*) FROM portfolio_scenarios WHERE owner_user_id=?", (owner,)
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM portfolio_scenarios WHERE owner_user_id=? ORDER BY "
                "created_at DESC, id DESC LIMIT ? OFFSET ?",
                (owner, page_size, (page - 1) * page_size),
            ).fetchall()
        return {
            "items": [self._scenario_item(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_next": page * page_size < total,
        }

    def preview(self, owner: int, candidates: list[Entry]) -> dict[str, Any]:
        """Return current/recomputed native balances and duplicates from one read snapshot."""
        if not 1 <= len(candidates) <= 200:
            raise LedgerError("Preview between one and two hundred transaction rows.")
        with self.repository.connect() as connection:
            connection.execute("BEGIN")
            accounts = self._accounts(connection, owner)
            entries = self._entries(connection, owner)
            keys = {row["id"] for row in accounts}
            before = replay(entries, keys).as_dict()
            after = replay(entries + candidates, keys).as_dict()
            existing = {
                row[0]
                for row in connection.execute(
                    "SELECT duplicate_sha256 FROM portfolio_transactions WHERE owner_user_id=?",
                    (owner,),
                )
            }
            duplicate_ids = []
            for entry in candidates:
                digest = fingerprint(entry)
                if digest in existing and entry.replaces is None:
                    duplicate_ids.append(entry.id)
                existing.add(digest)
        return {
            "before": before,
            "after": after,
            "account_revisions": {row["id"]: row["revision"] for row in accounts},
            "duplicate_ids": duplicate_ids,
        }

    def commit(
        self,
        owner: int,
        key: str,
        preview_id: str,
        candidates: list[Entry],
        account_revisions: dict[str, int],
        approved_duplicates: set[str],
        now: datetime,
        *,
        manual_openings: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Commit the reviewed batch atomically only while all owner-account revisions match."""
        if not 1 <= len(candidates) <= 200:
            raise LedgerError("Commit between one and two hundred reviewed transaction rows.")
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.repository._ensure_owner_can_write(connection, owner)
            request_hash = hashlib.sha256(
                encoded(
                    [
                        preview_id,
                        [[row.id, fingerprint(row), row.replaces] for row in candidates],
                        sorted(approved_duplicates),
                    ]
                ).encode()
            ).hexdigest()
            existing = connection.execute(
                "SELECT id, preview_id, request_sha256, receipt_json FROM portfolio_batches "
                "WHERE owner_user_id=? AND idempotency_key=?",
                (owner, key),
            ).fetchone()
            if existing:
                if (
                    existing["preview_id"] != preview_id
                    or existing["request_sha256"] != request_hash
                ):
                    raise LedgerError("This commit key belongs to a different preview.")
                return {**json.loads(existing["receipt_json"]), "replayed": True}
            accounts = self._accounts(connection, owner)
            if {row["id"]: row["revision"] for row in accounts} != account_revisions:
                raise LedgerError("Balances changed. Review a fresh preview before committing.")
            touched = {item.account for item in candidates} | {
                item.destination_account for item in candidates if item.destination_account
            }
            entries = self._entries(connection, owner)
            manual_keys: dict[str, str] = {}
            for identifier, source in (manual_openings or {}).items():
                candidate = next((row for row in candidates if row.id == identifier), None)
                if (
                    candidate is None
                    or candidate.kind != "opening_position"
                    or candidate.book_cost is not None
                ):
                    raise LedgerError(
                        "Manual holdings conversion must retain unknown original cost."
                    )
                current = connection.execute(
                    "SELECT quantity, added_at FROM user_instrument_list_items "
                    "WHERE owner_user_id=? AND kind='portfolio' AND provider=? "
                    "AND canonical_symbol=? AND asset_type=?",
                    (owner, source["provider"], candidate.symbol, candidate.asset_type),
                ).fetchone()
                if (
                    current is None
                    or str(current["quantity"]) != source["quantity"]
                    or current["added_at"] != source["added_at"]
                    or decimal(candidate.quantity) != decimal(source["quantity"])
                ):
                    raise LedgerError("Manual holdings changed. Review a new conversion preview.")
                manual_key = hashlib.sha256(
                    encoded(
                        [owner, source["provider"], candidate.symbol, candidate.asset_type]
                    ).encode()
                ).hexdigest()
                if connection.execute(
                    "SELECT 1 FROM portfolio_transactions WHERE owner_user_id=? "
                    "AND manual_holding_key=?",
                    (owner, manual_key),
                ).fetchone():
                    raise LedgerError(
                        "This manual holding was already converted; use a correction."
                    )
                manual_keys[identifier] = manual_key
            if len(entries) + len(candidates) > 5000:
                raise LedgerError("The five-thousand transaction limit has been reached.")
            for item in entries:
                if any(row.replaces == item.id for row in candidates) and item.destination_account:
                    touched.add(item.destination_account)
            if any(row["archived"] and row["id"] in touched for row in accounts):
                raise LedgerError("Reopen an archived account before adding transactions.")
            result = replay(entries + candidates, {row["id"] for row in accounts}).as_dict()
            seen = {
                row[0]
                for row in connection.execute(
                    "SELECT duplicate_sha256 FROM portfolio_transactions WHERE owner_user_id=?",
                    (owner,),
                )
            }
            for item in candidates:
                digest = fingerprint(item)
                if digest in seen and item.replaces is None and item.id not in approved_duplicates:
                    raise LedgerError(
                        "Review duplicate rows explicitly before committing this batch."
                    )
                seen.add(digest)
            batch_id = str(uuid4())
            receipt = {"batch_id": batch_id, "replayed": False, "balances": result}
            receipt_json = encoded(receipt)
            payloads = []
            for entry in candidates:
                data = asdict(entry)
                for field in ("id", "account", "effective_date"):
                    data.pop(field)
                payload = encoded(data)
                if len(payload.encode()) > 4096:
                    raise LedgerError("A transaction row is too large.")
                payloads.append(payload)
            if len(receipt_json.encode()) > 262144:
                raise LedgerError("The resulting balance receipt is too large.")
            self._storage_room(
                connection,
                owner,
                len(receipt_json.encode()) + sum(len(row.encode()) for row in payloads),
            )
            connection.execute(
                "INSERT INTO portfolio_batches VALUES (?, ?, ?, ?, ?, ?, ?)",
                (batch_id, owner, key, preview_id, request_hash, receipt_json, now.isoformat()),
            )
            for entry, payload in zip(candidates, payloads, strict=True):
                connection.execute(
                    "INSERT INTO portfolio_transactions (id, owner_user_id, account_id, batch_id, "
                    "effective_date, payload_json, duplicate_sha256, replaces_id, "
                    "manual_holding_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        entry.id,
                        owner,
                        entry.account,
                        batch_id,
                        entry.effective_date.isoformat(),
                        payload,
                        fingerprint(entry),
                        entry.replaces,
                        manual_keys.get(entry.id),
                        now.isoformat(),
                    ),
                )
            for account in touched:
                connection.execute(
                    "UPDATE portfolio_accounts SET revision=revision+1, updated_at=? "
                    "WHERE id=? AND owner_user_id=?",
                    (now.isoformat(), account, owner),
                )
            connection.commit()
        return receipt

    def batch_for_key(
        self, owner: int, key: str, preview_id: str, approved_duplicates: set[str]
    ) -> dict[str, Any] | None:
        """Replay a committed request after its volatile preview expires or the process restarts."""
        with self.repository.connect() as connection:
            batch = connection.execute(
                "SELECT * FROM portfolio_batches WHERE owner_user_id=? AND idempotency_key=?",
                (owner, key),
            ).fetchone()
            if batch is None:
                return None
            rows = connection.execute(
                "SELECT * FROM portfolio_transactions WHERE owner_user_id=? AND "
                "batch_id=? ORDER BY sequence",
                (owner, batch["id"]),
            ).fetchall()
        entries = [from_row(row) for row in rows]
        request_hash = hashlib.sha256(
            encoded(
                [
                    preview_id,
                    [[row.id, fingerprint(row), row.replaces] for row in entries],
                    sorted(approved_duplicates),
                ]
            ).encode()
        ).hexdigest()
        if batch["preview_id"] != preview_id or batch["request_sha256"] != request_hash:
            raise LedgerError(
                "This commit key belongs to a different preview or duplicate decision."
            )
        return {**json.loads(batch["receipt_json"]), "replayed": True}
