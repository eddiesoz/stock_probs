"""M03 domain tests pin numerical, timestamp, and completed-bar semantics."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from stock_probs.domain import (
    Bar,
    DomainError,
    calculate_forecasts,
    evaluate_outcome,
    label_fresh_historical_analysis,
    normalize_lookup_query,
    normalize_symbol,
    scheduled_session_close,
)
from stock_probs.provider import FixtureProvider

NOW = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)


def test_fixture_forecast_contract_and_repeatability():
    data = FixtureProvider().fetch("ACDC", "stock", NOW)
    first = calculate_forecasts(data, NOW)
    second = calculate_forecasts(data, NOW)

    assert first == second
    snapshot, results = first
    assert snapshot["quality"] == "current"
    assert snapshot["canonical_symbol"] == "ACDC"
    assert snapshot["display_name"] == "ProFrac Holding Corp."
    assert snapshot["company_name"] == "ProFrac Holding Corp."
    assert snapshot["quote_type"] == "EQUITY"
    assert snapshot["instrument_identity"]["asset_type"] == "stock"
    assert snapshot["instrument_identity"] == snapshot["provenance"]["instrument_identity"]
    assert snapshot["identity_fingerprint"] == snapshot["provenance"]["identity_fingerprint"]
    assert snapshot["provider"] == "deterministic fixture"
    assert snapshot["provider_query"]["intraday"] == "5m/60d"
    assert [result["horizon"] for result in results] == ["close_to_close", "completed_5m_to_close"]
    for result in results:
        assert sum(
            result["direction_probabilities"][key] for key in ("down", "flat", "up")
        ) == pytest.approx(1)
        assert [interval["level"] for interval in result["magnitude_intervals"]] == [0.5, 0.8, 0.95]
        assert all(
            interval["percent"]["unit"] == "percent_return"
            for interval in result["magnitude_intervals"]
        )
        assert all(
            interval["price"]["low"] <= interval["price"]["high"]
            for interval in result["magnitude_intervals"]
        )
        assert len(result["forecast_fingerprint"]) == 64
        assert result["model_fingerprint"] == snapshot["model_fingerprint"]


def test_tail_probabilities_and_intervals_are_ordered_and_explicit():
    """M03 exposes symmetric tail risks without violating empirical monotonicity."""

    snapshot, results = calculate_forecasts(FixtureProvider().fetch("ACDC", "stock", NOW), NOW)

    assert snapshot["parameters"]["return_thresholds_percent"] == [
        -1.0,
        -3.0,
        -5.0,
        -10.0,
        1.0,
        3.0,
        5.0,
        10.0,
    ]
    assert snapshot["stale_state"] == {"state": "current", "reasons": []}
    assert snapshot["session_state_at_request"] == "open"
    assert snapshot["provenance"]["content_fingerprint"] == snapshot["content_fingerprint"]
    for result in results:
        negative = [
            item["probability"]
            for item in result["threshold_probabilities"]
            if item["operator"] == "lte"
        ]
        positive = [
            item["probability"]
            for item in result["threshold_probabilities"]
            if item["operator"] == "gte"
        ]
        assert negative == sorted(negative, reverse=True)
        assert positive == sorted(positive, reverse=True)
        intervals = result["magnitude_intervals"]
        assert [item["percent"]["low"] for item in intervals] == sorted(
            (item["percent"]["low"] for item in intervals), reverse=True
        )
        assert [item["percent"]["high"] for item in intervals] == sorted(
            item["percent"]["high"] for item in intervals
        )
        assert result["reference_state"].startswith("completed_")
        assert result["target_state"] == "scheduled_session_close"
        directions = result["direction_probabilities"]
        assert sum(directions[key] for key in ("down", "unchanged", "up")) == pytest.approx(1)
        assert directions["flat"] == directions["unchanged"]
        for tail in result["threshold_probabilities"]:
            assert tail["sample_count"] == result["sample_size"]
            assert 0 <= tail["event_count"] <= tail["sample_count"]
            assert 0 <= tail["probability"] <= 1
            assert 0 <= tail["uncertainty"]["low"] <= tail["uncertainty"]["high"] <= 1
            assert tail["rare_event"] == (tail["event_count"] < 10)
        for conditional in result["conditional_magnitudes"].values():
            assert conditional["sample_count"] == result["sample_size"]
            assert conditional["expected"] is None or conditional["expected"] >= 0
            assert conditional["median"] is None or conditional["median"] >= 0


def test_walk_forward_evaluation_is_bounded_chronological_and_compares_baseline():
    """Every reported score has realized outcomes and prior-only training behind it."""

    _, results = calculate_forecasts(FixtureProvider().fetch("ACDC", "stock", NOW), NOW)

    for result in results:
        evaluation = result["evaluation"]
        assert evaluation["status"] == "available"
        assert 0 < evaluation["evaluation_count"] <= evaluation["max_evaluation_points"] == 120
        assert datetime.fromisoformat(evaluation["date_range"]["last_target"]) <= NOW
        assert "at or before its origin" in evaluation["information_rule"]
        assert evaluation["training_sample_range"]["minimum_effective_count"] >= 3
        for report in (evaluation["forecast_model"], evaluation["baseline"]):
            assert 0 <= report["direction_brier"]["multiclass_mean"] <= 2
            assert len(report["threshold_brier"]) == 8
            assert all(0 <= item["score"] <= 1 for item in report["threshold_brier"])
            assert [item["level"] for item in report["interval_coverage"]] == [0.5, 0.8, 0.95]
            assert all(
                item["sample_count"] == evaluation["evaluation_count"]
                for item in report["interval_coverage"]
            )
            for bins in report["reliability"]["direction"].values():
                assert sum(item["count"] for item in bins) == evaluation["evaluation_count"]
        assert evaluation["baseline"]["name"] == "prior-only empirical climatology"


def test_future_daily_row_cannot_change_forecast_or_evaluation():
    """A provider's active daily candle is not a completed close or walk-forward outcome."""

    data = FixtureProvider().fetch("ACDC", "stock", NOW)
    baseline_snapshot, baseline_results = calculate_forecasts(data, NOW)
    changed = replace(
        data,
        daily=(
            *data.daily,
            Bar(
                datetime(2025, 1, 10, 16, 0, tzinfo=ZoneInfo("America/New_York")),
                9_999.0,
                0,
            ),
        ),
    )

    changed_snapshot, changed_results = calculate_forecasts(changed, NOW)

    assert changed_results == baseline_results
    assert changed_snapshot["selected_daily_bars"] == baseline_snapshot["selected_daily_bars"]
    assert changed_snapshot["content_fingerprint"] != baseline_snapshot["content_fingerprint"]


