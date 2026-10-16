"""Deterministic book accounting draft; no provider, persistence or trade execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

ZERO = Decimal("0")


def currency_code(value: str) -> bool:
    """Currencies remain explicit native three-letter codes, including recorded exchanges."""
    return len(value) == 3 and value.isascii() and value.isalpha() and value.isupper()


class LedgerError(ValueError):
    """A reviewed transaction cannot preserve the supported ledger invariants."""


def decimal(
    value: object,
    *,
    positive: bool = False,
    max_places: int = 12,
    max_chars: int = 48,
    upper: str = "1000000000000",
) -> Decimal:
    """Reject binary floats, nonfinite values and amounts outside the bounded ledger."""
    if not isinstance(value, str | Decimal) or len(str(value)) > max_chars:
        raise LedgerError(f"Use a decimal amount with at most {max_chars} characters.")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise LedgerError("Invalid decimal amount.") from error
    if not result.is_finite() or result < ZERO or result > Decimal(upper):
        raise LedgerError("Amount must be finite, nonnegative and within the ledger limit.")
    if positive and result == ZERO:
        raise LedgerError("Amount must be greater than zero.")
    exponent = result.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -max_places:
        raise LedgerError(f"Use at most {max_places} decimal places.")
    return result


def calculated_decimal(value: object, *, positive: bool = False) -> Decimal:
    """Provider quotes and deterministic results retain precision beyond user-entry fields."""
    return decimal(value, positive=positive, max_places=64, max_chars=128, upper="1e30")


def text(value: Decimal | None) -> str | None:
    """Serialize exact calculated decimal amounts without binary rounding."""
    return None if value is None else format(value, "f")


@dataclass(frozen=True)
class Entry:
    """One append-only input, ordered by effective date then its recorded sequence."""

    id: str
    account: str
    effective_date: date
    kind: str
    currency: str = "CAD"
    symbol: str | None = None
    asset_type: str = "stock"
    quantity: str = "0"
    price: str = "0"
    amount: str = "0"
    fee: str = "0"
    book_cost: str | None = None
    split_ratio: str = "1"
    destination_account: str | None = None
    destination_currency: str | None = None
    received_amount: str = "0"
    replaces: str | None = None


@dataclass
class Position:
    """Unknown opening cost remains unknown until the entire position is disposed."""

    quantity: Decimal = ZERO
    cost: Decimal | None = ZERO


@dataclass
class Book:
    """Native-currency balances and realized dispositions from recorded inputs only."""

    cash: dict[tuple[str, str], Decimal] = field(default_factory=dict)
    positions: dict[tuple[str, str, str, str], Position] = field(default_factory=dict)
    realized: list[dict[str, Any]] = field(default_factory=list)

    def cash_move(self, account: str, currency: str, amount: Decimal) -> None:
        """Disallow negative cash at each effective transaction, including backdated changes."""
        key = account, currency
        balance = self.cash.get(key, ZERO) + amount
        if balance < ZERO:
            raise LedgerError(f"Insufficient {currency} cash in the selected account.")
        self.cash[key] = balance

    def position(self, entry: Entry, account: str | None = None) -> Position:
        """Never combine an instrument's book cost in two different original currencies."""
        account = account or entry.account
        for key, position in self.positions.items():
            if (
                key[:3] == (account, entry.symbol, entry.asset_type)
                and key[3] != entry.currency
                and position.quantity
            ):
                raise LedgerError("This position already uses a different book currency.")
        key = account, entry.symbol or "", entry.asset_type, entry.currency
        return self.positions.setdefault(key, Position())

    def as_dict(self) -> dict[str, Any]:
        """Keep realized results separate from balances and unresolved cost inputs."""
        return {
            "cash": [
                {"account_id": key[0], "currency": key[1], "amount": text(amount)}
                for key, amount in sorted(self.cash.items())
            ],
            "positions": [
                {
                    "account_id": key[0],
                    "symbol": key[1],
                    "asset_type": key[2],
                    "currency": key[3],
                    "quantity": text(position.quantity),
                    "book_cost": text(position.cost),
                    "cost_known": position.cost is not None,
                }
                for key, position in sorted(self.positions.items())
                if position.quantity
            ],
            "realized": self.realized,
            "label": "Weighted-average book calculations; not a tax report.",
        }


def replay(entries: list[Entry], accounts: set[str]) -> Book:
    """Replay active corrections atomically; reject short positions and unfunded cash moves."""
    if len(entries) > 5000 or len(accounts) > 20:
        raise LedgerError("The account or transaction limit has been reached.")
    with localcontext() as context:
        context.prec = 48
        return _replay(entries, accounts)


