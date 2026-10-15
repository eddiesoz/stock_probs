"""Owner-authorized deterministic briefing orchestration over injected local adapters."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from stock_probs.briefing_domain import (
    MAX_PRICE_OBSERVATIONS,
    MAX_SOURCE_ITEMS,
    BriefingDomainError,
    BriefingSnapshot,
    BriefingWindow,
    DueThesisReviewSummary,
    ForecastOutcomeChange,
    PriceObservation,
    TriggeredAlertSummary,
    baseline_for_window,
    canonical_uuid,
    request_fingerprint,
    summarize_price_movements,
    utc_instant,
    validate_due_thesis_reviews,
    validate_outcome_changes,
    validate_price_observations,
    validate_threshold_bps,
    validate_triggered_alerts,
)
from stock_probs.briefing_store import (
    BriefingCapacityError,
    BriefingConflictError,
    BriefingStore,
    BriefingStoreError,
    BriefingUnavailableError,
    PriceThresholdPreference,
    SnapshotPage,
    VisitAnchor,
)

MAX_STORED_PRICE_HISTORY = MAX_PRICE_OBSERVATIONS
MAX_SNAPSHOT_ITEMS_PER_SOURCE = MAX_SOURCE_ITEMS


class BriefingPriceSource(Protocol):
    """Read a bounded set of persisted price observations for one active owner."""

    def list_price_observations(
        self, owner_user_id: int, *, observed_as_of: datetime, limit: int
    ) -> Sequence[PriceObservation]:
        """Return immutable observations already recorded by an allowed source."""


class BriefingOutcomeSource(Protocol):
    """Read corrected or unavailable forecast evidence without scoring predictions."""

    def list_outcome_changes(
        self,
        owner_user_id: int,
        *,
        baseline_at: datetime | None,
        observed_as_of: datetime,
        limit: int,
    ) -> Sequence[ForecastOutcomeChange]:
        """Return explicit outcome evidence revisions for the frozen interval."""


class BriefingAlertSource(Protocol):
    """Read bounded persisted alert events for one active owner."""

    def list_triggered_alerts(
        self,
        owner_user_id: int,
        *,
        baseline_at: datetime | None,
        observed_as_of: datetime,
        limit: int,
    ) -> Sequence[TriggeredAlertSummary]:
        """Return changed alert references without notification delivery side effects."""


class BriefingThesisSource(Protocol):
    """Read due thesis-review references without exposing thesis text."""

    def list_due_thesis_reviews(
        self, owner_user_id: int, *, observed_as_of: datetime, limit: int
    ) -> Sequence[DueThesisReviewSummary]:
        """Return due authenticated resource references and revision numbers only."""


class BriefingServiceError(ValueError):
    """Safe failure of briefing request validation or source projection."""


class BriefingAccessDeniedError(BriefingServiceError):
    """The current caller cannot read or change this owner's briefing data."""


class BriefingSourceUnavailableError(BriefingServiceError):
    """A local source adapter failed or exceeded its bounded result contract."""


OwnerAuthorizer = Callable[[int], object]
Clock = Callable[[], datetime]