def test_split_or_unit_discontinuity_is_filtered_and_counted():
    """An unadjusted corporate-action jump cannot dominate the historical distribution."""

    data = FixtureProvider().fetch("ACDC", "stock", NOW)
    changed_daily = list(data.daily)
    changed_daily[-20] = replace(changed_daily[-20], close=changed_daily[-20].close * 10)

    _, first = calculate_forecasts(replace(data, daily=tuple(changed_daily)), NOW)
    _, second = calculate_forecasts(replace(data, daily=tuple(changed_daily)), NOW)

    accounting = first[0]["sample_accounting"]
    assert accounting["excluded_anomaly_count"] == 2
    assert accounting["eligible_count"] + accounting["excluded_anomaly_count"] == accounting[
        "candidate_count"
    ]
    assert "corporate-action" in accounting["filter"]["purpose"]
    assert first == second


def test_incomplete_bar_values_cannot_leak_into_the_distribution():
    """Changing an in-progress bar may alter response provenance but never forecast output."""

    data = FixtureProvider().fetch("ACDC", "stock", NOW)
    baseline_snapshot, baseline_results = calculate_forecasts(data, NOW)
    in_progress = Bar(
        datetime(2025, 1, 10, 12, 0, tzinfo=ZoneInfo("America/New_York")),
        data.intraday[-1].close,
        300,
    )
    changed = replace(
        data,
        intraday=(*data.intraday, replace(in_progress, close=in_progress.close * 100)),
    )

    changed_snapshot, changed_results = calculate_forecasts(changed, NOW)

    assert changed_results == baseline_results
    assert changed_snapshot["selected_intraday_bars"] == baseline_snapshot["selected_intraday_bars"]
    assert changed_snapshot["content_fingerprint"] != baseline_snapshot["content_fingerprint"]


def test_in_progress_five_minute_bar_is_excluded():
    data = FixtureProvider().fetch("ACDC", "stock", NOW)
    _, results = calculate_forecasts(data, NOW)
    intraday = results[1]

    assert intraday["origin_timestamp"] == "2025-01-10T11:55:00-05:00"
    assert intraday["origin_bar_end"] == "2025-01-10T12:00:00-05:00"
    assert intraday["target_timestamp"] == "2025-01-10T16:00:00-05:00"


