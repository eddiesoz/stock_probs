"""Deterministic, owner-scoped briefing values and price-change summaries.

This module intentionally has no provider, network, headline, model, or persistence imports.
Adapters supply bounded immutable observations; the functions here only validate and summarize
those observations at a caller-frozen instant.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction
from typing import Literal
from uuid import UUID

DEFAULT_PRICE_CHANGE_THRESHOLD_BPS = 300
MIN_PRICE_CHANGE_THRESHOLD_BPS = 50
MAX_PRICE_CHANGE_THRESHOLD_BPS = 1_000
MAX_SOURCE_ITEMS = 100
MAX_PRICE_OBSERVATIONS = 20_000
_PRICE_REASONS = frozenset(
    {
        "invalid_price",
        "missing_currency",
        "missing_price",
        "provider_unavailable",
        "source_mismatch",
        "source_unavailable",
        "timestamp_unavailable",
    }
)

_REFERENCE_RE = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_SYMBOL_RE = re.compile(r"[A-Z0-9][A-Z0-9.-]{0,19}\Z")
_ASSET_TYPE_RE = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")
_PROVIDER_RE = re.compile(r"[A-Za-z0-9_.:-]{1,80}\Z")
_CURRENCY_RE = re.compile(r"[A-Z]{3}\Z")


class BriefingDomainError(ValueError):
    """Raised when briefing input cannot be interpreted without guessing."""


class BriefingWindow(StrEnum):
    """Supported deterministic briefing windows."""

    SINCE_LAST_VISIT = "since_last_visit"
    LAST_24_HOURS = "last_24_hours"
    LAST_7_DAYS = "last_7_days"


PriceObservationState = Literal["initial", "observed", "unavailable"]
OutcomeEvidenceState = Literal[
    "observed", "corrected", "unavailable", "incomparable", "manual_review"
]


@dataclass(frozen=True, slots=True)
class PriceObservation:
    """One immutable provider observation stored with its source provenance."""

    owner_user_id: int
    source_ref: str
    symbol: str
    asset_type: str
    provider: str | None
    currency: str | None
    price: Decimal | None
    observed_at: datetime | None
    received_at: datetime | None
    state: PriceObservationState
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ForecastOutcomeChange:
    """A corrected or otherwise explicit outcome state, never a score or success claim."""

    owner_user_id: int
    resource_ref: str
    source_ref: str
    state: OutcomeEvidenceState
    revision: int
    recorded_at: datetime
    observed_at: datetime | None
    correction_of: str | None = None


@dataclass(frozen=True, slots=True)
class TriggeredAlertSummary:
    """A safe reference to one persisted triggered alert."""

    owner_user_id: int
    resource_ref: str
    symbol: str
    asset_type: str
    triggered_at: datetime


@dataclass(frozen=True, slots=True)
class DueThesisReviewSummary:
    """A due-review reference without copying thesis title or body text."""

    owner_user_id: int
    thesis_ref: str
    revision: int
    due_at: datetime


@dataclass(frozen=True, slots=True)
class PriceMovementSummary:
    """A threshold result that omits raw prices and keeps unavailable states explicit."""

    symbol: str
    asset_type: str
    state: str
    baseline_at: datetime | None
    observed_at: datetime | None
    currency: str | None
    provider: str | None
    change_bps: Decimal | None
    reason: str | None = None
    baseline_received_at: datetime | None = None
    received_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class BriefingSnapshot:
    """An immutable, timestamp-frozen briefing suitable for later reopen without recompute."""

    snapshot_id: str
    owner_user_id: int
    idempotency_key: str
    request_sha256: str
    window: BriefingWindow
    baseline_at: datetime | None
    observed_as_of: datetime
    baseline_anchor_revision: int
    preference_revision: int
    threshold_bps: int
    generated_at: datetime
    price_changes: tuple[PriceMovementSummary, ...]
    outcome_changes: tuple[ForecastOutcomeChange, ...]
    triggered_alerts: tuple[TriggeredAlertSummary, ...]
    due_thesis_reviews: tuple[DueThesisReviewSummary, ...]

    def payload(self) -> dict[str, object]:
        """Return only safe changed-item summaries, never balances or thesis text."""

        return {
            "version": 1,
            "window": self.window.value,
            "baseline_at": timestamp_text(self.baseline_at) if self.baseline_at else None,
            "observed_as_of": timestamp_text(self.observed_as_of),
            "threshold_bps": self.threshold_bps,
            "price_changes": [
                {
                    "symbol": item.symbol,
                    "asset_type": item.asset_type,
                    "state": item.state,
                    "baseline_at": timestamp_text(item.baseline_at) if item.baseline_at else None,
                    "observed_at": timestamp_text(item.observed_at) if item.observed_at else None,
                    "baseline_received_at": timestamp_text(item.baseline_received_at)
                    if item.baseline_received_at
                    else None,
                    "received_at": timestamp_text(item.received_at) if item.received_at else None,
                    "currency": item.currency,
                    "provider": item.provider,
                    "change_bps": decimal_text(item.change_bps)
                    if item.change_bps is not None
                    else None,
                    "reason": item.reason,
                }
                for item in self.price_changes
            ],
            "outcome_changes": [
                {
                    "resource_ref": item.resource_ref,
                    "source_ref": item.source_ref,
                    "state": item.state,
                    "revision": item.revision,
                    "recorded_at": timestamp_text(item.recorded_at),
                    "observed_at": timestamp_text(item.observed_at) if item.observed_at else None,
                    "correction_of": item.correction_of,
                }
                for item in self.outcome_changes
            ],
            "triggered_alerts": [
                {
                    "resource_ref": item.resource_ref,
                    "symbol": item.symbol,
                    "asset_type": item.asset_type,
                    "triggered_at": timestamp_text(item.triggered_at),
                }
                for item in self.triggered_alerts
            ],
            "due_thesis_reviews": [
                {
                    "thesis_ref": item.thesis_ref,
                    "revision": item.revision,
                    "due_at": timestamp_text(item.due_at),
                }
                for item in self.due_thesis_reviews
            ],
        }


def utc_instant(value: object, field: str) -> datetime:
    """Validate and normalize an aware datetime to UTC."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise BriefingDomainError(f"{field} must identify a timezone-aware instant.")
    return value.astimezone(UTC)


