"""Bounded, explicitly mapped CSV draft; parsing never commits account transactions."""

from __future__ import annotations

import csv
import io
from datetime import date
from uuid import uuid4

from stock_probs.portfolio_ledger import Entry, LedgerError, currency_code, decimal

FIELDS = {
    "effective_date",
    "kind",
    "currency",
    "symbol",
    "asset_type",
    "quantity",
    "price",
    "amount",
    "fee",
    "book_cost",
    "split_ratio",
    "destination_account",
    "destination_currency",
    "received_amount",
    "replaces",
}
NUMBER_FIELDS = {
    "quantity",
    "price",
    "amount",
    "fee",
    "book_cost",
    "split_ratio",
    "received_amount",
}
KINDS = {
    "opening_cash",
    "opening_position",
    "buy",
    "sell",
    "deposit",
    "withdrawal",
    "dividend",
    "interest",
    "fee",
    "split",
    "exchange",
    "transfer",
    "reversal",
}


def parse_import(source: str, mapping: dict[str, str], account: str) -> list[Entry]:
    """Require one explicit field mapping and validate every row before returning candidates."""
    if not isinstance(source, str) or len(source.encode()) > 65536 or "\x00" in source:
        raise LedgerError("The CSV must be UTF-8 text of at most 64 KiB.")
    if not mapping or len(mapping) > len(FIELDS) or len(set(mapping.values())) != len(mapping):
        raise LedgerError("Map each destination field once.")
    if not set(mapping.values()) <= FIELDS or not {"effective_date", "kind"} <= set(
        mapping.values()
    ):
        raise LedgerError("Map the date and type columns and use only supported fields.")
    reader = csv.DictReader(io.StringIO(source.removeprefix("\ufeff")), strict=True)
    try:
        headers = reader.fieldnames
    except csv.Error as error:
        raise LedgerError("The CSV headers are malformed.") from error
    if not headers or len(headers) > 40 or len(set(headers)) != len(headers):
        raise LedgerError("The CSV needs distinct column headers.")
    if not set(mapping) <= set(headers):
        raise LedgerError("A mapped column is missing from the CSV.")
    candidates: list[Entry] = []
    try:
        for line, row in enumerate(reader, 2):
            if (
                len(candidates) >= 200
                or None in row
                or any(value is None for value in row.values())
            ):
                raise LedgerError(f"Row {line}: incomplete row or too many rows.")
            data = {field: row[column].strip() for column, field in mapping.items()}
            if any(len(value) > 4096 for value in data.values()):
                raise LedgerError(f"Row {line}: a selected field is too long.")
            raw_date = data.pop("effective_date")
            if len(raw_date) != 10 or raw_date[4] != "-" or raw_date[7] != "-":
                raise LedgerError(f"Row {line}: use an unambiguous YYYY-MM-DD date.")
            try:
                effective_date = date.fromisoformat(raw_date)
            except ValueError as error:
                raise LedgerError(f"Row {line}: invalid calendar date.") from error
            if data["kind"] not in KINDS:
                raise LedgerError(f"Row {line}: unsupported transaction type.")
            for field in ("currency", "asset_type"):
                if field in data and data[field] == "":
                    data.pop(field)
            if not currency_code(data.get("currency", "CAD")):
                raise LedgerError(f"Row {line}: invalid original currency.")
            if data.get("asset_type", "stock") not in {"stock", "etf"}:
                raise LedgerError(f"Row {line}: unsupported instrument type.")
            for field in NUMBER_FIELDS:
                if field not in data:
                    continue
                if data[field] == "":
                    if field == "book_cost":
                        data[field] = None
                    else:
                        data.pop(field)
                else:
                    try:
                        decimal(data[field])
                    except LedgerError as error:
                        raise LedgerError(f"Row {line}: invalid {field} decimal.") from error
            if data.get("book_cost") is not None and data["kind"] != "opening_position":
                raise LedgerError(
                    f"Row {line}: only an opening position accepts an explicit original book cost."
                )
            for field in ("symbol", "destination_account", "destination_currency", "replaces"):
                if field in data and data[field] == "":
                    data[field] = None
            if data.get("destination_currency") is not None and data["kind"] != "exchange":
                raise LedgerError(
                    f"Row {line}: only a currency exchange accepts a destination currency."
                )
            if data.get("destination_account") is not None and data["kind"] != "transfer":
                raise LedgerError(f"Row {line}: only a linked transfer accepts another account.")
            if data.get("destination_currency") and not currency_code(data["destination_currency"]):
                raise LedgerError(f"Row {line}: invalid destination currency.")
            if data.get("symbol"):
                symbol = data["symbol"].upper()
                if (
                    not symbol.isascii()
                    or len(symbol) > 15
                    or any(
                        not character.isalnum() and character not in ".^-" for character in symbol
                    )
                ):
                    raise LedgerError(f"Row {line}: invalid symbol.")
                data["symbol"] = symbol
            candidates.append(Entry(str(uuid4()), account, effective_date, **data))
    except csv.Error as error:
        raise LedgerError("The CSV quoting is malformed. No rows were imported.") from error
    if not candidates:
        raise LedgerError("The CSV has no transaction rows.")
    return candidates


def csv_template() -> str:
    """Opening positions intentionally omit cost unless the user knows their original cost."""
    return (
        "date,type,currency,symbol,asset_type,quantity,price,amount,fee,book_cost\n"
        "2026-10-01,opening_cash,CAD,,,,,1000,0,\n"
        "2026-10-01,opening_position,USD,SPY,etf,2,,,,\n"
    )
