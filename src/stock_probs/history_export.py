"""Bounded owner-selected exports for durable monitoring and review records."""

from __future__ import annotations

import csv
import json
import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from io import StringIO
from typing import Any, Final, Literal

from stock_probs.repository import Repository

HistorySection = Literal["notifications", "rules", "reviews", "evidence", "preferences"]
EXPORT_FORMAT = "stock-probs-monitoring-history"
EXPORT_FORMAT_VERSION = 1
MAX_EXPORT_LIMIT = 100
MAX_EXPORT_BYTES = 2 * 1024 * 1024
MAX_EXPORT_FIELD_BYTES = 4096
_EXPORT_SECTIONS: Final[tuple[HistorySection, ...]] = (
    "notifications",
    "rules",
    "reviews",
    "evidence",
    "preferences",
)
_NOTIFICATION_FIELDS: Final = {
    "price_alert": (
        "alert_id",
        "generation",
        "symbol",
        "currency",
        "threshold",
        "direction",
        "price",
        "provider",
        "observed_at",
    ),
    "forecast_outcome": (
        "result_id",
        "horizon",
        "symbol",
        "state",
        "observed_close",
        "observed_at",
    ),
    "thesis_review": ("result_id", "symbol", "state", "revision", "reviewed_at"),
}
_OBSERVATION_FIELDS: Final = ("symbol", "currency", "price", "provider", "observed_at")
_EVIDENCE_FIELDS: Final = (
    "schema",
    "state",
    "provider",
    "symbol",
    "currency",
    "adjustment_basis",
)
_EVIDENCE_ENDPOINT_FIELDS: Final = ("timestamp", "close")
_CORPORATE_ACTION_FIELDS: Final = (
    "state",
    "provider",
    "symbol",
    "currency",
    "from_timestamp",
    "through_timestamp",
)
CellSanitizer = Callable[[object], str]


class HistoryExportError(ValueError):
    """Raised when a bounded owner-selected export cannot be built safely."""


