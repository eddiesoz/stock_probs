"""Persist owner-scoped daily forecast collection jobs and immutable observations."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from stock_probs.domain import evaluate_outcome
from stock_probs.repository import Repository

DAILY_HORIZONS = frozenset({"close_to_close", "daily_1", "weekly_5", "monthly_21", "quarterly_63"})
MAX_BATCH = 50
MAX_LEASE_SECONDS = 300
MAX_CHECKPOINT_BYTES = 4096
MAX_EVIDENCE_BYTES = 262_144
RECHECK_INTERVAL = timedelta(days=1)
PARKED_DUE_AT = "9999-12-31T23:59:59.999999Z"
_WORKER_RE = re.compile(r"[A-Za-z0-9_.:-]{1,80}\Z")
_FAILURE_RE = re.compile(r"[a-z0-9_:-]{1,80}\Z")


class OutcomeCollectionStoreError(ValueError):
    """Safe validation or storage failure for daily outcome collection."""


class OutcomeCollectionLeaseConflict(OutcomeCollectionStoreError):
    """A collection lease expired, changed, or no longer belongs to this worker."""


def _raise_if_cancelled(cancelled: Callable[[], bool] | None) -> None:
    """Prevent a stopping worker from committing an outcome or lease transition."""
    if cancelled is None:
        return
    try:
        is_cancelled = cancelled() is not False
    except Exception:
        is_cancelled = True
    if is_cancelled:
        raise OutcomeCollectionLeaseConflict("The collection worker is stopping.")


@dataclass(frozen=True)
class OutcomeJobClaim:
    """One persisted outcome job lease with enough identity to reject stale work."""

    job_id: str
    owner_user_id: int
    result_id: int
    lease_token: str
    lease_until: str
    request_id: str
    requested_at: str
    job_revision: int
    worker_id: str
    checkpoint: Mapping[str, Any]


@dataclass(frozen=True)
class OutcomeForecast:
    """An active owner's immutable saved forecast selected by a current lease."""

    owner_user_id: int
    result_id: int
    symbol: str
    asset_type: str
    forecast: Mapping[str, Any]
    latest_outcome_is_manual: bool


