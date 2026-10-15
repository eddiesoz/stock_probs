"""Owner-bound, append-only persistence for deterministic briefing snapshots.

This draft store expects the unregistered migration-drafts/019 schema to have been applied by an
explicit future integration. Construction is inert and does not migrate or create database state.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from stock_probs.briefing_domain import (
    MAX_PRICE_OBSERVATIONS,
    BriefingDomainError,
    BriefingSnapshot,
    BriefingWindow,
    DueThesisReviewSummary,
    ForecastOutcomeChange,
    PriceMovementSummary,
    PriceObservation,
    TriggeredAlertSummary,
    baseline_for_window,
    canonical_uuid,
    decimal_text,
    parse_timestamp,
    request_fingerprint,
    summarize_price_movements,
    timestamp_text,
    utc_instant,
    validate_due_thesis_reviews,
    validate_outcome_changes,
    validate_price_observations,
    validate_threshold_bps,
    validate_triggered_alerts,
)
from stock_probs.repository import Repository

MAX_SNAPSHOT_BYTES = 65_536
MAX_PAGE_SIZE = 50
MAX_PRICE_ROWS = MAX_PRICE_OBSERVATIONS
MAX_OWNER_RETAINED_ROWS = 20_000
MAX_OWNER_RETAINED_BYTES = 64 * 1024 * 1024
_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_OWNER_USAGE_SQL = (
    "SELECT COUNT(*),COALESCE(SUM(length(CAST(owner_user_id AS TEXT)) + "
    "COALESCE(length(CAST(source_ref AS BLOB)),0) + "
    "COALESCE(length(CAST(payload_sha256 AS BLOB)),0) + "
    "COALESCE(length(CAST(symbol AS BLOB)),0) + "
    "COALESCE(length(CAST(asset_type AS BLOB)),0) + "
    "COALESCE(length(CAST(provider AS BLOB)),0) + "
    "COALESCE(length(CAST(currency AS BLOB)),0) + "
    "COALESCE(length(CAST(price_text AS BLOB)),0) + "
    "COALESCE(length(CAST(observed_at AS BLOB)),0) + "
    "COALESCE(length(CAST(received_at AS BLOB)),0) + "
    "COALESCE(length(CAST(state AS BLOB)),0) + "
    "COALESCE(length(CAST(reason AS BLOB)),0) + "
    "COALESCE(length(CAST(created_at AS BLOB)),0)),0) "
    "FROM briefing_price_observations WHERE owner_user_id=?",
    "SELECT COUNT(*),COALESCE(SUM(length(CAST(id AS BLOB)) + "
    "length(CAST(owner_user_id AS TEXT)) + length(CAST(idempotency_key AS BLOB)) + "
    "length(CAST(request_sha256 AS BLOB)) + length(CAST(window AS BLOB)) + "
    "COALESCE(length(CAST(baseline_at AS BLOB)),0) + "
    "length(CAST(observed_as_of AS BLOB)) + "
    "length(CAST(baseline_anchor_revision AS TEXT)) + "
    "length(CAST(preference_revision AS TEXT)) + length(CAST(threshold_bps AS TEXT)) + "
    "length(CAST(payload_json AS BLOB)) + length(CAST(created_at AS BLOB))),0) "
    "FROM briefing_snapshots WHERE owner_user_id=?",
    "SELECT COUNT(*),COALESCE(SUM(length(CAST(owner_user_id AS TEXT)) + "
    "length(CAST(revision AS TEXT)) + length(CAST(threshold_bps AS TEXT)) + "
    "length(CAST(updated_at AS BLOB))),0) "
    "FROM briefing_preferences WHERE owner_user_id=?",
    "SELECT COUNT(*),COALESCE(SUM(length(CAST(owner_user_id AS TEXT)) + "
    "length(CAST(revision AS TEXT)) + length(CAST(snapshot_id AS BLOB)) + "
    "length(CAST(baseline_at AS BLOB)) + length(CAST(visited_at AS BLOB))),0) "
    "FROM briefing_visit_anchors WHERE owner_user_id=?",
)
_LATEST_REVISION_SQL = {
    "briefing_preferences": (
        "SELECT revision FROM briefing_preferences WHERE owner_user_id=? "
        "ORDER BY revision DESC LIMIT 1"
    ),
    "briefing_visit_anchors": (
        "SELECT revision FROM briefing_visit_anchors WHERE owner_user_id=? "
        "ORDER BY revision DESC LIMIT 1"
    ),
}


class BriefingStoreError(ValueError):
    """Safe validation or schema failure for briefing persistence."""


class BriefingConflictError(BriefingStoreError):
    """An idempotency key or compare-and-swap revision conflicts with saved state."""


class BriefingCapacityError(BriefingStoreError):
    """An append would exceed the owner's retained briefing row or byte limit."""