def build_owner_history_export(
    repository: Repository,
    owner_user_id: int,
    sections: Sequence[str],
    *,
    generated_at: datetime | None = None,
    limit: int = MAX_EXPORT_LIMIT,
) -> dict[str, Any]:
    """Return only selected rows owned by one active user.

    Address rows, verification challenges, outbox records, attempt leases, and worker jobs are
    intentionally outside this user history projection.
    """

    if type(owner_user_id) is not int or owner_user_id < 1:
        raise HistoryExportError("An active owner is required for export.")
    if type(limit) is not int or not 1 <= limit <= MAX_EXPORT_LIMIT:
        raise HistoryExportError("Export limit is outside the allowed range.")
    selected = _selected_sections(sections)
    timestamp = generated_at or datetime.now(UTC)
    if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
        raise HistoryExportError("Export timestamp must include a timezone offset.")
    timestamp = timestamp.astimezone(UTC)

    records: dict[str, list[dict[str, Any]]] = {}
    truncated: dict[str, bool] = {}
    try:
        with repository.connect() as connection:
            owner = connection.execute(
                "SELECT status FROM users WHERE id = ?", (owner_user_id,)
            ).fetchone()
            if owner is None or owner["status"] != "active":
                raise HistoryExportError("An active owner is required for export.")
            for section in selected:
                rows, was_truncated = _read_section(connection, section, owner_user_id, limit)
                records[section] = rows
                truncated[section] = was_truncated
    except HistoryExportError:
        raise
    except (OSError, sqlite3.Error, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HistoryExportError("Owner history could not be exported safely.") from exc

    projection = {
        "format": EXPORT_FORMAT,
        "format_version": EXPORT_FORMAT_VERSION,
        "generated_at": timestamp.isoformat(),
        "sections": list(selected),
        "records": records,
        "counts": {section: len(rows) for section, rows in records.items()},
        "truncated": truncated,
    }
    if len(_stable_json(projection).encode("utf-8")) > MAX_EXPORT_BYTES:
        raise HistoryExportError("Owner history exceeds the export size limit.")
    return projection


def serialize_owner_history_json(projection: dict[str, Any]) -> str:
    """Serialize a previously validated export projection as stable JSON."""

    try:
        encoded = _stable_json(projection)
        if len(encoded.encode("utf-8")) > MAX_EXPORT_BYTES:
            raise HistoryExportError("Owner history exceeds the export size limit.")
        return encoded
    except HistoryExportError:
        raise
    except (TypeError, ValueError) as exc:
        raise HistoryExportError("Owner history could not be serialized safely.") from exc


def serialize_owner_history_csv(projection: dict[str, Any], *, safe_cell: CellSanitizer) -> str:
    """Serialize selected records while delegating formula defense to the API's shared helper."""

    records = projection.get("records")
    sections = projection.get("sections")
    if (
        not isinstance(records, dict)
        or not isinstance(sections, list)
        or any(section not in _EXPORT_SECTIONS for section in sections)
        or not callable(safe_cell)
    ):
        raise HistoryExportError("Owner history projection is invalid.")

    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(("section", "record_type", "record_json"))
    for section in sections:
        rows = records.get(section)
        if not isinstance(rows, list):
            raise HistoryExportError("Owner history projection is invalid.")
        for record in rows:
            if not isinstance(record, dict):
                raise HistoryExportError("Owner history projection is invalid.")
            record_type = record.get("record_type", section.removesuffix("s"))
            encoded = _stable_json(_sanitize_csv_json(record, safe_cell))
            writer.writerow(
                (
                    safe_cell(section),
                    safe_cell(record_type),
                    safe_cell(encoded),
                )
            )
    result = output.getvalue()
    if len(result.encode("utf-8")) > MAX_EXPORT_BYTES:
        raise HistoryExportError("Owner history exceeds the export size limit.")
    return result


def _selected_sections(sections: Sequence[str]) -> tuple[HistorySection, ...]:
    """Validate explicit, unique section selection and use stable contract order."""

    if not isinstance(sections, list | tuple) or len(sections) > len(_EXPORT_SECTIONS):
        raise HistoryExportError("Choose one or more supported export sections.")
    selected = tuple(sections)
    if (
        not selected
        or any(type(section) is not str or section not in _EXPORT_SECTIONS for section in selected)
        or len(set(selected)) != len(selected)
    ):
        raise HistoryExportError("Choose one or more supported export sections.")
    return tuple(section for section in _EXPORT_SECTIONS if section in selected)


def _stable_json(value: object) -> str:
    """Encode the bounded projection deterministically and reject non-JSON values."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sanitize_csv_json(value: object, safe_cell: CellSanitizer) -> object:
    """Apply the API formula policy to every string inside a CSV JSON cell."""

    if isinstance(value, str):
        return safe_cell(value)
    if isinstance(value, list):
        return [_sanitize_csv_json(item, safe_cell) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_csv_json(item, safe_cell) for key, item in value.items()}
    return value


def _decode_object(payload_json: str) -> dict[str, Any]:
    """Decode one persisted JSON object before selecting its public fields."""

    value = json.loads(payload_json)
    if not isinstance(value, dict):
        raise HistoryExportError("A saved history record is invalid.")
    return value


def _fixed_json_projection(payload_json: str, fields: Sequence[str]) -> dict[str, Any]:
    """Keep only an explicit flat field allowlist from a persisted JSON object."""

    decoded = _decode_object(payload_json)
    return _scalar_projection(decoded, fields)


def _scalar_projection(decoded: dict[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    """Reject nested or oversized data inside the scalar export contract."""

    projection: dict[str, Any] = {}
    for field in fields:
        if field not in decoded:
            continue
        value = decoded[field]
        if value is not None and type(value) not in (str, int, float, bool):
            raise HistoryExportError("A saved history record has invalid public fields.")
        if isinstance(value, str) and len(value.encode("utf-8")) > MAX_EXPORT_FIELD_BYTES:
            raise HistoryExportError("A saved history field exceeds the export limit.")
        projection[field] = value
    return projection


def _notification_payload(kind: str, payload_json: str) -> dict[str, Any]:
    """Project only known notification display fields, omitting transport metadata."""

    fields = _NOTIFICATION_FIELDS.get(kind)
    if fields is None:
        return {}
    return _fixed_json_projection(payload_json, fields)


def _evidence_projection(payload_json: str) -> dict[str, Any]:
    """Keep known report-card evidence while discarding unrecognized nested metadata."""

    decoded = _decode_object(payload_json)
    projection = _scalar_projection(decoded, _EVIDENCE_FIELDS)
    for endpoint in ("origin", "target"):
        value = decoded.get(endpoint)
        if isinstance(value, dict):
            projection[endpoint] = _scalar_projection(value, _EVIDENCE_ENDPOINT_FIELDS)
    actions = decoded.get("corporate_actions")
    if isinstance(actions, dict):
        action_projection = _scalar_projection(actions, _CORPORATE_ACTION_FIELDS)
        events = actions.get("events")
        if isinstance(events, list):
            action_projection["event_count"] = len(events)
        projection["corporate_actions"] = action_projection
    return projection


def _read_section(
    connection: sqlite3.Connection,
    section: HistorySection,
    owner_user_id: int,
    limit: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Read bounded public columns using fixed SQL and an explicit owner predicate."""

    if section == "notifications":
        rows = connection.execute(
            "SELECT id,kind,payload_json,is_read,revision,created_at FROM notifications "
            "WHERE owner_user_id=? ORDER BY created_at,id LIMIT ?",
            (owner_user_id, limit + 1),
        ).fetchall()
        return (
            [
                {
                    "record_type": "notification",
                    "id": row["id"],
                    "kind": row["kind"],
                    "payload": _notification_payload(row["kind"], row["payload_json"]),
                    "is_read": bool(row["is_read"]),
                    "revision": row["revision"],
                    "created_at": row["created_at"],
                }
                for row in rows[:limit]
            ],
            len(rows) > limit,
        )

    if section == "rules":
        alerts = connection.execute(
            "SELECT id,revision,payload_json,enabled,armed_at,arm_generation,ready,last_side,"
            "last_observed_at,last_observation_json,last_check_at,last_success_at,check_state,"
            "created_at,updated_at FROM price_alerts WHERE owner_user_id=? "
            "ORDER BY created_at,id LIMIT ?",
            (owner_user_id, limit + 1),
        ).fetchall()
        revisions = connection.execute(
            "SELECT alert_id,revision,payload_json,enabled,recorded_at FROM price_alert_revisions "
            "WHERE owner_user_id=? ORDER BY alert_id,revision LIMIT ?",
            (owner_user_id, limit + 1),
        ).fetchall()
        records = [
            {
                "record_type": "rule",
                "id": row["id"],
                "revision": row["revision"],
                "configuration": _fixed_json_projection(
                    row["payload_json"],
                    ("symbol", "currency", "threshold", "direction", "repeating"),
                ),
                "enabled": bool(row["enabled"]),
                "armed_at": row["armed_at"],
                "arm_generation": row["arm_generation"],
                "ready": bool(row["ready"]),
                "last_side": row["last_side"],
                "last_observed_at": row["last_observed_at"],
                "last_observation": (
                    _fixed_json_projection(row["last_observation_json"], _OBSERVATION_FIELDS)
                    if row["last_observation_json"] is not None
                    else None
                ),
                "last_check_at": row["last_check_at"],
                "last_success_at": row["last_success_at"],
                "check_state": row["check_state"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in alerts[:limit]
        ]
        records.extend(
            {
                "record_type": "rule_revision",
                "alert_id": row["alert_id"],
                "revision": row["revision"],
                "configuration": _fixed_json_projection(
                    row["payload_json"],
                    ("symbol", "currency", "threshold", "direction", "repeating"),
                ),
                "enabled": bool(row["enabled"]),
                "recorded_at": row["recorded_at"],
            }
            for row in revisions[:limit]
        )
        return records, len(alerts) > limit or len(revisions) > limit

    if section == "reviews":
        rows = connection.execute(
            "SELECT result_id,revision,state,note,reviewed_at FROM forecast_outcome_reviews "
            "WHERE owner_user_id=? ORDER BY result_id,revision LIMIT ?",
            (owner_user_id, limit + 1),
        ).fetchall()
        return (
            [
                {
                    "record_type": "outcome_review",
                    "result_id": row["result_id"],
                    "revision": row["revision"],
                    "state": row["state"],
                    "note": row["note"],
                    "reviewed_at": row["reviewed_at"],
                }
                for row in rows[:limit]
            ],
            len(rows) > limit,
        )

    if section == "evidence":
        outcomes = connection.execute(
            "SELECT outcome_id,result_id,state,payload_json,collected_at "
            "FROM collected_outcome_evidence WHERE owner_user_id=? "
            "ORDER BY collected_at,outcome_id LIMIT ?",
            (owner_user_id, limit + 1),
        ).fetchall()
        observations = connection.execute(
            "SELECT alert_id,generation,observation_kind,requested_at,received_at,accepted_at,"
            "observed_at,provider,symbol,currency,price,disposition,stale,"
            "state_revision_before,state_revision_after FROM price_alert_observations "
            "WHERE owner_user_id=? ORDER BY observed_at,alert_id,generation LIMIT ?",
            (owner_user_id, limit + 1),
        ).fetchall()
        records = [
            {
                "record_type": "collected_outcome_evidence",
                "outcome_id": row["outcome_id"],
                "result_id": row["result_id"],
                "state": row["state"],
                "evidence": _evidence_projection(row["payload_json"]),
                "collected_at": row["collected_at"],
            }
            for row in outcomes[:limit]
        ]
        records.extend(
            {
                "record_type": "price_alert_observation",
                "alert_id": row["alert_id"],
                "generation": row["generation"],
                "observation_kind": row["observation_kind"],
                "requested_at": row["requested_at"],
                "received_at": row["received_at"],
                "accepted_at": row["accepted_at"],
                "observed_at": row["observed_at"],
                "provider": row["provider"],
                "symbol": row["symbol"],
                "currency": row["currency"],
                "price": row["price"],
                "disposition": row["disposition"],
                "stale": bool(row["stale"]),
                "state_revision_before": row["state_revision_before"],
                "state_revision_after": row["state_revision_after"],
            }
            for row in observations[:limit]
        )
        return records, len(outcomes) > limit or len(observations) > limit

    rows = connection.execute(
        "SELECT revision,alert_email,digest_email,digest_time,digest_timezone,updated_at "
        "FROM notification_preferences WHERE owner_user_id=?",
        (owner_user_id,),
    ).fetchall()
    return (
        [
            {
                "record_type": "notification_preferences",
                "revision": row["revision"],
                "alert_email": bool(row["alert_email"]),
                "digest_email": bool(row["digest_email"]),
                "digest_time": row["digest_time"],
                "digest_timezone": row["digest_timezone"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ],
        False,
    )