def _replay(entries: list[Entry], accounts: set[str]) -> Book:
    recorded: dict[str, Entry] = {}
    replaced: set[str] = set()
    for entry in entries:
        if entry.id in recorded or entry.account not in accounts:
            raise LedgerError("Duplicate transaction or unavailable account.")
        if entry.replaces:
            original = recorded.get(entry.replaces)
            if original is None or original.account != entry.account or original.id in replaced:
                raise LedgerError("Only an active transaction in this account can be corrected.")
            replaced.add(original.id)
        recorded[entry.id] = entry
    active = [(index, entry) for index, entry in enumerate(entries) if entry.id not in replaced]
    book = Book()
    for _, entry in sorted(active, key=lambda item: (item[1].effective_date, item[0])):
        if entry.kind == "reversal":
            if entry.replaces is None:
                raise LedgerError("A reversal must identify the active transaction.")
            continue
        if not currency_code(entry.currency):
            raise LedgerError("Choose an uppercase three-letter currency.")
        fee = decimal(entry.fee)
        if entry.kind in {"opening_cash", "deposit", "withdrawal", "dividend", "interest", "fee"}:
            amount = decimal(entry.amount, positive=True)
            if entry.kind in {"withdrawal", "fee"}:
                amount = -amount
            book.cash_move(entry.account, entry.currency, amount - fee)
            continue
        if entry.kind == "exchange":
            if (
                not entry.destination_currency
                or not currency_code(entry.destination_currency)
                or entry.destination_currency == entry.currency
            ):
                raise LedgerError("Choose a different destination currency.")
            amount = decimal(entry.amount, positive=True)
            received = decimal(entry.received_amount, positive=True)
            book.cash_move(entry.account, entry.currency, -amount - fee)
            book.cash_move(entry.account, entry.destination_currency, received)
            continue
        if entry.kind == "transfer" and not entry.symbol:
            if (
                entry.destination_account not in accounts
                or entry.destination_account == entry.account
            ):
                raise LedgerError("Choose a different account that you own.")
            amount = decimal(entry.amount, positive=True)
            book.cash_move(entry.account, entry.currency, -amount - fee)
            book.cash_move(entry.destination_account, entry.currency, amount)
            continue
        if not entry.symbol or entry.asset_type not in {"stock", "etf"}:
            raise LedgerError("Choose an instrument and its type.")
        position = book.position(entry)
        if entry.kind == "split":
            if position.quantity <= ZERO or fee != ZERO:
                raise LedgerError("A split needs an existing position and no transaction fee.")
            position.quantity *= decimal(entry.split_ratio, positive=True)
            continue
        quantity = decimal(entry.quantity, positive=True)
        if entry.kind in {"buy", "opening_position"}:
            cost: Decimal | None
            if entry.kind == "buy":
                cost = quantity * decimal(entry.price, positive=True) + fee
                book.cash_move(entry.account, entry.currency, -cost)
            else:
                if fee != ZERO:
                    raise LedgerError("Record opening costs directly, including any known fees.")
                cost = decimal(entry.book_cost) if entry.book_cost is not None else None
            position.quantity += quantity
            position.cost = None if position.cost is None or cost is None else position.cost + cost
            continue
        if entry.kind not in {"sell", "transfer"}:
            raise LedgerError("Unsupported transaction type.")
        if quantity > position.quantity:
            raise LedgerError("This transaction would create a short position.")
        allocated = None if position.cost is None else position.cost * quantity / position.quantity
        if entry.kind == "sell":
            proceeds = quantity * decimal(entry.price, positive=True) - fee
            if proceeds < ZERO:
                raise LedgerError("The sale fee exceeds its recorded proceeds.")
            book.cash_move(entry.account, entry.currency, proceeds)
            book.realized.append(
                {
                    "transaction_id": entry.id,
                    "account_id": entry.account,
                    "symbol": entry.symbol,
                    "currency": entry.currency,
                    "proceeds": text(proceeds),
                    "allocated_cost": text(allocated),
                    "gain": text(None if allocated is None else proceeds - allocated),
                }
            )
        else:
            if (
                entry.destination_account not in accounts
                or entry.destination_account == entry.account
            ):
                raise LedgerError("Choose a different account that you own.")
            target = book.position(entry, entry.destination_account)
            target.quantity += quantity
            target.cost = (
                None if target.cost is None or allocated is None else target.cost + allocated
            )
            book.cash_move(entry.account, entry.currency, -fee)
        position.quantity -= quantity
        position.cost = (
            ZERO
            if position.quantity == ZERO
            else (None if position.cost is None or allocated is None else position.cost - allocated)
        )
    return book
