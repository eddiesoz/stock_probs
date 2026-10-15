"""Bounded, owner-scoped adapters over persisted briefing evidence.

The adapter reads only immutable/local records. It does not call providers, schedulers, mail, or
the network. Historical prices are derived from captured forecast inputs and monitoring
observations; missing watchlist history remains explicitly unavailable.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, cast

from stock_probs.briefing_domain import (
    MAX_SOURCE_ITEMS,
    DueThesisReviewSummary,
    ForecastOutcomeChange,
    OutcomeEvidenceState,
    PriceObservation,
    PriceObservationState,
    TriggeredAlertSummary,
    utc_instant,
)
from stock_probs.briefing_service import BriefingSourceUnavailableError
from stock_probs.repository import Repository

_MAX_WATCHLIST_ITEMS = 50
_MAX_ALERTS_PER_OWNER = 50
_MAX_ALERT_CONFIG_REVISIONS = 1_000
_MAX_PRICE_SNAPSHOT_BYTES = 256 * 1024
_MAX_PRICE_BAR_ITEMS = 505
_MAX_OUTCOME_SCAN_ROWS = 1_000
_MAX_THESIS_ITEMS = 50
_MAX_THESIS_REVISIONS = 1_000
_MAX_RESEARCH_PAYLOAD_BYTES = 32 * 1024
_MAX_SOURCE_LIMIT = MAX_SOURCE_ITEMS
_SYMBOL_RE = re.compile(r"[A-Z0-9][A-Z0-9.-]{0,19}\Z")
_PROVIDER_RE = re.compile(r"[A-Za-z0-9_.:-]{1,80}\Z")
_CURRENCY_RE = re.compile(r"[A-Z]{3}\Z")


class RepositoryBriefingSources:
    """Implement the four briefing source protocols from owner-bound SQLite records."""

    def __init__(self, repository: Repository) -> None:
        if not isinstance(repository, Repository):
            raise TypeError("repository must be a Repository")
        self.repository = repository

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        try:
            with self.repository.connect() as connection:
                yield connection
        except BriefingSourceUnavailableError:
            raise
        except Exception as error:
            raise BriefingSourceUnavailableError(
                "Persisted briefing data is temporarily unavailable."
            ) from error

    @staticmethod
    def _request(
        owner_user_id: int,
        observed_as_of: datetime,
        limit: int,
        baseline_at: datetime | None = None,
    ) -> tuple[datetime, datetime | None]:
        if type(owner_user_id) is not int or owner_user_id < 1:
            raise BriefingSourceUnavailableError("The briefing source is unavailable.")
        if type(limit) is not int or not 1 <= limit <= _MAX_SOURCE_LIMIT:
            raise BriefingSourceUnavailableError("The briefing source exceeded its bounds.")
        try:
            end = utc_instant(observed_as_of, "observed_as_of")
            start = utc_instant(baseline_at, "baseline_at") if baseline_at is not None else None
        except ValueError as error:
            raise BriefingSourceUnavailableError("The briefing source is unavailable.") from error
        if start is not None and start > end:
            raise BriefingSourceUnavailableError("The briefing source is unavailable.")
        return end, start

    @staticmethod
    def _check_active_owner(connection: sqlite3.Connection, owner_user_id: int) -> None:
        row = connection.execute(
            "SELECT status FROM users WHERE id = ?", (owner_user_id,)
        ).fetchone()
        if row is None or row["status"] != "active":
            raise BriefingSourceUnavailableError("The briefing source is unavailable.")

    @staticmethod
    def _parse_timestamp(value: object, label: str) -> datetime:
        if not isinstance(value, str) or not 1 <= len(value) <= 40:
            raise BriefingSourceUnavailableError("Persisted briefing timestamps are invalid.")
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
            return utc_instant(parsed, label)
        except (ValueError, TypeError) as error:
            raise BriefingSourceUnavailableError(
                "Persisted briefing timestamps are invalid."
            ) from error

    @staticmethod
    def _in_window(recorded_at: datetime, baseline_at: datetime | None, end: datetime) -> bool:
        return recorded_at <= end and (baseline_at is None or recorded_at > baseline_at)

    @staticmethod
    def _decode_json(value: object, *, maximum_bytes: int, label: str) -> Any:
        if not isinstance(value, str) or len(value.encode("utf-8")) > maximum_bytes:
            raise BriefingSourceUnavailableError(f"Persisted {label} exceeds its bounds.")
        try:
            return json.loads(value)
        except (json.JSONDecodeError, UnicodeError) as error:
            raise BriefingSourceUnavailableError(f"Persisted {label} is invalid.") from error

    @staticmethod
    def _positive_decimal(value: object, label: str) -> Decimal:
        if type(value) not in {str, int, float}:
            raise BriefingSourceUnavailableError(f"Persisted {label} is invalid.")
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError) as error:
            raise BriefingSourceUnavailableError(f"Persisted {label} is invalid.") from error
        if not result.is_finite() or result <= 0 or len(result.as_tuple().digits) > 32:
            raise BriefingSourceUnavailableError(f"Persisted {label} is invalid.")
        return result

    @staticmethod
    def _bounded_rows(rows: list[sqlite3.Row], maximum: int, label: str) -> list[sqlite3.Row]:
        if len(rows) > maximum:
            raise BriefingSourceUnavailableError(f"Persisted {label} exceed the scan limit.")
        return rows

    def _watchlist(
        self, connection: sqlite3.Connection, owner_user_id: int, end: datetime
    ) -> dict[tuple[str, str], datetime]:
        rows = connection.execute(
            "SELECT canonical_symbol, asset_type, added_at FROM user_instrument_list_items "
            "WHERE owner_user_id = ? AND kind = 'watchlist' "
            "ORDER BY added_at, canonical_symbol, asset_type LIMIT ?",
            (owner_user_id, _MAX_WATCHLIST_ITEMS + 1),
        ).fetchall()
        self._bounded_rows(rows, _MAX_WATCHLIST_ITEMS, "watchlist entries")
        members: dict[tuple[str, str], datetime] = {}
        for row in rows:
            symbol, asset_type = row["canonical_symbol"], row["asset_type"]
            if not isinstance(symbol, str) or _SYMBOL_RE.fullmatch(symbol) is None:
                raise BriefingSourceUnavailableError("Persisted watchlist identity is invalid.")
            if asset_type not in {"stock", "etf"}:
                raise BriefingSourceUnavailableError("Persisted watchlist identity is invalid.")
            added_at = self._parse_timestamp(row["added_at"], "watchlist added_at")
            if added_at <= end:
                key = (symbol, asset_type)
                prior = members.get(key)
                if prior is None or added_at < prior:
                    members[key] = added_at
        return members

    @staticmethod
    def _alert_config(value: object) -> dict[str, Any]:
        payload = RepositoryBriefingSources._decode_json(
            value, maximum_bytes=4_096, label="alert configuration"
        )
        if not isinstance(payload, dict) or set(payload) != {
            "symbol",
            "currency",
            "threshold",
            "direction",
            "repeating",
        }:
            raise BriefingSourceUnavailableError("Persisted alert configuration is invalid.")
        symbol = payload.get("symbol")
        currency = payload.get("currency")
        if (
            not isinstance(symbol, str)
            or _SYMBOL_RE.fullmatch(symbol) is None
            or not isinstance(currency, str)
            or _CURRENCY_RE.fullmatch(currency) is None
            or payload.get("direction") not in {"above", "below"}
            or type(payload.get("repeating")) is not bool
        ):
            raise BriefingSourceUnavailableError("Persisted alert configuration is invalid.")
        RepositoryBriefingSources._positive_decimal(payload.get("threshold"), "alert threshold")
        return payload

    def _alert_rows(self, connection: sqlite3.Connection, owner_user_id: int) -> list[sqlite3.Row]:
        rows = connection.execute(
            "SELECT id FROM price_alerts WHERE owner_user_id = ? ORDER BY created_at, id LIMIT ?",
            (owner_user_id, _MAX_ALERTS_PER_OWNER + 1),
        ).fetchall()
        self._bounded_rows(rows, _MAX_ALERTS_PER_OWNER, "alert configurations")
        return rows

    @staticmethod
    def _price_point(
        *,
        owner_user_id: int,
        source_ref: str,
        symbol: str,
        asset_type: str,
        provider: str,
        currency: str,
        price: object,
        observed_at: datetime,
        received_at: datetime,
        state: str = "observed",
    ) -> PriceObservation:
        if (
            _SYMBOL_RE.fullmatch(symbol) is None
            or asset_type not in {"stock", "etf"}
            or _PROVIDER_RE.fullmatch(provider) is None
            or _CURRENCY_RE.fullmatch(currency) is None
        ):
            raise BriefingSourceUnavailableError("Persisted price provenance is invalid.")
        return PriceObservation(
            owner_user_id=owner_user_id,
            source_ref=source_ref,
            symbol=symbol,
            asset_type=asset_type,
            provider=provider,
            currency=currency,
            price=RepositoryBriefingSources._positive_decimal(price, "price"),
            observed_at=observed_at,
            received_at=received_at,
            state=cast(PriceObservationState, state),
        )

    def _snapshot_points(
        self,
        connection: sqlite3.Connection,
        owner_user_id: int,
        identity: tuple[str, str],
        added_at: datetime,
        end: datetime,
    ) -> list[PriceObservation]:
        symbol, asset_type = identity
        row = connection.execute(
            "SELECT input.id AS input_id, input.created_at, input.snapshot_json, "
            "owner.assigned_at, run.symbol, run.asset_type "
            "FROM forecast_inputs AS input "
            "JOIN forecast_runs AS run ON run.id = input.run_id "
            "JOIN forecast_run_owners AS owner ON owner.run_id = input.run_id "
            "WHERE owner.owner_user_id = ? AND run.symbol = ? AND run.asset_type = ? "
            "AND input.created_at <= ? AND owner.assigned_at <= ? "
            "ORDER BY input.created_at DESC, input.id DESC LIMIT 1",
            (
                owner_user_id,
                symbol,
                asset_type,
                _timestamp_text(end),
                _timestamp_text(end),
            ),
        ).fetchone()
        if row is None:
            return []
        assigned_at = self._parse_timestamp(row["assigned_at"], "forecast ownership time")
        created_at = self._parse_timestamp(row["created_at"], "forecast input created_at")
        if assigned_at > end or created_at > end:
            return []
        snapshot = self._decode_json(
            row["snapshot_json"],
            maximum_bytes=_MAX_PRICE_SNAPSHOT_BYTES,
            label="forecast snapshot",
        )
        if not isinstance(snapshot, dict):
            raise BriefingSourceUnavailableError("Persisted forecast snapshot is invalid.")
        captured_at = self._parse_timestamp(snapshot.get("captured_at"), "captured_at")
        if not captured_at <= created_at <= end:
            raise BriefingSourceUnavailableError("Forecast snapshot provenance is invalid.")
        snapshot_symbol = snapshot.get("canonical_symbol")
        if snapshot_symbol != symbol or snapshot.get("asset_type") != asset_type:
            raise BriefingSourceUnavailableError("Forecast snapshot identity is inconsistent.")
        provider, currency = snapshot.get("provider"), snapshot.get("currency")
        if (
            not isinstance(provider, str)
            or _PROVIDER_RE.fullmatch(provider) is None
            or not isinstance(currency, str)
            or _CURRENCY_RE.fullmatch(currency) is None
        ):
            raise BriefingSourceUnavailableError("Forecast snapshot provenance is invalid.")
        bars = snapshot.get("selected_daily_bars")
        if not isinstance(bars, list) or len(bars) > _MAX_PRICE_BAR_ITEMS:
            raise BriefingSourceUnavailableError("Persisted daily bars exceed their bounds.")

        candidates: list[PriceObservation] = []
        previous_bar_at: datetime | None = None
        for index, bar in enumerate(bars):
            if not isinstance(bar, dict) or set(bar) != {
                "timestamp",
                "end",
                "close",
                "duration_seconds",
            }:
                raise BriefingSourceUnavailableError("Persisted daily bar is invalid.")
            if type(bar.get("duration_seconds")) is not int or bar["duration_seconds"] != 0:
                raise BriefingSourceUnavailableError("Persisted daily bar is not a close.")
            observed_at = self._parse_timestamp(bar.get("timestamp"), "daily bar timestamp")
            bar_end = self._parse_timestamp(bar.get("end"), "daily bar end")
            if observed_at != bar_end or bar_end > captured_at:
                raise BriefingSourceUnavailableError("Persisted daily bar provenance is invalid.")
            if previous_bar_at is not None and observed_at <= previous_bar_at:
                raise BriefingSourceUnavailableError("Persisted daily bar ordering is invalid.")
            previous_bar_at = observed_at
            if observed_at < added_at or observed_at > end:
                continue
            source_ref = f"forecast-input:{int(row['input_id'])}:daily:{index}"
            candidates.append(
                self._price_point(
                    owner_user_id=owner_user_id,
                    source_ref=source_ref,
                    symbol=symbol,
                    asset_type=asset_type,
                    provider=provider,
                    currency=currency,
                    price=bar.get("close"),
                    observed_at=observed_at,
                    received_at=created_at,
                )
            )
        if not candidates:
            return []
        return [max(candidates, key=self._point_order)]

    @staticmethod
    def _point_order(item: PriceObservation) -> tuple[datetime, datetime, str]:
        if item.observed_at is None or item.received_at is None:
            raise BriefingSourceUnavailableError("Persisted price timestamps are incomplete.")
        return item.observed_at, item.received_at, item.source_ref

    def _alert_price_points(
        self,
        connection: sqlite3.Connection,
        owner_user_id: int,
        members: dict[tuple[str, str], datetime],
        end: datetime,
    ) -> list[PriceObservation]:
        types_by_symbol: dict[str, set[str]] = defaultdict(set)
        for symbol, asset_type in members:
            types_by_symbol[symbol].add(asset_type)
        candidates: list[PriceObservation] = []
        self._alert_rows(connection, owner_user_id)
        for symbol, matched_types in sorted(types_by_symbol.items()):
            if len(matched_types) != 1:
                continue
            asset_type = next(iter(matched_types))
            identity = (symbol, asset_type)
            added_at = members[identity]
            row = connection.execute(
                "SELECT observation.request_id, observation.observation_kind, "
                "observation.requested_at, observation.received_at, observation.accepted_at, "
                "observation.observed_at, observation.provider, observation.symbol, "
                "observation.currency, observation.price, observation.disposition, "
                "observation.stale, observation.generation "
                "FROM price_alert_observations AS observation "
                "JOIN price_alerts AS alert ON alert.id = observation.alert_id "
                "AND alert.owner_user_id = observation.owner_user_id "
                "WHERE observation.owner_user_id = ? AND observation.symbol = ? "
                "AND observation.stale = 0 AND observation.observed_at >= ? "
                "AND observation.observed_at <= ? AND observation.received_at <= ? "
                "ORDER BY observation.observed_at DESC, observation.received_at DESC, "
                "observation.request_id DESC LIMIT 1",
                (
                    owner_user_id,
                    symbol,
                    _timestamp_text(added_at),
                    _timestamp_text(end),
                    _timestamp_text(end),
                ),
            ).fetchone()
            if row is None:
                continue
            else:
                observed_at = self._parse_timestamp(row["observed_at"], "alert observation time")
                received_at = self._parse_timestamp(row["received_at"], "alert receipt time")
                requested_at = self._parse_timestamp(row["requested_at"], "alert request time")
                accepted_at = self._parse_timestamp(row["accepted_at"], "alert acceptance time")
                if not (
                    observed_at <= received_at <= accepted_at <= end
                    and requested_at <= received_at
                    and observed_at >= added_at
                    and row["symbol"] == symbol
                    and isinstance(row["currency"], str)
                    and _CURRENCY_RE.fullmatch(row["currency"]) is not None
                    and type(row["stale"]) is int
                    and row["stale"] == 0
                    and type(row["generation"]) is int
                    and row["generation"] > 0
                    and row["observation_kind"] in {"arm_snapshot", "tick"}
                    and row["disposition"] in {"initial", "ignored", "observed", "triggered"}
                ):
                    raise BriefingSourceUnavailableError("Alert observation provenance is invalid.")
                request_id = row["request_id"]
                if not isinstance(request_id, str) or len(request_id) != 36:
                    raise BriefingSourceUnavailableError("Alert observation identity is invalid.")
                state = "initial" if row["disposition"] == "initial" else "observed"
                candidates.append(
                    self._price_point(
                        owner_user_id=owner_user_id,
                        source_ref=f"alert-observation:{request_id}",
                        symbol=symbol,
                        asset_type=asset_type,
                        provider=row["provider"],
                        currency=row["currency"],
                        price=row["price"],
                        observed_at=observed_at,
                        received_at=received_at,
                        state=state,
                    )
                )
        # Repeated stored snapshots can contain the same daily close. Identical observations
        # collapse to the latest persisted receipt; conflicting same-time prices fail closed.
        return candidates

    def list_price_observations(
        self, owner_user_id: int, *, observed_as_of: datetime, limit: int
    ) -> list[PriceObservation]:
        end, _ = self._request(owner_user_id, observed_as_of, limit)
        try:
            with self._read() as connection:
                self._check_active_owner(connection, owner_user_id)
                members = self._watchlist(connection, owner_user_id, end)
                if not members:
                    return []
                candidates: list[PriceObservation] = []
                for identity, added_at in sorted(members.items()):
                    candidates.extend(
                        self._snapshot_points(connection, owner_user_id, identity, added_at, end)
                    )
                candidates.extend(self._alert_price_points(connection, owner_user_id, members, end))
                grouped: dict[tuple[str, str], list[PriceObservation]] = defaultdict(list)
                for item in candidates:
                    if item.observed_at is None or item.received_at is None:
                        raise BriefingSourceUnavailableError(
                            "Persisted price timestamps are incomplete."
                        )
                    grouped[(item.symbol, item.asset_type)].append(item)
                selected: list[PriceObservation] = []
                for identity, added_at in sorted(members.items()):
                    points = grouped.get(identity, [])
                    eligible_points: list[PriceObservation] = []
                    for item in points:
                        item_observed_at = item.observed_at
                        if item_observed_at is None:
                            raise BriefingSourceUnavailableError(
                                "Persisted price timestamps are incomplete."
                            )
                        if item_observed_at >= added_at:
                            eligible_points.append(item)
                    points = eligible_points
                    if points:
                        deduplicated: dict[datetime, PriceObservation] = {}
                        for item in points:
                            if item.observed_at is None:
                                raise BriefingSourceUnavailableError(
                                    "Persisted price timestamps are incomplete."
                                )
                            previous = deduplicated.get(item.observed_at)
                            if previous is not None:
                                if (previous.price, previous.currency, previous.provider) != (
                                    item.price,
                                    item.currency,
                                    item.provider,
                                ):
                                    raise BriefingSourceUnavailableError(
                                        "Persisted price sources disagree at one observation time."
                                    )
                                if self._point_order(item) > self._point_order(previous):
                                    deduplicated[item.observed_at] = item
                            else:
                                deduplicated[item.observed_at] = item
                        selected.append(max(deduplicated.values(), key=self._point_order))
                    else:
                        stable_ref = sha256(
                            f"{owner_user_id}:{identity[0]}:{identity[1]}".encode()
                        ).hexdigest()[:32]
                        selected.append(
                            PriceObservation(
                                owner_user_id=owner_user_id,
                                source_ref=f"watchlist-unavailable:{stable_ref}",
                                symbol=identity[0],
                                asset_type=identity[1],
                                provider=None,
                                currency=None,
                                price=None,
                                observed_at=None,
                                received_at=None,
                                state="unavailable",
                                reason="source_unavailable",
                            )
                        )
                if len(selected) > limit:
                    raise BriefingSourceUnavailableError(
                        "Price observations exceed the source limit."
                    )
                return sorted(
                    selected,
                    key=lambda item: (
                        item.observed_at is None,
                        item.observed_at or datetime.max.replace(tzinfo=UTC),
                        item.received_at or datetime.max.replace(tzinfo=UTC),
                        item.source_ref,
                    ),
                )
        except BriefingSourceUnavailableError:
            raise
        except Exception as error:
            raise BriefingSourceUnavailableError(
                "Persisted price data is temporarily unavailable."
            ) from error

    def list_outcome_changes(
        self,
        owner_user_id: int,
        *,
        baseline_at: datetime | None,
        observed_as_of: datetime,
        limit: int,
    ) -> list[ForecastOutcomeChange]:
        end, baseline = self._request(owner_user_id, observed_as_of, limit, baseline_at)
        try:
            with self._read() as connection:
                self._check_active_owner(connection, owner_user_id)
                outcomes = connection.execute(
                    "SELECT outcome.id, outcome.result_id, outcome.state, outcome.observed_at, "
                    "outcome.created_at FROM outcomes AS outcome "
                    "JOIN outcome_owners AS outcome_owner ON outcome_owner.outcome_id = outcome.id "
                    "JOIN forecast_result_owners AS result_owner "
                    "ON result_owner.result_id = outcome.result_id "
                    "WHERE outcome_owner.owner_user_id = ? AND result_owner.owner_user_id = ? "
                    "ORDER BY outcome.id LIMIT ?",
                    (owner_user_id, owner_user_id, _MAX_OUTCOME_SCAN_ROWS + 1),
                ).fetchall()
                self._bounded_rows(outcomes, _MAX_OUTCOME_SCAN_ROWS, "outcome history")
                evidence = connection.execute(
                    "SELECT evidence.outcome_id, evidence.result_id, evidence.state, "
                    "evidence.payload_json, evidence.collected_at, outcome.observed_at "
                    "FROM collected_outcome_evidence "
                    "AS evidence JOIN outcome_owners AS outcome_owner "
                    "ON outcome_owner.outcome_id = evidence.outcome_id "
                    "JOIN forecast_result_owners AS result_owner "
                    "ON result_owner.result_id = evidence.result_id "
                    "JOIN outcomes AS outcome ON outcome.id = evidence.outcome_id "
                    "WHERE evidence.owner_user_id = ? AND outcome_owner.owner_user_id = ? "
                    "AND result_owner.owner_user_id = ? ORDER BY evidence.outcome_id LIMIT ?",
                    (owner_user_id, owner_user_id, owner_user_id, _MAX_OUTCOME_SCAN_ROWS + 1),
                ).fetchall()
                self._bounded_rows(evidence, _MAX_OUTCOME_SCAN_ROWS, "collected outcome evidence")
                reviews = connection.execute(
                    "SELECT review.result_id, review.revision, review.state, review.reviewed_at "
                    "FROM forecast_outcome_reviews AS review "
                    "JOIN forecast_result_owners AS result_owner "
                    "ON result_owner.result_id = review.result_id "
                    "WHERE review.owner_user_id = ? AND result_owner.owner_user_id = ? "
                    "ORDER BY review.result_id, review.revision LIMIT ?",
                    (owner_user_id, owner_user_id, _MAX_OUTCOME_SCAN_ROWS + 1),
                ).fetchall()
                self._bounded_rows(reviews, _MAX_OUTCOME_SCAN_ROWS, "outcome reviews")

            events: list[ForecastOutcomeChange] = []
            revision_by_result: dict[int, int] = defaultdict(int)
            ordered_outcomes = [
                (
                    row,
                    self._parse_timestamp(row["created_at"], "outcome created_at"),
                )
                for row in outcomes
            ]
            ordered_outcomes.sort(key=lambda item: (item[0]["result_id"], item[1], item[0]["id"]))
            for row, recorded_at in ordered_outcomes:
                if recorded_at > end:
                    continue
                result_id = row["result_id"]
                revision_by_result[result_id] += 1
                if baseline is not None and recorded_at <= baseline:
                    continue
                state_map = {
                    "observed": "observed",
                    "unavailable": "unavailable",
                    "provisional": "manual_review",
                    # The schema stores no superseded outcome ID, so do not claim a correction link.
                    "corrected": "manual_review",
                }
                state = state_map.get(row["state"])
                if state is None:
                    raise BriefingSourceUnavailableError("Persisted outcome state is invalid.")
                observed_at = self._parse_timestamp(row["observed_at"], "outcome observed_at")
                if observed_at > recorded_at:
                    raise BriefingSourceUnavailableError("Persisted outcome timing is invalid.")
                events.append(
                    ForecastOutcomeChange(
                        owner_user_id=owner_user_id,
                        resource_ref=f"forecast-result:{result_id}",
                        source_ref=f"forecast-outcome:{row['id']}",
                        state=cast(OutcomeEvidenceState, state),
                        revision=revision_by_result[result_id],
                        recorded_at=recorded_at,
                        observed_at=observed_at,
                        correction_of=None,
                    )
                )
            for row in evidence:
                recorded_at = self._parse_timestamp(row["collected_at"], "evidence collected_at")
                if not self._in_window(recorded_at, baseline, end):
                    continue
                evidence_payload = self._decode_json(
                    row["payload_json"], maximum_bytes=262_144, label="collected outcome evidence"
                )
                if not isinstance(evidence_payload, dict):
                    raise BriefingSourceUnavailableError(
                        "Persisted collected outcome evidence is invalid."
                    )
                state_map = {
                    "observed": "observed",
                    "unavailable": "unavailable",
                    "incomparable": "incomparable",
                }
                state = state_map.get(row["state"])
                if state is None:
                    raise BriefingSourceUnavailableError("Collected outcome state is invalid.")
                observed_at = self._parse_timestamp(row["observed_at"], "outcome observed_at")
                if observed_at > recorded_at:
                    raise BriefingSourceUnavailableError("Collected outcome timing is invalid.")
                events.append(
                    ForecastOutcomeChange(
                        owner_user_id=owner_user_id,
                        resource_ref=f"forecast-result:{row['result_id']}",
                        source_ref=f"collected-outcome:{row['outcome_id']}",
                        state=cast(OutcomeEvidenceState, state),
                        revision=1,
                        recorded_at=recorded_at,
                        observed_at=observed_at,
                    )
                )
            for row in reviews:
                recorded_at = self._parse_timestamp(row["reviewed_at"], "outcome reviewed_at")
                if not self._in_window(recorded_at, baseline, end):
                    continue
                if row["state"] not in {"confirmed", "disputed"}:
                    raise BriefingSourceUnavailableError("Persisted outcome review is invalid.")
                events.append(
                    ForecastOutcomeChange(
                        owner_user_id=owner_user_id,
                        resource_ref=f"forecast-result:{row['result_id']}",
                        source_ref=f"outcome-review:{row['result_id']}:{row['revision']}",
                        state="manual_review",
                        revision=row["revision"],
                        recorded_at=recorded_at,
                        observed_at=None,
                    )
                )
            events.sort(key=lambda item: (item.recorded_at, item.source_ref))
            if len(events) > limit:
                raise BriefingSourceUnavailableError("Outcome changes exceed the source limit.")
            return events
        except BriefingSourceUnavailableError:
            raise
        except Exception as error:
            raise BriefingSourceUnavailableError(
                "Persisted outcome data is temporarily unavailable."
            ) from error

    def list_triggered_alerts(
        self,
        owner_user_id: int,
        *,
        baseline_at: datetime | None,
        observed_as_of: datetime,
        limit: int,
    ) -> list[TriggeredAlertSummary]:
        end, baseline = self._request(owner_user_id, observed_as_of, limit, baseline_at)
        try:
            with self._read() as connection:
                self._check_active_owner(connection, owner_user_id)
                notifications = connection.execute(
                    "SELECT id, payload_json, created_at FROM notifications "
                    "WHERE owner_user_id = ? AND kind = 'price_alert' "
                    "ORDER BY created_at, id LIMIT ?",
                    (owner_user_id, 1_000 + 1),
                ).fetchall()
                self._bounded_rows(notifications, 1_000, "alert notifications")
                alerts = {
                    row["id"]: row["payload_json"]
                    for row in connection.execute(
                        "SELECT id, payload_json FROM price_alerts WHERE owner_user_id = ? "
                        "ORDER BY created_at, id LIMIT ?",
                        (owner_user_id, _MAX_ALERTS_PER_OWNER + 1),
                    ).fetchall()
                }
                if len(alerts) > _MAX_ALERTS_PER_OWNER:
                    raise BriefingSourceUnavailableError(
                        "Persisted alert configurations exceed the scan limit."
                    )
                members = self._watchlist(connection, owner_user_id, end)
                types_by_symbol: dict[str, set[str]] = defaultdict(set)
                for symbol, asset_type in members:
                    types_by_symbol[symbol].add(asset_type)
                result: list[TriggeredAlertSummary] = []
                seen_events: set[tuple[str, datetime]] = set()
                for notification in notifications:
                    event_at = self._parse_timestamp(
                        notification["created_at"], "notification time"
                    )
                    if not self._in_window(event_at, baseline, end):
                        continue
                    payload = self._decode_json(
                        notification["payload_json"], maximum_bytes=8_192, label="notification"
                    )
                    required = {
                        "alert_id",
                        "generation",
                        "symbol",
                        "currency",
                        "threshold",
                        "direction",
                        "price",
                        "provider",
                        "observed_at",
                    }
                    if not isinstance(payload, dict) or set(payload) != required:
                        raise BriefingSourceUnavailableError(
                            "Persisted alert notification is invalid."
                        )
                    alert_id = payload["alert_id"]
                    config_text = alerts.get(alert_id)
                    symbol = payload["symbol"]
                    if (
                        config_text is None
                        or not isinstance(symbol, str)
                        or _SYMBOL_RE.fullmatch(symbol) is None
                        or not isinstance(payload["currency"], str)
                        or _CURRENCY_RE.fullmatch(payload["currency"]) is None
                        or payload["direction"] not in {"above", "below"}
                        or type(payload["generation"]) is not int
                        or payload["generation"] < 1
                    ):
                        raise BriefingSourceUnavailableError(
                            "Alert notification provenance is invalid."
                        )
                    notification_config = self._alert_config(config_text)
                    revision_rows = connection.execute(
                        "SELECT payload_json FROM price_alert_revisions "
                        "WHERE alert_id = ? AND owner_user_id = ? "
                        "ORDER BY revision DESC LIMIT ?",
                        (alert_id, owner_user_id, _MAX_ALERT_CONFIG_REVISIONS + 1),
                    ).fetchall()
                    self._bounded_rows(
                        revision_rows,
                        _MAX_ALERT_CONFIG_REVISIONS,
                        "alert configuration revisions",
                    )
                    historical_configs = [notification_config]
                    historical_configs.extend(
                        self._alert_config(row["payload_json"]) for row in revision_rows
                    )
                    notification_threshold = self._positive_decimal(
                        payload["threshold"], "notification threshold"
                    )
                    if not any(
                        config["symbol"] == symbol
                        and config["currency"] == payload["currency"]
                        and config["direction"] == payload["direction"]
                        and self._positive_decimal(config["threshold"], "alert threshold")
                        == notification_threshold
                        for config in historical_configs
                    ):
                        raise BriefingSourceUnavailableError(
                            "Alert notification configuration is not in the owner history."
                        )
                    observed_at = self._parse_timestamp(payload["observed_at"], "alert observed_at")
                    if observed_at > event_at:
                        raise BriefingSourceUnavailableError(
                            "Alert notification timing is invalid."
                        )
                    provider = payload["provider"]
                    if not isinstance(provider, str) or _PROVIDER_RE.fullmatch(provider) is None:
                        raise BriefingSourceUnavailableError(
                            "Alert notification provenance is invalid."
                        )
                    self._positive_decimal(payload["threshold"], "alert threshold")
                    self._positive_decimal(payload["price"], "alert price")
                    observation_rows = connection.execute(
                        "SELECT request_id, price, received_at, accepted_at "
                        "FROM price_alert_observations "
                        "WHERE owner_user_id = ? AND alert_id = ? AND generation = ? "
                        "AND symbol = ? AND currency = ? AND provider = ? AND observed_at = ? "
                        "AND stale = 0 LIMIT 2",
                        (
                            owner_user_id,
                            alert_id,
                            payload["generation"],
                            symbol,
                            payload["currency"],
                            provider,
                            _timestamp_text(observed_at),
                        ),
                    ).fetchall()
                    matches = [
                        row
                        for row in observation_rows
                        if self._positive_decimal(row["price"], "stored alert price")
                        == self._positive_decimal(payload["price"], "alert price")
                    ]
                    if len(matches) != 1:
                        raise BriefingSourceUnavailableError(
                            "Alert notification does not match one stored observation."
                        )
                    received_at = self._parse_timestamp(
                        matches[0]["received_at"], "alert observation receipt time"
                    )
                    accepted_at = self._parse_timestamp(
                        matches[0]["accepted_at"], "alert observation acceptance time"
                    )
                    if not observed_at <= received_at <= accepted_at <= event_at:
                        raise BriefingSourceUnavailableError(
                            "Alert notification precedes its stored observation."
                        )
                    matched_types = types_by_symbol.get(symbol, set())
                    asset_type = next(iter(matched_types)) if len(matched_types) == 1 else "unknown"
                    if asset_type not in {"stock", "etf"}:
                        # Ambiguous identities stay out of price-history joins.
                        asset_type = "unknown"
                    resource_ref = f"price-alert:{alert_id}"
                    event_key = (resource_ref, event_at)
                    if event_key in seen_events:
                        raise BriefingSourceUnavailableError("Alert event identity is ambiguous.")
                    seen_events.add(event_key)
                    result.append(
                        TriggeredAlertSummary(
                            owner_user_id=owner_user_id,
                            resource_ref=resource_ref,
                            symbol=symbol,
                            asset_type=asset_type,
                            triggered_at=event_at,
                        )
                    )
            result.sort(key=lambda item: (item.triggered_at, item.resource_ref))
            if len(result) > limit:
                raise BriefingSourceUnavailableError("Alert events exceed the source limit.")
            return result
        except BriefingSourceUnavailableError:
            raise
        except Exception as error:
            raise BriefingSourceUnavailableError(
                "Persisted alert data is temporarily unavailable."
            ) from error

    def list_due_thesis_reviews(
        self, owner_user_id: int, *, observed_as_of: datetime, limit: int
    ) -> list[DueThesisReviewSummary]:
        end, _ = self._request(owner_user_id, observed_as_of, limit)
        try:
            with self._read() as connection:
                self._check_active_owner(connection, owner_user_id)
                theses = connection.execute(
                    "SELECT id FROM research_theses WHERE owner_user_id = ? "
                    "ORDER BY updated_at, id LIMIT ?",
                    (owner_user_id, _MAX_THESIS_ITEMS + 1),
                ).fetchall()
                self._bounded_rows(theses, _MAX_THESIS_ITEMS, "thesis records")
                revisions_by_thesis: list[tuple[str, list[sqlite3.Row]]] = []
                for thesis in theses:
                    thesis_id = thesis["id"]
                    revisions = connection.execute(
                        "SELECT revision, payload_json, recorded_at FROM research_thesis_revisions "
                        "WHERE thesis_id = ? AND owner_user_id = ? "
                        "ORDER BY revision DESC LIMIT ?",
                        (thesis_id, owner_user_id, _MAX_THESIS_REVISIONS + 1),
                    ).fetchall()
                    self._bounded_rows(revisions, _MAX_THESIS_REVISIONS, "thesis revisions")
                    revisions_by_thesis.append((thesis_id, revisions))
            result: list[DueThesisReviewSummary] = []
            for thesis_id, revisions in revisions_by_thesis:
                eligible: list[tuple[int, datetime, dict[str, Any]]] = []
                for row in revisions:
                    recorded_at = self._parse_timestamp(row["recorded_at"], "thesis revision time")
                    if recorded_at > end:
                        continue
                    payload = self._decode_json(
                        row["payload_json"],
                        maximum_bytes=_MAX_RESEARCH_PAYLOAD_BYTES,
                        label="thesis revision",
                    )
                    if not isinstance(payload, dict):
                        raise BriefingSourceUnavailableError(
                            "Persisted thesis revision is invalid."
                        )
                    eligible.append((row["revision"], recorded_at, payload))
                if not eligible:
                    continue
                revision, _, payload = max(eligible, key=lambda item: (item[1], item[0]))
                status = payload.get("status")
                review_date = payload.get("review_date")
                if status not in {"watching", "active", "archived"}:
                    raise BriefingSourceUnavailableError("Persisted thesis status is invalid.")
                if status == "archived" or review_date is None:
                    continue
                if not isinstance(review_date, str) or len(review_date) != 10:
                    raise BriefingSourceUnavailableError("Persisted thesis review date is invalid.")
                try:
                    due_date = date.fromisoformat(review_date)
                except ValueError as error:
                    raise BriefingSourceUnavailableError(
                        "Persisted thesis review date is invalid."
                    ) from error
                if due_date.isoformat() != review_date:
                    raise BriefingSourceUnavailableError("Persisted thesis review date is invalid.")
                due_at = datetime.combine(due_date, time.min, tzinfo=UTC)
                if due_at <= end:
                    result.append(
                        DueThesisReviewSummary(
                            owner_user_id=owner_user_id,
                            thesis_ref=f"research-thesis:{thesis_id}",
                            revision=revision,
                            due_at=due_at,
                        )
                    )
            result.sort(key=lambda item: (item.due_at, item.thesis_ref, item.revision))
            if len(result) > limit:
                raise BriefingSourceUnavailableError("Thesis reviews exceed the source limit.")
            return result
        except BriefingSourceUnavailableError:
            raise
        except Exception as error:
            raise BriefingSourceUnavailableError(
                "Persisted thesis data is temporarily unavailable."
            ) from error


def _timestamp_text(value: datetime) -> str:
    """Normalize UTC parameters to the same form written by monitoring and briefing services."""

    return utc_instant(value, "timestamp").isoformat(timespec="microseconds").replace("+00:00", "Z")
