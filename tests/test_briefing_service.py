"""Injected-adapter service tests for R4's frozen owner-scoped briefing contract."""

from __future__ import annotations

import ast
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from stock_probs.briefing_domain import (
    BriefingWindow,
    DueThesisReviewSummary,
    ForecastOutcomeChange,
    PriceObservation,
    TriggeredAlertSummary,
    summarize_price_movements,
)
from stock_probs.briefing_service import (
    BriefingAccessDeniedError,
    BriefingService,
    BriefingServiceError,
)
from stock_probs.briefing_store import (
    BriefingConflictError,
    BriefingStore,
    BriefingUnavailableError,
)
from stock_probs.repository import Repository

NOW = datetime(2026, 10, 14, 12, tzinfo=UTC)


class FakeClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class PriceSource:
    def __init__(self) -> None:
        self.rows: Sequence[PriceObservation] = ()
        self.calls = 0
        self.after_read: Callable[[], None] | None = None

    def list_price_observations(
        self, owner_user_id: int, *, observed_as_of: datetime, limit: int
    ) -> Sequence[PriceObservation]:
        self.calls += 1
        rows = self.rows
        if self.after_read is not None:
            self.after_read()
        return rows


class OutcomeSource:
    def __init__(self) -> None:
        self.rows: Sequence[ForecastOutcomeChange] = ()
        self.calls = 0

    def list_outcome_changes(
        self,
        owner_user_id: int,
        *,
        baseline_at: datetime | None,
        observed_as_of: datetime,
        limit: int,
    ) -> Sequence[ForecastOutcomeChange]:
        self.calls += 1
        return self.rows


class AlertSource:
    def __init__(self) -> None:
        self.rows: Sequence[TriggeredAlertSummary] = ()
        self.calls = 0

    def list_triggered_alerts(
        self,
        owner_user_id: int,
        *,
        baseline_at: datetime | None,
        observed_as_of: datetime,
        limit: int,
    ) -> Sequence[TriggeredAlertSummary]:
        self.calls += 1
        return self.rows


class ThesisSource:
    def __init__(self) -> None:
        self.rows: Sequence[DueThesisReviewSummary] = ()
        self.calls = 0
        self.after_read: Callable[[], None] | None = None

    def list_due_thesis_reviews(
        self, owner_user_id: int, *, observed_as_of: datetime, limit: int
    ) -> Sequence[DueThesisReviewSummary]:
        self.calls += 1
        rows = self.rows
        if self.after_read is not None:
            self.after_read()
        return rows


@pytest.fixture
def service_parts(tmp_path: Path):
    repository = Repository(tmp_path / "briefing-service.sqlite3")
    repository.migrate()
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO users(id,display_name,role,status,created_at,updated_at) "
            "VALUES(2,'Briefing member','member','active',?,?)",
            ("2026-10-14T00:00:00Z", "2026-10-14T00:00:00Z"),
        )
        connection.commit()
    price, outcome, alert, thesis = PriceSource(), OutcomeSource(), AlertSource(), ThesisSource()
    clock = FakeClock(NOW + timedelta(days=10))
    service = BriefingService(
        BriefingStore(repository),
        price_source=price,
        outcome_source=outcome,
        alert_source=alert,
        thesis_source=thesis,
        owner_authorizer=lambda owner: owner == 2,
        clock=clock,
    )
    return service, price, outcome, alert, thesis, clock, repository


def _point(
    ref: str, price: str, observed_at: datetime, *, state: str = "observed"
) -> PriceObservation:
    return PriceObservation(
        owner_user_id=2,
        source_ref=ref,
        symbol="SPY",
        asset_type="etf",
        provider="FixtureProvider",
        currency="USD",
        price=Decimal(price),
        observed_at=observed_at,
        received_at=observed_at + timedelta(seconds=1),
        state=state,  # type: ignore[arg-type]
    )


def _calls(
    price: PriceSource, outcome: OutcomeSource, alert: AlertSource, thesis: ThesisSource
) -> tuple[int, ...]:
    return price.calls, outcome.calls, alert.calls, thesis.calls