def _utc_microseconds(value: object) -> int | None:
    """Convert bounded aware ISO values to exact UTC integers for queue filtering."""
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    delta = parsed.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def _timestamp(value: datetime) -> str:
    """Serialize one aware instant in the same canonical form as monitoring jobs."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise OutcomeCollectionStoreError("Collection times must identify an instant.")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime:
    """Parse an ISO timestamp while rejecting naive or oversized values."""
    if not isinstance(value, str) or len(value) > 64:
        raise OutcomeCollectionStoreError("A saved forecast timestamp is invalid.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise OutcomeCollectionStoreError("A saved forecast timestamp is invalid.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OutcomeCollectionStoreError("A saved forecast timestamp is ambiguous.")
    return parsed.astimezone(UTC)


def _canonical_json(value: object, maximum: int) -> str:
    """Encode bounded JSON without non-finite numbers or ambiguous keys."""
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        )
    except (TypeError, ValueError) as error:
        raise OutcomeCollectionStoreError("The collection payload is invalid.") from error
    if len(encoded.encode("utf-8")) > maximum:
        raise OutcomeCollectionStoreError("The collection payload exceeds its size limit.")
    return encoded


def _collection_fingerprint(
    *,
    outcome_state: str,
    close: float | None,
    observed_at: str,
    evidence_state: str,
    payload_json: str,
) -> str:
    """Give an immutable collection the stable identity used for correction checks."""
    material = _canonical_json(
        {
            "outcome_state": "observed"
            if outcome_state in {"observed", "corrected"}
            else "unavailable",
            "close": close,
            "observed_at": observed_at,
            "evidence_state": evidence_state,
            "payload_json": payload_json,
        },
        MAX_EVIDENCE_BYTES + 512,
    )
    return hashlib.sha256(material.encode("ascii")).hexdigest()


class OutcomeCollectionStore:
    """Schedule, lease, and atomically record eligible daily forecast observations."""

    def __init__(self, repository: Repository, *, admin_only: bool = False):
        if not isinstance(repository, Repository):
            raise TypeError("repository must be a Repository")
        if type(admin_only) is not bool:
            raise TypeError("admin_only must be a boolean")
        self.repository = repository
        self.admin_only = admin_only

    def enqueue_due(self, now: datetime, *, limit: int = MAX_BATCH) -> int:
        """Queue a bounded, fair batch of matured submitted forecasts without reading providers."""
        if type(limit) is not int or not 1 <= limit <= MAX_BATCH:
            raise OutcomeCollectionStoreError("The collection scan limit is invalid.")
        now_text = _timestamp(now)
        current_us = _utc_microseconds(now_text)
        if current_us is None:
            raise OutcomeCollectionStoreError("The collection clock is invalid.")
        with self.repository.connect() as connection:
            connection.create_function(
                "forecast_target_us", 1, _utc_microseconds, deterministic=True
            )
            connection.execute("BEGIN IMMEDIATE")
            try:
                control = connection.execute(
                    "SELECT enabled FROM monitoring_control WHERE id=1"
                ).fetchone()
                if control is None or control["enabled"] != 1:
                    connection.commit()
                    return 0
                rows = connection.execute(
                    """WITH eligible AS (
                        SELECT DISTINCT result.id AS result_id, result_owner.owner_user_id,
                            forecast_target_us(json_extract(result.result_json,
                                '$.target_timestamp')) AS target_us,
                            json_extract(result.result_json, '$.target_timestamp') AS target_text,
                            COALESCE(queue.service_sequence, 0) AS owner_sequence
                        FROM forecast_results AS result
                        JOIN forecast_inputs AS input ON input.id=result.input_id
                        JOIN forecast_runs AS run ON run.id=input.run_id
                        JOIN forecast_result_owners AS result_owner
                            ON result_owner.result_id=result.id
                        JOIN users AS account ON account.id=result_owner.owner_user_id
                            AND account.status='active'
                            AND (?=0 OR account.role='admin')
                        JOIN search_events AS event ON event.run_id=run.id
                            AND event.analysis_kind='submitted_forecast'
                            AND event.status IN ('successful','repeated')
                        JOIN search_event_owners AS event_owner ON event_owner.event_id=event.id
                            AND event_owner.owner_user_id=result_owner.owner_user_id
                        LEFT JOIN monitoring_owner_queue AS queue
                            ON queue.owner_user_id=result_owner.owner_user_id
                        WHERE result.horizon IN
                            ('close_to_close','daily_1','weekly_5','monthly_21','quarterly_63')
                          AND COALESCE(json_extract(result.result_json, '$.availability'),
                              'available')='available'
                          AND forecast_target_us(json_extract(result.result_json,
                              '$.target_timestamp')) IS NOT NULL
                          AND forecast_target_us(json_extract(result.result_json,
                              '$.target_timestamp'))<=?
                          AND forecast_target_us(event.completed_at)<=
                              forecast_target_us(json_extract(result.result_json,
                                  '$.target_timestamp'))
                          AND NOT EXISTS (
                              SELECT 1 FROM outcomes AS outcome
                              JOIN outcome_owners AS outcome_owner
                                ON outcome_owner.outcome_id=outcome.id
                              WHERE outcome.result_id=result.id
                                AND outcome_owner.owner_user_id=result_owner.owner_user_id
                          )
                          AND NOT EXISTS (
                              SELECT 1 FROM monitoring_jobs AS job
                              WHERE job.owner_user_id=result_owner.owner_user_id
                                AND job.kind='outcome'
                                AND job.resource_id=CAST(result.id AS TEXT)
                          )
                    ), ranked AS (
                        SELECT eligible.*,
                            ROW_NUMBER() OVER (PARTITION BY owner_user_id
                                ORDER BY target_us,result_id) AS owner_rank
                        FROM eligible
                    )
                    SELECT result_id,owner_user_id,target_text FROM ranked
                    WHERE owner_rank<=?
                    ORDER BY owner_rank,owner_sequence,owner_user_id,target_us,result_id
                    LIMIT ?""",
                    (int(self.admin_only), current_us, limit, limit),
                ).fetchall()
                inserted = 0
                for row in rows:
                    target = _parse_timestamp(row["target_text"])
                    job_id = str(uuid4())
                    changed = connection.execute(
                        "INSERT OR IGNORE INTO monitoring_jobs"
                        "(id,owner_user_id,kind,resource_id,due_at,checkpoint_json) "
                        "VALUES(?,?,'outcome',?,?, '{}')",
                        (
                            job_id,
                            row["owner_user_id"],
                            str(row["result_id"]),
                            _timestamp(target),
                        ),
                    ).rowcount
                    if changed:
                        connection.execute(
                            "INSERT INTO monitoring_owner_queue"
                            "(owner_user_id,service_sequence,last_served_at) VALUES(?,0,?) "
                            "ON CONFLICT(owner_user_id) DO NOTHING",
                            (row["owner_user_id"], now_text),
                        )
                        inserted += 1
                connection.commit()
                return inserted
            except BaseException:
                connection.rollback()
                raise

    def claim_due(
        self,
        worker_id: str,
        now: datetime,
        *,
        limit: int = 10,
        lease_seconds: int = MAX_LEASE_SECONDS,
    ) -> list[OutcomeJobClaim]:
        """Claim only outcome jobs through the shared persisted owner-fair lease queue."""
        if not isinstance(worker_id, str) or not _WORKER_RE.fullmatch(worker_id):
            raise OutcomeCollectionStoreError("The worker identifier is invalid.")
        if type(limit) is not int or not 1 <= limit <= MAX_BATCH:
            raise OutcomeCollectionStoreError("The collection batch limit is invalid.")
        if type(lease_seconds) is not int or not 5 <= lease_seconds <= MAX_LEASE_SECONDS:
            raise OutcomeCollectionStoreError("The collection lease duration is invalid.")
        now_text = _timestamp(now)
        lease_until = _timestamp(now + timedelta(seconds=lease_seconds))
        claims: list[OutcomeJobClaim] = []
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                control = connection.execute(
                    "SELECT enabled,queue_sequence FROM monitoring_control WHERE id=1"
                ).fetchone()
                if control is None or control["enabled"] != 1:
                    connection.commit()
                    return []
                queue_sequence = int(control["queue_sequence"])
                for _ in range(limit):
                    row = connection.execute(
                        """SELECT job.*,COALESCE(queue.service_sequence,0) AS owner_sequence
                        FROM monitoring_jobs AS job
                        JOIN users AS account ON account.id=job.owner_user_id
                            AND account.status='active'
                            AND (?=0 OR account.role='admin')
                        LEFT JOIN monitoring_owner_queue AS queue
                            ON queue.owner_user_id=job.owner_user_id
                        WHERE job.kind='outcome' AND job.due_at<=?
                          AND (job.lease_token IS NULL OR job.lease_until<=?)
                        ORDER BY owner_sequence,job.owner_user_id,job.due_at,job.id LIMIT 1""",
                        (int(self.admin_only), now_text, now_text),
                    ).fetchone()
                    if row is None:
                        break
                    Repository._ensure_owner_can_write(connection, int(row["owner_user_id"]))
                    if queue_sequence >= 2**63 - 1:
                        raise OutcomeCollectionStoreError("The fairness sequence is exhausted.")
                    request_id = str(uuid4())
                    lease_token = str(uuid4())
                    checkpoint = json.loads(row["checkpoint_json"])
                    if not isinstance(checkpoint, dict):
                        raise OutcomeCollectionStoreError("The saved checkpoint is invalid.")
                    checkpoint.pop("active_claim", None)
                    checkpoint["active_claim"] = {
                        "request_id": request_id,
                        "requested_at": now_text,
                        "worker_id": worker_id,
                    }
                    checkpoint_json = _canonical_json(checkpoint, MAX_CHECKPOINT_BYTES)
                    revision = int(row["revision"])
                    changed = connection.execute(
                        "UPDATE monitoring_jobs SET lease_token=?,lease_until=?,"
                        "active_request_id=?,active_requested_at=?,attempts=attempts+1,"
                        "revision=revision+1,last_attempt_at=?,checkpoint_json=? "
                        "WHERE id=? AND owner_user_id=? AND kind='outcome' AND revision=? "
                        "AND (lease_token IS NULL OR lease_until<=?)",
                        (
                            lease_token,
                            lease_until,
                            request_id,
                            now_text,
                            now_text,
                            checkpoint_json,
                            row["id"],
                            row["owner_user_id"],
                            revision,
                            now_text,
                        ),
                    ).rowcount
                    if changed != 1:
                        raise OutcomeCollectionLeaseConflict("The collection job changed.")
                    queue_sequence += 1
                    connection.execute(
                        "UPDATE monitoring_control SET queue_sequence=? WHERE id=1",
                        (queue_sequence,),
                    )
                    queue_changed = connection.execute(
                        "UPDATE monitoring_owner_queue SET service_sequence=?,last_served_at=? "
                        "WHERE owner_user_id=?",
                        (queue_sequence, now_text, row["owner_user_id"]),
                    ).rowcount
                    if queue_changed != 1:
                        raise OutcomeCollectionStoreError("The owner fairness row is missing.")
                    try:
                        result_id = int(row["resource_id"])
                    except (TypeError, ValueError) as error:
                        raise OutcomeCollectionStoreError(
                            "The outcome job identity is invalid."
                        ) from error
                    if str(result_id) != row["resource_id"] or result_id <= 0:
                        raise OutcomeCollectionStoreError("The outcome job identity is invalid.")
                    claims.append(
                        OutcomeJobClaim(
                            job_id=row["id"],
                            owner_user_id=int(row["owner_user_id"]),
                            result_id=result_id,
                            lease_token=lease_token,
                            lease_until=lease_until,
                            request_id=request_id,
                            requested_at=now_text,
                            job_revision=revision + 1,
                            worker_id=worker_id,
                            checkpoint=checkpoint,
                        )
                    )
                connection.commit()
                return claims
            except BaseException:
                connection.rollback()
                raise

    def load_forecast(self, claim: OutcomeJobClaim, now: datetime) -> OutcomeForecast | None:
        """Read the exact owned submitted forecast only while its lease and owner remain live."""
        now_text = _timestamp(now)
        with self.repository.connect() as connection:
            if not self._claim_is_current(connection, claim, now_text):
                return None
            row = connection.execute(
                """SELECT result.result_json,result.horizon,run.symbol,run.asset_type
                FROM forecast_results AS result
                JOIN forecast_inputs AS input ON input.id=result.input_id
                JOIN forecast_runs AS run ON run.id=input.run_id
                JOIN forecast_result_owners AS result_owner
                    ON result_owner.result_id=result.id
                JOIN search_events AS event ON event.run_id=run.id
                    AND event.analysis_kind='submitted_forecast'
                    AND event.status IN ('successful','repeated')
                JOIN search_event_owners AS event_owner ON event_owner.event_id=event.id
                    AND event_owner.owner_user_id=result_owner.owner_user_id
                WHERE result.id=? AND result_owner.owner_user_id=?
                  AND result.horizon IN
                    ('close_to_close','daily_1','weekly_5','monthly_21','quarterly_63')
                LIMIT 1""",
                (claim.result_id, claim.owner_user_id),
            ).fetchone()
            if row is None:
                return None
            try:
                forecast = json.loads(row["result_json"])
            except (TypeError, json.JSONDecodeError):
                return None
            if not isinstance(forecast, dict):
                return None
            horizon: object = forecast.get("horizon")
            if not isinstance(horizon, str) or not horizon or horizon not in DAILY_HORIZONS:
                return None
            latest = connection.execute(
                """SELECT outcome.id,evidence.state AS evidence_state,evidence.payload_json
                FROM outcomes AS outcome
                JOIN outcome_owners AS outcome_owner ON outcome_owner.outcome_id=outcome.id
                LEFT JOIN collected_outcome_evidence AS evidence
                  ON evidence.outcome_id=outcome.id AND evidence.owner_user_id=?
                WHERE outcome.result_id=? AND outcome_owner.owner_user_id=?
                ORDER BY outcome.id DESC LIMIT 1""",
                (claim.owner_user_id, claim.result_id, claim.owner_user_id),
            ).fetchone()
            manual = False
            if latest is not None:
                payload_text = latest["payload_json"]
                if not isinstance(payload_text, str):
                    manual = True
                else:
                    try:
                        payload = json.loads(payload_text)
                    except (json.JSONDecodeError, RecursionError):
                        manual = True
                    else:
                        checkpointed_collection = claim.checkpoint.get("last_outcome_id") == int(
                            latest["id"]
                        ) and latest["evidence_state"] in {"unavailable", "incomparable"}
                        manual = not (
                            checkpointed_collection
                            or (
                                isinstance(payload, dict)
                                and payload.get("method") == "provider_bar"
                            )
                        )
            return OutcomeForecast(
                owner_user_id=claim.owner_user_id,
                result_id=claim.result_id,
                symbol=str(row["symbol"]),
                asset_type=str(row["asset_type"]),
                forecast=forecast,
                latest_outcome_is_manual=manual,
            )

    def record_collection(
        self,
        claim: OutcomeJobClaim,
        forecast: OutcomeForecast,
        *,
        outcome_state: str,
        observed_close: float | None,
        observed_at: datetime,
        evidence_state: str,
        evidence_payload: Mapping[str, object],
        now: datetime,
        source_succeeded: bool,
        retry_at: datetime | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        """Append a changed observation and evidence atomically with a checked lease release."""
        if outcome_state not in {"observed", "unavailable"}:
            raise OutcomeCollectionStoreError("The collected outcome state is unsupported.")
        if evidence_state not in {"observed", "unavailable", "incomparable"}:
            raise OutcomeCollectionStoreError("The source evidence state is unsupported.")
        if outcome_state == "unavailable" and observed_close is not None:
            raise OutcomeCollectionStoreError("Unavailable outcomes cannot include a close.")
        if outcome_state == "observed" and (
            isinstance(observed_close, bool)
            or not isinstance(observed_close, int | float)
            or not math.isfinite(float(observed_close))
            or observed_close <= 0
        ):
            raise OutcomeCollectionStoreError("Observed closes must be positive and finite.")
        now_text = _timestamp(now)
        next_due = _timestamp(retry_at or (now + RECHECK_INTERVAL))
        observed_text = _timestamp(observed_at)
        payload_json = _canonical_json(dict(evidence_payload), MAX_EVIDENCE_BYTES)
        fingerprint = _collection_fingerprint(
            outcome_state=outcome_state,
            close=float(observed_close) if observed_close is not None else None,
            observed_at=observed_text,
            evidence_state=evidence_state,
            payload_json=payload_json,
        )
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if not self._claim_is_current(connection, claim, now_text):
                    raise OutcomeCollectionLeaseConflict("The collection lease is stale.")
                Repository._ensure_owner_can_write(connection, claim.owner_user_id)
                if (
                    forecast.owner_user_id != claim.owner_user_id
                    or forecast.result_id != claim.result_id
                    or forecast.latest_outcome_is_manual
                ):
                    raise OutcomeCollectionLeaseConflict("The collection target changed.")
                row = connection.execute(
                    "SELECT result_json FROM forecast_results WHERE id=? AND EXISTS ("
                    "SELECT 1 FROM forecast_result_owners WHERE result_id=? AND owner_user_id=?)",
                    (claim.result_id, claim.result_id, claim.owner_user_id),
                ).fetchone()
                if row is None:
                    raise OutcomeCollectionLeaseConflict("The saved forecast is unavailable.")
                current_forecast = json.loads(row["result_json"])
                if current_forecast != dict(forecast.forecast):
                    raise OutcomeCollectionLeaseConflict("The saved forecast changed.")
                if _parse_timestamp(current_forecast.get("target_timestamp")) != _parse_timestamp(
                    observed_text
                ) or _parse_timestamp(now_text) < _parse_timestamp(
                    current_forecast.get("target_timestamp")
                ):
                    raise OutcomeCollectionStoreError(
                        "A collected observation must match its published target session."
                    )
                control = connection.execute(
                    "SELECT enabled FROM monitoring_control WHERE id=1"
                ).fetchone()
                if control is None or control["enabled"] != 1:
                    raise OutcomeCollectionLeaseConflict(
                        "Monitoring was disabled during collection."
                    )

                latest = connection.execute(
                    """SELECT outcome.id,outcome.observed_close,outcome.observed_at,
                        outcome.state,evidence.state AS evidence_state,
                        evidence.payload_json,evidence.outcome_id AS evidence_id
                    FROM outcomes AS outcome
                    JOIN outcome_owners AS outcome_owner ON outcome_owner.outcome_id=outcome.id
                    LEFT JOIN collected_outcome_evidence AS evidence
                      ON evidence.outcome_id=outcome.id
                     AND evidence.owner_user_id=outcome_owner.owner_user_id
                    WHERE outcome.result_id=? AND outcome_owner.owner_user_id=?
                    ORDER BY outcome.id DESC LIMIT 1""",
                    (claim.result_id, claim.owner_user_id),
                ).fetchone()
                checkpointed_collection = latest is not None and claim.checkpoint.get(
                    "last_outcome_id"
                ) == int(latest["id"])
                latest_payload: object = None
                if latest is not None and latest["payload_json"] is not None:
                    try:
                        latest_payload = json.loads(latest["payload_json"])
                    except (TypeError, json.JSONDecodeError, RecursionError):
                        latest_payload = None
                latest_is_collector_evidence = (
                    isinstance(latest_payload, dict)
                    and latest_payload.get("method") == "provider_bar"
                ) or (
                    checkpointed_collection
                    and latest is not None
                    and latest["evidence_state"] in {"unavailable", "incomparable"}
                )
                if latest is not None and not latest_is_collector_evidence:
                    _raise_if_cancelled(cancelled)
                    self._release_claim(
                        connection,
                        claim,
                        now_text=now_text,
                        due_at=PARKED_DUE_AT,
                        checkpoint={"disposition": "manual_outcome_preserved"},
                        failure_code=None,
                        source_succeeded=False,
                    )
                    _raise_if_cancelled(cancelled)
                    connection.commit()
                    return {"disposition": "manual_outcome_preserved", "outcome_id": None}
                if latest is not None and (
                    latest["evidence_id"] is None
                    or latest["payload_json"] is None
                    or latest["evidence_state"] not in {"observed", "unavailable", "incomparable"}
                ):
                    raise OutcomeCollectionStoreError("The prior collection evidence is invalid.")

                observed_return, comparison_rule = evaluate_outcome(
                    current_forecast,
                    float(observed_close) if observed_close is not None else None,
                    observed_at,
                )
                same_as_latest = False
                latest_id: int | None = None
                if latest is not None:
                    latest_id = int(latest["id"])
                    same_as_latest = (
                        _collection_fingerprint(
                            outcome_state=str(latest["state"]),
                            close=(
                                float(latest["observed_close"])
                                if latest["observed_close"] is not None
                                else None
                            ),
                            observed_at=_timestamp(_parse_timestamp(latest["observed_at"])),
                            evidence_state=str(latest["evidence_state"]),
                            payload_json=_canonical_json(
                                json.loads(latest["payload_json"]), MAX_EVIDENCE_BYTES
                            ),
                        )
                        == fingerprint
                    )
                outcome_id = latest_id if same_as_latest else None
                if not same_as_latest:
                    _raise_if_cancelled(cancelled)
                    state = (
                        "unavailable"
                        if outcome_state == "unavailable"
                        else "corrected"
                        if latest is not None
                        else "observed"
                    )
                    note = (
                        ""
                        if evidence_state == "observed"
                        else str(
                            evidence_payload.get("reason_code", "source_evidence_unavailable")
                        )[:256]
                    )
                    cursor = connection.execute(
                        """INSERT INTO outcomes
                        (result_id,observed_close,observed_return,observed_at,comparison_rule,
                         state,note,created_at) VALUES(?,?,?,?,?,?,?,?)""",
                        (
                            claim.result_id,
                            float(observed_close) if observed_close is not None else None,
                            observed_return,
                            observed_text,
                            comparison_rule,
                            state,
                            note,
                            now_text,
                        ),
                    )
                    inserted_outcome_id = cursor.lastrowid
                    if type(inserted_outcome_id) is not int or inserted_outcome_id <= 0:
                        raise OutcomeCollectionStoreError(
                            "The collected outcome identifier is invalid."
                        )
                    outcome_id = inserted_outcome_id
                    connection.execute(
                        "INSERT INTO outcome_owners(outcome_id,owner_user_id,assigned_at) "
                        "VALUES(?,?,?)",
                        (outcome_id, claim.owner_user_id, now_text),
                    )
                    connection.execute(
                        """INSERT INTO collected_outcome_evidence
                        (outcome_id,owner_user_id,result_id,state,payload_json,collected_at)
                        VALUES(?,?,?,?,?,?)""",
                        (
                            outcome_id,
                            claim.owner_user_id,
                            claim.result_id,
                            evidence_state,
                            payload_json,
                            now_text,
                        ),
                    )
                checkpoint = dict(claim.checkpoint)
                checkpoint.pop("active_claim", None)
                checkpoint.update(
                    {
                        "last_collection_sha256": fingerprint,
                        "last_outcome_id": outcome_id,
                        "last_collected_at": now_text,
                    }
                )
                failure_code = None
                if evidence_state != "observed":
                    reason = evidence_payload.get("reason_code")
                    failure_code = (
                        reason
                        if isinstance(reason, str) and _FAILURE_RE.fullmatch(reason)
                        else "source_unavailable"
                    )
                self._release_claim(
                    connection,
                    claim,
                    now_text=now_text,
                    due_at=next_due,
                    checkpoint=checkpoint,
                    failure_code=failure_code,
                    source_succeeded=source_succeeded,
                )
                _raise_if_cancelled(cancelled)
                connection.commit()
                return {
                    "disposition": "unchanged" if same_as_latest else "recorded",
                    "outcome_id": outcome_id,
                    "fingerprint": fingerprint,
                }
            except BaseException:
                connection.rollback()
                raise

    def defer_claim(
        self,
        claim: OutcomeJobClaim,
        now: datetime,
        *,
        retry_at: datetime,
        failure_code: str,
    ) -> None:
        """Release a failed provider attempt with a bounded retry and safe failure code."""
        if not isinstance(failure_code, str) or not _FAILURE_RE.fullmatch(failure_code):
            raise OutcomeCollectionStoreError("The collection failure code is invalid.")
        now_text = _timestamp(now)
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if not self._claim_is_current(connection, claim, now_text):
                    raise OutcomeCollectionLeaseConflict("The collection lease is stale.")
                Repository._ensure_owner_can_write(connection, claim.owner_user_id)
                checkpoint = dict(claim.checkpoint)
                checkpoint.pop("active_claim", None)
                self._release_claim(
                    connection,
                    claim,
                    now_text=now_text,
                    due_at=_timestamp(retry_at),
                    checkpoint=checkpoint,
                    failure_code=failure_code,
                    source_succeeded=False,
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def preserve_manual_outcome(self, claim: OutcomeJobClaim, now: datetime) -> None:
        """Park collection when a user-authored outcome already owns this result."""
        now_text = _timestamp(now)
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if not self._claim_is_current(connection, claim, now_text):
                    raise OutcomeCollectionLeaseConflict("The collection lease is stale.")
                Repository._ensure_owner_can_write(connection, claim.owner_user_id)
                self._release_claim(
                    connection,
                    claim,
                    now_text=now_text,
                    due_at=PARKED_DUE_AT,
                    checkpoint={"disposition": "manual_outcome_preserved"},
                    failure_code=None,
                    source_succeeded=False,
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def _claim_is_current(
        self, connection: sqlite3.Connection, claim: OutcomeJobClaim, now_text: str
    ) -> bool:
        """Bind every later read/write to the complete persisted lease identity."""
        try:
            claim_until = _timestamp(_parse_timestamp(claim.lease_until))
        except OutcomeCollectionStoreError:
            return False
        row = connection.execute(
            "SELECT job.revision,job.lease_token,job.lease_until,job.active_request_id,"
            "job.active_requested_at FROM monitoring_jobs AS job "
            "JOIN users AS account ON account.id=job.owner_user_id AND account.status='active' "
            "AND (?=0 OR account.role='admin') "
            "JOIN monitoring_control AS control ON control.id=1 AND control.enabled=1 "
            "WHERE job.id=? AND job.owner_user_id=? AND job.kind='outcome' "
            "AND job.resource_id=?",
            (int(self.admin_only), claim.job_id, claim.owner_user_id, str(claim.result_id)),
        ).fetchone()
        return bool(
            row is not None
            and row["revision"] == claim.job_revision
            and row["lease_token"] == claim.lease_token
            and row["lease_until"] == claim_until
            and row["active_request_id"] == claim.request_id
            and row["active_requested_at"] == claim.requested_at
            and row["lease_until"] > now_text
        )

    @staticmethod
    def _release_claim(
        connection: sqlite3.Connection,
        claim: OutcomeJobClaim,
        *,
        now_text: str,
        due_at: str,
        checkpoint: Mapping[str, object],
        failure_code: str | None,
        source_succeeded: bool,
    ) -> None:
        """Release a still-current lease and persist only bounded status metadata."""
        checkpoint_json = _canonical_json(dict(checkpoint), MAX_CHECKPOINT_BYTES)
        changed = connection.execute(
            "UPDATE monitoring_jobs SET due_at=?,checkpoint_json=?,lease_token=NULL,"
            "lease_until=NULL,active_request_id=NULL,active_requested_at=NULL,revision=revision+1,"
            "last_success_at=COALESCE(?,last_success_at),failure_code=? "
            "WHERE id=? AND owner_user_id=? AND kind='outcome' "
            "AND revision=? AND lease_token=? AND active_request_id=?",
            (
                due_at,
                checkpoint_json,
                now_text if source_succeeded else None,
                failure_code,
                claim.job_id,
                claim.owner_user_id,
                claim.job_revision,
                claim.lease_token,
                claim.request_id,
            ),
        ).rowcount
        if changed != 1:
            raise OutcomeCollectionLeaseConflict("The collection lease changed during commit.")
