"""Score persisted forecast outcomes using only timestamped source evidence."""

from __future__ import annotations

import json
import math
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from stock_probs.domain import FLAT_THRESHOLD

STATES = ("scored", "pending", "unavailable", "disputed", "incomparable")
FIVE_MINUTE_HORIZONS = {"five_min_forward", "completed_5m_to_close"}
SUPPORTED_HORIZONS = FIVE_MINUTE_HORIZONS | {
    "close_to_close",
    "daily_1",
    "weekly_5",
    "monthly_21",
    "quarterly_63",
}
_OUTCOME_COMPARISON_RULE = "close divided by immutable origin price minus one"
_EVIDENCE_ENVELOPE_FIELDS = {
    "outcome_id",
    "owner_user_id",
    "result_id",
    "state",
    "payload_json",
    "collected_at",
}
_REVIEW_FIELDS = {"owner_user_id", "result_id", "revision", "state", "note", "reviewed_at"}
_BAR_FIELDS = {"timestamp", "end", "close", "duration_seconds"}
_COMPARABILITY_SCHEMA = "forecast-outcome-comparability-v1"
_COMPARABILITY_FIELDS = {
    "schema",
    "state",
    "provider",
    "symbol",
    "currency",
    "adjustment_basis",
    "origin",
    "target",
    "corporate_actions",
}
_COMPARISON_ENDPOINT_FIELDS = {"timestamp", "close"}
_CORPORATE_ACTION_FIELDS = {
    "state",
    "provider",
    "symbol",
    "currency",
    "from_timestamp",
    "through_timestamp",
    "events",
}
_UNAVAILABLE_REASONS = {
    "provider_unavailable": "The required source provider was unavailable.",
    "corporate_action_unknown": "Corporate-action comparability could not be established.",
    "series_incomplete": "The comparable origin-to-target series was incomplete.",
}
_FORECAST_ADJUSTMENT_BASIS = "unadjusted provider closes (actions=False, auto_adjust=False)"


class _EvidencePending(ValueError):
    """Signal that an otherwise valid evidence row is not published as of the report clock."""


def _number(value: object, *, positive: bool = False) -> float:
    """Convert a finite numeric field, optionally requiring a positive value."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValueError("Unusable numeric evidence.")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError("Unusable numeric evidence.")
    return result


def _json_positive_number(value: object) -> float:
    """Require a positive JSON number for a persisted source-series endpoint."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("Source endpoint is not a JSON number.")
    return _number(value, positive=True)


def _time(value: object) -> datetime:
    """Parse one persisted ISO timestamp without accepting a naive wall clock."""
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("Missing observation instant.")
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Ambiguous observation instant.")
    return result.astimezone(UTC)


def _positive_id(value: object) -> int:
    """Require the positive integer primary keys used by persisted rows."""
    if type(value) is not int or value <= 0:
        raise ValueError("Recorded row identity is malformed.")
    return value


def _evidence_payload(
    record: dict[str, Any],
    outcome: dict[str, Any],
    evidence: dict[str, Any],
    target: datetime,
    now: datetime,
) -> dict[str, Any]:
    """Validate the immutable evidence envelope and decode its bounded payload."""
    if set(evidence) != _EVIDENCE_ENVELOPE_FIELDS or evidence.get("state") not in {
        "observed",
        "unavailable",
        "incomparable",
    }:
        raise ValueError("Source evidence envelope is incomplete.")
    owner_id = _positive_id(record.get("owner_user_id"))
    result_id = _positive_id(record.get("result_id"))
    outcome_id = _positive_id(outcome.get("id"))
    if (
        _positive_id(outcome.get("result_id")) != result_id
        or _positive_id(evidence.get("owner_user_id")) != owner_id
        or _positive_id(evidence.get("result_id")) != result_id
        or _positive_id(evidence.get("outcome_id")) != outcome_id
    ):
        raise ValueError("Source evidence does not identify this owned outcome.")

    collected_at = _time(evidence.get("collected_at"))
    if collected_at > now:
        raise _EvidencePending("Source evidence is not published as of this report.")
    if collected_at < target:
        raise ValueError("Source evidence predates its recorded target session.")

    encoded_payload = evidence.get("payload_json")
    if not isinstance(encoded_payload, str) or len(encoded_payload.encode("utf-8")) > 262_144:
        raise ValueError("Source payload is missing or too large.")
    payload = json.loads(
        encoded_payload, object_pairs_hook=_unique_object, parse_constant=_reject_json_constant
    )
    if not isinstance(payload, dict):
        raise ValueError("Source payload is malformed.")
    return payload