def test_generation_combines_prices_corrections_alerts_and_due_reviews(service_parts) -> None:
    service, price, outcome, alert, thesis, clock, repository = service_parts
    first_as_of = NOW + timedelta(minutes=5)
    price.rows = (_point("initial-price", "100", NOW, state="initial"),)
    initial = service.generate(
        2,
        idempotency_key=str(uuid4()),
        window=BriefingWindow.SINCE_LAST_VISIT,
        observed_as_of=first_as_of,
    )
    assert initial.price_changes[0].state == "first_observation"
    assert initial.price_changes[0].change_bps is None
    assert initial.baseline_at is None
    assert initial.threshold_bps == 300

    service.record_visit(2, initial.snapshot_id, expected_revision=0)
    anchor = service.store.get_visit_anchor(2)
    assert anchor.baseline_at == first_as_of

    second_as_of = NOW + timedelta(hours=2)
    clock.value = NOW + timedelta(hours=3)
    price.rows = (_point("next-price", "103", NOW + timedelta(hours=1)),)
    outcome.rows = (
        ForecastOutcomeChange(
            owner_user_id=2,
            resource_ref="forecast:42",
            source_ref="evidence:42-r2",
            state="corrected",
            revision=2,
            recorded_at=NOW + timedelta(hours=1, minutes=10),
            observed_at=NOW + timedelta(hours=1),
            correction_of="evidence:42-r1",
        ),
    )
    alert.rows = (
        TriggeredAlertSummary(2, "alert:abc", "SPY", "etf", NOW + timedelta(hours=1, minutes=15)),
    )
    thesis.rows = (DueThesisReviewSummary(2, "thesis:abc", 3, NOW + timedelta(hours=1)),)

    snapshot = service.generate(
        2,
        idempotency_key=str(uuid4()),
        window=BriefingWindow.SINCE_LAST_VISIT,
        observed_as_of=second_as_of,
    )
    assert snapshot.baseline_at == first_as_of
    assert snapshot.observed_as_of == second_as_of
    assert snapshot.price_changes[0].state == "threshold_crossed"
    assert snapshot.price_changes[0].change_bps == Decimal("300")
    assert snapshot.price_changes[0].received_at == NOW + timedelta(hours=1, seconds=1)
    assert snapshot.outcome_changes[0].state == "corrected"
    assert snapshot.outcome_changes[0].correction_of == "evidence:42-r1"
    assert snapshot.triggered_alerts[0].resource_ref == "alert:abc"
    assert snapshot.due_thesis_reviews[0].thesis_ref == "thesis:abc"

    payload = snapshot.payload()
    encoded = json.dumps(payload, sort_keys=True)
    assert "headline" not in encoded.lower()
    assert "score" not in encoded.lower()
    assert "balance" not in encoded.lower()
    assert "thesis body" not in encoded.lower()
    assert "title" not in payload["due_thesis_reviews"][0]
    assert service.get_snapshot(2, snapshot.snapshot_id) == snapshot
    assert service.store.get_visit_anchor(2) == anchor
    assert repository.database_path.exists()


def test_idempotent_replay_skips_every_adapter_and_preserves_frozen_snapshot(service_parts) -> None:
    service, price, outcome, alert, thesis, clock, _repository = service_parts
    as_of = NOW + timedelta(minutes=2)
    key = str(uuid4())
    price.rows = (_point("first-price", "100", NOW, state="initial"),)
    first = service.generate(
        2, idempotency_key=key, window=BriefingWindow.LAST_24_HOURS, observed_as_of=as_of
    )
    call_counts = _calls(price, outcome, alert, thesis)
    price.rows = (_point("changed-source", "200", NOW + timedelta(minutes=1)),)
    clock.value += timedelta(days=1)

    replay = service.generate(
        2, idempotency_key=key, window=BriefingWindow.LAST_24_HOURS, observed_as_of=as_of
    )
    assert replay == first
    assert _calls(price, outcome, alert, thesis) == call_counts
    assert replay.baseline_at == as_of - timedelta(hours=24)
    with pytest.raises(BriefingConflictError, match="another request"):
        service.generate(
            2, idempotency_key=key, window=BriefingWindow.LAST_7_DAYS, observed_as_of=as_of
        )
    assert _calls(price, outcome, alert, thesis) == call_counts


