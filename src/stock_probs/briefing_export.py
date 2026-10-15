"""Bounded JSON and CSV exports for one owner's immutable saved briefing."""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Callable, Mapping
from io import StringIO
from typing import Final

from stock_probs.briefing_domain import (
    MAX_PRICE_OBSERVATIONS,
    MAX_SOURCE_ITEMS,
    BriefingDomainError,
    BriefingSnapshot,
    BriefingWindow,
    canonical_uuid,
    parse_timestamp,
    timestamp_text,
    utc_instant,
    validate_threshold_bps,
)
from stock_probs.briefing_service import (
    BriefingAccessDeniedError,
    BriefingService,
    BriefingServiceError,
    BriefingSourceUnavailableError,
)
from stock_probs.briefing_store import (
    MAX_SNAPSHOT_BYTES,
    BriefingNotFoundError,
    BriefingStoreError,
    BriefingUnavailableError,
)

BRIEFING_EXPORT_FORMAT = "stock-probs-personal-briefing"
BRIEFING_EXPORT_VERSION = 1
MAX_EXPORT_BYTES = MAX_SNAPSHOT_BYTES * 2
MAX_EXPORT_FIELD_BYTES = MAX_SNAPSHOT_BYTES
MAX_REVISION = 2**63 - 1

_SNAPSHOT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "id",
        "generated_at",
        "version",
        "window",
        "baseline_at",
        "observed_as_of",
        "threshold_bps",
        "baseline_anchor_revision",
        "preference_revision",
        "price_changes",
        "outcome_changes",
        "triggered_alerts",
        "due_thesis_reviews",
    }
)
_PAYLOAD_FIELDS: Final[frozenset[str]] = frozenset(
    {
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
)
_COLLECTION_FIELDS: Final[tuple[str, ...]] = (
    "price_changes",
    "outcome_changes",
    "triggered_alerts",
    "due_thesis_reviews",
)
_ITEM_FIELDS: Final[dict[str, frozenset[str]]] = {
    "price_changes": frozenset(
        {
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
    ),
    "outcome_changes": frozenset(
        {
            "resource_ref",
            "source_ref",
            "state",
            "revision",
            "recorded_at",
            "observed_at",
            "correction_of",
        }
    ),
    "triggered_alerts": frozenset({"resource_ref", "symbol", "asset_type", "triggered_at"}),
    "due_thesis_reviews": frozenset({"thesis_ref", "revision", "due_at"}),
}
_PRICE_STATES: Final[frozenset[str]] = frozenset(
    {
        "unavailable",
        "first_observation",
        "insufficient_history",
        "below_threshold",
        "threshold_crossed",
    }
)
_OUTCOME_STATES: Final[frozenset[str]] = frozenset(
    {"observed", "corrected", "unavailable", "incomparable", "manual_review"}
)
_WINDOWS: Final[frozenset[str]] = frozenset(window.value for window in BriefingWindow)

CellSanitizer = Callable[[object], str]


class BriefingExportError(ValueError):
    """Base error for a safe, bounded briefing export failure."""


class BriefingExportAccessError(BriefingExportError):
    """The requested active owner cannot access briefing exports."""


class BriefingExportNotFoundError(BriefingExportError):
    """The selected snapshot is not available to the requested owner."""


class BriefingExportUnavailableError(BriefingExportError):
    """The saved snapshot could not be read or validated safely."""


class BriefingExportTooLargeError(BriefingExportError):
    """The serialized export exceeds its bounded output size."""


class BriefingExportSerializationError(BriefingExportError):
    """A JSON or CSV export could not be serialized safely."""


def build_briefing_export(
    service: BriefingService, owner_user_id: int, snapshot_id: str
) -> dict[str, object]:
    """Project one owner-selected saved snapshot without refreshing any source data."""

    if type(owner_user_id) is not int or owner_user_id < 1:
        raise BriefingExportAccessError("The active owner is unavailable for export.")
    try:
        selected_snapshot_id = canonical_uuid(snapshot_id, "snapshot_id")
    except (BriefingDomainError, TypeError, ValueError) as error:
        raise BriefingExportNotFoundError("The saved briefing is unavailable.") from error
    try:
        snapshot = service.get_snapshot(owner_user_id, selected_snapshot_id)
    except BriefingAccessDeniedError as error:
        raise BriefingExportAccessError("The active owner is unavailable for export.") from error
    except BriefingNotFoundError as error:
        raise BriefingExportNotFoundError("The saved briefing is unavailable.") from error
    except BriefingUnavailableError as error:
        raise BriefingExportAccessError("The active owner is unavailable for export.") from error
    except BriefingSourceUnavailableError as error:
        raise BriefingExportUnavailableError("The saved briefing could not be exported.") from error
    except BriefingServiceError as error:
        raise BriefingExportUnavailableError("The saved briefing could not be exported.") from error
    except BriefingStoreError as error:
        raise BriefingExportUnavailableError("The saved briefing could not be exported.") from error
    except Exception as error:
        raise BriefingExportUnavailableError("The saved briefing could not be exported.") from error

    snapshot_projection = _snapshot_projection(snapshot, owner_user_id)
    result: dict[str, object] = {
        "format": BRIEFING_EXPORT_FORMAT,
        "format_version": BRIEFING_EXPORT_VERSION,
        "snapshot": snapshot_projection,
    }
    serialize_briefing_export_json(result)
    return result


def serialize_briefing_export_json(projection: Mapping[str, object]) -> str:
    """Serialize an export projection with stable key ordering and a strict size bound."""

    try:
        checked = _checked_projection(projection)
        encoded = json.dumps(
            checked,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        _ensure_output_size(encoded)
        return encoded
    except BriefingExportError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise BriefingExportSerializationError("The briefing JSON is invalid.") from error


def serialize_briefing_export_csv(
    projection: Mapping[str, object], *, safe_cell: CellSanitizer
) -> str:
    """Serialize metadata and item rows while applying the shared CSV-cell policy to strings."""

    if not callable(safe_cell):
        raise BriefingExportSerializationError("The CSV safety callback is required.")
    try:
        checked = _checked_projection(projection)
        snapshot = checked["snapshot"]
        if not isinstance(snapshot, dict):
            raise BriefingExportSerializationError("The briefing export is invalid.")
        metadata = {key: value for key, value in snapshot.items() if key not in _COLLECTION_FIELDS}
        metadata["item_counts"] = {
            section: len(snapshot[section])
            for section in _COLLECTION_FIELDS
            if isinstance(snapshot[section], list)
        }
        output = StringIO(newline="")
        writer = csv.writer(output, lineterminator="\r\n")
        writer.writerow(
            tuple(_safe_cell(safe_cell, item) for item in ("section", "record_type", "record_json"))
        )
        writer.writerow(
            (
                _safe_cell(safe_cell, "snapshot"),
                _safe_cell(safe_cell, "metadata"),
                _encode_csv_json(
                    {
                        "format": checked["format"],
                        "format_version": checked["format_version"],
                        "snapshot": metadata,
                    },
                    safe_cell,
                ),
            )
        )
        for section in _COLLECTION_FIELDS:
            records = snapshot[section]
            if not isinstance(records, list):
                raise BriefingExportSerializationError("The briefing export is invalid.")
            for record in records:
                writer.writerow(
                    (
                        _safe_cell(safe_cell, section),
                        _safe_cell(safe_cell, "item"),
                        _encode_csv_json(record, safe_cell),
                    )
                )
        result = output.getvalue()
        _ensure_output_size(result)
        return result
    except BriefingExportError:
        raise
    except (TypeError, ValueError, UnicodeError, csv.Error, RecursionError) as error:
        raise BriefingExportSerializationError("The briefing CSV is invalid.") from error


def _snapshot_projection(snapshot: BriefingSnapshot, owner_user_id: int) -> dict[str, object]:
    """Keep the route-reviewed public fields and preserve the frozen snapshot values."""

    if (
        not isinstance(snapshot, BriefingSnapshot)
        or type(snapshot.owner_user_id) is not int
        or snapshot.owner_user_id != owner_user_id
        or not isinstance(snapshot.window, BriefingWindow)
    ):
        raise BriefingExportUnavailableError("The saved briefing could not be exported.")
    try:
        snapshot_id = canonical_uuid(snapshot.snapshot_id, "snapshot_id")
        generated_at = timestamp_text(utc_instant(snapshot.generated_at, "generated_at"))
        payload = snapshot.payload()
    except (BriefingDomainError, TypeError, ValueError) as error:
        raise BriefingExportUnavailableError("The saved briefing could not be exported.") from error
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_FIELDS:
        raise BriefingExportUnavailableError("The saved briefing could not be exported.")
    if (
        type(payload.get("version")) is not int
        or payload["version"] != 1
        or not isinstance(payload.get("window"), str)
        or payload["window"] not in _WINDOWS
        or payload["window"] != snapshot.window.value
        or type(payload.get("threshold_bps")) is not int
        or payload["threshold_bps"] != snapshot.threshold_bps
    ):
        raise BriefingExportUnavailableError("The saved briefing could not be exported.")
    try:
        validate_threshold_bps(payload["threshold_bps"])
        if payload["baseline_at"] is not None:
            parse_timestamp(payload["baseline_at"], "baseline_at")
        observed_as_of = parse_timestamp(payload["observed_as_of"], "observed_as_of")
        if observed_as_of != utc_instant(snapshot.observed_as_of, "observed_as_of"):
            raise BriefingDomainError("The saved as-of timestamp is inconsistent.")
        if snapshot.baseline_at is None:
            if payload["baseline_at"] is not None:
                raise BriefingDomainError("The saved baseline timestamp is inconsistent.")
        elif parse_timestamp(payload["baseline_at"], "baseline_at") != utc_instant(
            snapshot.baseline_at, "baseline_at"
        ):
            raise BriefingDomainError("The saved baseline timestamp is inconsistent.")
        if generated_at < timestamp_text(observed_as_of):
            raise BriefingDomainError("The saved generation time is invalid.")
        baseline_revision = _revision(snapshot.baseline_anchor_revision)
        preference_revision = _revision(snapshot.preference_revision)
    except (BriefingDomainError, TypeError, ValueError) as error:
        raise BriefingExportUnavailableError("The saved briefing could not be exported.") from error

    result: dict[str, object] = {
        "id": snapshot_id,
        "generated_at": generated_at,
        "version": 1,
        "window": payload["window"],
        "baseline_at": payload["baseline_at"],
        "observed_as_of": payload["observed_as_of"],
        "threshold_bps": payload["threshold_bps"],
        "baseline_anchor_revision": baseline_revision,
        "preference_revision": preference_revision,
    }
    for section in _COLLECTION_FIELDS:
        maximum = MAX_PRICE_OBSERVATIONS if section == "price_changes" else MAX_SOURCE_ITEMS
        result[section] = _public_items(section, payload[section], maximum)
    return result


def _public_items(section: str, value: object, maximum: int) -> list[dict[str, object]]:
    """Validate bounded scalar item rows against a fixed public field schema."""

    fields = _ITEM_FIELDS.get(section)
    if fields is None or not isinstance(value, list) or len(value) > maximum:
        raise BriefingExportUnavailableError("The saved briefing could not be exported.")
    checked: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != fields:
            raise BriefingExportUnavailableError("The saved briefing could not be exported.")
        row: dict[str, object] = {}
        for key in fields:
            field_value = item[key]
            if field_value is not None and type(field_value) not in (str, int, float, bool):
                raise BriefingExportUnavailableError("The saved briefing could not be exported.")
            if type(field_value) is str:
                _check_string(field_value)
            if type(field_value) is int and (field_value < 0 or field_value > MAX_REVISION):
                raise BriefingExportUnavailableError("The saved briefing could not be exported.")
            if type(field_value) is float and not math.isfinite(field_value):
                raise BriefingExportUnavailableError("The saved briefing could not be exported.")
            row[key] = field_value
        if section == "price_changes" and row["state"] not in _PRICE_STATES:
            raise BriefingExportUnavailableError("The saved briefing could not be exported.")
        if section == "outcome_changes" and row["state"] not in _OUTCOME_STATES:
            raise BriefingExportUnavailableError("The saved briefing could not be exported.")
        checked.append(row)
    return checked


def _checked_projection(projection: Mapping[str, object]) -> dict[str, object]:
    """Reapply the exact export allowlist before either serializer emits bytes."""

    if (
        not isinstance(projection, Mapping)
        or set(projection) != {"format", "format_version", "snapshot"}
        or projection.get("format") != BRIEFING_EXPORT_FORMAT
        or type(projection.get("format_version")) is not int
        or projection.get("format_version") != BRIEFING_EXPORT_VERSION
    ):
        raise BriefingExportSerializationError("The briefing export projection is invalid.")
    snapshot = projection.get("snapshot")
    if not isinstance(snapshot, Mapping) or set(snapshot) != _SNAPSHOT_FIELDS:
        raise BriefingExportSerializationError("The briefing export projection is invalid.")
    checked_snapshot: dict[str, object] = {
        key: snapshot[key] for key in _SNAPSHOT_FIELDS if key not in _COLLECTION_FIELDS
    }
    if (
        type(snapshot.get("id")) is not str
        or type(snapshot.get("generated_at")) is not str
        or type(snapshot.get("version")) is not int
        or snapshot.get("version") != 1
        or type(snapshot.get("window")) is not str
        or snapshot.get("window") not in _WINDOWS
        or type(snapshot.get("threshold_bps")) is not int
        or type(snapshot.get("baseline_anchor_revision")) is not int
        or type(snapshot.get("preference_revision")) is not int
    ):
        raise BriefingExportSerializationError("The briefing export projection is invalid.")
    try:
        canonical_uuid(snapshot["id"], "snapshot_id")
        generated_at = parse_timestamp(snapshot["generated_at"], "generated_at")
        baseline_at = (
            parse_timestamp(snapshot["baseline_at"], "baseline_at")
            if snapshot["baseline_at"] is not None
            else None
        )
        observed_as_of = parse_timestamp(snapshot["observed_as_of"], "observed_as_of")
        if generated_at < observed_as_of or (
            baseline_at is not None and baseline_at > observed_as_of
        ):
            raise BriefingDomainError("The saved briefing timestamps are inconsistent.")
        validate_threshold_bps(snapshot["threshold_bps"])
    except (BriefingDomainError, TypeError, ValueError) as error:
        raise BriefingExportSerializationError(
            "The briefing export projection is invalid."
        ) from error
    for field in ("baseline_anchor_revision", "preference_revision"):
        try:
            _revision(snapshot[field])
        except BriefingDomainError as error:
            raise BriefingExportSerializationError(
                "The briefing export projection is invalid."
            ) from error
    for section in _COLLECTION_FIELDS:
        maximum = MAX_PRICE_OBSERVATIONS if section == "price_changes" else MAX_SOURCE_ITEMS
        try:
            checked_snapshot[section] = _public_items(section, snapshot[section], maximum)
        except BriefingExportTooLargeError:
            raise
        except BriefingExportUnavailableError as error:
            raise BriefingExportSerializationError(
                "The briefing export projection is invalid."
            ) from error
    _check_string(BRIEFING_EXPORT_FORMAT)
    return {
        "format": BRIEFING_EXPORT_FORMAT,
        "format_version": BRIEFING_EXPORT_VERSION,
        "snapshot": checked_snapshot,
    }


def _revision(value: object) -> int:
    """Validate a stored preference or visit-anchor revision without bool coercion."""

    if type(value) is not int or value < 0 or value > MAX_REVISION:
        raise BriefingDomainError("A saved briefing revision is invalid.")
    return value


def _check_string(value: str) -> None:
    """Bound UTF-8 fields and reject invalid surrogate text before serialization."""

    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise BriefingExportUnavailableError("The saved briefing could not be exported.") from error
    if size > MAX_EXPORT_FIELD_BYTES:
        raise BriefingExportTooLargeError("The briefing contains a field above the export limit.")


def _ensure_output_size(value: str) -> None:
    """Limit JSON and CSV output after encoding to UTF-8 bytes."""

    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise BriefingExportSerializationError(
            "The briefing export contains invalid text."
        ) from error
    if size > MAX_EXPORT_BYTES:
        raise BriefingExportTooLargeError("The briefing export exceeds the output limit.")


def _safe_cell(safe_cell: CellSanitizer, value: object) -> str:
    """Call and bound the shared spreadsheet-formula sanitizer for one string cell."""

    try:
        sanitized = safe_cell(value)
    except Exception as error:
        raise BriefingExportSerializationError("The CSV safety callback failed.") from error
    if not isinstance(sanitized, str):
        raise BriefingExportSerializationError("The CSV safety callback returned invalid text.")
    _check_string(sanitized)
    return sanitized


def _sanitize_csv_value(value: object, safe_cell: CellSanitizer) -> object:
    """Apply the shared formula policy recursively without prefixing the JSON document."""

    if isinstance(value, str):
        return _safe_cell(safe_cell, value)
    if isinstance(value, list):
        return [_sanitize_csv_value(item, safe_cell) for item in value]
    if isinstance(value, dict):
        sanitized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise BriefingExportSerializationError("The CSV JSON object is invalid.")
            safe_key = _safe_cell(safe_cell, key)
            if safe_key in sanitized:
                raise BriefingExportSerializationError("The CSV JSON object is ambiguous.")
            sanitized[safe_key] = _sanitize_csv_value(item, safe_cell)
        return sanitized
    return value


def _encode_csv_json(value: object, safe_cell: CellSanitizer) -> str:
    """Keep nested JSON valid while sanitizing each contained string, not its opening brace."""

    try:
        encoded = json.dumps(
            _sanitize_csv_value(value, safe_cell),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except BriefingExportError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise BriefingExportSerializationError("The CSV JSON cell is invalid.") from error
    _ensure_output_size(encoded)
    return _safe_cell(safe_cell, encoded)
