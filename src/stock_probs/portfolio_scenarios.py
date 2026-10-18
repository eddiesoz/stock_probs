"""Frozen native amounts, indicative display conversion and deterministic simulation drafts."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, localcontext
from typing import Any

from stock_probs.portfolio_ledger import LedgerError, calculated_decimal, decimal, text


def valuation(
    book: dict[str, Any],
    quotes: list[dict[str, Any]],
    fx: dict[str, Any],
    display_currency: str = "CAD",
    *,
    allow_zero_prices: bool = False,
) -> dict[str, Any]:
    """A missing quote or FX input makes the total unavailable, never deceptively partial."""
    if display_currency not in {"CAD", "USD"}:
        raise LedgerError("Display currency must be CAD or USD.")
    with localcontext() as context:
        context.prec = 48
        return _valuation(book, quotes, fx, display_currency, allow_zero_prices)


def _valuation(
    book: dict[str, Any],
    quotes: list[dict[str, Any]],
    fx: dict[str, Any],
    display_currency: str,
    allow_zero_prices: bool,
) -> dict[str, Any]:
    quote_map = {(row["symbol"], row["asset_type"]): row for row in quotes}
    rows: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    partial = Decimal("0")

    def rate(currency: str) -> Decimal | None:
        if currency == "CAD":
            return Decimal("1")
        row = fx.get(currency)
        try:
            return calculated_decimal(row["value"], positive=True) if row else None
        except (KeyError, LedgerError):
            return None

    def converted(amount: Decimal, currency: str) -> Decimal | None:
        if amount.is_zero():
            return Decimal("0")
        origin, destination = rate(currency), rate(display_currency)
        return None if origin is None or destination is None else amount * origin / destination

    for row in book["positions"]:
        quote = quote_map.get((row["symbol"], row["asset_type"]))
        output = {
            **row,
            "quote": deepcopy(quote),
            "native_value": None,
            "display_value": None,
            "unrealized_native": None,
            "unrealized_display": None,
        }
        try:
            if not quote or quote["currency"] != row["currency"]:
                raise LedgerError("Missing or mismatched quote currency.")
            price = calculated_decimal(quote["price"], positive=not allow_zero_prices)
        except (KeyError, LedgerError):
            missing.append({"symbol": row["symbol"], "reason": "quote_unavailable"})
            rows.append(output)
            continue
        native = Decimal(row["quantity"]) * price
        display = converted(native, row["currency"])
        gain = native - Decimal(row["book_cost"]) if row["book_cost"] is not None else None
        output.update(
            native_value=text(native),
            display_value=text(display),
            unrealized_native=text(gain),
            unrealized_display=text(converted(gain, row["currency"])) if gain is not None else None,
        )
        if display is None:
            missing.append({"symbol": row["symbol"], "reason": "fx_unavailable"})
        else:
            partial += display
        rows.append(output)
    cash = []
    for row in book["cash"]:
        value = converted(Decimal(row["amount"]), row["currency"])
        cash.append({**row, "display_value": text(value)})
        if value is None and Decimal(row["amount"]) != 0:
            missing.append({"symbol": row["currency"], "reason": "fx_unavailable"})
        elif value is not None:
            partial += value
    complete = not missing
    cash_total = sum(
        (Decimal(row["display_value"]) for row in cash if row["display_value"] is not None),
        Decimal("0"),
    )
    gains_complete = complete and all(row["unrealized_display"] is not None for row in rows)
    gain_total = sum(
        (
            Decimal(row["unrealized_display"])
            for row in rows
            if row["unrealized_display"] is not None
        ),
        Decimal("0"),
    )
    if complete and partial > 0:
        for row in rows:
            row["allocation_percent"] = text(Decimal(row["display_value"]) / partial * 100)
        for row in cash:
            row["allocation_percent"] = text(Decimal(row["display_value"] or "0") / partial * 100)
    else:
        for row in rows + cash:
            row["allocation_percent"] = None
    instrument_values: dict[tuple[str, str], Decimal] = {}
    for row in rows:
        if complete and row["display_value"] is not None:
            key = row["symbol"], row["asset_type"]
            instrument_values[key] = instrument_values.get(key, Decimal("0")) + Decimal(
                row["display_value"]
            )
    instrument_allocations = [
        {
            "symbol": symbol,
            "asset_type": asset_type,
            "display_value": text(value),
            "allocation_percent": text(value / partial * 100) if partial > 0 else None,
        }
        for (symbol, asset_type), value in sorted(instrument_values.items())
    ]
    return {
        "display_currency": display_currency,
        "complete": complete,
        "total_value": text(partial) if complete else None,
        "known_subtotal": text(partial),
        "cash_value": text(cash_total)
        if all(row["display_value"] is not None for row in cash)
        else None,
        "unrealized_gain": text(gain_total) if gains_complete else None,
        "largest_position_percent": max(
            (
                row["allocation_percent"]
                for row in instrument_allocations
                if row["allocation_percent"] is not None
            ),
            default=None,
            key=lambda value: Decimal(value),
        ),
        "instrument_allocations": instrument_allocations,
        "positions": rows,
        "cash": cash,
        "missing_inputs": missing,
        "unknown_cost_count": sum(row["book_cost"] is None for row in rows),
        "realized": deepcopy(book["realized"]),
        "fx": deepcopy(fx),
        "label": "Estimated value using dated quotes and indicative display FX; book results only.",
    }


def shock(value: str) -> Decimal:
    """Prices cannot drop below zero; scenario shocks are percentages, not predictions."""
    if not isinstance(value, str) or len(value) > 24:
        raise LedgerError("Invalid percentage shock.")
    try:
        result = Decimal(value)
    except ArithmeticError as error:
        raise LedgerError("Invalid percentage shock.") from error
    if not result.is_finite() or result < -100 or result > 1000:
        raise LedgerError("Percentage shocks must be between -100 and 1000.")
    return result


def simulate(baseline: dict[str, Any], assumptions: dict[str, Any]) -> dict[str, Any]:
    """Reallocate at frozen baseline prices, then apply shocks without changing real records."""
    with localcontext() as context:
        context.prec = 48
        book = deepcopy(baseline["book"])
        quotes = deepcopy(baseline["quotes"])
        fx = deepcopy(baseline["fx"])
        quote_map = {(row["symbol"], row["asset_type"]): row for row in quotes}
        cash_map = {(row["account_id"], row["currency"]): row for row in book["cash"]}
        if (
            len(assumptions.get("reallocations", [])) > 20
            or len(assumptions.get("price_shocks", [])) > 100
        ):
            raise LedgerError("Too many scenario assumptions.")
        for item in assumptions.get("reallocations", []):
            quote = quote_map.get((item["symbol"], item["asset_type"]))
            if not quote:
                raise LedgerError("A reallocation needs a frozen quote in this baseline.")
            funding_currency = item.get("funding_currency") or quote["currency"]

            def frozen_rate(currency: str) -> Decimal:
                if currency == "CAD":
                    return Decimal("1")
                if currency not in fx:
                    raise LedgerError("This reallocation needs a frozen indicative FX rate.")
                return calculated_decimal(fx[currency]["value"], positive=True)

            funding_rate, instrument_rate = (
                frozen_rate(funding_currency),
                frozen_rate(quote["currency"]),
            )
            if item.get("amount") is not None:
                if item.get("quantity") is not None:
                    raise LedgerError("Choose a cash amount or units, not both.")
                spent = decimal(item["amount"], positive=True)
                cost = spent * funding_rate / instrument_rate
                quantity = cost / calculated_decimal(quote["price"], positive=True)
            else:
                quantity = decimal(item["quantity"], positive=True)
                cost = quantity * calculated_decimal(quote["price"], positive=True)
                spent = cost * instrument_rate / funding_rate
            cash = cash_map.get((item["account_id"], funding_currency))
            if not cash or Decimal(cash["amount"]) < spent:
                raise LedgerError(
                    "Hypothetical reallocation exceeds existing selected-currency cash."
                )
            cash["amount"] = text(Decimal(cash["amount"]) - spent)
            existing = next(
                (
                    row
                    for row in book["positions"]
                    if (row["account_id"], row["symbol"], row["asset_type"])
                    == (item["account_id"], item["symbol"], item["asset_type"])
                ),
                None,
            )
            if existing:
                if existing["currency"] != quote["currency"]:
                    raise LedgerError(
                        "This frozen quote uses a different currency from the existing position."
                    )
                existing["quantity"] = text(Decimal(existing["quantity"]) + quantity)
                if existing["book_cost"] is not None:
                    existing["book_cost"] = text(Decimal(existing["book_cost"]) + cost)
            else:
                book["positions"].append(
                    {
                        "account_id": item["account_id"],
                        "symbol": item["symbol"],
                        "asset_type": item["asset_type"],
                        "currency": quote["currency"],
                        "quantity": text(quantity),
                        "book_cost": text(cost),
                        "cost_known": True,
                    }
                )
        seen = set()
        for item in assumptions.get("price_shocks", []):
            key = item["symbol"], item["asset_type"]
            if key in seen or key not in quote_map:
                raise LedgerError("Choose distinct instruments with frozen baseline quotes.")
            seen.add(key)
            quote_map[key]["price"] = text(
                calculated_decimal(quote_map[key]["price"], positive=True)
                * (1 + shock(item["percent"]) / 100)
            )
        fx_percent = shock(assumptions.get("usd_cad_percent", "0"))
        if fx_percent != 0:
            if "USD" not in fx:
                raise LedgerError("This baseline has no USD/CAD rate.")
            if fx_percent == -100:
                raise LedgerError("USD/CAD must remain greater than zero.")
            fx["USD"]["value"] = text(
                calculated_decimal(fx["USD"]["value"], positive=True) * (1 + fx_percent / 100)
            )
        before = valuation(
            baseline["book"], baseline["quotes"], baseline["fx"], baseline["display_currency"]
        )
        after = valuation(book, quotes, fx, baseline["display_currency"], allow_zero_prices=True)
        difference = (
            None
            if not before["complete"] or not after["complete"]
            else (Decimal(after["total_value"]) - Decimal(before["total_value"]))
        )
        return {
            "baseline_id": baseline["id"],
            "captured_at": baseline["captured_at"],
            "assumptions": deepcopy(assumptions),
            "before": before,
            "after": after,
            "value_difference": text(difference),
            "label": "Simulation only",
            "sequence": "Reallocate from existing cash at baseline prices and indicative "
            "FX, then apply price and FX shocks. No actual exchange is "
            "recorded.",
        }