def test_admin_or_revoked_callback_cannot_skip_owner_authorization(service_parts) -> None:
    service, price, outcome, alert, thesis, _clock, _repository = service_parts
    calls_before = _calls(price, outcome, alert, thesis)
    with pytest.raises(BriefingAccessDeniedError):
        service.generate(
            1,
            idempotency_key=str(uuid4()),
            window=BriefingWindow.SINCE_LAST_VISIT,
            observed_as_of=NOW,
        )
    assert _calls(price, outcome, alert, thesis) == calls_before

    revoked = BriefingService(
        service.store,
        price_source=price,
        outcome_source=outcome,
        alert_source=alert,
        thesis_source=thesis,
        owner_authorizer=lambda _owner: False,
        clock=lambda: NOW + timedelta(days=1),
    )
    with pytest.raises(BriefingAccessDeniedError):
        revoked.generate(
            2,
            idempotency_key=str(uuid4()),
            window=BriefingWindow.SINCE_LAST_VISIT,
            observed_as_of=NOW,
        )
    assert _calls(price, outcome, alert, thesis) == calls_before

    truthy_not_true = BriefingService(
        service.store,
        price_source=price,
        outcome_source=outcome,
        alert_source=alert,
        thesis_source=thesis,
        owner_authorizer=lambda _owner: 1,
        clock=lambda: NOW + timedelta(days=1),
    )
    with pytest.raises(BriefingAccessDeniedError):
        truthy_not_true.generate(
            2,
            idempotency_key=str(uuid4()),
            window=BriefingWindow.SINCE_LAST_VISIT,
            observed_as_of=NOW,
        )
    assert _calls(price, outcome, alert, thesis) == calls_before


def test_source_owner_mismatch_future_timestamp_and_float_are_rejected_before_persistence(
    service_parts,
) -> None:
    service, price, outcome, alert, thesis, _clock, repository = service_parts
    price.rows = (
        PriceObservation(
            owner_user_id=1,
            source_ref="foreign-price",
            symbol="SPY",
            asset_type="etf",
            provider="FixtureProvider",
            currency="USD",
            price=Decimal("100"),
            observed_at=NOW,
            received_at=NOW,
            state="initial",
        ),
    )
    with pytest.raises(BriefingServiceError, match="source returned invalid"):
        service.generate(
            2,
            idempotency_key=str(uuid4()),
            window=BriefingWindow.SINCE_LAST_VISIT,
            observed_as_of=NOW + timedelta(minutes=1),
        )
    with repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM briefing_snapshots").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM briefing_price_observations").fetchone()[0]
            == 0
        )

    price.rows = (_point("future", "100", NOW + timedelta(hours=2)),)
    with pytest.raises(BriefingServiceError, match="source returned invalid"):
        service.generate(
            2,
            idempotency_key=str(uuid4()),
            window=BriefingWindow.SINCE_LAST_VISIT,
            observed_as_of=NOW + timedelta(hours=1),
        )
    with repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM briefing_snapshots").fetchone()[0] == 0


def test_session_revocation_between_sources_stops_before_later_adapters_and_writes(
    service_parts,
) -> None:
    service, price, outcome, alert, thesis, _clock, repository = service_parts
    session = {"active": True}
    price.rows = (_point("revoked-before-commit", "100", NOW),)
    price.after_read = lambda: session.update(active=False)
    guarded = BriefingService(
        service.store,
        price_source=price,
        outcome_source=outcome,
        alert_source=alert,
        thesis_source=thesis,
        owner_authorizer=lambda owner: owner == 2 and session["active"],
        clock=lambda: NOW + timedelta(hours=1),
    )

    with pytest.raises(BriefingAccessDeniedError):
        guarded.generate(
            2,
            idempotency_key=str(uuid4()),
            window=BriefingWindow.SINCE_LAST_VISIT,
            observed_as_of=NOW + timedelta(minutes=1),
        )

    assert _calls(price, outcome, alert, thesis) == (1, 0, 0, 0)
    with repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM briefing_snapshots").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM briefing_price_observations").fetchone()[0]
            == 0
        )