def _validate_comparability(
    result: dict[str, Any],
    target: datetime,
    provider: str,
    symbol: str,
    currency: str,
    target_close: float,
    comparability: object,
) -> dict[str, Any]:
    """Require matching endpoint and explicit checked-clear action evidence.

    This validates a collector's persisted evidence contract; it does not detect corporate
    actions from prices. A collector must bind both source endpoints and an explicit complete
    action check, or persist the outcome as unavailable/incomparable.
    """
    if not isinstance(comparability, dict) or set(comparability) != _COMPARABILITY_FIELDS:
        raise ValueError("Comparable source series evidence is incomplete.")
    if (
        comparability.get("schema") != _COMPARABILITY_SCHEMA
        or comparability.get("state") != "comparable"
        or comparability.get("provider") != provider
        or comparability.get("symbol") != symbol
        or comparability.get("currency") != currency
        or comparability.get("adjustment_basis") != _FORECAST_ADJUSTMENT_BASIS
        or result.get("adjustment_basis") != _FORECAST_ADJUSTMENT_BASIS
    ):
        raise ValueError("Source series identity or adjustment basis is incompatible.")

    origin_at = _time(result.get("origin_timestamp"))
    origin_price = _number(result.get("origin_price"), positive=True)
    if origin_at >= target:
        raise ValueError("Forecast origin does not precede its target session.")
    origin = comparability.get("origin")
    target_endpoint = comparability.get("target")
    if (
        not isinstance(origin, dict)
        or set(origin) != _COMPARISON_ENDPOINT_FIELDS
        or not isinstance(target_endpoint, dict)
        or set(target_endpoint) != _COMPARISON_ENDPOINT_FIELDS
        or _time(origin.get("timestamp")) != origin_at
        or not math.isclose(
            _json_positive_number(origin.get("close")),
            origin_price,
            rel_tol=0,
            abs_tol=1e-12,
        )
        or _time(target_endpoint.get("timestamp")) != target
        or not math.isclose(
            _json_positive_number(target_endpoint.get("close")),
            target_close,
            rel_tol=0,
            abs_tol=1e-12,
        )
    ):
        raise ValueError("Source series endpoints do not match the immutable forecast outcome.")

    corporate_actions = comparability.get("corporate_actions")
    if (
        not isinstance(corporate_actions, dict)
        or set(corporate_actions) != _CORPORATE_ACTION_FIELDS
        or corporate_actions.get("state") != "checked"
        or corporate_actions.get("provider") != provider
        or corporate_actions.get("symbol") != symbol
        or corporate_actions.get("currency") != currency
        or _time(corporate_actions.get("from_timestamp")) != origin_at
        or _time(corporate_actions.get("through_timestamp")) != target
        or corporate_actions.get("events") != []
    ):
        raise ValueError("Corporate-action status is unknown or incompatible with the series.")
    return {
        "state": "checked_clear",
        "adjustment_basis": _FORECAST_ADJUSTMENT_BASIS,
        "origin_timestamp": origin_at.isoformat(),
        "target_timestamp": target.isoformat(),
    }


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys before evidence fields are interpreted."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate source field.")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    """Reject non-standard JSON numeric constants such as NaN and Infinity."""
    raise ValueError(f"Invalid JSON numeric constant: {value}.")


