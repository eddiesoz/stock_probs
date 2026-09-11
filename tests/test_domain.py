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
    assert snapshot["provider_query"]["intraday"] == "5m/5d"
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


def test_incomplete_bar_values_cannot_leak_into_the_distribution():
    """Changing an in-progress bar may alter response provenance but never forecast output."""

    data = FixtureProvider().fetch("ACDC", "stock", NOW)
    baseline_snapshot, baseline_results = calculate_forecasts(data, NOW)
    in_progress = next(
        bar
        for bar in data.intraday
        if bar.timestamp.isoformat() == "2025-01-10T12:00:00-05:00"
    )
    changed = replace(
        data,
        intraday=tuple(
            replace(bar, close=bar.close * 100)
            if bar.timestamp == in_progress.timestamp
            else bar
            for bar in data.intraday
        ),
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

    _, results = calculate_forecasts(
        replace(data, daily=shifted_daily, intraday=shifted_intraday), after_close
    )

    # Martin Luther King Jr. Day is closed, so Friday's next close is Tuesday.
    assert results[0]["target_timestamp"] == "2025-01-21T16:00:00-05:00"
    assert results[1]["target_timestamp"] == "2025-01-21T16:00:00-05:00"


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
