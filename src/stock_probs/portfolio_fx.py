"""Bounded daily indicative USD/CAD fetch; actual exchanges retain recorded execution amounts."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from stock_probs.portfolio_ledger import LedgerError, decimal
from stock_probs.repository import Repository

URL = "https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?recent=10"


class FixtureIndicativeFX:
    """Keep deterministic fixture mode isolated from live FX and label simulated rates."""

    def rates(self, now: datetime) -> dict[str, Any]:
        """A fixture observation is explicitly simulated and never persisted as Bank data."""
        return {
            "rates": {
                "CAD": {"value": "1", "provider": "Native currency"},
                "USD": {
                    "value": "1.32",
                    "provider": "Deterministic simulated FX",
                    "publication_date": now.date().isoformat(),
                    "basis": "Simulated CAD per USD; not Bank of Canada data",
                },
            },
            "status": "available",
            "last_attempt_failed": False,
            "label": "Deterministic simulated FX; not live Bank of Canada observations.",
        }


def fetch_public_rates() -> object:
    """Use a fixed TLS destination, no redirects/cookies/proxy, and bounded response bytes/time."""
    deadline = time.monotonic() + 8
    with (
        httpx.Client(timeout=4, follow_redirects=False, trust_env=False) as client,
        client.stream("GET", URL, headers={"Accept": "application/json"}) as response,
    ):
        if response.status_code != 200:
            raise LedgerError("Bank of Canada rates are unavailable.")
        content = bytearray()
        for chunk in response.iter_bytes():
            content.extend(chunk)
            if len(content) > 65536 or time.monotonic() > deadline:
                raise LedgerError("Bank of Canada response exceeded its limit.")
    try:
        return json.loads(content)
    except (ValueError, UnicodeError) as error:
        raise LedgerError("Bank of Canada response was invalid.") from error


def latest_usd(payload: object, today: date) -> dict[str, str]:
    """Select a valid dated published observation, never a future date or undated latest value."""
    if not isinstance(payload, dict) or not isinstance(payload.get("observations"), list):
        raise LedgerError("No published FX observations were available.")
    observations = payload["observations"]
    if not 1 <= len(observations) <= 31:
        raise LedgerError("Invalid FX observation count.")
    candidates = []
    for row in observations:
        if not isinstance(row, dict) or not isinstance(row.get("d"), str):
            raise LedgerError("An FX observation has no publication date.")
        try:
            published = date.fromisoformat(row["d"])
            amount = decimal(row["FXUSDCAD"]["v"], positive=True)
        except (KeyError, TypeError, ValueError) as error:
            raise LedgerError("An FX observation is malformed.") from error
        if published > today or published < today - timedelta(days=30) or amount > 10000:
            raise LedgerError("An FX observation is out of range.")
        candidates.append((published, amount))
    published, amount = max(candidates)
    return {
        "value": format(amount, "f"),
        "publication_date": published.isoformat(),
        "provider": "Bank of Canada",
        "basis": "CAD per USD; daily average indicative rate",
        "source_url": URL,
    }


class IndicativeFX:
    """Persist the daily attempt date so restarts cannot blindly repeat requests."""

    def __init__(
        self, repository: Repository, fetch: Callable[[], object] = fetch_public_rates
    ) -> None:
        self.repository = repository
        self.fetch = fetch
        self.lock = threading.Lock()

    def rates(self, now: datetime) -> dict[str, Any]:
        """Return provenance and failure/staleness status beside any usable prior publication."""
        now = now.astimezone(UTC)
        with self.lock:
            with self.repository.connect() as connection:
                state = connection.execute(
                    "SELECT * FROM portfolio_fx_fetch_state WHERE provider='Bank of Canada'"
                ).fetchone()
            if state is None or state["last_attempt_date"] != now.date().isoformat():
                # Reserve the daily attempt before I/O so a restart never blindly repeats it.
                with self.repository.connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    current = connection.execute(
                        "SELECT last_attempt_date FROM portfolio_fx_fetch_state WHERE "
                        "provider='Bank of Canada'"
                    ).fetchone()
                    reserved = current is None or current[0] != now.date().isoformat()
                    if reserved:
                        connection.execute(
                            "INSERT INTO portfolio_fx_fetch_state VALUES ('Bank of Canada', "
                            "?, ?, 'failed') "
                            "ON CONFLICT(provider) DO UPDATE SET "
                            "last_attempt_at=excluded.last_attempt_at, "
                            "last_attempt_date=excluded.last_attempt_date, last_result='failed'",
                            (now.isoformat(), now.date().isoformat()),
                        )
                    connection.commit()
                if reserved:
                    try:
                        row = latest_usd(self.fetch(), now.date())
                    except (LedgerError, httpx.HTTPError):
                        row = None
                    if row is not None:
                        with self.repository.connect() as connection:
                            connection.execute("BEGIN IMMEDIATE")
                            connection.execute(
                                "INSERT INTO portfolio_fx_cache VALUES (?, 'Bank of Canada', ?, ?) "
                                "ON CONFLICT(publication_date) DO UPDATE SET "
                                "fetched_at=excluded.fetched_at, "
                                "rates_json=excluded.rates_json",
                                (
                                    row["publication_date"],
                                    now.isoformat(),
                                    json.dumps({"USD": row}),
                                ),
                            )
                            connection.execute(
                                "UPDATE portfolio_fx_fetch_state SET last_result='successful' "
                                "WHERE provider='Bank of Canada' AND last_attempt_date=?",
                                (now.date().isoformat(),),
                            )
                            connection.execute(
                                "DELETE FROM portfolio_fx_cache WHERE publication_date < ?",
                                ((now.date() - timedelta(days=365)).isoformat(),),
                            )
                            connection.commit()
            with self.repository.connect() as connection:
                cache = connection.execute(
                    "SELECT * FROM portfolio_fx_cache WHERE publication_date <= ? "
                    "ORDER BY publication_date DESC LIMIT 1",
                    (now.date().isoformat(),),
                ).fetchone()
                state = connection.execute(
                    "SELECT * FROM portfolio_fx_fetch_state WHERE provider='Bank of Canada'"
                ).fetchone()
        values: dict[str, Any] = {"CAD": {"value": "1", "provider": "Native currency"}}
        if cache and date.fromisoformat(cache["publication_date"]) >= now.date() - timedelta(
            days=30
        ):
            values.update(json.loads(cache["rates_json"]))
            values["USD"]["fetched_at"] = cache["fetched_at"]
            values["USD"]["publication_age_days"] = (
                now.date() - date.fromisoformat(cache["publication_date"])
            ).days
        return {
            "rates": values,
            "status": "available" if "USD" in values else "unavailable",
            "last_attempt_at": state["last_attempt_at"] if state else None,
            "last_attempt_failed": state is None or state["last_result"] == "failed",
            "label": "Dated indicative display rates; recorded exchanges retain their "
            "execution amounts.",
        }