def _provider_bar_source(
    record: dict[str, Any],
    result: dict[str, Any],
    outcome: dict[str, Any],
    payload: dict[str, Any],
    target: datetime,
) -> dict[str, Any]:
    """Validate provider bar provenance and its exact comparable source series."""
    if set(payload) != {"method", "provider", "symbol", "currency", "bar", "comparability"}:
        raise ValueError("Provider-bar source payload is malformed.")
    if payload.get("method") != "provider_bar":
        raise ValueError("Unsupported automatic source method.")

    provenance = result.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("Forecast source identity is unavailable.")
    identity = provenance.get("instrument_identity")
    if not isinstance(identity, dict):
        raise ValueError("Forecast source identity is unavailable.")
    symbol = result.get("canonical_symbol")
    provider = provenance.get("source")
    currency = result.get("currency")
    if (
        not isinstance(symbol, str)
        or not symbol
        or len(symbol) > 80
        or record.get("symbol") != symbol
        or identity.get("canonical_symbol") != symbol
        or payload.get("symbol") != symbol
        or not isinstance(provider, str)
        or not provider
        or len(provider) > 80
        or identity.get("provider") != provider
        or payload.get("provider") != provider
        or not isinstance(currency, str)
        or not currency
        or len(currency) > 12
        or identity.get("currency") != currency
        or payload.get("currency") != currency
    ):
        raise ValueError("Provider source does not match the recorded forecast identity.")

    bar = payload.get("bar")
    if not isinstance(bar, dict) or set(bar) != _BAR_FIELDS:
        raise ValueError("Provider bar is malformed.")
    start = _time(bar.get("timestamp"))
    end = _time(bar.get("end"))
    raw_close = bar.get("close")
    if isinstance(raw_close, bool) or not isinstance(raw_close, int | float):
        raise ValueError("Provider bar close is not a JSON number.")
    close = _number(raw_close, positive=True)
    duration = bar.get("duration_seconds")
    expected_duration = 300 if result.get("horizon") in FIVE_MINUTE_HORIZONS else 0
    if type(duration) is not int or duration != expected_duration:
        raise ValueError("Provider bar interval does not support this forecast horizon.")
    if start + timedelta(seconds=duration) != end or end != target:
        raise ValueError("Provider bar does not end at the recorded target session.")
    observed_close = _number(outcome.get("observed_close"), positive=True)
    if not math.isclose(close, observed_close, abs_tol=1e-12):
        raise ValueError("Provider bar does not match the persisted outcome close.")
    comparability = _validate_comparability(
        result,
        target,
        provider,
        symbol,
        currency,
        close,
        payload.get("comparability"),
    )
    return {
        "method": "provider_bar",
        "provider": provider,
        "symbol": symbol,
        "currency": currency,
        "bar_timestamp": start.isoformat(),
        "bar_end": end.isoformat(),
        "bar_close": close,
        "bar_duration_seconds": duration,
        "comparability": comparability,
    }