@pytest.mark.parametrize(
    ("now", "origin"),
    [
        (datetime(2025, 1, 10, 16, 59, 59, tzinfo=UTC), "2025-01-10T11:50:00-05:00"),
        (datetime(2025, 1, 10, 17, 0, tzinfo=UTC), "2025-01-10T11:55:00-05:00"),
    ],
)
def test_five_minute_completion_boundary_is_exact(now, origin):
    _, results = calculate_forecasts(FixtureProvider().fetch("ACDC", "stock", now), now)
    assert results[1]["origin_timestamp"] == origin


def test_early_close_target_rules_inside_and_after_session():
    """Post-Thanksgiving uses 13:00 while an after-close origin targets the next session."""

    zone = ZoneInfo("America/New_York")
    assert scheduled_session_close(datetime(2025, 11, 28).date(), str(zone)).hour == 13
    historical = FixtureProvider().fetch("ACDC", "stock", datetime(2025, 1, 10, 22, tzinfo=UTC))
    prior_bars = tuple(
        Bar(
            datetime.combine(day, datetime.min.time(), zone)
            + timedelta(hours=9, minutes=30 + 5 * index),
            24.0 + session_index / 10 + index / 100,
            300,
        )
        for session_index, day in enumerate(
            (
                datetime(2025, 11, 20).date(),
                datetime(2025, 11, 21).date(),
                datetime(2025, 11, 24).date(),
                datetime(2025, 11, 25).date(),
                datetime(2025, 11, 26).date(),
            )
        )
        for index in range(78)
    )
    early_day = datetime(2025, 11, 28).date()
    early_bars = tuple(
        Bar(
            datetime.combine(early_day, datetime.min.time(), zone)
            + timedelta(hours=9, minutes=30 + 5 * index),
            25.0 + index / 100,
            300,
        )
        for index in range(42)
    )
    current_data = replace(
        historical,
        fetched_at=datetime(2025, 11, 28, 17, 3, tzinfo=UTC),
        intraday=(*prior_bars, *early_bars),
        provider_metadata={
            key: value
            for key, value in historical.provider_metadata.items()
            if key != "regular_session"
        },
    )

    open_snapshot, open_results = calculate_forecasts(
        current_data, datetime(2025, 11, 28, 17, 3, tzinfo=UTC)
    )
    assert open_results[1]["target_timestamp"] == "2025-11-28T13:00:00-05:00"
    assert not any("internal five-minute" in reason for reason in open_snapshot["quality_reasons"])

    after_data = replace(
        current_data,
        fetched_at=datetime(2025, 11, 28, 19, tzinfo=UTC),
    )
    _, after_results = calculate_forecasts(after_data, datetime(2025, 11, 28, 19, tzinfo=UTC))
    assert after_results[1]["target_timestamp"] == "2025-12-01T16:00:00-05:00"


def test_after_close_targets_next_weekday_close():
    after_close = datetime(2025, 1, 10, 22, 0, tzinfo=UTC)
    data = FixtureProvider().fetch("SPY", "etf", after_close)
    _, results = calculate_forecasts(data, after_close)

    assert results[1]["origin_timestamp"] == "2025-01-10T15:55:00-05:00"
    assert results[1]["target_timestamp"] == "2025-01-13T16:00:00-05:00"


def test_outside_session_rejects_a_partial_old_session_reference():
    """After hours cannot silently treat an old midday bar as a completed close."""

    after_close = datetime(2025, 1, 10, 22, 0, tzinfo=UTC)
    data = FixtureProvider().fetch("ACDC", "stock", after_close)
    partial = tuple(
        bar
        for bar in data.intraday
        if not (
            bar.timestamp.astimezone(ZoneInfo("America/New_York")).date().isoformat()
            == "2025-01-10"
            and bar.timestamp.astimezone(ZoneInfo("America/New_York")).hour >= 12
        )
    )

    with pytest.raises(DomainError) as failure:
        calculate_forecasts(replace(data, intraday=partial), after_close)
    assert failure.value.code == "incomplete_session_data"


def test_next_close_skips_a_scheduled_exchange_holiday():
    friday_close = datetime(2025, 1, 17, 16, 0, tzinfo=ZoneInfo("America/New_York"))
    after_close = datetime(2025, 1, 17, 22, 0, tzinfo=UTC)
    data = FixtureProvider().fetch("SPY", "etf", after_close)
    shifted_intraday = tuple(
        Bar(bar.timestamp + timedelta(days=7), bar.close, bar.duration_seconds)
        for bar in data.intraday
    )
    shifted_daily = (*data.daily[:-1], Bar(friday_close, data.daily[-1].close, 0))

    snapshot, results = calculate_forecasts(
        replace(data, daily=shifted_daily, intraday=shifted_intraday), after_close
    )

    # Martin Luther King Jr. Day is closed, so Friday's next close is Tuesday.
    assert results[0]["target_timestamp"] == "2025-01-21T16:00:00-05:00"
    assert results[1]["target_timestamp"] == "2025-01-21T16:00:00-05:00"
    assert not any("internal five-minute" in reason for reason in snapshot["quality_reasons"])


