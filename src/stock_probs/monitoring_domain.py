"""Evaluate ordered price observations without jobs, email or implicit trading actions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal

MAX_ARM_GENERATION = 2**63 - 1


class MonitoringError(ValueError):
    """A controlled observation/rule failure, safe to present without provider internals."""


def price(value: str) -> Decimal:
    """Thresholds and observed prices must be finite positive bounded decimal strings."""
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        raise MonitoringError("Use a bounded decimal price.")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise MonitoringError("Use a valid decimal price.") from error
    if not result.is_finite() or not 0 < result <= Decimal("1e15"):
        raise MonitoringError("Prices must be positive and finite.")
    return result


def instant(value: datetime) -> datetime:
    """Provider and rule timestamps must identify an actual instant."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise MonitoringError("Observation times must include a timezone.")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class PriceObservation:
    """A provider-labelled observation; receipt time does not replace provider time."""

    symbol: str
    price: str
    currency: str
    observed_at: datetime
    provider: str


@dataclass(frozen=True)
class ArmBaselineSnapshot:
    """A designated fetch result for one arm generation, separate from provider time."""

    generation: int
    observation: PriceObservation
    requested_at: datetime
    received_at: datetime


@dataclass(frozen=True)
class CrossingState:
    """Keep crossings bound to one arm generation.

    Generation zero exists for prototype/legacy pure callers only. Future server arming and
    resume paths must call ``begin_arm_generation`` and persist the generation, arm snapshot,
    provider observation, and fetch request/receipt metadata with compare-and-swap (CAS).
    This module does not implement persistence.
    """

    symbol: str
    currency: str
    threshold: str
    direction: Literal["above", "below"]
    repeating: bool
    armed_at: datetime
    enabled: bool = True
    last_side: int | None = None
    ready: bool = False
    last_observed_at: datetime | None = None
    arm_generation: int = 0
    arm_snapshot_generation: int | None = None


@dataclass(frozen=True)
class CrossingEvaluation:
    state: CrossingState
    disposition: Literal["paused", "initial", "ignored", "observed", "triggered"]
    stale: bool


def begin_arm_generation(state: CrossingState, armed_at: datetime) -> CrossingState:
    """Begin a new arm/resume generation and clear any baseline from an older rule run.

    The returned generation identifies the deliberate snapshot request and each later provider
    request. Callers must retain it with the request so delayed work cannot update a newer arm.
    """
    generation = _next_generation(state.arm_generation)
    return replace(
        state,
        armed_at=instant(armed_at),
        enabled=True,
        last_side=None,
        ready=False,
        last_observed_at=None,
        arm_generation=generation,
        arm_snapshot_generation=None,
    )


def pause_crossing(state: CrossingState) -> CrossingState:
    """Pause a rule and invalidate outstanding observations from its current generation."""
    generation = _next_generation(state.arm_generation)
    return replace(
        state,
        enabled=False,
        last_side=None,
        ready=False,
        last_observed_at=None,
        arm_generation=generation,
        arm_snapshot_generation=None,
    )


def evaluate_arm_snapshot(
    state: CrossingState, snapshot: ArmBaselineSnapshot, now: datetime
) -> CrossingEvaluation:
    """Establish one non-triggering baseline from the active generation's deliberate fetch.

    Provider time remains the stored observation time even when it predates arming, as can happen
    after market close. The request must start after arming, its result must belong to this
    generation, and a previously recorded baseline cannot be replaced by a duplicate.
    """
    current = instant(now)
    if not state.enabled:
        return CrossingEvaluation(state, "paused", False)
    if not isinstance(snapshot, ArmBaselineSnapshot):
        raise MonitoringError("A generation-labelled arm snapshot is required.")
    generation = _checked_generation(state.arm_generation)
    snapshot_generation = _checked_generation(snapshot.generation)
    observed, side, target, stale = _validated_observation(state, snapshot.observation, current)
    armed = instant(state.armed_at)
    requested = instant(snapshot.requested_at)
    received = instant(snapshot.received_at)
    if requested > current or received > current:
        raise MonitoringError("Fetch times cannot be in the future.")
    if received < requested:
        raise MonitoringError("A snapshot cannot arrive before its request.")
    if observed > received:
        raise MonitoringError("Provider time cannot follow snapshot receipt time.")
    if generation == 0 or snapshot_generation != generation:
        return CrossingEvaluation(state, "ignored", stale)
    if requested < armed:
        return CrossingEvaluation(state, "ignored", stale)
    if state.arm_snapshot_generation is not None:
        _validate_snapshot_marker(state)
        return CrossingEvaluation(state, "ignored", stale)
    if state.last_observed_at is not None or state.last_side is not None:
        return CrossingEvaluation(state, "ignored", stale)
    return CrossingEvaluation(
        replace(
            state,
            last_side=side,
            last_observed_at=observed,
            ready=side != target,
            arm_snapshot_generation=generation,
        ),
        "initial",
        stale,
    )