def _manual_review_source(
    record: dict[str, Any],
    result: dict[str, Any],
    outcome: dict[str, Any],
    review: dict[str, Any],
    payload: dict[str, Any],
    created_at: datetime,
    target: datetime,
    now: datetime,
) -> dict[str, Any]:
    """Validate a confirmed manual review and its independently bound comparable endpoints."""
    if set(review) != _REVIEW_FIELDS or review.get("state") != "confirmed":
        raise ValueError("A confirmed outcome review is required.")
    owner_id = _positive_id(record.get("owner_user_id"))
    result_id = _positive_id(record.get("result_id"))
    if (
        _positive_id(review.get("owner_user_id")) != owner_id
        or _positive_id(review.get("result_id")) != result_id
        or _positive_id(outcome.get("result_id")) != result_id
        or type(review.get("revision")) is not int
        or review["revision"] <= 0
        or not isinstance(review.get("note"), str)
        or len(review["note"].encode("utf-8")) > 2048
    ):
        raise ValueError("Manual review does not identify this owned forecast outcome.")
    reviewed_at = _time(review.get("reviewed_at"))
    if reviewed_at > now:
        raise _EvidencePending("Manual review is not published as of this report.")
    if reviewed_at < created_at:
        raise ValueError("Manual review predates the published outcome.")
    if (
        set(payload) != {"method", "review_revision", "comparability"}
        or payload.get("method") != "manual_review"
        or type(payload.get("review_revision")) is not int
        or payload.get("review_revision") != review["revision"]
    ):
        raise ValueError("Manual source evidence does not bind the confirmed review revision.")
    provenance = result.get("provenance")
    identity = provenance.get("instrument_identity") if isinstance(provenance, dict) else None
    provider = provenance.get("source") if isinstance(provenance, dict) else None
    symbol = result.get("canonical_symbol")
    currency = result.get("currency")
    if not isinstance(identity, dict):
        raise ValueError("Forecast source identity is unavailable.")
    if (
        not isinstance(provider, str)
        or not 1 <= len(provider) <= 80
        or not isinstance(symbol, str)
        or not 1 <= len(symbol) <= 80
        or not isinstance(currency, str)
        or not 1 <= len(currency) <= 12
        or identity.get("provider") != provider
        or identity.get("canonical_symbol") != symbol
        or identity.get("currency") != currency
        or record.get("symbol") != symbol
    ):
        raise ValueError("Manual source identity does not match the forecast.")
    comparability = _validate_comparability(
        result,
        target,
        provider,
        symbol,
        currency,
        _number(outcome.get("observed_close"), positive=True),
        payload.get("comparability"),
    )
    return {
        "method": "manual_review",
        "review_revision": review["revision"],
        "reviewed_at": reviewed_at.isoformat(),
        "comparability": comparability,
    }