class BriefingService:
    """Build deterministic snapshots without invoking providers, models, headlines, or mail."""

    def __init__(
        self,
        store: BriefingStore,
        *,
        price_source: BriefingPriceSource,
        outcome_source: BriefingOutcomeSource,
        alert_source: BriefingAlertSource,
        thesis_source: BriefingThesisSource,
        owner_authorizer: OwnerAuthorizer,
        clock: Clock | None = None,
    ) -> None:
        if not isinstance(store, BriefingStore):
            raise TypeError("store must be a BriefingStore")
        for name, source in (
            ("price_source", price_source),
            ("outcome_source", outcome_source),
            ("alert_source", alert_source),
            ("thesis_source", thesis_source),
        ):
            if source is None:
                raise TypeError(f"{name} is required")
        if not callable(owner_authorizer):
            raise TypeError("owner_authorizer must be callable")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self.store = store
        self.price_source = price_source
        self.outcome_source = outcome_source
        self.alert_source = alert_source
        self.thesis_source = thesis_source
        self.owner_authorizer = owner_authorizer
        self.clock = clock or (lambda: datetime.now(UTC))

    def _authorize(self, owner_user_id: object) -> int:
        if type(owner_user_id) is not int or owner_user_id < 1:
            raise BriefingAccessDeniedError("The briefing is unavailable.")
        try:
            allowed = self.owner_authorizer(owner_user_id)
        except Exception as error:
            raise BriefingAccessDeniedError("The briefing is unavailable.") from error
        if allowed is not True:
            raise BriefingAccessDeniedError("The briefing is unavailable.")
        return owner_user_id

    def _commit_authorized(self, owner_user_id: int) -> bool:
        try:
            self._authorize(owner_user_id)
        except BriefingAccessDeniedError:
            return False
        return True

    def _now(self) -> datetime:
        try:
            return utc_instant(self.clock(), "clock")
        except BriefingDomainError as error:
            raise BriefingServiceError("The briefing clock is invalid.") from error

    @staticmethod
    def _request_hash(window: BriefingWindow, as_of: datetime) -> str:
        return request_fingerprint(window, as_of)

    @staticmethod
    def _bounded_result(value: object, field: str, limit: int) -> tuple[object, ...]:
        if not isinstance(value, tuple | list) or len(value) > limit:
            raise BriefingSourceUnavailableError(f"The {field} source exceeded its result limit.")
        return tuple(value)

    def generate(
        self,
        owner_user_id: int,
        *,
        idempotency_key: str,
        window: BriefingWindow,
        observed_as_of: datetime,
    ) -> BriefingSnapshot:
        """Freeze one owner-scoped snapshot at an explicit as-of timestamp."""

        owner = self._authorize(owner_user_id)
        try:
            key = canonical_uuid(idempotency_key, "idempotency_key")
            selected_window = (
                window if isinstance(window, BriefingWindow) else BriefingWindow(window)
            )
            as_of = utc_instant(observed_as_of, "observed_as_of")
        except (BriefingDomainError, TypeError, ValueError) as error:
            raise BriefingServiceError("The briefing request is invalid.") from error
        if as_of > self._now():
            raise BriefingServiceError("The briefing observation time cannot be in the future.")
        request_sha256 = self._request_hash(selected_window, as_of)
        try:
            existing = self.store.get_snapshot_by_idempotency(owner, key, request_sha256)
        except BriefingConflictError:
            raise
        except BriefingStoreError as error:
            raise BriefingServiceError("The briefing request could not be read.") from error
        if existing is not None:
            self._authorize(owner)
            return existing

        try:
            preference = self.store.get_preference(owner)
            anchor = self.store.get_visit_anchor(owner)
            threshold = validate_threshold_bps(preference.threshold_bps)
            baseline = baseline_for_window(selected_window, as_of, anchor.baseline_at)
            history = self.store.list_price_observations(owner, through=as_of)
            self._authorize(owner)
            incoming = validate_price_observations(
                self._bounded_result(
                    self.price_source.list_price_observations(
                        owner, observed_as_of=as_of, limit=MAX_SNAPSHOT_ITEMS_PER_SOURCE
                    ),
                    "price",
                    MAX_SNAPSHOT_ITEMS_PER_SOURCE,
                ),
                owner,
                as_of,
            )
            combined = _merge_price_observations(history, incoming, owner, as_of)
            self._authorize(owner)
            outcomes = validate_outcome_changes(
                self._bounded_result(
                    self.outcome_source.list_outcome_changes(
                        owner,
                        baseline_at=baseline,
                        observed_as_of=as_of,
                        limit=MAX_SNAPSHOT_ITEMS_PER_SOURCE,
                    ),
                    "outcome",
                    MAX_SNAPSHOT_ITEMS_PER_SOURCE,
                ),
                owner_user_id=owner,
                baseline_at=baseline,
                observed_as_of=as_of,
            )
            self._authorize(owner)
            alerts = validate_triggered_alerts(
                self._bounded_result(
                    self.alert_source.list_triggered_alerts(
                        owner,
                        baseline_at=baseline,
                        observed_as_of=as_of,
                        limit=MAX_SNAPSHOT_ITEMS_PER_SOURCE,
                    ),
                    "alert",
                    MAX_SNAPSHOT_ITEMS_PER_SOURCE,
                ),
                owner_user_id=owner,
                baseline_at=baseline,
                observed_as_of=as_of,
            )
            self._authorize(owner)
            reviews = validate_due_thesis_reviews(
                self._bounded_result(
                    self.thesis_source.list_due_thesis_reviews(
                        owner, observed_as_of=as_of, limit=MAX_SNAPSHOT_ITEMS_PER_SOURCE
                    ),
                    "thesis review",
                    MAX_SNAPSHOT_ITEMS_PER_SOURCE,
                ),
                owner_user_id=owner,
                observed_as_of=as_of,
            )
            price_changes = summarize_price_movements(
                combined,
                owner_user_id=owner,
                baseline_at=baseline,
                observed_as_of=as_of,
                threshold_bps=threshold,
            )
            now = self._now()
            snapshot = BriefingSnapshot(
                snapshot_id=str(uuid4()),
                owner_user_id=owner,
                idempotency_key=key,
                request_sha256=request_sha256,
                window=selected_window,
                baseline_at=baseline,
                observed_as_of=as_of,
                baseline_anchor_revision=anchor.revision,
                preference_revision=preference.revision,
                threshold_bps=threshold,
                generated_at=now,
                price_changes=price_changes,
                outcome_changes=outcomes,
                triggered_alerts=alerts,
                due_thesis_reviews=reviews,
            )
            return self.store.create_snapshot(
                snapshot,
                observations=incoming,
                expected_preference_revision=preference.revision,
                expected_anchor_revision=anchor.revision,
                commit_guard=lambda: self._commit_authorized(owner),
            )
        except (
            BriefingAccessDeniedError,
            BriefingCapacityError,
            BriefingConflictError,
            BriefingUnavailableError,
        ):
            raise
        except BriefingStoreError as error:
            raise BriefingServiceError("The briefing could not be saved.") from error
        except BriefingDomainError as error:
            raise BriefingServiceError("A briefing source returned invalid evidence.") from error
        except Exception as error:
            raise BriefingSourceUnavailableError("A briefing source is unavailable.") from error

    def get_snapshot(self, owner_user_id: int, snapshot_id: str) -> BriefingSnapshot:
        """Reopen one immutable snapshot without changing its baseline or visit anchor."""

        owner = self._authorize(owner_user_id)
        return self.store.get_snapshot(owner, snapshot_id)

    def list_snapshots(
        self, owner_user_id: int, *, limit: int = 20, cursor: str | None = None
    ) -> SnapshotPage:
        """Return a bounded owner-only history page."""

        owner = self._authorize(owner_user_id)
        return self.store.list_snapshots(owner, limit=limit, cursor=cursor)

    def get_preference(self, owner_user_id: int) -> PriceThresholdPreference:
        """Read the current owner threshold preference."""

        owner = self._authorize(owner_user_id)
        return self.store.get_preference(owner)

    def update_preference(
        self,
        owner_user_id: int,
        threshold_bps: int,
        *,
        expected_revision: int,
    ) -> PriceThresholdPreference:
        """Append a preference revision using the injected wall clock and exact CAS revision."""

        owner = self._authorize(owner_user_id)
        try:
            threshold = validate_threshold_bps(threshold_bps)
        except BriefingDomainError as error:
            raise BriefingServiceError("The price threshold is invalid.") from error
        return self.store.update_preference(
            owner,
            threshold,
            expected_revision=expected_revision,
            updated_at=self._now(),
        )

    def record_visit(
        self, owner_user_id: int, snapshot_id: str, *, expected_revision: int
    ) -> VisitAnchor:
        """Explicitly advance the visit anchor to this snapshot's frozen as-of time."""

        owner = self._authorize(owner_user_id)
        return self.store.record_visit(
            owner,
            snapshot_id,
            expected_revision=expected_revision,
            visited_at=self._now(),
        )


def _merge_price_observations(
    history: tuple[PriceObservation, ...],
    incoming: tuple[PriceObservation, ...],
    owner_user_id: int,
    observed_as_of: datetime,
) -> tuple[PriceObservation, ...]:
    """Combine immutable local history and source additions without accepting ref rewrites."""

    if len(history) + len(incoming) > MAX_STORED_PRICE_HISTORY * 2:
        raise BriefingServiceError("The price history exceeds its bounded merge limit.")
    combined: dict[str, PriceObservation] = {}
    for item in (*history, *incoming):
        old = combined.get(item.source_ref)
        if old is not None and old != item:
            raise BriefingConflictError("A price source reference has conflicting content.")
        combined[item.source_ref] = item
    values = list(combined.values())
    values.sort(
        key=lambda item: (
            item.observed_at is None,
            item.observed_at or datetime.max.replace(tzinfo=UTC),
            item.received_at or datetime.max.replace(tzinfo=UTC),
            item.source_ref,
        )
    )
    if len(values) > MAX_STORED_PRICE_HISTORY:
        raise BriefingServiceError("The owner price history reached its retained-row capacity.")
    return validate_price_observations(values, owner_user_id, observed_as_of)
