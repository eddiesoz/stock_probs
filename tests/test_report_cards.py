"""Persisted report-card scoring uses database row and provider-domain contracts."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from stock_probs.report_cards import score_record, summarize

NOW = datetime(2026, 10, 12, 22, tzinfo=UTC)
TARGET = datetime(2026, 10, 12, 20, tzinfo=UTC)
OWNER_ID = 42
PROVIDER = "FixtureMarketProvider"
ADJUSTMENT_BASIS = "unadjusted provider closes (actions=False, auto_adjust=False)"


def record(identifier: int = 1, close: float = 105, horizon: str = "daily_1") -> dict[str, object]:
    """Build one owner-scoped result, outcome and collected-evidence row."""
    duration = 300 if horizon in {"five_min_forward", "completed_5m_to_close"} else 0
    start = TARGET - timedelta(seconds=duration)
    origin = TARGET - timedelta(minutes=5 if duration else 1440)
    forecast = {
        "horizon": horizon,
        "canonical_symbol": "SPY",
        "currency": "USD",
        "origin_timestamp": origin.isoformat(),
        "model": {"version": "recorded-test-v1"},
        "provenance": {
            "model_version": "recorded-test-v1",
            "source": PROVIDER,
            "instrument_identity": {
                "canonical_symbol": "SPY",
                "currency": "USD",
                "provider": PROVIDER,
            },
        },
        "origin_price": 100,
        "adjustment_basis": ADJUSTMENT_BASIS,
        "target_timestamp": TARGET.isoformat(),
        "direction_probabilities": {"down": 0.1, "unchanged": 0.2, "up": 0.7},
        "magnitude_intervals": [{"level": 0.8, "price": {"low": 90, "high": 110}}],
        "evaluation": {"direction_accuracy": 1, "coverage": 1},
    }
    outcome_id = 1000 + identifier
    outcome = {
        "id": outcome_id,
        "result_id": identifier,
        "observed_close": close,
        "observed_return": close / 100 - 1,
        "observed_at": TARGET.isoformat(),
        "comparison_rule": "close divided by immutable origin price minus one",
        "state": "observed",
        "note": "",
        "created_at": (TARGET + timedelta(seconds=1)).isoformat(),
    }
    payload = {
        "method": "provider_bar",
        "provider": PROVIDER,
        "symbol": "SPY",
        "currency": "USD",
        "bar": {
            "timestamp": start.isoformat(),
            "end": TARGET.isoformat(),
            "close": close,
            "duration_seconds": duration,
        },
        "comparability": {
            "schema": "forecast-outcome-comparability-v1",
            "state": "comparable",
            "provider": PROVIDER,
            "symbol": "SPY",
            "currency": "USD",
            "adjustment_basis": ADJUSTMENT_BASIS,
            "origin": {"timestamp": origin.isoformat(), "close": 100},
            "target": {"timestamp": TARGET.isoformat(), "close": close},
            "corporate_actions": {
                "state": "checked",
                "provider": PROVIDER,
                "symbol": "SPY",
                "currency": "USD",
                "from_timestamp": origin.isoformat(),
                "through_timestamp": TARGET.isoformat(),
                "events": [],
            },
        },
    }
    evidence = {
        "outcome_id": outcome_id,
        "owner_user_id": OWNER_ID,
        "result_id": identifier,
        "state": "observed",
        "payload_json": json.dumps(payload, sort_keys=True, separators=(",", ":")),
        "collected_at": (TARGET + timedelta(seconds=2)).isoformat(),
    }
    return {
        "owner_user_id": OWNER_ID,
        "result_id": identifier,
        "symbol": "SPY",
        "forecast": forecast,
        "outcome": outcome,
        "evidence": evidence,
    }


def review(row: dict[str, object], *, state: str = "confirmed") -> dict[str, object]:
    """Build the persisted review-table row for a recorded forecast result."""
    return {
        "owner_user_id": row["owner_user_id"],
        "result_id": row["result_id"],
        "revision": 1,
        "state": state,
        "note": "Outcome checked against the recorded target close.",
        "reviewed_at": (TARGET + timedelta(seconds=3)).isoformat(),
    }


def _payload(row: dict[str, object]) -> dict[str, object]:
    """Decode the bounded source payload from its persisted sidecar row."""
    return json.loads(row["evidence"]["payload_json"])


def _set_payload(row: dict[str, object], payload: dict[str, object]) -> None:
    """Store deterministic JSON in a copied sidecar fixture."""
    row["evidence"]["payload_json"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _manual_evidence(row: dict[str, object]) -> dict[str, object]:
    """Build a manual source sidecar bound to the row's checked comparison endpoints."""
    provider_payload = _payload(row)
    return {
        "outcome_id": row["outcome"]["id"],
        "owner_user_id": row["owner_user_id"],
        "result_id": row["result_id"],
        "state": "observed",
        "payload_json": json.dumps(
            {
                "method": "manual_review",
                "review_revision": 1,
                "comparability": provider_payload["comparability"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        "collected_at": (TARGET + timedelta(seconds=4)).isoformat(),
    }


def test_direction_and_inclusive_interval_denominators_ignore_backtest_values() -> None:
    """Persisted evidence, not forecast evaluation metadata, drives both denominators."""
    rows = [record(1, 90), record(2, 110), record(3, 111)]
    original = deepcopy(rows)
    report = summarize(rows, NOW)
    group = report["groups"][0]
    assert report["counts"]["scored"] == 3
    assert group["direction"] == {"correct": 2, "denominator": 3, "accuracy": 2 / 3}
    assert group["interval_80"] == {"covered": 2, "denominator": 3, "coverage": 2 / 3}
    assert rows == original
    assert report["items"][0]["model_version"] == "recorded-test-v1"


def test_append_correction_scores_its_new_linked_observation_not_the_prior_row() -> None:
    """A linked correction is scored from its own appended outcome and evidence rows."""
    row = record(close=105)
    row["outcome"].update(
        id=2001,
        observed_close=110,
        observed_return=0.1,
        state="corrected",
        created_at=(TARGET + timedelta(minutes=1)).isoformat(),
    )
    row["evidence"].update(
        outcome_id=2001,
        collected_at=(TARGET + timedelta(minutes=2)).isoformat(),
    )
    payload = _payload(row)
    payload["bar"]["close"] = 110
    payload["comparability"]["target"]["close"] = 110
    _set_payload(row, payload)
    scored = score_record(row, NOW)
    assert scored["state"] == "scored"
    assert scored["outcome"]["id"] == 2001
    assert scored["observed_return"] == pytest.approx(0.1)
    assert scored["interval_80_covered"] is True


def test_tied_predictions_are_excluded_only_from_direction_accuracy() -> None:
    """A tied top class remains interval evidence without a direction contribution."""
    tied = record()
    tied["forecast"]["direction_probabilities"] = {"down": 0.5, "unchanged": 0, "up": 0.5}
    report = summarize([tied], NOW)
    group = report["groups"][0]
    assert group["tied_predictions"] == 1
    assert group["direction"]["denominator"] == 0 and group["direction"]["accuracy"] is None
    assert group["interval_80"]["denominator"] == 1 and group["interval_80"]["coverage"] == 1


@pytest.mark.parametrize("close", [99.9, 100, 100.1])
def test_existing_unchanged_boundaries_remain_inclusive(close: float) -> None:
    """The established inclusive flat-return boundary remains unchanged."""
    row = record(close=close)
    row["forecast"]["direction_probabilities"] = {"down": 0.1, "unchanged": 0.8, "up": 0.1}
    scored = score_record(row, NOW)
    assert scored["observed_class"] == "unchanged" and scored["direction_correct"] is True


def test_daily_result_requires_linked_provider_bar_and_reports_its_provenance() -> None:
    """A daily close scores only with an identity-matched target-session provider bar."""
    row = record()
    scored = score_record(row, NOW)
    assert scored["state"] == "scored"
    assert scored["source"] == {
        "method": "provider_bar",
        "provider": PROVIDER,
        "symbol": "SPY",
        "currency": "USD",
        "bar_timestamp": TARGET.isoformat(),
        "bar_end": TARGET.isoformat(),
        "bar_close": 105.0,
        "bar_duration_seconds": 0,
        "comparability": {
            "state": "checked_clear",
            "adjustment_basis": ADJUSTMENT_BASIS,
            "origin_timestamp": row["forecast"]["origin_timestamp"],
            "target_timestamp": TARGET.isoformat(),
        },
    }


def test_non_object_provider_provenance_fails_closed_without_scoring() -> None:
    """Malformed provenance keeps the saved forecast incomparable rather than raising."""
    row = record()
    row["forecast"]["provenance"] = ["unexpected", "shape"]

    scored = score_record(row, NOW)

    assert scored["state"] == "incomparable"
    assert scored["source"] is None
    assert scored["direction_correct"] is None
    assert scored["interval_80_covered"] is None


def test_missing_or_arbitrary_source_never_becomes_implicit_manual_evidence() -> None:
    """Absent, free-form and malformed payloads never count as accepted source evidence."""
    missing = record()
    missing["evidence"] = None
    arbitrary = record(2)
    arbitrary["evidence"]["payload_json"] = json.dumps({"method": "manual recorded observation"})
    malformed = record(3)
    malformed["evidence"]["payload_json"] = "{broken"
    rows = [missing, arbitrary, malformed]
    report = summarize(rows, NOW)
    assert report["counts"]["incomparable"] == 3
    assert all(item["source"] is None for item in report["items"])
    assert all(item["direction_correct"] is None for item in report["items"])


@pytest.mark.parametrize(
    ("mutation", "value"),
    [
        ("provider", "OtherProvider"),
        ("symbol", "QQQ"),
        ("currency", "CAD"),
        ("bar_end", (TARGET + timedelta(minutes=1)).isoformat()),
        ("bar_duration", 60),
        ("bar_close", 106),
    ],
)
def test_automatic_evidence_must_match_forecast_identity_and_exact_target(
    mutation: str, value: object
) -> None:
    """Provider evidence must match the forecast identity, price, and target boundary."""
    row = record()
    payload = _payload(row)
    if mutation in {"provider", "symbol", "currency"}:
        payload[mutation] = value
    elif mutation == "bar_end":
        payload["bar"]["end"] = value
    elif mutation == "bar_duration":
        payload["bar"]["duration_seconds"] = value
    else:
        payload["bar"]["close"] = value
    _set_payload(row, payload)
    assert score_record(row, NOW)["state"] == "incomparable"


def test_evidence_row_must_reference_the_exact_published_outcome_and_owner() -> None:
    """A sidecar row linked to another owner or outcome cannot support a score."""
    row = record()
    row["evidence"]["outcome_id"] += 1
    assert score_record(row, NOW)["state"] == "incomparable"
    row = record()
    row["evidence"]["owner_user_id"] += 1
    assert score_record(row, NOW)["state"] == "incomparable"


def test_explicit_unavailable_sidecar_projects_unavailable_without_scoring() -> None:
    """An unavailable linked source has its own bucket and cannot enter either denominator."""
    row = record()
    row["evidence"].update(
        state="unavailable",
        payload_json=json.dumps({"reason_code": "corporate_action_unknown"}),
    )
    item = score_record(row, NOW)
    report = summarize([row], NOW)
    assert item["state"] == "unavailable"
    assert item["reason"] == "Corporate-action comparability could not be established."
    assert item["direction_correct"] is None and item["interval_80_covered"] is None
    assert report["counts"]["unavailable"] == 1
    assert report["counts"]["incomparable"] == 0
    assert report["groups"][0]["direction"]["denominator"] == 0
    assert report["groups"][0]["interval_80"]["denominator"] == 0


def test_unavailable_sidecar_requires_a_bounded_recognized_reason_code() -> None:
    """Malformed unavailable metadata cannot conceal a source-contract failure."""
    row = record()
    row["evidence"].update(
        state="unavailable",
        payload_json=json.dumps({"reason_code": "some guessed cause"}),
    )
    item = score_record(row, NOW)
    assert item["state"] == "incomparable"
    assert item["direction_correct"] is None and item["interval_80_covered"] is None


def test_outcome_published_after_report_clock_is_pending() -> None:
    """Historical report clocks cannot include a later-published outcome."""
    row = record()
    row["outcome"]["created_at"] = (NOW + timedelta(seconds=1)).isoformat()
    report = summarize([row], NOW)
    assert report["counts"]["pending"] == 1
    assert report["groups"][0]["direction"]["denominator"] == 0


def test_future_evidence_publication_is_pending_even_when_the_bar_is_valid() -> None:
    """A valid bar collected after the report clock is not available to that report."""
    row = record()
    row["evidence"]["collected_at"] = (NOW + timedelta(seconds=1)).isoformat()
    assert score_record(row, NOW)["state"] == "pending"


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "unknown_action_state",
        "split_event",
        "action_identity_mismatch",
        "adjustment_mismatch",
        "origin_mismatch",
        "target_mismatch",
        "action_interval_mismatch",
    ],
)
def test_corporate_action_or_series_uncertainty_never_counts_as_a_success(mutation: str) -> None:
    """Only matching endpoint and explicit checked-empty action evidence may be scored."""
    row = record(close=50)
    payload = _payload(row)
    comparison = payload["comparability"]
    if mutation == "missing":
        del payload["comparability"]
    elif mutation == "unknown_action_state":
        comparison["corporate_actions"]["state"] = "unknown"
    elif mutation == "split_event":
        comparison["corporate_actions"]["events"] = [{"kind": "split", "ratio": 2}]
    elif mutation == "action_identity_mismatch":
        comparison["corporate_actions"]["provider"] = "OtherProvider"
    elif mutation == "adjustment_mismatch":
        comparison["adjustment_basis"] = "adjusted provider closes"
    elif mutation == "origin_mismatch":
        comparison["origin"]["close"] = 50
    elif mutation == "target_mismatch":
        comparison["target"]["close"] = 100
    else:
        comparison["corporate_actions"]["through_timestamp"] = (
            TARGET - timedelta(minutes=1)
        ).isoformat()
    _set_payload(row, payload)
    item = score_record(row, NOW)
    report = summarize([row], NOW)
    assert item["state"] == "incomparable"
    assert item["direction_correct"] is None and item["interval_80_covered"] is None
    assert report["groups"][0]["direction"]["denominator"] == 0
    assert report["groups"][0]["interval_80"]["denominator"] == 0


def test_checked_no_action_and_matching_adjustment_basis_are_comparable() -> None:
    """Explicitly checked action coverage and matching raw-price bases allow scoring."""
    row = record(close=105)
    item = score_record(row, NOW)
    assert item["state"] == "scored"
    assert item["source"]["comparability"] == {
        "state": "checked_clear",
        "adjustment_basis": ADJUSTMENT_BASIS,
        "origin_timestamp": row["forecast"]["origin_timestamp"],
        "target_timestamp": TARGET.isoformat(),
    }


def test_observation_timestamp_must_be_the_recorded_target_session_close() -> None:
    """A nearby observation is incomparable unless it matches the exact forecast target."""
    row = record()
    row["outcome"]["observed_at"] = (TARGET + timedelta(seconds=1)).isoformat()
    assert score_record(row, NOW)["state"] == "incomparable"


def test_five_minute_provider_observation_requires_a_completed_five_minute_bar() -> None:
    """Five-minute automatic evidence must use a completed 300-second bar."""
    row = record(horizon="completed_5m_to_close")
    assert score_record(row, NOW)["state"] == "scored"
    assert score_record(row, NOW)["source"]["bar_duration_seconds"] == 300
    payload = _payload(row)
    payload["bar"]["duration_seconds"] = 0
    payload["bar"]["timestamp"] = TARGET.isoformat()
    _set_payload(row, payload)
    assert score_record(row, NOW)["state"] == "incomparable"


def test_model_horizon_groups_and_duplicate_immutable_results_are_preserved() -> None:
    """Model/horizon grouping stays explicit and repeated immutable result IDs are rejected."""
    daily = record(1)
    intraday = record(2, horizon="five_min_forward")
    report = summarize([daily, intraday], NOW)
    assert {(group["horizon"], group["model_version"]) for group in report["groups"]} == {
        ("daily_1", "recorded-test-v1"),
        ("five_min_forward", "recorded-test-v1"),
    }
    with pytest.raises(ValueError, match="unique"):
        summarize([daily, daily], NOW)


def test_five_minute_manual_outcome_requires_explicit_confirmed_persisted_review() -> None:
    """A five-minute manual score requires a same-owner, confirmed persisted review."""
    row = record(horizon="five_min_forward")
    row["review"] = review(row)
    row["evidence"] = _manual_evidence(row)
    scored = score_record(row, NOW)
    assert scored["state"] == "scored"
    assert scored["source"] == {
        "method": "manual_review",
        "review_revision": 1,
        "reviewed_at": row["review"]["reviewed_at"],
        "comparability": {
            "state": "checked_clear",
            "adjustment_basis": ADJUSTMENT_BASIS,
            "origin_timestamp": row["forecast"]["origin_timestamp"],
            "target_timestamp": TARGET.isoformat(),
        },
    }
    row["review"]["owner_user_id"] += 1
    assert score_record(row, NOW)["state"] == "incomparable"


def test_five_minute_outcome_without_provider_evidence_or_review_is_incomparable() -> None:
    """A five-minute outcome without either supported bars or review cannot score."""
    row = record(horizon="five_min_forward")
    row["evidence"] = None
    assert score_record(row, NOW)["state"] == "incomparable"


def test_manual_review_after_report_clock_does_not_backdate_a_five_minute_score() -> None:
    """A future confirmation cannot leak into an earlier report-card snapshot."""
    row = record(horizon="five_min_forward")
    row["review"] = review(row)
    row["evidence"] = _manual_evidence(row)
    row["review"]["reviewed_at"] = (NOW + timedelta(seconds=1)).isoformat()
    assert score_record(row, NOW)["state"] == "pending"


def test_deeply_nested_evidence_json_is_incomparable_without_echoing_payload() -> None:
    """A bounded but deeply nested source document fails closed without escaping the scorer."""
    row = record(horizon="five_min_forward")
    row["review"] = review(row)
    row["evidence"] = _manual_evidence(row)
    nested = "[" * 2207 + "0" + "]" * 2207
    assert len(nested.encode("utf-8")) < 262_144
    row["evidence"]["payload_json"] = nested

    result = score_record(row, NOW)

    assert result["state"] == "incomparable"
    assert result["direction_correct"] is None
    assert result["interval_80_covered"] is None
    assert result["source"] is None
    assert nested not in json.dumps(result)


def test_manual_review_rejects_unknown_actions_and_excludes_them_from_denominators() -> None:
    """A human confirmation cannot make a discontinuous or unknown source comparable."""
    valid = record(1, horizon="five_min_forward")
    valid["review"] = review(valid)
    valid["evidence"] = _manual_evidence(valid)
    invalid = record(2, close=50, horizon="five_min_forward")
    invalid["review"] = review(invalid)
    invalid["evidence"] = _manual_evidence(invalid)
    payload = json.loads(invalid["evidence"]["payload_json"])
    payload["comparability"]["corporate_actions"]["events"] = [{"kind": "unknown"}]
    invalid["evidence"]["payload_json"] = json.dumps(payload)
    mismatched_review = record(3, horizon="five_min_forward")
    mismatched_review["review"] = review(mismatched_review)
    mismatched_review["evidence"] = _manual_evidence(mismatched_review)
    payload = json.loads(mismatched_review["evidence"]["payload_json"])
    payload["review_revision"] = 2
    mismatched_review["evidence"]["payload_json"] = json.dumps(payload)
    report = summarize([valid, invalid, mismatched_review], NOW)
    assert report["counts"]["scored"] == 1
    assert report["counts"]["incomparable"] == 2
    assert report["groups"][0]["direction"]["denominator"] == 1
    assert report["groups"][0]["interval_80"]["denominator"] == 1


def test_unavailable_forecasts_have_the_unavailable_state_and_denominator() -> None:
    """An unavailable forecast is counted as unavailable rather than incomparable."""
    row = record()
    row["forecast"]["availability"] = "unavailable"
    report = summarize([row], NOW)
    assert report["counts"]["unavailable"] == 1
    assert report["counts"]["incomparable"] == 0
    assert report["groups"][0]["interval_80"]["denominator"] == 0
    malformed = record(2)
    malformed["forecast"]["availability"] = "unknown"
    assert score_record(malformed, NOW)["state"] == "incomparable"


def test_missing_provisional_incompatible_and_disputed_counts_are_separate() -> None:
    """Outcome, source, and review states retain separate report-card counts."""
    pending = record(1)
    pending["outcome"] = None
    missing = record(2)
    missing["outcome"].update(state="unavailable", observed_close=None, observed_return=None)
    missing["evidence"] = None
    provisional = record(3)
    provisional["outcome"]["state"] = "provisional"
    incompatible = record(4)
    incompatible["evidence"]["state"] = "incomparable"
    disputed = record(5)
    disputed["review"] = review(disputed, state="disputed")
    report = summarize([pending, missing, provisional, incompatible, disputed], NOW)
    assert report["counts"] == {
        "scored": 0,
        "pending": 1,
        "unavailable": 1,
        "disputed": 2,
        "incomparable": 1,
    }
    assert report["groups"][0]["direction"]["denominator"] == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observed_at", "2026-10-12T19:59:59Z"),
        ("observed_at", "2026-10-12T20:00:00"),
        ("observed_close", float("inf")),
        ("observed_return", 1),
    ],
)
def test_unusable_published_observation_never_contributes_a_success(
    field: str, value: object
) -> None:
    """Malformed persisted timestamps and returns are excluded from all score denominators."""
    row = record()
    row["outcome"][field] = value
    scored = score_record(row, NOW)
    assert scored["state"] == "incomparable"
    assert scored["direction_correct"] is None and scored["interval_80_covered"] is None