def score_record(record: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Score one owner-scoped immutable forecast and its latest published outcome.

    Provider evidence must be the persisted sidecar row linked by outcome, result, and owner IDs.
    Its exact domain ``Bar`` payload must match forecast identity, interval, target session, and
    outcome price. Both provider and confirmed five-minute manual sources also require the
    versioned origin/target series record and an explicit checked-empty corporate-action interval;
    this scorer validates that record and never infers action absence from prices. The caller
    remains responsible for deriving trusted source evidence and selecting the latest owner-scoped
    outcome and review rows.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Report time must identify an instant.")
    result, outcome = record["forecast"], record.get("outcome")
    provenance = result.get("provenance") if isinstance(result, dict) else None
    model = provenance.get("model_version") if isinstance(provenance, dict) else None
    model = model or (result.get("model_version") if isinstance(result, dict) else None)
    horizon = result.get("horizon") if isinstance(result, dict) else None
    output = {
        "result_id": record["result_id"],
        "symbol": record["symbol"],
        "horizon": horizon if isinstance(horizon, str) and len(horizon) <= 80 else "unknown",
        "model_version": model if isinstance(model, str) and len(model) <= 80 else "unknown",
        "five_minute": horizon in FIVE_MINUTE_HORIZONS,
        "target_timestamp": result.get("target_timestamp") if isinstance(result, dict) else None,
        "state": "incomparable",
        "reason": "Recorded forecast inputs are incomplete.",
        "predicted_class": None,
        "observed_class": None,
        "direction_correct": None,
        "interval_80_covered": None,
        "observed_return": None,
        "interval_80_price": None,
        "outcome": outcome,
        "source": None,
    }
    try:
        if (
            not isinstance(result, dict)
            or horizon not in SUPPORTED_HORIZONS
            or not isinstance(model, str)
            or not 1 <= len(model) <= 80
        ):
            return output
        target = _time(result.get("target_timestamp"))
        availability = result.get("availability", "available")
        if availability == "unavailable":
            return {**output, "state": "unavailable", "reason": "Forecast was unavailable."}
        if availability != "available":
            return {**output, "reason": "Forecast availability is malformed."}
        current = now.astimezone(UTC)
        if target > current or outcome is None:
            return {**output, "state": "pending", "reason": "Target or outcome still pending."}
        if not isinstance(outcome, dict):
            return output

        created_at = _time(outcome.get("created_at"))
        observed_at = _time(outcome.get("observed_at"))
        if created_at > current:
            return {**output, "state": "pending", "reason": "Outcome is not yet published."}
        if created_at < observed_at or observed_at != target:
            return {
                **output,
                "reason": "Published observation does not match the exact target session.",
            }
        _positive_id(outcome.get("id"))
        if _positive_id(outcome.get("result_id")) != _positive_id(record.get("result_id")):
            return output
        if outcome.get("state") == "unavailable":
            return {**output, "state": "unavailable", "reason": "Observation unavailable."}
        if outcome.get("state") == "provisional":
            return {
                **output,
                "state": "disputed",
                "reason": "Provisional, unconfirmed observation.",
            }
        if outcome.get("state") not in {"observed", "corrected"}:
            return output

        evidence = record.get("evidence")
        evidence_payload: dict[str, Any] | None = None
        if isinstance(evidence, dict):
            evidence_payload = _evidence_payload(record, outcome, evidence, target, current)
            evidence_state = evidence.get("state")
            if evidence_state == "unavailable":
                if (
                    set(evidence_payload) != {"reason_code"}
                    or evidence_payload.get("reason_code") not in _UNAVAILABLE_REASONS
                ):
                    return {
                        **output,
                        "reason": "Unavailable source evidence has no recognized reason.",
                    }
                reason_code = evidence_payload["reason_code"]
                return {
                    **output,
                    "state": "unavailable",
                    "reason": _UNAVAILABLE_REASONS[reason_code],
                }
            if evidence_state == "incomparable":
                return {
                    **output,
                    "reason": "Source evidence was recorded as incomparable.",
                }
            if evidence_state != "observed":
                return output

        review = record.get("review")
        if isinstance(review, dict) and review.get("state") == "disputed":
            if set(review) != _REVIEW_FIELDS:
                return output
            if (
                _positive_id(review.get("owner_user_id"))
                != _positive_id(record.get("owner_user_id"))
                or _positive_id(review.get("result_id")) != _positive_id(record.get("result_id"))
                or type(review.get("revision")) is not int
                or review["revision"] <= 0
                or not isinstance(review.get("note"), str)
                or len(review["note"].encode("utf-8")) > 2048
            ):
                return output
            reviewed_at = _time(review.get("reviewed_at"))
            if reviewed_at > current:
                return {**output, "state": "pending", "reason": "Review is not yet published."}
            if reviewed_at >= created_at:
                return {**output, "state": "disputed", "reason": "Observation under review."}
            return output

        observed = _number(outcome.get("observed_close"), positive=True)
        origin = _number(result["origin_price"], positive=True)
        observed_return = observed / origin - 1.0
        stored_return = _number(outcome.get("observed_return"))
        if (
            not math.isfinite(observed_return)
            or not math.isclose(stored_return, observed_return, rel_tol=0, abs_tol=1e-12)
            or outcome.get("comparison_rule") != _OUTCOME_COMPARISON_RULE
        ):
            return {**output, "reason": "Persisted outcome calculation is inconsistent."}

        if evidence_payload is not None and evidence_payload.get("method") == "provider_bar":
            source = _provider_bar_source(record, result, outcome, evidence_payload, target)
        elif (
            evidence_payload is not None
            and evidence_payload.get("method") == "manual_review"
            and horizon in FIVE_MINUTE_HORIZONS
            and isinstance(review, dict)
        ):
            source = _manual_review_source(
                record,
                result,
                outcome,
                review,
                evidence_payload,
                created_at,
                target,
                current,
            )
        else:
            return {**output, "reason": "Required source evidence is missing or malformed."}

        probabilities = result["direction_probabilities"]
        values = {
            "down": _number(probabilities["down"]),
            "unchanged": _number(probabilities.get("unchanged", probabilities.get("flat"))),
            "up": _number(probabilities["up"]),
        }
        if any(not 0 <= value <= 1 for value in values.values()) or not math.isclose(
            sum(values.values()), 1, abs_tol=1e-8
        ):
            return {**output, "reason": "Probability classes are incomparable."}
        winners = [name for name, value in values.items() if value == max(values.values())]
        predicted = winners[0] if len(winners) == 1 else None
        intervals = [row for row in result["magnitude_intervals"] if _number(row["level"]) == 0.8]
        if len(intervals) != 1:
            return {**output, "reason": "A unique recorded 80% price interval is unavailable."}
        low, high = (
            _number(intervals[0]["price"]["low"], positive=True),
            _number(intervals[0]["price"]["high"], positive=True),
        )
        if low > high:
            return output
        return {
            **output,
            "state": "scored",
            "reason": "Recorded outcome; inclusive interval boundaries.",
            "predicted_class": predicted,
            "observed_class": (
                "down"
                if observed_return < -FLAT_THRESHOLD
                else ("up" if observed_return > FLAT_THRESHOLD else "unchanged")
            ),
            "direction_correct": predicted
            == (
                "down"
                if observed_return < -FLAT_THRESHOLD
                else ("up" if observed_return > FLAT_THRESHOLD else "unchanged")
            )
            if predicted is not None
            else None,
            "interval_80_covered": low <= observed <= high,
            "observed_return": observed_return,
            "interval_80_price": {"low": low, "high": high},
            "source": source,
        }
    except _EvidencePending as error:
        return {**output, "state": "pending", "reason": str(error)}
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError, json.JSONDecodeError):
        return output