def test_canary_demotion_at_persistence_boundary_creates_no_snapshot_or_prices(
    service_parts,
) -> None:
    service, price, outcome, alert, thesis, _clock, repository = service_parts
    canary = {"active": True}
    price.rows = (_point("canary-demoted-before-commit", "100", NOW),)
    thesis.after_read = lambda: canary.update(active=False)
    guarded = BriefingService(
        service.store,
        price_source=price,
        outcome_source=outcome,
        alert_source=alert,
        thesis_source=thesis,
        owner_authorizer=lambda owner: owner == 2 and canary["active"],
        clock=lambda: NOW + timedelta(hours=1),
    )

    with pytest.raises(BriefingUnavailableError):
        guarded.generate(
            2,
            idempotency_key=str(uuid4()),
            window=BriefingWindow.SINCE_LAST_VISIT,
            observed_as_of=NOW + timedelta(minutes=1),
        )

    assert _calls(price, outcome, alert, thesis) == (1, 1, 1, 1)
    with repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM briefing_snapshots").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM briefing_price_observations").fetchone()[0]
            == 0
        )


def test_preference_cas_controls_future_snapshot_without_rewriting_old_snapshot(
    service_parts,
) -> None:
    service, price, _outcome, _alert, _thesis, clock, _repository = service_parts
    as_of = NOW + timedelta(minutes=1)
    price.rows = (_point("base", "100", NOW, state="initial"),)
    first = service.generate(
        2,
        idempotency_key=str(uuid4()),
        window=BriefingWindow.SINCE_LAST_VISIT,
        observed_as_of=as_of,
    )
    service.record_visit(2, first.snapshot_id, expected_revision=0)
    pref = service.update_preference(2, 500, expected_revision=0)
    assert (pref.revision, pref.threshold_bps) == (1, 500)
    clock.value = NOW + timedelta(hours=2)
    price.rows = (_point("current", "104", NOW + timedelta(hours=1)),)
    second = service.generate(
        2,
        idempotency_key=str(uuid4()),
        window=BriefingWindow.SINCE_LAST_VISIT,
        observed_as_of=NOW + timedelta(hours=1, minutes=30),
    )
    assert second.price_changes[0].state == "below_threshold"
    assert second.price_changes[0].change_bps == Decimal("400")
    next_pref = service.update_preference(2, 300, expected_revision=1)
    assert (next_pref.revision, next_pref.threshold_bps) == (2, 300)
    clock.value = NOW + timedelta(hours=3)
    price.rows = (_point("current-after-preference", "103", NOW + timedelta(hours=2)),)
    third = service.generate(
        2,
        idempotency_key=str(uuid4()),
        window=BriefingWindow.SINCE_LAST_VISIT,
        observed_as_of=NOW + timedelta(hours=2, minutes=30),
    )
    assert first.threshold_bps == 300
    assert second.threshold_bps == 500
    assert third.price_changes[0].state == "threshold_crossed"
    assert third.price_changes[0].change_bps == Decimal("300")
    assert service.get_snapshot(2, first.snapshot_id) == first


def test_briefing_modules_have_no_outbound_transport_imports() -> None:
    root = Path(__file__).parents[1] / "src/stock_probs"
    forbidden = {"httpx", "requests", "urllib", "socket", "smtplib", "subprocess"}
    for name in ("briefing_domain.py", "briefing_store.py", "briefing_service.py"):
        tree = ast.parse((root / name).read_text())
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )
        assert imports.isdisjoint(forbidden), (name, imports & forbidden)


def test_seven_day_baseline_survives_history_above_legacy_limit() -> None:
    from stock_probs.briefing_service import _merge_price_observations

    history = tuple(
        _point(f"history-{index:04d}", "100", NOW - timedelta(days=7) + timedelta(seconds=index))
        for index in range(299)
    )
    current = _point("history-current", "103", NOW + timedelta(minutes=1))
    as_of = NOW + timedelta(hours=1)

    merged = _merge_price_observations(history, (current,), 2, as_of)
    result = summarize_price_movements(
        merged,
        owner_user_id=2,
        baseline_at=NOW - timedelta(days=7),
        observed_as_of=as_of,
    )[0]

    assert len(merged) == 300
    assert merged[0].source_ref == "history-0000"
    assert merged[-1].source_ref == "history-current"
    assert result.state == "threshold_crossed"
    assert result.baseline_at == NOW - timedelta(days=7)