@pytest.mark.parametrize("evidence", [[], "invalid evidence", {"state": "observed"}])
def test_malformed_source_rows_are_incomparable_without_aborting_report(evidence: object) -> None:
    """Malformed evidence stays local to its row and does not abort report generation."""
    row = record()
    row["evidence"] = evidence
    original = deepcopy(row)
    scored = score_record(row, NOW)
    assert scored["state"] == "incomparable"
    assert scored["direction_correct"] is None and scored["interval_80_covered"] is None
    assert summarize([row], NOW)["counts"]["incomparable"] == 1
    assert row == original


def test_chart_evidence_uses_recorded_bounds_and_observation_without_mutation() -> None:
    """Report output exposes the recorded bounds without mutating persisted inputs."""
    original = record(close=110)
    baseline = deepcopy(original)
    item = summarize([original], NOW)["items"][0]
    assert item["observed_return"] == pytest.approx(0.1)
    assert item["interval_80_price"] == {"low": 90, "high": 110}
    assert original == baseline


@pytest.mark.parametrize("state", ["pending", "unavailable", "disputed", "incomparable"])
def test_unscored_chart_evidence_is_explicitly_missing(state: str) -> None:
    """Rows outside the scored state do not synthesize chart prices or returns."""
    original = record()
    if state == "pending":
        original["outcome"] = None
    elif state == "disputed":
        original["review"] = review(original, state="disputed")
    elif state == "incomparable":
        original["evidence"]["state"] = "incomparable"
    else:
        original["outcome"].update(state="unavailable", observed_close=None, observed_return=None)
    item = score_record(original, NOW)
    assert item["state"] == state
    assert item["observed_return"] is None
    assert item["interval_80_price"] is None