def test_stale_and_insufficient_data_are_explicit():
    data = FixtureProvider().fetch("ACDC", "stock", NOW)
    with pytest.raises(DomainError, match="No completed") as failure:
        calculate_forecasts(replace(data, intraday=()), NOW)
    assert failure.value.code == "insufficient_intraday_data"

    # Stale reconstruction starts from a response that had completed its source session.
    completed_source = FixtureProvider().fetch(
        "ACDC", "stock", datetime(2025, 1, 10, 22, 0, tzinfo=UTC)
    )
    _, results = calculate_forecasts(completed_source, NOW + timedelta(days=6))
    # The after-hours path remains calculable but its shared quality is visibly stale.
    snapshot, _ = calculate_forecasts(completed_source, NOW + timedelta(days=6))
    assert snapshot["quality"] == "stale"
    assert results


def test_missing_intervals_are_visible_and_unsupported_markets_are_rejected():
    data = FixtureProvider().fetch("ACDC", "stock", NOW)
    metadata = {**data.provider_metadata, "missing_intraday_intervals": 2}
    snapshot, _ = calculate_forecasts(replace(data, provider_metadata=metadata), NOW)

    assert snapshot["quality"] == "stale"
    assert "2 missing intraday bars" in snapshot["quality_reasons"][0]
    with pytest.raises(DomainError) as failure:
        calculate_forecasts(replace(data, timezone="Europe/London"), NOW)
    assert failure.value.code == "unsupported_market"


def test_removed_completed_daily_session_marks_quality_stale():
    """R-M03-1 detects an omitted row even when provider missing-value metadata stays zero."""

    data = FixtureProvider().fetch("ACDC", "stock", NOW)
    removed = data.daily[-4]
    changed = replace(data, daily=tuple(bar for bar in data.daily if bar != removed))

    snapshot, _ = calculate_forecasts(changed, NOW)

    assert snapshot["quality"] == "stale"
    assert "daily history omits 1 scheduled session closes" in snapshot["quality_reasons"]


def test_removed_latest_eligible_intraday_bar_marks_quality_stale():
    """R-M03-2 detects a trailing hole that has no following returned bar to expose it."""

    data = FixtureProvider().fetch("ACDC", "stock", NOW)
    changed = replace(
        data,
        intraday=tuple(
            bar
            for bar in data.intraday
            if bar.timestamp.isoformat() != "2025-01-10T11:55:00-05:00"
        ),
    )

    snapshot, results = calculate_forecasts(changed, NOW)

    assert results[1]["origin_timestamp"] == "2025-01-10T11:50:00-05:00"
    assert snapshot["quality"] == "stale"
    assert (
        "latest completed intraday bar precedes the latest eligible five-minute boundary"
        in snapshot["quality_reasons"]
    )


def test_removed_internal_intraday_bar_is_detected_without_provider_gap_metadata():
    """R-M03-7 derives a completed same-session hole from immutable bar timestamps."""

    data = FixtureProvider().fetch("ACDC", "stock", NOW)
    removed_timestamp = "2025-01-10T10:30:00-05:00"
    changed = replace(
        data,
        intraday=tuple(
            bar for bar in data.intraday if bar.timestamp.isoformat() != removed_timestamp
        ),
        provider_metadata={
            **data.provider_metadata,
            "missing_intraday_closes": 0,
            "missing_intraday_intervals": 0,
            "trailing_missing_intraday_intervals": 0,
        },
    )

    snapshot, _ = calculate_forecasts(changed, NOW)

    assert snapshot["quality"] == "stale"
    assert (
        "intraday history omits 1 completed internal five-minute bar within 1 regular session"
        in snapshot["quality_reasons"]
    )
    selected_timestamps = {bar["timestamp"] for bar in snapshot["selected_intraday_bars"]}
    assert removed_timestamp not in selected_timestamps
    assert len(snapshot["selected_intraday_bars"]) == len(data.intraday) - 1