def summarize(records: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """Expose denominators and per-model/horizon groups; no walk-forward values are consumed."""
    if len(records) > 5000 or now.tzinfo is None:
        raise ValueError("Report input is unbounded or its clock is ambiguous.")
    identifiers = [record["result_id"] for record in records]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Report inputs must contain unique recorded forecast results.")
    rows = [score_record(record, now) for record in records]
    counts = Counter(row["state"] for row in rows)
    groups = []
    keys = sorted({(row["horizon"], row["model_version"]) for row in rows})
    for horizon, model in keys:
        selected = [
            row for row in rows if (row["horizon"], row["model_version"]) == (horizon, model)
        ]
        directions = [
            row["direction_correct"] for row in selected if row["direction_correct"] is not None
        ]
        intervals = [
            row["interval_80_covered"] for row in selected if row["interval_80_covered"] is not None
        ]
        groups.append(
            {
                "horizon": horizon,
                "model_version": model,
                "five_minute": horizon in FIVE_MINUTE_HORIZONS,
                "counts": {
                    state: sum(row["state"] == state for row in selected) for state in STATES
                },
                "direction": {
                    "correct": sum(directions),
                    "denominator": len(directions),
                    "accuracy": sum(directions) / len(directions) if directions else None,
                },
                "interval_80": {
                    "covered": sum(intervals),
                    "denominator": len(intervals),
                    "coverage": sum(intervals) / len(intervals) if intervals else None,
                },
                "tied_predictions": sum(
                    row["state"] == "scored" and row["predicted_class"] is None for row in selected
                ),
            }
        )
    return {
        "as_of": now.astimezone(UTC).isoformat(),
        "counts": {state: counts[state] for state in STATES},
        "groups": groups,
        "items": rows,
        "label": "Recorded forecast outcomes; separate from historical walk-forward evaluation",
        "sample_limit": (
            "Small samples do not establish predictive reliability. "
            "Repeated submissions sharing an immutable result count once."
        ),
        "direction_boundaries": {
            "down": f"return < {-FLAT_THRESHOLD}",
            "unchanged": f"absolute return <= {FLAT_THRESHOLD}",
            "up": f"return > {FLAT_THRESHOLD}",
        },
    }
