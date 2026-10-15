"""Pure deterministic contracts for R4 briefing summaries."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from stock_probs.briefing_domain import (
    BriefingDomainError,
    BriefingWindow,
    DueThesisReviewSummary,
    ForecastOutcomeChange,
    PriceObservation,
    baseline_for_window,
    summarize_price_movements,
    validate_due_thesis_reviews,
    validate_outcome_changes,
    validate_price_observations,
)

NOW = datetime(2026, 10, 14, 12, tzinfo=UTC)


def _price(
    ref: str,
    price: str,
    observed_at: datetime,
    *,
    owner: int = 1,
    state: str = "observed",
    currency: str | None = "USD",
    provider: str | None = "FixtureProvider",
    reason: str | None = None,
) -> PriceObservation:
    return PriceObservation(
        owner_user_id=owner,
        source_ref=ref,
        symbol="SPY",
        asset_type="etf",
        provider=provider,
        currency=currency,
        price=Decimal(price) if price is not None else None,
        observed_at=observed_at,
        received_at=observed_at + timedelta(seconds=1),
        state=state,  # type: ignore[arg-type]
        reason=reason,
    )


def test_first_observation_is_explicit_and_never_a_price_change() -> None:
    first = _price("price-1", "100", NOW, state="initial")
    summary = summarize_price_movements(
        (first,), owner_user_id=1, baseline_at=None, observed_as_of=NOW + timedelta(minutes=1)
    )[0]

    assert summary.state == "first_observation"
    assert summary.change_bps is None
    assert summary.reason == "no_prior_visit_baseline"

    baseline = _price("price-2", "100", NOW)
    post_visit_initial = _price("price-3", "103", NOW + timedelta(hours=1), state="initial")
    later = summarize_price_movements(
        (baseline, post_visit_initial),
        owner_user_id=1,
        baseline_at=NOW + timedelta(minutes=5),
        observed_as_of=NOW + timedelta(hours=2),
    )[0]
    assert later.state == "first_observation"
    assert later.change_bps is None


def test_exact_three_percent_threshold_uses_decimal_math() -> None:
    points = (_price("base", "100", NOW), _price("current", "103", NOW + timedelta(hours=1)))
    crossing = summarize_price_movements(
        points,
        owner_user_id=1,
        baseline_at=NOW + timedelta(minutes=1),
        observed_as_of=NOW + timedelta(hours=2),
    )[0]
    assert crossing.state == "threshold_crossed"
    assert crossing.change_bps == Decimal("300")
    assert crossing.currency == "USD"
    assert crossing.provider == "FixtureProvider"

    below_points = (
        _price("base-below", "100", NOW),
        _price("current-below", "102.999", NOW + timedelta(hours=1)),
    )
    below = summarize_price_movements(
        below_points,
        owner_user_id=1,
        baseline_at=NOW + timedelta(minutes=1),
        observed_as_of=NOW + timedelta(hours=2),
    )[0]
    assert below.state == "below_threshold"
    assert below.change_bps == Decimal("299.9")


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        ("1029999999999999999999999999999", "below_threshold"),
        ("1030000000000000000000000000000", "threshold_crossed"),
        ("970000000000000000000000000001", "below_threshold"),
        ("970000000000000000000000000000", "threshold_crossed"),
    ],
)
def test_high_precision_threshold_comparison_is_exact(current: str, expected: str) -> None:
    points = (
        _price("large-base", "1000000000000000000000000000000", NOW),
        _price("large-current", current, NOW + timedelta(hours=1)),
    )

    result = summarize_price_movements(
        points,
        owner_user_id=1,
        baseline_at=NOW + timedelta(minutes=1),
        observed_as_of=NOW + timedelta(hours=2),
    )[0]

    assert result.state == expected
    if expected == "below_threshold":
        assert result.change_bps is not None
        assert abs(result.change_bps) == Decimal("300")


@pytest.mark.parametrize(
    ("newest", "expected", "reason"),
    [
        (_price("cur-zero", "0", NOW + timedelta(hours=1)), "unavailable", "invalid_price"),
        (
            _price("cur-currency-missing", "103", NOW + timedelta(hours=1), currency=None),
            "unavailable",
            "currency_unavailable",
        ),
        (
            _price("cur-currency-diff", "103", NOW + timedelta(hours=1), currency="CAD"),
            "unavailable",
            "currency_mismatch",
        ),
        (
            replace(
                _price(
                    "cur-missing-price",
                    "103",
                    NOW + timedelta(hours=1),
                    state="unavailable",
                    reason="missing_price",
                ),
                price=None,
            ),
            "unavailable",
            "missing_price",
        ),
        (
            _price("cur-provider-diff", "103", NOW + timedelta(hours=1), provider="Other"),
            "unavailable",
            "provider_mismatch",
        ),
        (
            _price(
                "cur-missing",
                "0",
                NOW + timedelta(hours=1),
                state="unavailable",
                reason="provider_unavailable",
            ),
            "unavailable",
            "provider_unavailable",
        ),
    ],
)
def test_incomparable_or_invalid_price_inputs_stay_explicit(
    newest: PriceObservation, expected: str, reason: str
) -> None:
    base = _price("base", "100", NOW)
    summary = summarize_price_movements(
        (base, newest),
        owner_user_id=1,
        baseline_at=NOW + timedelta(minutes=1),
        observed_as_of=NOW + timedelta(hours=2),
    )[0]

    assert summary.state == expected
    assert summary.change_bps is None
    assert summary.reason == reason


def test_missing_baseline_history_and_timestamps_are_not_scored_as_changes() -> None:
    current = _price("only-current", "110", NOW + timedelta(hours=1))
    missing_history = summarize_price_movements(
        (current,),
        owner_user_id=1,
        baseline_at=NOW,
        observed_as_of=NOW + timedelta(hours=2),
    )[0]
    assert missing_history.state == "insufficient_history"
    assert missing_history.change_bps is None

    no_new_point = summarize_price_movements(
        (_price("old", "100", NOW),),
        owner_user_id=1,
        baseline_at=NOW + timedelta(minutes=1),
        observed_as_of=NOW + timedelta(hours=1),
    )[0]
    assert no_new_point.state == "insufficient_history"
    assert no_new_point.reason == "no_observation_after_baseline"

    missing_time = PriceObservation(
        owner_user_id=1,
        source_ref="time-missing",
        symbol="SPY",
        asset_type="etf",
        provider=None,
        currency=None,
        price=None,
        observed_at=None,
        received_at=None,
        state="unavailable",
        reason="timestamp_unavailable",
    )
    summary = summarize_price_movements(
        (missing_time,), owner_user_id=1, baseline_at=None, observed_as_of=NOW
    )[0]
    assert summary.state == "unavailable"
    assert summary.reason == "timestamp_unavailable"


def test_windows_freeze_exact_baseline_and_reject_future_visit_anchor() -> None:
    assert baseline_for_window(BriefingWindow.LAST_24_HOURS, NOW, NOW) == NOW - timedelta(hours=24)
    assert baseline_for_window(BriefingWindow.LAST_7_DAYS, NOW, None) == NOW - timedelta(days=7)
    assert baseline_for_window(BriefingWindow.SINCE_LAST_VISIT, NOW, None) is None
    assert baseline_for_window(
        BriefingWindow.SINCE_LAST_VISIT, NOW, NOW - timedelta(days=3)
    ) == NOW - timedelta(days=3)
    with pytest.raises(BriefingDomainError, match="later"):
        baseline_for_window(BriefingWindow.SINCE_LAST_VISIT, NOW, NOW + timedelta(seconds=1))


def test_future_out_of_order_owner_and_float_price_sources_fail_closed() -> None:
    first = _price("newer", "100", NOW + timedelta(hours=1))
    older = _price("older", "99", NOW)
    with pytest.raises(BriefingDomainError, match="order"):
        validate_price_observations((first, older), 1, NOW + timedelta(hours=2))
    with pytest.raises(BriefingDomainError, match="future"):
        validate_price_observations((first,), 1, NOW)
    with pytest.raises(BriefingDomainError, match="another owner"):
        validate_price_observations((_price("foreign", "100", NOW, owner=2),), 1, NOW)
    float_price = PriceObservation(
        owner_user_id=1,
        source_ref="float-price",
        symbol="SPY",
        asset_type="etf",
        provider="FixtureProvider",
        currency="USD",
        price=100.0,  # type: ignore[arg-type]
        observed_at=NOW,
        received_at=NOW,
        state="observed",
    )
    with pytest.raises(BriefingDomainError, match="Decimal"):
        validate_price_observations((float_price,), 1, NOW)


def test_corrected_outcome_is_a_reference_not_a_success_score() -> None:
    change = ForecastOutcomeChange(
        owner_user_id=1,
        resource_ref="forecast:42",
        source_ref="evidence:42-r2",
        state="corrected",
        revision=2,
        recorded_at=NOW,
        observed_at=NOW - timedelta(days=1),
        correction_of="evidence:42-r1",
    )
    values = validate_outcome_changes(
        (change,), owner_user_id=1, baseline_at=NOW - timedelta(hours=1), observed_as_of=NOW
    )
    assert values == (change,)
    assert not hasattr(change, "score")
    with pytest.raises(BriefingDomainError, match="superseded"):
        validate_outcome_changes(
            (replace(change, correction_of=None),),
            owner_user_id=1,
            baseline_at=None,
            observed_as_of=NOW,
        )


def test_thesis_projection_contains_only_authenticated_resource_reference() -> None:
    review = DueThesisReviewSummary(1, "thesis:abc", 4, NOW - timedelta(minutes=1))
    assert validate_due_thesis_reviews((review,), owner_user_id=1, observed_as_of=NOW) == (review,)
    future = DueThesisReviewSummary(1, "thesis:future", 1, NOW + timedelta(seconds=1))
    with pytest.raises(BriefingDomainError, match="not due"):
        validate_due_thesis_reviews((future,), owner_user_id=1, observed_as_of=NOW)
