"""Owner-bound reads and append-only manual reviews for forecast report cards."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any, Literal

from stock_probs.auth import AuthContext
from stock_probs.auth_write_guard import StepUpChecker, authorize_current_write
from stock_probs.report_cards import SUPPORTED_HORIZONS, score_record, summarize
from stock_probs.repository import Repository

MAX_REPORT_PAGE = 10_000
MAX_REPORT_PAGE_SIZE = 100
MAX_REVIEW_NOTE_BYTES = 2048
_MANUAL_HORIZONS = frozenset({"five_min_forward", "completed_5m_to_close"})
_MAX_TIMESTAMP_LENGTH = 64
_MICROSECONDS_PER_DAY = 86_400_000_000


def _utc_microseconds(value: object) -> int | None:
    """Parse a bounded aware ISO timestamp to exact UTC microseconds, or exclude it."""
    if not isinstance(value, str) or len(value) > _MAX_TIMESTAMP_LENGTH:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        utc = parsed.astimezone(UTC)
        return (
            (utc.toordinal() - 1) * _MICROSECONDS_PER_DAY
            + utc.hour * 3_600_000_000
            + utc.minute * 60_000_000
            + utc.second * 1_000_000
            + utc.microsecond
        )
    except (OverflowError, TypeError, ValueError):
        return None


class ReportStoreError(ValueError):
    """A safe, classified report-card validation or state failure."""

    def __init__(self, code: str, message: str, *, status_code: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ReportNotFoundError(ReportStoreError):
    """The requested report resource is absent or belongs to another owner."""

    def __init__(self) -> None:
        super().__init__("REPORT_NOT_FOUND", "The report card was not found.", status_code=404)


class ReportConflictError(ReportStoreError):
    """The requested review no longer matches its source or expected revision."""

    def __init__(self, message: str = "The report card changed; refresh and try again."):
        super().__init__("REPORT_CONFLICT", message, status_code=409)


def _owner_id(value: object) -> int:
    if type(value) is not int or value < 1:
        raise ReportStoreError(
            "INVALID_OWNER", "The authenticated owner is unavailable.", status_code=401
        )
    return value


def _instant(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ReportStoreError(
            "INVALID_REPORT_CLOCK", "A timezone-aware report time is required.", status_code=422
        )
    return value.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON property")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _decode_object(value: object) -> dict[str, Any] | None:
    if not isinstance(value, str) or len(value.encode("utf-8", errors="replace")) > 262_144:
        return None
    try:
        decoded = json.loads(
            value,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, TypeError, ValueError, RecursionError):
        return None
    return decoded if isinstance(decoded, dict) else None


class ReportCardStore:
    """Read immutable saved forecasts and append owner-scoped review events.

    The collection response contains one bounded page. Its scoring denominators describe only
    that page, while ``total`` reports the matching saved-result count as of the same clock.
    Historical walk-forward evaluation fields are never queried or used for scoring.
    """

    def __init__(
        self,
        repository: Repository,
        *,
        write_authorization_mode: Literal[
            "required", "development_no_auth", "test_no_auth"
        ] = "required",
        step_up_checker: StepUpChecker | None = None,
    ):
        if write_authorization_mode not in {
            "required",
            "development_no_auth",
            "test_no_auth",
        }:
            raise TypeError("write_authorization_mode is invalid")
        if step_up_checker is not None and not callable(step_up_checker):
            raise TypeError("step_up_checker must be callable")
        self.repository = repository
        self.write_authorization_mode = write_authorization_mode
        self.step_up_checker = step_up_checker

    def _authorize_user_mutation(
        self,
        connection: sqlite3.Connection,
        auth_context: AuthContext | None,
        owner: int,
    ) -> None:
        """Bind an interactive review to its cached context inside the existing transaction."""
        if self.write_authorization_mode != "required":
            return
        authorize_current_write(
            connection,
            auth_context,
            owner,
            datetime.now(UTC),
            step_up_checker=self.step_up_checker,
        )

    @staticmethod
    def _register_time_function(connection: sqlite3.Connection) -> None:
        """Install exact timestamp comparisons on this short-lived report connection."""
        connection.create_function(
            "report_utc_microseconds", 1, _utc_microseconds, deterministic=True
        )

    @staticmethod
    def _active_owner(connection: sqlite3.Connection, owner: int) -> None:
        row = connection.execute("SELECT status FROM users WHERE id = ?", (owner,)).fetchone()
        if row is None or row["status"] != "active":
            raise ReportNotFoundError()

    @staticmethod
    def _where(
        owner: int,
        as_of: str,
        symbol: str | None,
        horizon: str | None,
    ) -> tuple[str, list[object]]:
        clauses = [
            "result_owner.owner_user_id = ?",
            "report_utc_microseconds(result_owner.assigned_at) <= report_utc_microseconds(?)",
            "report_utc_microseconds(result.created_at) <= report_utc_microseconds(?)",
            "report_utc_microseconds(input.created_at) <= report_utc_microseconds(?)",
            "report_utc_microseconds(run.created_at) <= report_utc_microseconds(?)",
            "EXISTS (SELECT 1 FROM search_events AS event "
            "JOIN search_event_owners AS event_owner ON event_owner.event_id = event.id "
            "WHERE event.run_id = run.id AND event_owner.owner_user_id = ? "
            "AND report_utc_microseconds(event_owner.assigned_at) <= "
            "report_utc_microseconds(?) AND event.analysis_kind = 'submitted_forecast' "
            "AND report_utc_microseconds(event.submitted_at) <= report_utc_microseconds(?) "
            "AND report_utc_microseconds(event.completed_at) <= report_utc_microseconds(?))",
        ]
        values: list[object] = [owner, as_of, as_of, as_of, as_of, owner, as_of, as_of, as_of]
        if symbol is not None:
            clauses.append("run.symbol = ?")
            values.append(symbol)
        if horizon is not None:
            clauses.append("result.horizon = ?")
            values.append(horizon)
        return " AND ".join(clauses), values

    def list_report(
        self,
        owner_user_id: int,
        now: datetime,
        *,
        page: int = 1,
        page_size: int = 20,
        symbol: str | None = None,
        horizon: str | None = None,
    ) -> dict[str, Any]:
        """Score one bounded owner page using only evidence published by ``now``."""
        owner = _owner_id(owner_user_id)
        current = _instant(now)
        if type(page) is not int or not 1 <= page <= MAX_REPORT_PAGE:
            raise ReportStoreError(
                "INVALID_PAGE", "Page must be between 1 and 10000.", status_code=422
            )
        if type(page_size) is not int or not 1 <= page_size <= MAX_REPORT_PAGE_SIZE:
            raise ReportStoreError(
                "INVALID_PAGE_SIZE", "Page size must be between 1 and 100.", status_code=422
            )
        if symbol is not None and (not isinstance(symbol, str) or not 1 <= len(symbol) <= 80):
            raise ReportStoreError(
                "INVALID_SYMBOL", "Symbol must contain 1 to 80 characters.", status_code=422
            )
        if horizon is not None and horizon not in SUPPORTED_HORIZONS:
            raise ReportStoreError(
                "INVALID_HORIZON", "The report horizon is not supported.", status_code=422
            )

        as_of = _timestamp(current)
        where, values = self._where(owner, as_of, symbol, horizon)
        source = (
            "forecast_results AS result "
            "JOIN forecast_inputs AS input ON input.id = result.input_id "
            "JOIN forecast_runs AS run ON run.id = input.run_id "
            "JOIN forecast_result_owners AS result_owner ON result_owner.result_id = result.id "
        )
        with self.repository.connect() as connection:
            self._register_time_function(connection)
            connection.execute("BEGIN")
            self._active_owner(connection, owner)
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {source} WHERE {where}",  # noqa: S608
                    values,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""SELECT result.id AS result_id, result.horizon AS result_horizon,
                    result.result_json AS forecast_json, result.created_at AS forecast_created_at,
                    run.symbol AS symbol,
                    outcome.id AS outcome_id, outcome.observed_close, outcome.observed_return,
                    outcome.observed_at, outcome.comparison_rule, outcome.state AS outcome_state,
                    outcome.note AS outcome_note, outcome.created_at AS outcome_created_at,
                    evidence.outcome_id AS evidence_outcome_id,
                    evidence.owner_user_id AS evidence_owner_user_id,
                    evidence.result_id AS evidence_result_id,
                    evidence.state AS evidence_state,
                    CASE WHEN report_utc_microseconds(evidence.collected_at) <=
                                   report_utc_microseconds(?)
                         THEN evidence.payload_json ELSE '' END AS evidence_payload_json,
                    evidence.collected_at AS evidence_collected_at,
                    review.owner_user_id AS review_owner_user_id,
                    review.result_id AS review_result_id, review.revision AS review_revision,
                    review.state AS review_state, review.note AS review_note,
                    review.reviewed_at AS review_reviewed_at
                FROM {source}
                LEFT JOIN outcomes AS outcome ON outcome.id = (
                    SELECT candidate.id FROM outcomes AS candidate
                    JOIN outcome_owners AS outcome_owner ON outcome_owner.outcome_id = candidate.id
                    WHERE candidate.result_id = result.id
                      AND outcome_owner.owner_user_id = result_owner.owner_user_id
                      AND report_utc_microseconds(candidate.created_at) <=
                          report_utc_microseconds(?)
                      AND report_utc_microseconds(outcome_owner.assigned_at) <=
                          report_utc_microseconds(?)
                    ORDER BY report_utc_microseconds(candidate.created_at) DESC,
                             candidate.id DESC LIMIT 1
                )
                LEFT JOIN collected_outcome_evidence AS evidence
                  ON evidence.outcome_id = outcome.id
                 AND evidence.owner_user_id = result_owner.owner_user_id
                 AND evidence.result_id = result.id
                 AND report_utc_microseconds(evidence.collected_at) IS NOT NULL
                LEFT JOIN forecast_outcome_reviews AS review
                  ON review.owner_user_id = result_owner.owner_user_id
                 AND review.result_id = result.id
                 AND review.revision = (
                    SELECT candidate_review.revision
                    FROM forecast_outcome_reviews AS candidate_review
                    WHERE candidate_review.owner_user_id = result_owner.owner_user_id
                      AND candidate_review.result_id = result.id
                      AND report_utc_microseconds(candidate_review.reviewed_at) <=
                          report_utc_microseconds(?)
                    ORDER BY report_utc_microseconds(candidate_review.reviewed_at) DESC,
                             candidate_review.revision DESC LIMIT 1
                 )
                WHERE {where}
                ORDER BY report_utc_microseconds(result.created_at) DESC,
                         result.id DESC LIMIT ? OFFSET ?""",  # noqa: S608
                [as_of, as_of, as_of, as_of, *values, page_size, (page - 1) * page_size],
            ).fetchall()

        records: list[dict[str, Any]] = []
        for row in rows:
            forecast = _decode_object(row["forecast_json"])
            if forecast is not None and forecast.get("horizon") != row["result_horizon"]:
                forecast = None
            outcome: dict[str, Any] | None = None
            if row["outcome_id"] is not None:
                outcome = {
                    "id": int(row["outcome_id"]),
                    "result_id": int(row["result_id"]),
                    "observed_close": row["observed_close"],
                    "observed_return": row["observed_return"],
                    "observed_at": row["observed_at"],
                    "comparison_rule": row["comparison_rule"],
                    "state": row["outcome_state"],
                    "note": row["outcome_note"],
                    "created_at": row["outcome_created_at"],
                }
            evidence: dict[str, Any] | None = None
            if row["evidence_outcome_id"] is not None:
                evidence = {
                    "outcome_id": int(row["evidence_outcome_id"]),
                    "owner_user_id": int(row["evidence_owner_user_id"]),
                    "result_id": int(row["evidence_result_id"]),
                    "state": row["evidence_state"],
                    "payload_json": row["evidence_payload_json"],
                    "collected_at": row["evidence_collected_at"],
                }
            review_item: dict[str, Any] | None = None
            if row["review_revision"] is not None:
                review_item = {
                    "owner_user_id": int(row["review_owner_user_id"]),
                    "result_id": int(row["review_result_id"]),
                    "revision": int(row["review_revision"]),
                    "state": row["review_state"],
                    "note": row["review_note"],
                    "reviewed_at": row["review_reviewed_at"],
                }
            records.append(
                {
                    "owner_user_id": owner,
                    "result_id": int(row["result_id"]),
                    "symbol": row["symbol"],
                    "forecast": forecast,
                    "outcome": outcome,
                    "evidence": evidence,
                    "review": review_item,
                }
            )

        scored = summarize(records, current)
        scored.update(
            {
                "total": total,
                "page": page,
                "page_size": page_size,
                "has_next": page * page_size < total,
                "denominator_scope": "current_page",
                "denominator_count": len(records),
            }
        )
        return scored

    @staticmethod
    def _saved_manual_source(
        connection: sqlite3.Connection,
        owner: int,
        result_id: int,
        as_of: str,
    ) -> tuple[sqlite3.Row, sqlite3.Row, sqlite3.Row, dict[str, Any], dict[str, Any]]:
        row = connection.execute(
            """SELECT result.id AS result_id, result.horizon, result.result_json,
                      result.created_at AS forecast_created_at, run.symbol
               FROM forecast_results AS result
               JOIN forecast_inputs AS input ON input.id=result.input_id
               JOIN forecast_runs AS run ON run.id=input.run_id
               JOIN forecast_result_owners AS result_owner ON result_owner.result_id=result.id
               WHERE result.id=? AND result_owner.owner_user_id=?
                 AND report_utc_microseconds(result_owner.assigned_at)<=
                     report_utc_microseconds(?)
                 AND report_utc_microseconds(result.created_at)<=report_utc_microseconds(?)
                 AND report_utc_microseconds(input.created_at)<=report_utc_microseconds(?)
                 AND report_utc_microseconds(run.created_at)<=report_utc_microseconds(?)
                 AND EXISTS (
                    SELECT 1 FROM search_events AS event
                    JOIN search_event_owners AS event_owner ON event_owner.event_id=event.id
                    WHERE event.run_id=run.id AND event_owner.owner_user_id=?
                      AND report_utc_microseconds(event_owner.assigned_at)<=
                          report_utc_microseconds(?) AND event.analysis_kind='submitted_forecast'
                      AND report_utc_microseconds(event.submitted_at)<=report_utc_microseconds(?)
                      AND report_utc_microseconds(event.completed_at)<=report_utc_microseconds(?)
                 )""",
            (result_id, owner, as_of, as_of, as_of, as_of, owner, as_of, as_of, as_of),
        ).fetchone()
        if row is None:
            raise ReportNotFoundError()
        forecast = _decode_object(row["result_json"])
        if row["horizon"] not in _MANUAL_HORIZONS or forecast is None:
            raise ReportConflictError(
                "Manual reviews are available only for a valid saved five-minute forecast."
            )
        if forecast.get("horizon") != row["horizon"]:
            raise ReportConflictError("The saved forecast is not internally consistent.")
        outcome = connection.execute(
            """SELECT outcome.* FROM outcomes AS outcome
               JOIN outcome_owners AS outcome_owner ON outcome_owner.outcome_id=outcome.id
               WHERE outcome.result_id=? AND outcome_owner.owner_user_id=?
                 AND report_utc_microseconds(outcome.created_at)<=report_utc_microseconds(?)
                 AND report_utc_microseconds(outcome_owner.assigned_at)<=
                     report_utc_microseconds(?)
               ORDER BY report_utc_microseconds(outcome.created_at) DESC,
                        outcome.id DESC LIMIT 1""",
            (result_id, owner, as_of, as_of),
        ).fetchone()
        if outcome is None or outcome["state"] not in {"observed", "corrected"}:
            raise ReportConflictError(
                "A published observed outcome is required before manual review."
            )
        evidence = connection.execute(
            """SELECT * FROM collected_outcome_evidence
               WHERE outcome_id=? AND owner_user_id=? AND result_id=?
                 AND report_utc_microseconds(collected_at)<=report_utc_microseconds(?)""",
            (outcome["id"], owner, result_id, as_of),
        ).fetchone()
        if evidence is None or evidence["state"] != "observed":
            raise ReportConflictError("Matching published manual-source evidence is required.")
        payload = _decode_object(evidence["payload_json"])
        if (
            payload is None
            or set(payload) != {"method", "review_revision", "comparability"}
            or payload.get("method") != "manual_review"
            or type(payload.get("review_revision")) is not int
            or payload["review_revision"] < 1
            or not isinstance(payload.get("comparability"), dict)
        ):
            raise ReportConflictError("Matching manual-source evidence is required.")
        return row, outcome, evidence, forecast, payload

    def append_manual_review(
        self,
        owner_user_id: int,
        result_id: int,
        expected_revision: int,
        state: str,
        note: str,
        now: datetime,
        *,
        auth_context: AuthContext | None = None,
    ) -> dict[str, Any]:
        """Append a CAS review for an existing, exact owner-bound manual five-minute source."""
        owner = _owner_id(owner_user_id)
        current = _instant(now)
        if type(result_id) is not int or result_id < 1:
            raise ReportStoreError(
                "INVALID_RESULT_ID", "Result id must be positive.", status_code=422
            )
        if (
            type(expected_revision) is not int
            or expected_revision < 0
            or expected_revision >= 2**63 - 1
        ):
            raise ReportStoreError(
                "INVALID_REVISION", "Expected revision is invalid.", status_code=422
            )
        if state not in {"confirmed", "disputed"}:
            raise ReportStoreError(
                "INVALID_REVIEW_STATE",
                "Review state must be confirmed or disputed.",
                status_code=422,
            )
        if not isinstance(note, str) or len(note.encode("utf-8")) > MAX_REVIEW_NOTE_BYTES:
            raise ReportStoreError(
                "INVALID_REVIEW_NOTE", "Review note exceeds 2048 UTF-8 bytes.", status_code=422
            )
        as_of = _timestamp(current)
        with self.repository.connect() as connection:
            self._register_time_function(connection)
            connection.execute("BEGIN IMMEDIATE")
            self._authorize_user_mutation(connection, auth_context, owner)
            self._active_owner(connection, owner)
            forecast_row, outcome_row, evidence_row, forecast, source_payload = (
                self._saved_manual_source(connection, owner, result_id, as_of)
            )
            last = connection.execute(
                """SELECT revision FROM forecast_outcome_reviews
                   WHERE owner_user_id=? AND result_id=? ORDER BY revision DESC LIMIT 1""",
                (owner, result_id),
            ).fetchone()
            latest_revision = int(last["revision"]) if last is not None else 0
            if latest_revision != expected_revision:
                raise ReportConflictError()
            revision = latest_revision + 1
            if source_payload["review_revision"] > revision:
                raise ReportConflictError("Manual evidence refers to a later review revision.")
            reviewed_at = _timestamp(current)
            record = {
                "owner_user_id": owner,
                "result_id": result_id,
                "symbol": forecast_row["symbol"],
                "forecast": forecast,
                "outcome": {
                    key: outcome_row[key]
                    for key in (
                        "id",
                        "result_id",
                        "observed_close",
                        "observed_return",
                        "observed_at",
                        "comparison_rule",
                        "state",
                        "note",
                        "created_at",
                    )
                },
                "evidence": {
                    "outcome_id": int(evidence_row["outcome_id"]),
                    "owner_user_id": int(evidence_row["owner_user_id"]),
                    "result_id": int(evidence_row["result_id"]),
                    "state": evidence_row["state"],
                    "payload_json": evidence_row["payload_json"],
                    "collected_at": evidence_row["collected_at"],
                },
                "review": {
                    "owner_user_id": owner,
                    "result_id": result_id,
                    "revision": source_payload["review_revision"],
                    "state": "confirmed",
                    "note": "",
                    "reviewed_at": reviewed_at,
                },
            }
            source_check = score_record(record, current)
            if (
                source_check["state"] != "scored"
                or source_check["source"] is None
                or source_check["source"].get("method") != "manual_review"
            ):
                raise ReportConflictError("Matching manual-source evidence is not scoreable.")
            if state == "confirmed":
                confirmation = {
                    **record,
                    "review": {
                        "owner_user_id": owner,
                        "result_id": result_id,
                        "revision": revision,
                        "state": state,
                        "note": note,
                        "reviewed_at": reviewed_at,
                    },
                }
                scored = score_record(confirmation, current)
                if (
                    scored["state"] != "scored"
                    or scored["source"] is None
                    or scored["source"].get("method") != "manual_review"
                ):
                    raise ReportConflictError(
                        "Manual evidence does not validate this confirmation revision."
                    )
            connection.execute(
                """INSERT INTO forecast_outcome_reviews
                   (owner_user_id,result_id,revision,state,note,reviewed_at)
                   VALUES (?,?,?,?,?,?)""",
                (owner, result_id, revision, state, note, reviewed_at),
            )
            connection.commit()
        return {
            "result_id": result_id,
            "revision": revision,
            "state": state,
            "note": note,
            "reviewed_at": reviewed_at,
        }

    def review_history(
        self,
        owner_user_id: int,
        result_id: int,
        now: datetime,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any] | None:
        """Page one owner's append-only review history for a saved result."""
        owner = _owner_id(owner_user_id)
        current = _instant(now)
        if type(result_id) is not int or result_id < 1:
            raise ReportNotFoundError()
        if type(page) is not int or not 1 <= page <= MAX_REPORT_PAGE:
            raise ReportStoreError(
                "INVALID_PAGE", "Page must be between 1 and 10000.", status_code=422
            )
        if type(page_size) is not int or not 1 <= page_size <= MAX_REPORT_PAGE_SIZE:
            raise ReportStoreError(
                "INVALID_PAGE_SIZE", "Page size must be between 1 and 100.", status_code=422
            )
        as_of = _timestamp(current)
        with self.repository.connect() as connection:
            self._register_time_function(connection)
            connection.execute("BEGIN")
            self._active_owner(connection, owner)
            saved = connection.execute(
                """SELECT 1 FROM forecast_results AS result
                   JOIN forecast_inputs AS input ON input.id=result.input_id
                   JOIN forecast_runs AS run ON run.id=input.run_id
                   JOIN forecast_result_owners AS result_owner ON result_owner.result_id=result.id
                   WHERE result.id=? AND result_owner.owner_user_id=?
                     AND report_utc_microseconds(result.created_at)<=report_utc_microseconds(?)
                     AND report_utc_microseconds(result_owner.assigned_at)<=
                         report_utc_microseconds(?)
                     AND report_utc_microseconds(input.created_at)<=report_utc_microseconds(?)
                     AND report_utc_microseconds(run.created_at)<=report_utc_microseconds(?)
                     AND EXISTS (
                       SELECT 1 FROM search_events AS event
                       JOIN search_event_owners AS event_owner ON event_owner.event_id=event.id
                       WHERE event.run_id=run.id AND event_owner.owner_user_id=?
                         AND report_utc_microseconds(event_owner.assigned_at)<=
                             report_utc_microseconds(?)
                         AND event.analysis_kind='submitted_forecast'
                         AND report_utc_microseconds(event.submitted_at)<=report_utc_microseconds(?)
                         AND report_utc_microseconds(event.completed_at)<=report_utc_microseconds(?)
                     )""",
                (result_id, owner, as_of, as_of, as_of, as_of, owner, as_of, as_of, as_of),
            ).fetchone()
            if saved is None:
                return None
            total = int(
                connection.execute(
                    """SELECT COUNT(*) FROM forecast_outcome_reviews
                       WHERE owner_user_id=? AND result_id=?
                         AND report_utc_microseconds(reviewed_at)<=report_utc_microseconds(?)""",
                    (owner, result_id, as_of),
                ).fetchone()[0]
            )
            rows = connection.execute(
                """SELECT revision,state,note,reviewed_at FROM forecast_outcome_reviews
                   WHERE owner_user_id=? AND result_id=?
                     AND report_utc_microseconds(reviewed_at)<=report_utc_microseconds(?)
                   ORDER BY revision DESC LIMIT ? OFFSET ?""",
                (owner, result_id, as_of, page_size, (page - 1) * page_size),
            ).fetchall()
        return {
            "result_id": result_id,
            "items": [dict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_next": page * page_size < total,
        }