class BriefingNotFoundError(BriefingStoreError):
    """An owner-scoped briefing resource does not exist."""


class BriefingUnavailableError(BriefingStoreError):
    """The requested owner is missing or no longer active."""


@dataclass(frozen=True, slots=True)
class PriceThresholdPreference:
    """Current threshold preference, using the default when no revision is stored."""

    owner_user_id: int
    revision: int
    threshold_bps: int
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class VisitAnchor:
    """Latest explicitly recorded visit baseline for one owner."""

    owner_user_id: int
    revision: int
    baseline_at: datetime | None
    snapshot_id: str | None
    visited_at: datetime | None


@dataclass(frozen=True, slots=True)
class SnapshotPage:
    """Owner-scoped descending page of immutable snapshots."""

    items: tuple[BriefingSnapshot, ...]
    next_cursor: str | None


def _owner_id(value: object) -> int:
    if type(value) is not int or value < 1:
        raise BriefingUnavailableError("The owner is unavailable.")
    return value


def _revision(value: object, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if type(value) is not int or value < minimum or value > 2**63 - 1:
        raise BriefingStoreError("A briefing revision is invalid.")
    return value


def _sha(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise BriefingStoreError(f"{field} is invalid.")
    return value


def _canonical_json(value: object, maximum: int = MAX_SNAPSHOT_BYTES) -> str:
    try:
        text = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        )
    except (TypeError, ValueError) as error:
        raise BriefingStoreError("The briefing payload is invalid.") from error
    if len(text.encode("utf-8")) > maximum:
        raise BriefingStoreError("The briefing payload exceeds its size limit.")
    return text


def _active_owner(connection: sqlite3.Connection, owner: int) -> None:
    row = connection.execute("SELECT status FROM users WHERE id=?", (owner,)).fetchone()
    if row is None or row["status"] != "active":
        raise BriefingUnavailableError("The owner is unavailable.")


def _row_bytes(*values: object | None) -> int:
    return sum(len(str(value).encode("utf-8")) for value in values if value is not None)


def _ensure_owner_capacity(
    connection: sqlite3.Connection,
    owner: int,
    *,
    additional_rows: int,
    additional_bytes: int,
) -> None:
    if (
        type(additional_rows) is not int
        or additional_rows < 0
        or type(additional_bytes) is not int
        or additional_bytes < 0
    ):
        raise BriefingStoreError("The retained briefing capacity estimate is invalid.")
    retained_rows, retained_bytes = _owner_usage(connection, owner)
    if retained_rows + additional_rows > MAX_OWNER_RETAINED_ROWS:
        raise BriefingCapacityError("The owner briefing history reached its retained-row limit.")
    if retained_bytes + additional_bytes > MAX_OWNER_RETAINED_BYTES:
        raise BriefingCapacityError("The owner briefing history reached its retained-byte limit.")


def _owner_usage(connection: sqlite3.Connection, owner: int) -> tuple[int, int]:
    """Return retained row count and UTF-8 cell bytes, excluding SQLite page/index overhead."""

    row_count = 0
    byte_count = 0
    for statement in _OWNER_USAGE_SQL:
        row = connection.execute(statement, (owner,)).fetchone()
        row_count += int(row[0])
        byte_count += int(row[1])
    return row_count, byte_count


def _price_row_bytes(item: PriceObservation, payload_sha256: str, created_at: str) -> int:
    material = _price_material(item)
    return _row_bytes(
        item.owner_user_id,
        item.source_ref,
        payload_sha256,
        item.symbol,
        item.asset_type,
        item.provider,
        item.currency,
        material["price"],
        material["observed_at"],
        material["received_at"],
        item.state,
        item.reason,
        created_at,
    )


def _latest_revision(connection: sqlite3.Connection, table: str, owner: int) -> int:
    statement = _LATEST_REVISION_SQL.get(table)
    if statement is None:
        raise BriefingStoreError("The requested revision table is invalid.")
    row = connection.execute(statement, (owner,)).fetchone()
    return int(row[0]) if row is not None else 0


def _price_material(item: PriceObservation) -> dict[str, object]:
    return {
        "owner_user_id": item.owner_user_id,
        "source_ref": item.source_ref,
        "symbol": item.symbol,
        "asset_type": item.asset_type,
        "provider": item.provider,
        "currency": item.currency,
        "price": decimal_text(item.price) if item.price is not None else None,
        "observed_at": timestamp_text(item.observed_at) if item.observed_at else None,
        "received_at": timestamp_text(item.received_at) if item.received_at else None,
        "state": item.state,
        "reason": item.reason,
    }


def _price_row(row: sqlite3.Row) -> PriceObservation:
    try:
        price = Decimal(row["price_text"]) if row["price_text"] is not None else None
    except InvalidOperation as error:
        raise BriefingStoreError("A stored price observation is invalid.") from error
    try:
        return PriceObservation(
            owner_user_id=int(row["owner_user_id"]),
            source_ref=str(row["source_ref"]),
            symbol=str(row["symbol"]),
            asset_type=str(row["asset_type"]),
            provider=str(row["provider"]) if row["provider"] is not None else None,
            currency=str(row["currency"]) if row["currency"] is not None else None,
            price=price,
            observed_at=parse_timestamp(row["observed_at"], "stored observed_at")
            if row["observed_at"] is not None
            else None,
            received_at=parse_timestamp(row["received_at"], "stored received_at")
            if row["received_at"] is not None
            else None,
            state=str(row["state"]),  # type: ignore[arg-type]
            reason=str(row["reason"]) if row["reason"] is not None else None,
        )
    except BriefingDomainError as error:
        raise BriefingStoreError("A stored price observation is invalid.") from error


def _stored_prices(
    connection: sqlite3.Connection,
    owner: int,
    through_text: str,
    through: datetime,
    *,
    limit: int,
) -> tuple[PriceObservation, ...]:
    rows = connection.execute(
        "SELECT * FROM briefing_price_observations WHERE owner_user_id=? "
        "AND (observed_at IS NULL OR observed_at<=?) "
        "ORDER BY observed_at DESC,received_at DESC,source_ref DESC LIMIT ?",
        (owner, through_text, limit),
    ).fetchall()
    try:
        values = tuple(_price_row(row) for row in reversed(rows))
        return validate_price_observations(values, owner, through)
    except BriefingDomainError as error:
        raise BriefingStoreError("Stored price history is invalid.") from error


def _snapshot_from_row(row: sqlite3.Row) -> BriefingSnapshot:
    try:
        payload = json.loads(row["payload_json"])
    except (json.JSONDecodeError, TypeError) as error:
        raise BriefingStoreError("A stored briefing snapshot is invalid.") from error
    root_keys = {
        "version",
        "window",
        "baseline_at",
        "observed_as_of",
        "threshold_bps",
        "price_changes",
        "outcome_changes",
        "triggered_alerts",
        "due_thesis_reviews",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != root_keys
        or type(payload.get("version")) is not int
        or payload.get("version") != 1
    ):
        raise BriefingStoreError("A stored briefing snapshot is invalid.")
    try:
        window = BriefingWindow(payload["window"])
        baseline = (
            parse_timestamp(payload["baseline_at"], "baseline_at")
            if payload["baseline_at"] is not None
            else None
        )
        observed_as_of = parse_timestamp(payload["observed_as_of"], "observed_as_of")
        if type(payload["threshold_bps"]) is not int:
            raise BriefingStoreError("A stored briefing threshold is invalid.")
        threshold = validate_threshold_bps(payload["threshold_bps"])
        if (
            payload["baseline_at"] != row["baseline_at"]
            or payload["observed_as_of"] != row["observed_as_of"]
        ):
            raise BriefingStoreError("Stored snapshot timestamps do not match their index.")
        if payload["window"] != row["window"] or threshold != row["threshold_bps"]:
            raise BriefingStoreError("Stored snapshot metadata does not match its index.")
        price_rows = payload["price_changes"]
        if not isinstance(price_rows, list) or len(price_rows) > MAX_PRICE_ROWS:
            raise BriefingStoreError("Stored price summaries exceed their limit.")
        price_changes: list[PriceMovementSummary] = []
        price_keys = {
            "symbol",
            "asset_type",
            "state",
            "baseline_at",
            "observed_at",
            "baseline_received_at",
            "received_at",
            "currency",
            "provider",
            "change_bps",
            "reason",
        }
        allowed_price_states = {
            "unavailable",
            "first_observation",
            "insufficient_history",
            "below_threshold",
            "threshold_crossed",
        }
        for item in price_rows:
            if not isinstance(item, dict) or set(item) != price_keys:
                raise BriefingStoreError("A stored price summary is invalid.")
            if item["state"] not in allowed_price_states:
                raise BriefingStoreError("A stored price summary state is invalid.")
            delta = Decimal(item["change_bps"]) if item["change_bps"] is not None else None
            if delta is not None and not delta.is_finite():
                raise BriefingStoreError("A stored price summary is invalid.")
            price_changes.append(
                PriceMovementSummary(
                    symbol=item["symbol"],
                    asset_type=item["asset_type"],
                    state=item["state"],
                    baseline_at=parse_timestamp(item["baseline_at"], "price baseline")
                    if item["baseline_at"] is not None
                    else None,
                    observed_at=parse_timestamp(item["observed_at"], "price observed_at")
                    if item["observed_at"] is not None
                    else None,
                    baseline_received_at=parse_timestamp(
                        item["baseline_received_at"], "price baseline received_at"
                    )
                    if item["baseline_received_at"] is not None
                    else None,
                    received_at=parse_timestamp(item["received_at"], "price received_at")
                    if item["received_at"] is not None
                    else None,
                    currency=item["currency"],
                    provider=item["provider"],
                    change_bps=delta,
                    reason=item["reason"],
                )
            )
        outcome_rows = payload["outcome_changes"]
        if not isinstance(outcome_rows, list) or len(outcome_rows) > 100:
            raise BriefingStoreError("Stored outcome summaries exceed their limit.")
        outcome_keys = {
            "resource_ref",
            "source_ref",
            "state",
            "revision",
            "recorded_at",
            "observed_at",
            "correction_of",
        }
        outcome_changes: list[ForecastOutcomeChange] = []
        for item in outcome_rows:
            if not isinstance(item, dict) or set(item) != outcome_keys:
                raise BriefingStoreError("A stored outcome summary is invalid.")
            outcome_changes.append(
                ForecastOutcomeChange(
                    owner_user_id=int(row["owner_user_id"]),
                    resource_ref=item["resource_ref"],
                    source_ref=item["source_ref"],
                    state=item["state"],
                    revision=item["revision"],
                    recorded_at=parse_timestamp(item["recorded_at"], "outcome recorded_at"),
                    observed_at=parse_timestamp(item["observed_at"], "outcome observed_at")
                    if item["observed_at"] is not None
                    else None,
                    correction_of=item["correction_of"],
                )
            )
        alert_rows = payload["triggered_alerts"]
        if not isinstance(alert_rows, list) or len(alert_rows) > 100:
            raise BriefingStoreError("Stored alert summaries exceed their limit.")
        alert_keys = {"resource_ref", "symbol", "asset_type", "triggered_at"}
        alerts = tuple(
            _alert_from_payload(item, int(row["owner_user_id"]), alert_keys) for item in alert_rows
        )
        review_rows = payload["due_thesis_reviews"]
        if not isinstance(review_rows, list) or len(review_rows) > 100:
            raise BriefingStoreError("Stored thesis summaries exceed their limit.")
        review_keys = {"thesis_ref", "revision", "due_at"}
        reviews = tuple(
            DueThesisReviewSummary(
                owner_user_id=int(row["owner_user_id"]),
                thesis_ref=item["thesis_ref"],
                revision=item["revision"],
                due_at=parse_timestamp(item["due_at"], "thesis due_at"),
            )
            for item in _payload_rows(review_rows, review_keys, "thesis")
        )
        result = BriefingSnapshot(
            snapshot_id=str(row["id"]),
            owner_user_id=int(row["owner_user_id"]),
            idempotency_key=str(row["idempotency_key"]),
            request_sha256=str(row["request_sha256"]),
            window=window,
            baseline_at=baseline,
            observed_as_of=observed_as_of,
            baseline_anchor_revision=int(row["baseline_anchor_revision"]),
            preference_revision=int(row["preference_revision"]),
            threshold_bps=threshold,
            generated_at=parse_timestamp(row["created_at"], "created_at"),
            price_changes=tuple(price_changes),
            outcome_changes=tuple(outcome_changes),
            triggered_alerts=alerts,
            due_thesis_reviews=reviews,
        )
        canonical_uuid(result.snapshot_id, "snapshot_id")
        canonical_uuid(result.idempotency_key, "idempotency_key")
        _sha(result.request_sha256, "request_sha256")
        if request_fingerprint(result.window, result.observed_as_of) != result.request_sha256:
            raise BriefingStoreError("The stored request fingerprint is invalid.")
        if (
            baseline_for_window(result.window, result.observed_as_of, result.baseline_at)
            != result.baseline_at
        ):
            raise BriefingStoreError("The stored briefing baseline is invalid.")
        if result.generated_at < result.observed_as_of:
            raise BriefingStoreError("The stored briefing generation time is invalid.")
        if (
            validate_outcome_changes(
                result.outcome_changes,
                owner_user_id=result.owner_user_id,
                baseline_at=result.baseline_at,
                observed_as_of=result.observed_as_of,
            )
            != result.outcome_changes
        ):
            raise BriefingStoreError("Stored outcome items do not match their frozen window.")
        if (
            validate_triggered_alerts(
                result.triggered_alerts,
                owner_user_id=result.owner_user_id,
                baseline_at=result.baseline_at,
                observed_as_of=result.observed_as_of,
            )
            != result.triggered_alerts
        ):
            raise BriefingStoreError("Stored alerts do not match their frozen window.")
        if (
            validate_due_thesis_reviews(
                result.due_thesis_reviews,
                owner_user_id=result.owner_user_id,
                observed_as_of=result.observed_as_of,
            )
            != result.due_thesis_reviews
        ):
            raise BriefingStoreError("Stored thesis reviews are invalid.")
        return result
    except (BriefingDomainError, InvalidOperation, KeyError, TypeError, ValueError) as error:
        if isinstance(error, BriefingStoreError):
            raise
        raise BriefingStoreError("A stored briefing snapshot is invalid.") from error


def _payload_rows(value: object, keys: set[str], field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 100:
        raise BriefingStoreError(f"Stored {field} summaries exceed their limit.")
    if any(not isinstance(item, dict) or set(item) != keys for item in value):
        raise BriefingStoreError(f"A stored {field} summary is invalid.")
    return value


def _alert_from_payload(value: object, owner_user_id: int, keys: set[str]) -> TriggeredAlertSummary:
    rows = _payload_rows([value], keys, "alert")
    item = rows[0]
    return TriggeredAlertSummary(
        owner_user_id=owner_user_id,
        resource_ref=item["resource_ref"],
        symbol=item["symbol"],
        asset_type=item["asset_type"],
        triggered_at=parse_timestamp(item["triggered_at"], "alert triggered_at"),
    )


class BriefingStore:
    """Persist immutable owner-scoped snapshots and explicit visit/preference revisions."""

    def __init__(self, repository: Repository) -> None:
        if not isinstance(repository, Repository):
            raise TypeError("repository must be a Repository")
        self.repository = repository

    def get_preference(self, owner_user_id: int) -> PriceThresholdPreference:
        """Return the current preference or the documented 300-basis-point default."""

        owner = _owner_id(owner_user_id)
        with self.repository.connect() as connection:
            _active_owner(connection, owner)
            row = connection.execute(
                "SELECT revision,threshold_bps,updated_at FROM briefing_preferences "
                "WHERE owner_user_id=? ORDER BY revision DESC LIMIT 1",
                (owner,),
            ).fetchone()
        if row is None:
            return PriceThresholdPreference(owner, 0, 300, None)
        return PriceThresholdPreference(
            owner,
            int(row["revision"]),
            int(row["threshold_bps"]),
            parse_timestamp(row["updated_at"], "preference updated_at"),
        )

    def update_preference(
        self,
        owner_user_id: int,
        threshold_bps: int,
        *,
        expected_revision: int,
        updated_at: datetime,
    ) -> PriceThresholdPreference:
        """Append a bounded preference revision after an exact compare-and-swap check."""

        owner = _owner_id(owner_user_id)
        threshold = validate_threshold_bps(threshold_bps)
        expected = _revision(expected_revision, allow_zero=True)
        updated_text = timestamp_text(utc_instant(updated_at, "updated_at"))
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                _active_owner(connection, owner)
                current = _latest_revision(connection, "briefing_preferences", owner)
                if current != expected:
                    raise BriefingConflictError("The briefing preference changed concurrently.")
                revision = current + 1
                _ensure_owner_capacity(
                    connection,
                    owner,
                    additional_rows=1,
                    additional_bytes=_row_bytes(owner, revision, threshold, updated_text),
                )
                connection.execute(
                    "INSERT INTO briefing_preferences(owner_user_id,revision,threshold_bps,"
                    "updated_at) "
                    "VALUES(?,?,?,?)",
                    (owner, revision, threshold, updated_text),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return PriceThresholdPreference(
            owner, revision, threshold, utc_instant(updated_at, "updated_at")
        )

    def get_visit_anchor(self, owner_user_id: int) -> VisitAnchor:
        """Return the latest acknowledged snapshot baseline without mutating it."""

        owner = _owner_id(owner_user_id)
        with self.repository.connect() as connection:
            _active_owner(connection, owner)
            row = connection.execute(
                "SELECT revision,snapshot_id,baseline_at,visited_at FROM briefing_visit_anchors "
                "WHERE owner_user_id=? ORDER BY revision DESC LIMIT 1",
                (owner,),
            ).fetchone()
        if row is None:
            return VisitAnchor(owner, 0, None, None, None)
        return VisitAnchor(
            owner,
            int(row["revision"]),
            parse_timestamp(row["baseline_at"], "visit baseline"),
            str(row["snapshot_id"]),
            parse_timestamp(row["visited_at"], "visited_at"),
        )

    def list_price_observations(
        self, owner_user_id: int, *, through: datetime, limit: int = MAX_PRICE_ROWS
    ) -> tuple[PriceObservation, ...]:
        """Return a bounded owner-only history ordered by provider observation time."""

        owner = _owner_id(owner_user_id)
        if type(limit) is not int or not 1 <= limit <= MAX_PRICE_ROWS:
            raise BriefingStoreError("The price history limit is invalid.")
        normalized_through = utc_instant(through, "through")
        through_text = timestamp_text(normalized_through)
        with self.repository.connect() as connection:
            _active_owner(connection, owner)
            return _stored_prices(connection, owner, through_text, normalized_through, limit=limit)

    def get_snapshot_by_idempotency(
        self, owner_user_id: int, idempotency_key: str, request_sha256: str
    ) -> BriefingSnapshot | None:
        """Return an existing snapshot only when its canonical request fingerprint matches."""

        owner = _owner_id(owner_user_id)
        key = canonical_uuid(idempotency_key, "idempotency_key")
        request_hash = _sha(request_sha256, "request_sha256")
        with self.repository.connect() as connection:
            _active_owner(connection, owner)
            row = connection.execute(
                "SELECT * FROM briefing_snapshots WHERE owner_user_id=? AND idempotency_key=?",
                (owner, key),
            ).fetchone()
        if row is None:
            return None
        if row["request_sha256"] != request_hash:
            raise BriefingConflictError(
                "The briefing idempotency key was reused for another request."
            )
        return _snapshot_from_row(row)

    def create_snapshot(
        self,
        snapshot: BriefingSnapshot,
        *,
        observations: tuple[PriceObservation, ...],
        expected_preference_revision: int,
        expected_anchor_revision: int,
        commit_guard: Callable[[], object] | None = None,
    ) -> BriefingSnapshot:
        """Atomically append observations and create one immutable snapshot with CAS guards.

        The optional authorization callback runs under the write transaction immediately before
        the first insert, after persisted-owner, idempotency, revision, and capacity checks.
        """

        if not isinstance(snapshot, BriefingSnapshot):
            raise BriefingStoreError("The briefing snapshot has an invalid type.")
        owner = _owner_id(snapshot.owner_user_id)
        if commit_guard is not None and not callable(commit_guard):
            raise BriefingStoreError("The snapshot commit guard is invalid.")
        key = canonical_uuid(snapshot.idempotency_key, "idempotency_key")
        snapshot_id = canonical_uuid(snapshot.snapshot_id, "snapshot_id")
        request_hash = _sha(snapshot.request_sha256, "request_sha256")
        expected_pref = _revision(expected_preference_revision, allow_zero=True)
        expected_anchor = _revision(expected_anchor_revision, allow_zero=True)
        if (
            snapshot.preference_revision != expected_pref
            or snapshot.baseline_anchor_revision != expected_anchor
        ):
            raise BriefingStoreError(
                "Snapshot revisions do not match their compare-and-swap values."
            )
        if not isinstance(snapshot.window, BriefingWindow):
            raise BriefingStoreError("The snapshot window is invalid.")
        try:
            threshold = validate_threshold_bps(snapshot.threshold_bps)
            computed_baseline = baseline_for_window(
                snapshot.window, snapshot.observed_as_of, snapshot.baseline_at
            )
            observed_text = timestamp_text(snapshot.observed_as_of)
            baseline_text = (
                timestamp_text(snapshot.baseline_at) if snapshot.baseline_at is not None else None
            )
            created_text = timestamp_text(snapshot.generated_at)
            if computed_baseline != snapshot.baseline_at:
                raise BriefingStoreError("The snapshot baseline does not match its window.")
            if snapshot.generated_at < snapshot.observed_as_of:
                raise BriefingStoreError("The snapshot was generated before its as-of time.")
            outcomes = validate_outcome_changes(
                snapshot.outcome_changes,
                owner_user_id=owner,
                baseline_at=snapshot.baseline_at,
                observed_as_of=snapshot.observed_as_of,
            )
            alerts = validate_triggered_alerts(
                snapshot.triggered_alerts,
                owner_user_id=owner,
                baseline_at=snapshot.baseline_at,
                observed_as_of=snapshot.observed_as_of,
            )
            reviews = validate_due_thesis_reviews(
                snapshot.due_thesis_reviews,
                owner_user_id=owner,
                observed_as_of=snapshot.observed_as_of,
            )
            if (
                outcomes != snapshot.outcome_changes
                or alerts != snapshot.triggered_alerts
                or reviews != snapshot.due_thesis_reviews
            ):
                raise BriefingStoreError("Snapshot items do not match their frozen window.")
        except BriefingDomainError as error:
            raise BriefingStoreError("The snapshot contents are invalid.") from error
        if request_fingerprint(snapshot.window, snapshot.observed_as_of) != request_hash:
            raise BriefingStoreError("The request fingerprint does not match the snapshot.")
        point_values = validate_price_observations(observations, owner, snapshot.observed_as_of)
        point_material: dict[str, tuple[PriceObservation, str, str]] = {}
        for point in point_values:
            material = _canonical_json(_price_material(point), 4096)
            digest = hashlib.sha256(material.encode("ascii")).hexdigest()
            prior = point_material.get(point.source_ref)
            if prior is not None and prior[2] != digest:
                raise BriefingConflictError("A price source reference has conflicting content.")
            point_material[point.source_ref] = (point, material, digest)
        payload_json = _canonical_json(snapshot.payload())

        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                _active_owner(connection, owner)
                existing = connection.execute(
                    "SELECT * FROM briefing_snapshots WHERE owner_user_id=? AND idempotency_key=?",
                    (owner, key),
                ).fetchone()
                if existing is not None:
                    if existing["request_sha256"] != request_hash:
                        raise BriefingConflictError(
                            "The briefing idempotency key was reused for another request."
                        )
                    connection.commit()
                    return _snapshot_from_row(existing)
                current_pref = _latest_revision(connection, "briefing_preferences", owner)
                current_anchor = _latest_revision(connection, "briefing_visit_anchors", owner)
                if current_pref != expected_pref or current_anchor != expected_anchor:
                    raise BriefingConflictError("Briefing state changed during snapshot creation.")
                preference = connection.execute(
                    "SELECT threshold_bps FROM briefing_preferences WHERE owner_user_id=? "
                    "ORDER BY revision DESC LIMIT 1",
                    (owner,),
                ).fetchone()
                saved_threshold = int(preference["threshold_bps"]) if preference else 300
                if saved_threshold != threshold:
                    raise BriefingConflictError("The briefing threshold changed during creation.")
                if snapshot.window is BriefingWindow.SINCE_LAST_VISIT:
                    anchor = connection.execute(
                        "SELECT baseline_at FROM briefing_visit_anchors WHERE owner_user_id=? "
                        "ORDER BY revision DESC LIMIT 1",
                        (owner,),
                    ).fetchone()
                    stored_baseline = str(anchor["baseline_at"]) if anchor is not None else None
                    if stored_baseline != baseline_text:
                        raise BriefingConflictError("The visit baseline changed during creation.")
                new_points: list[tuple[PriceObservation, str]] = []
                for point, _material, digest in point_material.values():
                    old = connection.execute(
                        "SELECT payload_sha256 FROM briefing_price_observations "
                        "WHERE owner_user_id=? AND source_ref=?",
                        (owner, point.source_ref),
                    ).fetchone()
                    if old is not None:
                        if old["payload_sha256"] != digest:
                            raise BriefingConflictError(
                                "A price source reference has conflicting content."
                            )
                        continue
                    new_points.append((point, digest))
                extra_price_bytes = sum(
                    _price_row_bytes(point, digest, created_text) for point, digest in new_points
                )
                extra_snapshot_bytes = _row_bytes(
                    snapshot_id,
                    owner,
                    key,
                    request_hash,
                    snapshot.window.value,
                    baseline_text,
                    observed_text,
                    expected_anchor,
                    expected_pref,
                    threshold,
                    payload_json,
                    created_text,
                )
                _ensure_owner_capacity(
                    connection,
                    owner,
                    additional_rows=len(new_points) + 1,
                    additional_bytes=extra_price_bytes + extra_snapshot_bytes,
                )
                if commit_guard is not None:
                    try:
                        authorized = commit_guard()
                    except Exception as error:
                        raise BriefingUnavailableError("The owner is unavailable.") from error
                    if authorized is not True:
                        raise BriefingUnavailableError("The owner is unavailable.")
                for point, digest in new_points:
                    record = _price_material(point)
                    connection.execute(
                        "INSERT INTO briefing_price_observations(owner_user_id,source_ref,"
                        "payload_sha256,symbol,asset_type,provider,currency,price_text,observed_at,"
                        "received_at,state,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            owner,
                            point.source_ref,
                            digest,
                            point.symbol,
                            point.asset_type,
                            point.provider,
                            point.currency,
                            record["price"],
                            record["observed_at"],
                            record["received_at"],
                            point.state,
                            point.reason,
                            created_text,
                        ),
                    )
                persisted_prices = _stored_prices(
                    connection,
                    owner,
                    observed_text,
                    snapshot.observed_as_of,
                    limit=MAX_PRICE_ROWS,
                )
                expected_changes = summarize_price_movements(
                    persisted_prices,
                    owner_user_id=owner,
                    baseline_at=snapshot.baseline_at,
                    observed_as_of=snapshot.observed_as_of,
                    threshold_bps=threshold,
                )
                if expected_changes != snapshot.price_changes:
                    raise BriefingConflictError(
                        "Price history changed while creating the snapshot."
                    )
                connection.execute(
                    "INSERT INTO briefing_snapshots(id,owner_user_id,idempotency_key,"
                    "request_sha256,"
                    "window,baseline_at,observed_as_of,baseline_anchor_revision,preference_revision,"
                    "threshold_bps,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        snapshot_id,
                        owner,
                        key,
                        request_hash,
                        snapshot.window.value,
                        baseline_text,
                        observed_text,
                        expected_anchor,
                        expected_pref,
                        snapshot.threshold_bps,
                        payload_json,
                        created_text,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return snapshot

    def get_snapshot(self, owner_user_id: int, snapshot_id: str) -> BriefingSnapshot:
        """Read an immutable snapshot only within its owning account."""

        owner = _owner_id(owner_user_id)
        item_id = canonical_uuid(snapshot_id, "snapshot_id")
        with self.repository.connect() as connection:
            _active_owner(connection, owner)
            row = connection.execute(
                "SELECT * FROM briefing_snapshots WHERE id=? AND owner_user_id=?",
                (item_id, owner),
            ).fetchone()
        if row is None:
            raise BriefingNotFoundError("The briefing snapshot is unavailable.")
        return _snapshot_from_row(row)

    def list_snapshots(
        self, owner_user_id: int, *, limit: int = 20, cursor: str | None = None
    ) -> SnapshotPage:
        """Read a bounded descending owner-only snapshot page using an opaque UUID cursor."""

        owner = _owner_id(owner_user_id)
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
            raise BriefingStoreError("The snapshot page size is invalid.")
        cursor_id = canonical_uuid(cursor, "cursor") if cursor is not None else None
        with self.repository.connect() as connection:
            _active_owner(connection, owner)
            if cursor_id is None:
                rows = connection.execute(
                    "SELECT * FROM briefing_snapshots WHERE owner_user_id=? "
                    "ORDER BY created_at DESC,id DESC LIMIT ?",
                    (owner, limit + 1),
                ).fetchall()
            else:
                anchor = connection.execute(
                    "SELECT created_at,id FROM briefing_snapshots WHERE owner_user_id=? AND id=?",
                    (owner, cursor_id),
                ).fetchone()
                if anchor is None:
                    raise BriefingNotFoundError("The briefing page cursor is unavailable.")
                rows = connection.execute(
                    "SELECT * FROM briefing_snapshots WHERE owner_user_id=? "
                    "AND (created_at,id)<(?,?) ORDER BY created_at DESC,id DESC LIMIT ?",
                    (owner, anchor["created_at"], anchor["id"], limit + 1),
                ).fetchall()
        has_more = len(rows) > limit
        selected = rows[:limit]
        items = tuple(_snapshot_from_row(row) for row in selected)
        return SnapshotPage(items, items[-1].snapshot_id if has_more and items else None)

    def record_visit(
        self,
        owner_user_id: int,
        snapshot_id: str,
        *,
        expected_revision: int,
        visited_at: datetime,
    ) -> VisitAnchor:
        """Append an explicit visit anchor without modifying the referenced snapshot."""

        owner = _owner_id(owner_user_id)
        item_id = canonical_uuid(snapshot_id, "snapshot_id")
        expected = _revision(expected_revision, allow_zero=True)
        visited = utc_instant(visited_at, "visited_at")
        visited_text = timestamp_text(visited)
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                _active_owner(connection, owner)
                snapshot = connection.execute(
                    "SELECT observed_as_of FROM briefing_snapshots WHERE id=? AND owner_user_id=?",
                    (item_id, owner),
                ).fetchone()
                if snapshot is None:
                    raise BriefingNotFoundError("The briefing snapshot is unavailable.")
                current = _latest_revision(connection, "briefing_visit_anchors", owner)
                if current != expected:
                    raise BriefingConflictError("The visit anchor changed concurrently.")
                baseline_text = str(snapshot["observed_as_of"])
                baseline = parse_timestamp(baseline_text, "snapshot observed_as_of")
                if visited < baseline:
                    raise BriefingStoreError("A visit cannot predate its snapshot.")
                old = connection.execute(
                    "SELECT baseline_at FROM briefing_visit_anchors WHERE owner_user_id=? "
                    "ORDER BY revision DESC LIMIT 1",
                    (owner,),
                ).fetchone()
                if old is not None and baseline <= parse_timestamp(
                    old["baseline_at"], "visit baseline"
                ):
                    raise BriefingConflictError(
                        "An older snapshot cannot move the visit baseline back."
                    )
                revision = current + 1
                _ensure_owner_capacity(
                    connection,
                    owner,
                    additional_rows=1,
                    additional_bytes=_row_bytes(
                        owner, revision, item_id, baseline_text, visited_text
                    ),
                )
                connection.execute(
                    "INSERT INTO briefing_visit_anchors(owner_user_id,revision,snapshot_id,"
                    "baseline_at,visited_at) VALUES(?,?,?,?,?)",
                    (owner, revision, item_id, baseline_text, visited_text),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return VisitAnchor(owner, revision, baseline, item_id, visited)