def evaluate_crossing(
    state: CrossingState,
    observation: PriceObservation,
    now: datetime,
    *,
    generation: int | None = None,
) -> CrossingEvaluation:
    """Ignore retries/older ticks, establish a baseline, then evaluate later real crossings.

    Equal-to-threshold observations do not rearm a repeating rule after it fires. Observations
    from before arming cannot establish a baseline here; only an explicit arm snapshot requested
    for the current generation can use an earlier provider timestamp to seed a baseline. No
    crossing is inferred between observations; a move and return can be missed entirely.
    """
    current = instant(now)
    if not state.enabled:
        return CrossingEvaluation(state, "paused", False)
    active_generation = _checked_generation(state.arm_generation)
    if generation is None:
        if active_generation:
            return CrossingEvaluation(state, "ignored", False)
    elif _checked_generation(generation) != active_generation:
        return CrossingEvaluation(state, "ignored", False)
    observed, side, target, stale = _validated_observation(state, observation, current)
    armed = instant(state.armed_at)
    snapshot_baseline = _validate_snapshot_marker(state)
    if observed < armed:
        return CrossingEvaluation(state, "ignored", stale)
    if state.last_observed_at is not None and observed <= instant(state.last_observed_at):
        return CrossingEvaluation(state, "ignored", stale)
    if (
        state.last_side is None
        or state.last_observed_at is None
        or (instant(state.last_observed_at) < armed and not snapshot_baseline)
    ):
        return CrossingEvaluation(
            replace(state, last_side=side, last_observed_at=observed, ready=side != target),
            "initial",
            stale,
        )
    ready = state.ready or side == -target
    triggered = ready and side == target
    return CrossingEvaluation(
        replace(
            state,
            last_side=side,
            last_observed_at=observed,
            ready=False if triggered else ready,
            enabled=state.enabled and (state.repeating or not triggered),
        ),
        "triggered" if triggered else "observed",
        stale,
    )


def _next_generation(current: int) -> int:
    """Return a SQLite-compatible next generation or reject malformed/exhausted state."""
    generation = _checked_generation(current)
    if generation == MAX_ARM_GENERATION:
        raise MonitoringError("This rule has exhausted its arm generations.")
    return generation + 1


def _checked_generation(generation: int) -> int:
    """Validate the non-negative SQLite integer used to bind a request to a rule arm."""
    if type(generation) is not int or not 0 <= generation <= MAX_ARM_GENERATION:
        raise MonitoringError("Arm generations must be non-negative bounded integers.")
    return generation


def _validate_snapshot_marker(state: CrossingState) -> bool:
    """Return whether a complete current-generation arm snapshot established the baseline."""
    marker = state.arm_snapshot_generation
    if marker is None:
        return False
    if (
        _checked_generation(marker) != _checked_generation(state.arm_generation)
        or marker == 0
        or type(state.last_side) is not int
        or state.last_side not in {-1, 0, 1}
        or state.last_observed_at is None
    ):
        raise MonitoringError("The saved arm snapshot does not match the active generation.")
    return True


def _validated_observation(
    state: CrossingState, observation: PriceObservation, current: datetime
) -> tuple[datetime, int, int, bool]:
    """Validate instrument, provenance, time and price before evaluating a provider tick."""
    if not isinstance(state.direction, str) or state.direction not in {"above", "below"}:
        raise MonitoringError("Choose an above or below crossing.")
    if (
        not isinstance(state.symbol, str)
        or not state.symbol.strip()
        or len(state.symbol) > 80
        or not state.symbol.isprintable()
        or not isinstance(state.currency, str)
        or len(state.currency) != 3
        or not state.currency.isascii()
        or not state.currency.isalpha()
        or state.currency.upper() != state.currency
    ):
        raise MonitoringError("The rule instrument or currency is invalid.")
    if not isinstance(observation, PriceObservation):
        raise MonitoringError("A provider-labelled observation is required.")
    if (
        not isinstance(observation.symbol, str)
        or not observation.symbol.strip()
        or len(observation.symbol) > 80
        or not observation.symbol.isprintable()
        or not isinstance(observation.currency, str)
        or observation.currency != state.currency
        or not isinstance(observation.provider, str)
        or not observation.provider.strip()
        or len(observation.provider) > 80
        or not observation.provider.isprintable()
        or observation.symbol != state.symbol
    ):
        raise MonitoringError("The observation source or instrument does not match this rule.")
    observed = instant(observation.observed_at)
    armed = instant(state.armed_at)
    if observed > current or armed > current:
        raise MonitoringError("Future observations cannot establish a crossing.")
    if current - observed > timedelta(days=7):
        raise MonitoringError("This observation is too old to monitor reliably.")
    amount, threshold = price(observation.price), price(state.threshold)
    side = (amount > threshold) - (amount < threshold)
    target = 1 if state.direction == "above" else -1
    stale = current - observed > timedelta(minutes=30)
    return observed, side, target, stale
