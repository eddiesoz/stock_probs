"""Explicit, bounded portfolio quote collection and frozen indicative valuation inputs."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from stock_probs.domain import DomainError
from stock_probs.portfolio_fx import FixtureIndicativeFX, IndicativeFX
from stock_probs.portfolio_ledger import LedgerError, calculated_decimal, currency_code
from stock_probs.portfolio_scenarios import valuation
from stock_probs.portfolio_store import PortfolioStore


class PortfolioMarket:
    """Collect only on a deliberate request; construction and saved reads perform no I/O."""

    def __init__(
        self,
        store: PortfolioStore,
        quote: Callable[[str, str], dict[str, object]],
        fx: IndicativeFX | FixtureIndicativeFX,
        clock: Callable[[], datetime],
    ) -> None:
        self.store, self.quote, self.fx, self.clock = store, quote, fx, clock
        self.capacity = threading.BoundedSemaphore(2)
        self.lock = threading.Lock()
        self.active_owners: set[int] = set()

    def collect(
        self,
        owner: int,
        display_currency: str,
        account_id: str | None = None,
        additional: list[tuple[str, str]] | None = None,
    ) -> tuple[dict[str, Any], dict[str, int]]:
        """Bind native balances first and disclose every missing or bounded-out quote."""
        with self.lock:
            if owner in self.active_owners or not self.capacity.acquire(blocking=False):
                raise LedgerError("Portfolio prices are already loading. Try again shortly.")
            self.active_owners.add(owner)
        try:
            state = self.store.state(owner)
            if account_id and account_id not in state["account_revisions"]:
                raise LedgerError("This portfolio account is unavailable.")
            book = state["book"]
            if account_id:
                book = {
                    key: (
                        [row for row in rows if row["account_id"] == account_id]
                        if isinstance(rows, list)
                        else rows
                    )
                    for key, rows in book.items()
                }
            instruments = sorted(
                {(row["symbol"], row["asset_type"]) for row in book["positions"]}
                | set(additional or [])
            )
            if len(instruments) > 100:
                raise LedgerError("A valuation supports at most one hundred distinct instruments.")
            captured_at = self.clock()
            deadline = time.monotonic() + 20
            quotes, missing = [], []
            for symbol, asset_type in instruments:
                try:
                    if time.monotonic() >= deadline:
                        raise LedgerError("Quote collection reached its time budget.")
                    row = self.quote(symbol, asset_type)
                    quote_currency = row.get("currency")
                    if (
                        row.get("symbol") != symbol
                        or not isinstance(quote_currency, str)
                        or not currency_code(quote_currency)
                    ):
                        raise LedgerError("Quote identity or currency did not match.")
                    price = calculated_decimal(str(row["price"]), positive=True)
                    as_of = datetime.fromisoformat(str(row["as_of"]))
                    if as_of.tzinfo is None or as_of > self.clock():
                        raise LedgerError("Quote observation time was invalid.")
                    quotes.append(
                        {
                            "symbol": symbol,
                            "asset_type": asset_type,
                            "price": format(price, "f"),
                            "currency": quote_currency,
                            "as_of": as_of.isoformat(),
                            "provider": row["provider"],
                            "delayed": row.get("delayed", True),
                            "label": row.get("label", "Provider observation; not instantaneous."),
                        }
                    )
                except (DomainError, LedgerError, ValueError, KeyError, TypeError):
                    missing.append({"symbol": symbol, "asset_type": asset_type})
            foreign = (
                display_currency == "USD"
                or any(row["currency"] != "CAD" for row in book["cash"] + book["positions"])
                or any(row["currency"] != "CAD" for row in quotes)
            )
            fx = (
                self.fx.rates(self.clock())
                if foreign
                else {
                    "rates": {"CAD": {"value": "1", "provider": "Native currency"}},
                    "status": "not_required",
                    "last_attempt_failed": False,
                }
            )
            data = {
                "captured_at": captured_at.isoformat(),
                "collection_completed_at": self.clock().isoformat(),
                "account_id": account_id,
                "accounts": state["accounts"],
                "book": book,
                "quotes": quotes,
                "unavailable_quotes": missing,
                "fx": fx["rates"],
                "fx_status": fx,
                "display_currency": display_currency,
            }
            data["valuation"] = valuation(book, quotes, fx["rates"], display_currency)
            return data, state["account_revisions"]
        finally:
            with self.lock:
                self.active_owners.remove(owner)
                self.capacity.release()
