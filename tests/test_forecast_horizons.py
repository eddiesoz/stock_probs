"""Additive rolling-horizon tests keep legacy calculations and provenance explicit."""

from dataclasses import replace
from datetime import UTC, datetime

from stock_probs.domain import calculate_forecasts, scheduled_session_close
from stock_probs.provider import FixtureProvider

NOW = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)


def test_selected_intervals_have_distinct_inputs_and_one_result_each():
    data = FixtureProvider(clock=lambda: NOW).fetch("ACDC", "stock")

    daily_snapshot, daily_results = calculate_forecasts(data, NOW, interval="daily")
    weekly_snapshot, weekly_results = calculate_forecasts(data, NOW, interval="weekly")
    legacy_snapshot, legacy_results = calculate_forecasts(data, NOW)

    assert [result["horizon"] for result in daily_results] == ["daily_1"]
    assert [result["horizon"] for result in weekly_results] == ["weekly_5"]
    assert [result["horizon"] for result in legacy_results] == [
        "close_to_close",
        "completed_5m_to_close",
    ]
    assert daily_snapshot["requested_interval"] == "daily"
    assert weekly_snapshot["requested_interval"] == "weekly"
    assert daily_results[0]["forecast_fingerprint"] == (
        "8ddc03d419ff448ff985c4fca2b1a1d8423ea9d78f51274f6c6d34604db5a006"
    )
    assert "requested_interval" not in legacy_snapshot
    assert len(
        {
            daily_snapshot["content_fingerprint"],
            weekly_snapshot["content_fingerprint"],
            legacy_snapshot["content_fingerprint"],
        }
    ) == 3


def test_rolling_horizons_expose_distributions_prices_and_provenance():
    data = FixtureProvider(clock=lambda: NOW).fetch("ACDC", "stock")
    calculated = [
        calculate_forecasts(data, NOW, interval=interval)
        for interval in ("5min", "daily", "weekly", "monthly", "quarterly")
    ]
    snapshot = calculated[0][0]
    results = [result for _, selected in calculated for result in selected]
    by_horizon = {result["horizon"]: result for result in results}

    for name in ("five_min_forward", "daily_1", "weekly_5", "monthly_21", "quarterly_63"):
        result = by_horizon[name]
        provenance = result["provenance"]
        assert result["availability"] == "available"
        assert [interval["level"] for interval in result["magnitude_intervals"]] == [0.5, 0.8, 0.95]
        assert provenance["definition_version"] == "rolling-horizons-v1"
        assert provenance["origin_at"] == result["origin_timestamp"]
        assert provenance["target_at"] == result["target_timestamp"]
        assert provenance["calendar"]["timezone"] == "America/New_York"
        assert provenance["adjustment_basis"].startswith("unadjusted provider closes")
        assert provenance["sample_counts"]["candidate"] >= provenance["sample_counts"]["eligible"]
        assert provenance["sample_counts"]["overlap_adjusted_effective"] >= result[
            "minimum_effective_samples"
        ]
        assert provenance["provider_snapshot"] == {
            "provider": "deterministic fixture",
            "fingerprint": snapshot["provenance"]["provider_content_fingerprint"],
            "as_of": NOW.isoformat(),
        }

    assert by_horizon["five_min_forward"]["origin_timestamp"] == "2025-01-10T12:00:00-05:00"
    assert by_horizon["five_min_forward"]["target_timestamp"] == "2025-01-10T12:05:00-05:00"
    assert by_horizon["five_min_forward"]["target_state"] == (
        "scheduled_five_minute_bar_close"
    )
    assert by_horizon["daily_1"]["target_timestamp"] == "2025-01-10T16:00:00-05:00"
    assert by_horizon["weekly_5"]["target_timestamp"] == "2025-01-16T16:00:00-05:00"
    assert [
        by_horizon[name]["interval"]
        for name in by_horizon
        if name not in {"close_to_close", "completed_5m_to_close"}
    ] == ["5min", "daily", "weekly", "monthly", "quarterly"]


def test_forward_horizon_and_insufficient_training_are_explicitly_unavailable():
    provider = FixtureProvider(clock=lambda: NOW)
    data = provider.fetch("ACDC", "stock")
    after_close = datetime(2025, 1, 10, 22, 0, tzinfo=UTC)
    _, after_results = calculate_forecasts(
        provider.fetch("ACDC", "stock", after_close), after_close, interval="5min"
    )
    forward = next(result for result in after_results if result["horizon"] == "five_min_forward")

    assert forward["availability"] == "unavailable"
    assert forward["target_timestamp"] is None
    assert "same session" in forward["unavailable_reason"]
    assert "direction_probabilities" not in forward

    _, short_results = calculate_forecasts(
        replace(data, daily=data.daily[-64:]), NOW, interval="quarterly"
    )
    quarterly = next(result for result in short_results if result["horizon"] == "quarterly_63")
    assert quarterly["availability"] == "unavailable"
    assert quarterly["unavailable_reason"] == "insufficient 63-session training history"


def test_toronto_calendar_supports_tsx_and_tsxv_regular_sessions():
    provider = FixtureProvider(clock=lambda: NOW)

    shop = provider.fetch("SHOP.TO", "stock")
    snapshot, results = calculate_forecasts(shop, NOW)

    assert shop.identity.exchange == "TSE"
    assert provider.fetch("PNG.V", "stock").identity.exchange == "VAN"
    assert shop.query["fixture"] == "acdc.json"
    assert snapshot["calendar"] == {
        "name": "scheduled TSX/TSXV equity sessions",
        "version": "tsx-equities-rules-v1",
        "timezone": "America/Toronto",
    }
    assert len(results) == 2
    assert scheduled_session_close(datetime(2025, 7, 1).date(), "America/Toronto") is None
    assert scheduled_session_close(datetime(2025, 7, 2).date(), "America/Toronto").isoformat() == (
        "2025-07-02T16:00:00-04:00"
    )
