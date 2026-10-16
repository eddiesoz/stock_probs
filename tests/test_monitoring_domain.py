"""Price crossings begin after arming and cannot duplicate on replay or threshold touches."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from stock_probs.monitoring_domain import (
    MAX_ARM_GENERATION,
    ArmBaselineSnapshot,
    CrossingState,
    MonitoringError,
    PriceObservation,
    begin_arm_generation,
    evaluate_arm_snapshot,
    evaluate_crossing,
    pause_crossing,
)

NOW = datetime(2026, 10, 12, 14, tzinfo=UTC)
FRIDAY_ARMED_AT = datetime(2026, 10, 9, 20, 30, tzinfo=UTC)
FRIDAY_PROVIDER_TIME = datetime(2026, 10, 9, 20, 0, tzinfo=UTC)
FRIDAY_SNAPSHOT_REQUESTED_AT = datetime(2026, 10, 9, 20, 30, 1, tzinfo=UTC)
FRIDAY_SNAPSHOT_RECEIVED_AT = datetime(2026, 10, 9, 20, 32, tzinfo=UTC)
MONDAY_ARMED_AT = datetime(2026, 10, 12, 13, 30, tzinfo=UTC)


def observe(state, value, minute):
    now = NOW + timedelta(minutes=minute)
    observation = PriceObservation("SPY", value, "USD", now, "test provider")
    return evaluate_crossing(state, observation, now)


@pytest.mark.parametrize(
    "direction,initial,crossed,opposite",
    [
        ("above", "99", "101", "99"),
        ("below", "101", "99", "101"),
    ],
)
def test_repeating_rule_requires_opposite_side_not_just_a_threshold_touch(
    direction, initial, crossed, opposite
):
    state = CrossingState("SPY", "USD", "100", direction, True, NOW)
    initial_result = observe(state, initial, 0)
    assert initial_result.disposition == "initial"
    first = observe(initial_result.state, crossed, 15)
    assert first.disposition == "triggered"
    touched = observe(first.state, "100", 30)
    assert not touched.state.ready
    bounced = observe(touched.state, crossed, 45)
    assert bounced.disposition == "observed"
    rearmed = observe(bounced.state, opposite, 60)
    assert rearmed.state.ready
    assert observe(rearmed.state, crossed, 75).disposition == "triggered"


def test_one_shot_disables_after_crossing_and_replayed_ticks_cannot_trigger():
    state = CrossingState("SPY", "USD", "100", "above", False, NOW)
    state = observe(state, "99", 0).state
    triggered = observe(state, "101", 15)
    assert triggered.disposition == "triggered" and not triggered.state.enabled
    assert observe(triggered.state, "105", 30).disposition == "paused"
    replay = observe(state, "99", 0)
    assert replay.disposition == "ignored" and replay.state == state
    older = PriceObservation("SPY", "105", "USD", NOW - timedelta(minutes=1), "test provider")
    assert evaluate_crossing(state, older, NOW).disposition == "ignored"


def test_already_above_arming_and_delayed_prearming_changes_do_not_notify():
    state = CrossingState("SPY", "USD", "100", "above", True, NOW)
    initial = observe(state, "105", 0)
    assert not initial.state.ready
    assert observe(initial.state, "106", 15).disposition == "observed"
    delayed = PriceObservation("SPY", "90", "USD", NOW - timedelta(minutes=10), "test provider")
    baseline = evaluate_crossing(state, delayed, NOW)
    newer_but_historical = replace(delayed, price="110", observed_at=NOW - timedelta(minutes=5))
    updated = evaluate_crossing(baseline.state, newer_but_historical, NOW)
    assert updated.disposition == "ignored" and updated.state == state
    assert observe(updated.state, "110", 15).disposition == "initial"


@pytest.mark.parametrize(
    "change",
    [
        {"price": "NaN"},
        {"price": "0"},
        {"price": "Infinity"},
        {"currency": "CAD"},
        {"symbol": "SHOP.TO"},
        {"provider": ""},
        {"observed_at": NOW + timedelta(seconds=1)},
        {"observed_at": NOW - timedelta(days=8)},
        {"observed_at": NOW.replace(tzinfo=None)},
    ],
)
def test_invalid_observations_cannot_arm_a_rule(change):
    state = CrossingState("SPY", "USD", "100", "above", True, NOW)
    observation = PriceObservation("SPY", "99", "USD", NOW, "test provider")
    with pytest.raises(MonitoringError):
        evaluate_crossing(state, replace(observation, **change), NOW)


def test_freshness_is_disclosed_without_inventing_crossings_between_observations():
    state = CrossingState("SPY", "USD", "100", "above", True, NOW)
    friday = PriceObservation("SPY", "99", "USD", NOW - timedelta(days=2), "test provider")
    initial = evaluate_crossing(state, friday, NOW)
    assert initial.stale and initial.disposition == "ignored" and initial.state == state
    # An unobserved rise-and-return is not an inferred success.
    assert observe(initial.state, "99", 15).disposition == "initial"


def test_post_arm_friday_snapshot_seeds_baseline_for_mondays_first_live_crossing():
    state = begin_arm_generation(
        CrossingState("SPY", "USD", "100", "above", True, FRIDAY_ARMED_AT),
        FRIDAY_ARMED_AT,
    )
    generation = state.arm_generation
    snapshot_observation = PriceObservation(
        "SPY", "99", "USD", FRIDAY_PROVIDER_TIME, "test provider"
    )
    snapshot = ArmBaselineSnapshot(
        generation,
        snapshot_observation,
        FRIDAY_SNAPSHOT_REQUESTED_AT,
        FRIDAY_SNAPSHOT_RECEIVED_AT,
    )

    baseline = evaluate_arm_snapshot(state, snapshot, FRIDAY_SNAPSHOT_RECEIVED_AT)

    assert baseline.disposition == "initial" and baseline.stale
    assert baseline.state.ready
    assert baseline.state.last_observed_at == FRIDAY_PROVIDER_TIME
    assert baseline.state.last_observed_at != snapshot.received_at
    delayed_prearm = PriceObservation(
        "SPY", "105", "USD", datetime(2026, 10, 9, 20, 25, tzinfo=UTC), "test provider"
    )
    late = evaluate_crossing(
        baseline.state,
        delayed_prearm,
        datetime(2026, 10, 9, 20, 40, tzinfo=UTC),
        generation=generation,
    )
    assert late.disposition == "ignored" and late.state == baseline.state

    monday = PriceObservation("SPY", "101", "USD", MONDAY_ARMED_AT, "test provider")
    crossed = evaluate_crossing(
        baseline.state,
        monday,
        datetime(2026, 10, 12, 13, 31, tzinfo=UTC),
        generation=generation,
    )
    assert crossed.disposition == "triggered"
    assert crossed.state.last_observed_at == MONDAY_ARMED_AT


def test_arm_snapshot_already_on_target_side_never_triggers_on_first_live_quote():
    armed = begin_arm_generation(CrossingState("SPY", "USD", "100", "above", True, NOW), NOW)
    snapshot = ArmBaselineSnapshot(
        armed.arm_generation,
        PriceObservation("SPY", "101", "USD", NOW, "test provider"),
        NOW,
        NOW + timedelta(seconds=1),
    )
    baseline = evaluate_arm_snapshot(armed, snapshot, NOW + timedelta(seconds=1))
    first_live = PriceObservation("SPY", "102", "USD", NOW + timedelta(minutes=1), "test provider")

    observed = evaluate_crossing(
        baseline.state,
        first_live,
        NOW + timedelta(minutes=1),
        generation=armed.arm_generation,
    )

    assert baseline.disposition == "initial" and not baseline.state.ready
    assert observed.disposition == "observed" and not observed.state.ready


@pytest.mark.parametrize(
    "direction,target,opposite",
    [("above", "101", "99"), ("below", "99", "101")],
)
def test_target_side_arm_snapshot_requires_opposite_then_target_crossing(
    direction, target, opposite
):
    state = begin_arm_generation(CrossingState("SPY", "USD", "100", direction, True, NOW), NOW)
    snapshot = ArmBaselineSnapshot(
        state.arm_generation,
        PriceObservation("SPY", target, "USD", NOW, "test provider"),
        NOW,
        NOW + timedelta(seconds=1),
    )
    baseline = evaluate_arm_snapshot(state, snapshot, NOW + timedelta(seconds=1))
    assert baseline.disposition == "initial" and not baseline.state.ready

    tick_results = []
    current = baseline.state
    for minute, value in enumerate((target, opposite, target), start=1):
        observed_at = NOW + timedelta(minutes=minute)
        observation = PriceObservation("SPY", value, "USD", observed_at, "test provider")
        result = evaluate_crossing(
            current,
            observation,
            observed_at,
            generation=state.arm_generation,
        )
        tick_results.append(result)
        current = result.state

    assert [result.disposition for result in tick_results] == [
        "observed",
        "observed",
        "triggered",
    ]
    assert tick_results[0].state.ready is False
    assert tick_results[1].state.ready is True


@pytest.mark.parametrize("generation", [True, 1.0, "1", -1, MAX_ARM_GENERATION + 1])
def test_malformed_arm_generation_types_fail_closed(generation):
    state = replace(
        CrossingState("SPY", "USD", "100", "above", True, NOW),
        arm_generation=generation,
    )
    observation = PriceObservation("SPY", "99", "USD", NOW, "test provider")

    with pytest.raises(MonitoringError):
        begin_arm_generation(state, NOW)
    with pytest.raises(MonitoringError):
        evaluate_crossing(state, observation, NOW)


@pytest.mark.parametrize("marker", [True, 1.0, "1", -1, 0, MAX_ARM_GENERATION + 1])
def test_malformed_arm_snapshot_generation_markers_fail_closed(marker):
    state = CrossingState(
        "SPY",
        "USD",
        "100",
        "above",
        True,
        NOW,
        last_side=-1,
        ready=True,
        last_observed_at=NOW,
        arm_generation=1,
        arm_snapshot_generation=marker,
    )
    observation = PriceObservation("SPY", "101", "USD", NOW + timedelta(seconds=1), "test provider")

    with pytest.raises(MonitoringError):
        evaluate_crossing(
            state,
            observation,
            NOW + timedelta(seconds=1),
            generation=state.arm_generation,
        )


def test_current_generation_live_observation_requires_generation_token():
    state = begin_arm_generation(CrossingState("SPY", "USD", "100", "above", True, NOW), NOW)
    observation = PriceObservation("SPY", "99", "USD", NOW, "test provider")

    result = evaluate_crossing(state, observation, NOW)

    assert result.disposition == "ignored" and result.state == state


def test_snapshot_and_live_duplicates_do_not_replace_the_current_baseline():
    armed = begin_arm_generation(
        CrossingState("SPY", "USD", "100", "above", True, FRIDAY_ARMED_AT),
        FRIDAY_ARMED_AT,
    )
    original = ArmBaselineSnapshot(
        armed.arm_generation,
        PriceObservation("SPY", "99", "USD", FRIDAY_PROVIDER_TIME, "test provider"),
        FRIDAY_SNAPSHOT_REQUESTED_AT,
        FRIDAY_SNAPSHOT_RECEIVED_AT,
    )
    baseline = evaluate_arm_snapshot(armed, original, FRIDAY_SNAPSHOT_RECEIVED_AT)
    replacement = replace(
        original,
        observation=replace(original.observation, price="101"),
        requested_at=FRIDAY_SNAPSHOT_REQUESTED_AT + timedelta(minutes=1),
        received_at=FRIDAY_SNAPSHOT_RECEIVED_AT + timedelta(minutes=1),
    )

    duplicate_snapshot = evaluate_arm_snapshot(
        baseline.state, replacement, FRIDAY_SNAPSHOT_RECEIVED_AT + timedelta(minutes=1)
    )
    duplicate_tick = evaluate_crossing(
        baseline.state,
        original.observation,
        FRIDAY_SNAPSHOT_RECEIVED_AT + timedelta(minutes=1),
        generation=armed.arm_generation,
    )

    assert duplicate_snapshot.disposition == "ignored"
    assert duplicate_snapshot.state == baseline.state
    assert duplicate_tick.disposition == "ignored"
    assert duplicate_tick.state == baseline.state


def test_pause_and_resume_invalidate_old_generation_fetches_and_reset_readiness():
    armed = begin_arm_generation(
        CrossingState("SPY", "USD", "100", "above", True, FRIDAY_ARMED_AT),
        FRIDAY_ARMED_AT,
    )
    old_generation = armed.arm_generation
    snapshot = ArmBaselineSnapshot(
        old_generation,
        PriceObservation("SPY", "99", "USD", FRIDAY_PROVIDER_TIME, "test provider"),
        FRIDAY_SNAPSHOT_REQUESTED_AT,
        FRIDAY_SNAPSHOT_RECEIVED_AT,
    )
    baseline = evaluate_arm_snapshot(armed, snapshot, FRIDAY_SNAPSHOT_RECEIVED_AT)
    paused = pause_crossing(baseline.state)
    resumed = begin_arm_generation(paused, MONDAY_ARMED_AT)
    late_observation = PriceObservation(
        "SPY", "101", "USD", MONDAY_ARMED_AT + timedelta(minutes=1), "test provider"
    )
    late_snapshot = ArmBaselineSnapshot(
        old_generation,
        late_observation,
        MONDAY_ARMED_AT + timedelta(minutes=1),
        MONDAY_ARMED_AT + timedelta(minutes=2),
    )

    old_snapshot_result = evaluate_arm_snapshot(
        resumed, late_snapshot, MONDAY_ARMED_AT + timedelta(minutes=2)
    )
    old_tick_result = evaluate_crossing(
        resumed,
        late_observation,
        MONDAY_ARMED_AT + timedelta(minutes=2),
        generation=old_generation,
    )
    first_live = evaluate_crossing(
        resumed,
        late_observation,
        MONDAY_ARMED_AT + timedelta(minutes=2),
        generation=resumed.arm_generation,
    )

    assert not paused.enabled and not paused.ready
    assert resumed.enabled and not resumed.ready and resumed.last_observed_at is None
    assert resumed.arm_generation > old_generation
    assert old_snapshot_result.disposition == "ignored" and old_snapshot_result.state == resumed
    assert old_tick_result.disposition == "ignored" and old_tick_result.state == resumed
    assert first_live.disposition == "initial" and not first_live.state.ready


@pytest.mark.parametrize(
    "change",
    [
        {"price": "NaN"},
        {"price": "0"},
        {"currency": "CAD"},
        {"symbol": "SHOP.TO"},
        {"provider": "   "},
        {"observed_at": FRIDAY_SNAPSHOT_RECEIVED_AT + timedelta(seconds=1)},
    ],
)
def test_invalid_arm_snapshot_observations_are_rejected(change):
    state = begin_arm_generation(
        CrossingState("SPY", "USD", "100", "above", True, FRIDAY_ARMED_AT),
        FRIDAY_ARMED_AT,
    )
    snapshot = ArmBaselineSnapshot(
        state.arm_generation,
        replace(
            PriceObservation("SPY", "99", "USD", FRIDAY_PROVIDER_TIME, "test provider"),
            **change,
        ),
        FRIDAY_SNAPSHOT_REQUESTED_AT,
        FRIDAY_SNAPSHOT_RECEIVED_AT,
    )

    with pytest.raises(MonitoringError):
        evaluate_arm_snapshot(state, snapshot, FRIDAY_SNAPSHOT_RECEIVED_AT)


def test_arm_snapshot_requires_current_fetch_order_and_rejects_future_receipts():
    state = begin_arm_generation(
        CrossingState("SPY", "USD", "100", "above", True, FRIDAY_ARMED_AT),
        FRIDAY_ARMED_AT,
    )
    observation = PriceObservation("SPY", "99", "USD", FRIDAY_PROVIDER_TIME, "test provider")
    before_arm = ArmBaselineSnapshot(
        state.arm_generation,
        observation,
        FRIDAY_ARMED_AT - timedelta(seconds=1),
        FRIDAY_SNAPSHOT_RECEIVED_AT,
    )
    ignored = evaluate_arm_snapshot(state, before_arm, FRIDAY_SNAPSHOT_RECEIVED_AT)
    assert ignored.disposition == "ignored" and ignored.state == state

    future_receipt = replace(
        before_arm,
        requested_at=FRIDAY_SNAPSHOT_REQUESTED_AT,
        received_at=FRIDAY_SNAPSHOT_RECEIVED_AT + timedelta(seconds=1),
    )
    with pytest.raises(MonitoringError, match="future"):
        evaluate_arm_snapshot(state, future_receipt, FRIDAY_SNAPSHOT_RECEIVED_AT)

    reversed_order = replace(
        before_arm,
        requested_at=FRIDAY_SNAPSHOT_RECEIVED_AT,
        received_at=FRIDAY_SNAPSHOT_REQUESTED_AT,
    )
    with pytest.raises(MonitoringError, match="arrive before"):
        evaluate_arm_snapshot(state, reversed_order, FRIDAY_SNAPSHOT_RECEIVED_AT)


@pytest.mark.parametrize(
    "direction,old_price,new_price", [("above", "99", "101"), ("below", "101", "99")]
)
def test_prearm_quote_cannot_make_first_valid_observation_a_crossing(
    direction, old_price, new_price
):
    state = CrossingState("SPY", "USD", "100", direction, True, NOW)
    old = PriceObservation("SPY", old_price, "USD", NOW - timedelta(minutes=1), "test provider")
    delayed = evaluate_crossing(state, old, NOW)
    assert delayed.disposition == "ignored" and delayed.state == state
    fresh = observe(delayed.state, new_price, 15)
    assert fresh.disposition == "initial" and not fresh.state.ready
    assert observe(fresh.state, new_price, 30).disposition == "observed"


@pytest.mark.parametrize(
    "direction,target,opposite,old_side", [("above", "101", "99", -1), ("below", "99", "101", 1)]
)
def test_resume_with_old_persisted_ready_state_establishes_a_new_baseline(
    direction, target, opposite, old_side
):
    state = CrossingState(
        "SPY",
        "USD",
        "100",
        direction,
        True,
        NOW,
        last_side=old_side,
        ready=True,
        last_observed_at=NOW - timedelta(minutes=15),
    )
    first = observe(state, target, 15)
    assert first.disposition == "initial" and not first.state.ready
    unchanged = observe(first.state, target, 30)
    assert unchanged.disposition == "observed"
    rearmed = observe(unchanged.state, opposite, 45)
    assert rearmed.state.ready
    assert observe(rearmed.state, target, 60).disposition == "triggered"
    assert state.ready and state.last_observed_at < NOW