def timestamp_text(value: datetime) -> str:
    """Serialize one aware instant in a stable UTC format."""

    return utc_instant(value, "timestamp").isoformat(timespec="microseconds").replace("+00:00", "Z")


def request_fingerprint(window: BriefingWindow, observed_as_of: datetime) -> str:
    """Hash the caller-controlled briefing body used by its idempotency key."""

    if not isinstance(window, BriefingWindow):
        raise BriefingDomainError("The briefing window is invalid.")
    material = json.dumps(
        {"window": window.value, "observed_as_of": timestamp_text(observed_as_of)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("ascii")).hexdigest()


def parse_timestamp(value: object, field: str) -> datetime:
    """Parse bounded canonical UTC text from an immutable stored snapshot."""

    if not isinstance(value, str) or len(value) > 40 or not value.endswith("Z"):
        raise BriefingDomainError(f"{field} is invalid.")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise BriefingDomainError(f"{field} is invalid.") from error
    return utc_instant(parsed, field)


def decimal_text(value: Decimal) -> str:
    """Serialize a finite Decimal without exponent or binary-float conversion."""

    if type(value) is not Decimal or not value.is_finite():
        raise BriefingDomainError("A decimal value is invalid.")
    exponent = value.as_tuple().exponent
    if type(exponent) is not int or not -18 <= exponent <= 18 or len(value.as_tuple().digits) > 32:
        raise BriefingDomainError("A decimal value is outside its supported precision.")
    return format(value, "f")


def canonical_uuid(value: object, field: str) -> str:
    """Require a canonical lowercase UUID string."""

    if not isinstance(value, str) or len(value) != 36:
        raise BriefingDomainError(f"{field} must be a canonical UUID.")
    try:
        normalized = str(UUID(value))
    except ValueError as error:
        raise BriefingDomainError(f"{field} must be a canonical UUID.") from error
    if normalized != value:
        raise BriefingDomainError(f"{field} must be a canonical UUID.")
    return value


def validate_threshold_bps(value: object) -> int:
    """Require a bounded positive price-movement threshold in basis points."""

    if (
        type(value) is not int
        or value < MIN_PRICE_CHANGE_THRESHOLD_BPS
        or value > MAX_PRICE_CHANGE_THRESHOLD_BPS
    ):
        raise BriefingDomainError("The price-change threshold is outside its supported range.")
    return value


def baseline_for_window(
    window: BriefingWindow, observed_as_of: datetime, last_visit_baseline: datetime | None
) -> datetime | None:
    """Freeze the comparison baseline for a selected briefing window."""

    if not isinstance(window, BriefingWindow):
        raise BriefingDomainError("The briefing window is invalid.")
    end = utc_instant(observed_as_of, "observed_as_of")
    if window is BriefingWindow.SINCE_LAST_VISIT:
        if last_visit_baseline is None:
            return None
        start = utc_instant(last_visit_baseline, "last_visit_baseline")
        if start > end:
            raise BriefingDomainError("The visit baseline is later than the observation time.")
        return start
    if window is BriefingWindow.LAST_24_HOURS:
        return end - timedelta(hours=24)
    if window is BriefingWindow.LAST_7_DAYS:
        return end - timedelta(days=7)
    raise BriefingDomainError("The briefing window is invalid.")


def validate_reference(value: object, field: str) -> str:
    """Validate an opaque persisted resource or provenance reference."""

    if not isinstance(value, str) or _REFERENCE_RE.fullmatch(value) is None:
        raise BriefingDomainError(f"{field} is invalid.")
    return value


def _validate_asset(symbol: object, asset_type: object) -> tuple[str, str]:
    if not isinstance(symbol, str) or _SYMBOL_RE.fullmatch(symbol) is None:
        raise BriefingDomainError("A canonical symbol is invalid.")
    if not isinstance(asset_type, str) or _ASSET_TYPE_RE.fullmatch(asset_type) is None:
        raise BriefingDomainError("An asset type is invalid.")
    return symbol, asset_type


def validate_price_observations(
    values: object, owner_user_id: int, observed_as_of: datetime
) -> tuple[PriceObservation, ...]:
    """Validate a bounded, chronologically ordered set of source observations."""

    if type(owner_user_id) is not int or owner_user_id < 1:
        raise BriefingDomainError("The owner is unavailable.")
    end = utc_instant(observed_as_of, "observed_as_of")
    if not isinstance(values, list | tuple) or len(values) > MAX_PRICE_OBSERVATIONS:
        raise BriefingDomainError("The price observation set exceeds its limit.")
    previous: tuple[datetime, datetime, str] | None = None
    checked: list[PriceObservation] = []
    source_refs: set[str] = set()
    for item in values:
        if not isinstance(item, PriceObservation):
            raise BriefingDomainError("A price observation has an invalid type.")
        if type(item.owner_user_id) is not int or item.owner_user_id != owner_user_id:
            raise BriefingDomainError("A price observation belongs to another owner.")
        validate_reference(item.source_ref, "source_ref")
        if item.source_ref in source_refs:
            raise BriefingDomainError("Price history contains a duplicate source reference.")
        source_refs.add(item.source_ref)
        _validate_asset(item.symbol, item.asset_type)
        if item.provider is not None and (
            not isinstance(item.provider, str) or _PROVIDER_RE.fullmatch(item.provider) is None
        ):
            raise BriefingDomainError("A price provider identity is invalid.")
        if item.currency is not None and (
            not isinstance(item.currency, str) or _CURRENCY_RE.fullmatch(item.currency) is None
        ):
            raise BriefingDomainError("A price currency is invalid.")
        if item.price is not None:
            if type(item.price) is not Decimal or not item.price.is_finite():
                raise BriefingDomainError("A price value must be a finite Decimal.")
            decimal_text(item.price)
        if not isinstance(item.state, str) or item.state not in {
            "initial",
            "observed",
            "unavailable",
        }:
            raise BriefingDomainError("A price observation state is invalid.")
        if item.state == "unavailable":
            if item.reason not in _PRICE_REASONS:
                raise BriefingDomainError("An unavailable price requires a known reason.")
        elif item.reason is not None:
            raise BriefingDomainError("A usable price observation cannot have an error reason.")
        observed_at = (
            utc_instant(item.observed_at, "price observed_at")
            if item.observed_at is not None
            else None
        )
        received_at = (
            utc_instant(item.received_at, "price received_at")
            if item.received_at is not None
            else None
        )
        if observed_at is None or received_at is None:
            if observed_at is not None or received_at is not None:
                raise BriefingDomainError("Price observation timestamps must be paired.")
            if item.state != "unavailable":
                raise BriefingDomainError("A price timestamp is missing.")
        elif observed_at > received_at or received_at > end:
            raise BriefingDomainError("Price observation timestamps are future or out of order.")
        else:
            order = (observed_at, received_at, item.source_ref)
            if previous is not None and order < previous:
                raise BriefingDomainError("Price observations are not in timestamp order.")
            previous = order
        checked.append(item)
    return tuple(checked)


def summarize_price_movements(
    observations: tuple[PriceObservation, ...],
    *,
    owner_user_id: int,
    baseline_at: datetime | None,
    observed_as_of: datetime,
    threshold_bps: int = DEFAULT_PRICE_CHANGE_THRESHOLD_BPS,
) -> tuple[PriceMovementSummary, ...]:
    """Compare native-currency observations without treating first sighting as a change."""

    threshold = validate_threshold_bps(threshold_bps)
    end = utc_instant(observed_as_of, "observed_as_of")
    start = utc_instant(baseline_at, "baseline_at") if baseline_at is not None else None
    values = validate_price_observations(observations, owner_user_id, end)
    grouped: dict[tuple[str, str], list[PriceObservation]] = {}
    for item in values:
        grouped.setdefault((item.symbol, item.asset_type), []).append(item)

    summaries: list[PriceMovementSummary] = []
    for (symbol, asset_type), items in sorted(grouped.items()):
        valid_times = [item for item in items if item.observed_at is not None]
        if not valid_times:
            latest = items[-1]
            summaries.append(
                PriceMovementSummary(
                    symbol,
                    asset_type,
                    "unavailable",
                    start,
                    None,
                    latest.currency,
                    latest.provider,
                    None,
                    latest.reason or "timestamp_unavailable",
                    received_at=latest.received_at,
                )
            )
            continue
        valid_times.sort(key=lambda point: (point.observed_at, point.received_at, point.source_ref))
        if start is None:
            latest = valid_times[-1]
            state = "unavailable" if latest.state == "unavailable" else "first_observation"
            summaries.append(
                PriceMovementSummary(
                    symbol,
                    asset_type,
                    state,
                    None,
                    latest.observed_at,
                    latest.currency,
                    latest.provider,
                    None,
                    latest.reason if state == "unavailable" else "no_prior_visit_baseline",
                    received_at=latest.received_at,
                )
            )
            continue

        previous = [
            item
            for item in valid_times
            if item.observed_at is not None and item.observed_at <= start
        ]
        current = [
            item
            for item in valid_times
            if item.observed_at is not None and item.observed_at > start
        ]
        if not current:
            latest = valid_times[-1]
            state = "first_observation" if latest.state == "initial" else "insufficient_history"
            summaries.append(
                PriceMovementSummary(
                    symbol,
                    asset_type,
                    state,
                    start,
                    latest.observed_at,
                    latest.currency,
                    latest.provider,
                    None,
                    "no_observation_after_baseline",
                    received_at=latest.received_at,
                )
            )
            continue
        newest = current[-1]
        if newest.state == "initial":
            summaries.append(
                PriceMovementSummary(
                    symbol,
                    asset_type,
                    "first_observation",
                    start,
                    newest.observed_at,
                    newest.currency,
                    newest.provider,
                    None,
                    "initial_observation_does_not_establish_change",
                    received_at=newest.received_at,
                )
            )
            continue
        if newest.state == "unavailable":
            summaries.append(
                PriceMovementSummary(
                    symbol,
                    asset_type,
                    "unavailable",
                    start,
                    newest.observed_at,
                    newest.currency,
                    newest.provider,
                    None,
                    newest.reason or "provider_unavailable",
                    received_at=newest.received_at,
                )
            )
            continue
        if not previous:
            summaries.append(
                PriceMovementSummary(
                    symbol,
                    asset_type,
                    "insufficient_history",
                    start,
                    newest.observed_at,
                    newest.currency,
                    newest.provider,
                    None,
                    "no_price_at_or_before_baseline",
                    received_at=newest.received_at,
                )
            )
            continue

        base = previous[-1]
        reason: str | None = None
        state = "threshold_crossed"
        change: Decimal | None = None
        currency = newest.currency if newest.currency == base.currency else None
        provider = newest.provider if newest.provider == base.provider else None
        if base.state == "unavailable":
            state, reason = "unavailable", base.reason or "provider_unavailable"
        elif base.currency is None or newest.currency is None:
            state, reason = "unavailable", "currency_unavailable"
        elif base.currency != newest.currency:
            state, reason = "unavailable", "currency_mismatch"
        elif base.provider is None or newest.provider is None:
            state, reason = "unavailable", "provider_unavailable"
        elif base.provider != newest.provider:
            state, reason = "unavailable", "provider_mismatch"
        elif base.price is None or newest.price is None:
            state, reason = "unavailable", "price_unavailable"
        elif base.price <= 0 or newest.price <= 0:
            state, reason = "unavailable", "invalid_price"
        else:
            exact_change_bps = (
                (Fraction(newest.price) - Fraction(base.price)) * 10_000 / Fraction(base.price)
            )
            # Decimal division obeys the ambient precision context, so it cannot decide a
            # threshold boundary for every accepted input. Keep only the display value rounded.
            change = Decimal(exact_change_bps.numerator) / Decimal(exact_change_bps.denominator)
            if abs(exact_change_bps) < threshold:
                state = "below_threshold"
        summaries.append(
            PriceMovementSummary(
                symbol,
                asset_type,
                state,
                base.observed_at,
                newest.observed_at,
                currency,
                provider,
                change,
                reason,
                baseline_received_at=base.received_at,
                received_at=newest.received_at,
            )
        )
    return tuple(summaries)


def validate_outcome_changes(
    values: object,
    *,
    owner_user_id: int,
    baseline_at: datetime | None,
    observed_as_of: datetime,
) -> tuple[ForecastOutcomeChange, ...]:
    """Validate bounded outcome revisions and retain corrections without outcome scoring."""

    start = utc_instant(baseline_at, "baseline_at") if baseline_at is not None else None
    end = utc_instant(observed_as_of, "observed_as_of")
    if not isinstance(values, list | tuple) or len(values) > MAX_SOURCE_ITEMS:
        raise BriefingDomainError("The outcome change set exceeds its limit.")
    checked: list[ForecastOutcomeChange] = []
    previous: datetime | None = None
    source_refs: set[str] = set()
    for item in values:
        if not isinstance(item, ForecastOutcomeChange) or type(item.owner_user_id) is not int:
            raise BriefingDomainError("An outcome change has an invalid type or owner.")
        if item.owner_user_id != owner_user_id:
            raise BriefingDomainError("An outcome change belongs to another owner.")
        validate_reference(item.resource_ref, "outcome resource reference")
        validate_reference(item.source_ref, "outcome source reference")
        if item.source_ref in source_refs:
            raise BriefingDomainError("Outcome evidence contains a duplicate source reference.")
        source_refs.add(item.source_ref)
        if item.correction_of is not None:
            validate_reference(item.correction_of, "correction reference")
        if not isinstance(item.state, str) or item.state not in {
            "observed",
            "corrected",
            "unavailable",
            "incomparable",
            "manual_review",
        }:
            raise BriefingDomainError("An outcome evidence state is invalid.")
        if type(item.revision) is not int or item.revision < 1:
            raise BriefingDomainError("An outcome revision is invalid.")
        recorded_at = utc_instant(item.recorded_at, "outcome recorded_at")
        observed_at = (
            utc_instant(item.observed_at, "outcome observed_at")
            if item.observed_at is not None
            else None
        )
        if recorded_at > end or (observed_at is not None and observed_at > recorded_at):
            raise BriefingDomainError("Outcome timestamps are future or out of order.")
        if previous is not None and recorded_at < previous:
            raise BriefingDomainError("Outcome revisions are not in timestamp order.")
        previous = recorded_at
        if item.state == "corrected" and item.correction_of is None:
            raise BriefingDomainError("A corrected outcome must reference the superseded record.")
        if start is not None and recorded_at <= start:
            continue
        checked.append(item)
    return tuple(checked)


def validate_triggered_alerts(
    values: object, *, owner_user_id: int, baseline_at: datetime | None, observed_as_of: datetime
) -> tuple[TriggeredAlertSummary, ...]:
    """Validate owner-scoped, bounded alert summaries and filter to the frozen window."""

    start = utc_instant(baseline_at, "baseline_at") if baseline_at is not None else None
    end = utc_instant(observed_as_of, "observed_as_of")
    if not isinstance(values, list | tuple) or len(values) > MAX_SOURCE_ITEMS:
        raise BriefingDomainError("The triggered alert set exceeds its limit.")
    checked: list[TriggeredAlertSummary] = []
    previous: datetime | None = None
    events: set[tuple[str, datetime]] = set()
    for item in values:
        if not isinstance(item, TriggeredAlertSummary) or type(item.owner_user_id) is not int:
            raise BriefingDomainError("A triggered alert has an invalid type or owner.")
        if item.owner_user_id != owner_user_id:
            raise BriefingDomainError("A triggered alert belongs to another owner.")
        validate_reference(item.resource_ref, "alert resource reference")
        symbol, asset_type = _validate_asset(item.symbol, item.asset_type)
        triggered_at = utc_instant(item.triggered_at, "alert triggered_at")
        event_key = (item.resource_ref, triggered_at)
        if event_key in events:
            raise BriefingDomainError("Triggered alerts contain a duplicate event.")
        events.add(event_key)
        if triggered_at > end:
            raise BriefingDomainError("An alert timestamp is later than the observation time.")
        if previous is not None and triggered_at < previous:
            raise BriefingDomainError("Alert events are not in timestamp order.")
        previous = triggered_at
        if start is None or triggered_at > start:
            checked.append(item)
    return tuple(checked)


def validate_due_thesis_reviews(
    values: object, *, owner_user_id: int, observed_as_of: datetime
) -> tuple[DueThesisReviewSummary, ...]:
    """Validate due review references without admitting thesis text or titles."""

    end = utc_instant(observed_as_of, "observed_as_of")
    if not isinstance(values, list | tuple) or len(values) > MAX_SOURCE_ITEMS:
        raise BriefingDomainError("The due thesis review set exceeds its limit.")
    checked: list[DueThesisReviewSummary] = []
    previous: datetime | None = None
    revisions: set[tuple[str, int]] = set()
    for item in values:
        if not isinstance(item, DueThesisReviewSummary) or type(item.owner_user_id) is not int:
            raise BriefingDomainError("A thesis review has an invalid type or owner.")
        if item.owner_user_id != owner_user_id:
            raise BriefingDomainError("A thesis review belongs to another owner.")
        validate_reference(item.thesis_ref, "thesis reference")
        due_at = utc_instant(item.due_at, "thesis due_at")
        if type(item.revision) is not int or item.revision < 1:
            raise BriefingDomainError("A thesis revision is invalid.")
        revision_key = (item.thesis_ref, item.revision)
        if revision_key in revisions:
            raise BriefingDomainError("Thesis reviews contain a duplicate revision.")
        revisions.add(revision_key)
        if due_at > end:
            raise BriefingDomainError("A thesis review is not due at the observation time.")
        if previous is not None and due_at < previous:
            raise BriefingDomainError("Thesis reviews are not in timestamp order.")
        previous = due_at
        checked.append(item)
    return tuple(checked)