def test_intraday_gap_detection_tolerates_weekend_and_cutoff_boundaries():
    """Closed days and an active partial interval never become internal missing bars."""

    zone = ZoneInfo("America/New_York")
    now = datetime(2025, 1, 13, 15, 3, tzinfo=UTC)
    data = FixtureProvider().fetch("ACDC", "stock", now)
    monday = datetime(2025, 1, 13, 9, 30, tzinfo=zone)
    completed_monday = tuple(
        Bar(monday + timedelta(minutes=5 * index), 25.0 + index / 100, 300)
        for index in range(6)
    )
    # This post-cutoff bar is provider payload only; selected completed history must ignore it.
    in_progress = Bar(monday + timedelta(minutes=30), 99.0, 300)
    changed = replace(data, intraday=(*data.intraday, *completed_monday, in_progress))

    snapshot, results = calculate_forecasts(changed, now)

    assert snapshot["quality"] == "current"
    assert snapshot["quality_reasons"] == []
    assert results[1]["origin_timestamp"] == "2025-01-13T09:55:00-05:00"
    assert in_progress.timestamp.isoformat() not in {
        bar["timestamp"] for bar in snapshot["selected_intraday_bars"]
    }


def test_outcome_cannot_precede_immutable_target():
    data = FixtureProvider().fetch("ACDC", "stock", NOW)
    _, results = calculate_forecasts(data, NOW)

    with pytest.raises(DomainError) as failure:
        evaluate_outcome(results[0], 25.0, NOW)
    assert failure.value.code == "outcome_before_target"

    observed_at = datetime.fromisoformat(results[0]["target_timestamp"])
    observed_return, rule = evaluate_outcome(results[0], 25.0, observed_at)
    assert observed_return == pytest.approx(25.0 / results[0]["origin_price"] - 1.0)
    assert "immutable origin" in rule

    with pytest.raises(DomainError) as invalid_price:
        evaluate_outcome(results[0], float("nan"), observed_at)
    assert invalid_price.value.code == "invalid_outcome_price"


def test_fresh_analysis_labelling_preserves_provider_fingerprint_and_original_values():
    snapshot, results = calculate_forecasts(FixtureProvider().fetch("ACDC", "stock", NOW), NOW)
    original_snapshot = snapshot.copy()
    performed = NOW + timedelta(minutes=2)

    labelled_snapshot, labelled_results = label_fresh_historical_analysis(
        snapshot,
        results,
        request_id="fresh-request-1",
        source_event_id=7,
        cutoff=NOW,
        performed_at=performed,
    )

    assert snapshot == original_snapshot
    analysis = labelled_snapshot["provider_query"]["analysis"]
    assert analysis["provider_content_fingerprint"] == snapshot["content_fingerprint"]
    assert labelled_snapshot["content_fingerprint"] != snapshot["content_fingerprint"]
    assert labelled_snapshot["provenance"]["content_fingerprint"] == labelled_snapshot[
        "content_fingerprint"
    ]
    assert labelled_snapshot["provenance"]["query"] == labelled_snapshot["provider_query"]
    assert labelled_snapshot["provenance"]["analysis"] == {
        key: value for key, value in analysis.items() if key != "provider_content_fingerprint"
    }
    assert labelled_snapshot["provenance"]["provider_content_fingerprint"] == analysis[
        "provider_content_fingerprint"
    ]
    assert analysis["requested_cutoff"] == NOW.isoformat()
    assert analysis["performed_at"] == performed.isoformat()
    assert labelled_results == results

    with pytest.raises(DomainError) as ambiguous:
        label_fresh_historical_analysis(
            snapshot,
            results,
            request_id="bad-time",
            source_event_id=7,
            cutoff=NOW.replace(tzinfo=None),
            performed_at=performed,
        )
    assert ambiguous.value.code == "ambiguous_historical_cutoff"


@pytest.mark.parametrize("value", ["", "../../etc", "A B", "A" * 16])
def test_symbol_validation_rejects_unsafe_or_oversized_values(value):
    with pytest.raises(DomainError) as failure:
        normalize_symbol(value)
    assert failure.value.code == "invalid_symbol"


def test_symbol_normalization_preserves_yahoo_syntax():
    assert normalize_symbol(" brk-b ") == "BRK-B"
    assert normalize_symbol("^gspc") == "^GSPC"


def test_company_lookup_query_retains_names_but_rejects_controls_and_unbounded_input():
    assert normalize_lookup_query("  Berkshire   Hathaway, Inc.  ") == "Berkshire Hathaway, Inc."
    with pytest.raises(DomainError) as control:
        normalize_lookup_query("Berkshire\u200bHathaway")
    assert control.value.code == "invalid_lookup_query"
    with pytest.raises(DomainError) as oversized:
        normalize_lookup_query("X" * 81)
    assert oversized.value.code == "invalid_lookup_query"
