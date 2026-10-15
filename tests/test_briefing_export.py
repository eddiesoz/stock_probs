"""Owner-isolated export tests for immutable saved briefing snapshots."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from stock_probs.api import _safe_csv_cell
from stock_probs.briefing_domain import (
    BriefingWindow,
    DueThesisReviewSummary,
    ForecastOutcomeChange,
    PriceObservation,
    TriggeredAlertSummary,
)
from stock_probs.briefing_export import (
    BRIEFING_EXPORT_FORMAT,
    BRIEFING_EXPORT_VERSION,
    MAX_EXPORT_FIELD_BYTES,
    BriefingExportAccessError,
    BriefingExportNotFoundError,
    BriefingExportSerializationError,
    BriefingExportTooLargeError,
    build_briefing_export,
    serialize_briefing_export_csv,
    serialize_briefing_export_json,
)
from stock_probs.briefing_service import BriefingService
from stock_probs.briefing_store import BriefingStore
from stock_probs.repository import Repository

NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)


class FixtureSources:
    """Provide frozen display evidence while counting any attempted source refresh."""

    def __init__(self) -> None:
        self.price_rows: Sequence[PriceObservation] = ()
        self.outcome_rows: Sequence[ForecastOutcomeChange] = ()
        self.alert_rows: Sequence[TriggeredAlertSummary] = ()
        self.review_rows: Sequence[DueThesisReviewSummary] = ()
        self.calls = {"price": 0, "outcome": 0, "alert": 0, "review": 0}

    def list_price_observations(
        self, owner_user_id: int, *, observed_as_of: datetime, limit: int
    ) -> Sequence[PriceObservation]:
        self.calls["price"] += 1
        return self.price_rows

    def list_outcome_changes(
        self,
        owner_user_id: int,
        *,
        baseline_at: datetime | None,
        observed_as_of: datetime,
        limit: int,
    ) -> Sequence[ForecastOutcomeChange]:
        self.calls["outcome"] += 1
        return self.outcome_rows

    def list_triggered_alerts(
        self,
        owner_user_id: int,
        *,
        baseline_at: datetime | None,
        observed_as_of: datetime,
        limit: int,
    ) -> Sequence[TriggeredAlertSummary]:
        self.calls["alert"] += 1
        return self.alert_rows

    def list_due_thesis_reviews(
        self, owner_user_id: int, *, observed_as_of: datetime, limit: int
    ) -> Sequence[DueThesisReviewSummary]:
        self.calls["review"] += 1
        return self.review_rows


@pytest.fixture
def export_parts(tmp_path: Path):
    repository = Repository(tmp_path / "briefing-export.sqlite3")
    repository.migrate()
    with repository.connect() as connection:
        for user_id in (2, 3):
            connection.execute(
                "INSERT INTO users(id,display_name,role,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?)",
                (
                    user_id,
                    f"Export owner {user_id}",
                    "member",
                    "active",
                    "2026-10-15T00:00:00Z",
                    "2026-10-15T00:00:00Z",
                ),
            )
        connection.commit()
    sources = FixtureSources()
    sources.price_rows = (
        PriceObservation(
            2,
            "price-initial",
            "SPY",
            "etf",
            "FixtureProvider",
            "USD",
            Decimal("100"),
            NOW - timedelta(minutes=3),
            NOW - timedelta(minutes=2),
            "initial",
        ),
        PriceObservation(
            2,
            "price-missing",
            "ACDC",
            "stock",
            "FixtureProvider",
            "USD",
            None,
            None,
            None,
            "unavailable",
            "provider_unavailable",
        ),
    )
    sources.outcome_rows = (
        ForecastOutcomeChange(
            2,
            "forecast:42",
            "evidence:42-r2",
            "corrected",
            2,
            NOW - timedelta(minutes=4),
            NOW - timedelta(minutes=5),
            "evidence:42-r1",
        ),
        ForecastOutcomeChange(
            2,
            "forecast:43",
            "evidence:43-r1",
            "unavailable",
            1,
            NOW - timedelta(minutes=3),
            None,
        ),
        ForecastOutcomeChange(
            2,
            "forecast:44",
            "evidence:44-r1",
            "incomparable",
            1,
            NOW - timedelta(minutes=2),
            NOW - timedelta(minutes=3),
        ),
        ForecastOutcomeChange(
            2,
            "forecast:45",
            "evidence:45-r1",
            "manual_review",
            1,
            NOW - timedelta(minutes=1),
            NOW - timedelta(minutes=2),
        ),
    )
    sources.alert_rows = (
        TriggeredAlertSummary(2, "alert:crossing-1", "SPY", "etf", NOW - timedelta(minutes=2)),
    )
    sources.review_rows = (
        DueThesisReviewSummary(2, "thesis:review-1", 4, NOW - timedelta(minutes=1)),
    )

    def owner_is_active(owner_user_id: int) -> bool:
        with repository.connect() as connection:
            row = connection.execute(
                "SELECT status FROM users WHERE id=?", (owner_user_id,)
            ).fetchone()
        return row is not None and row["status"] == "active"

    service = BriefingService(
        BriefingStore(repository),
        price_source=sources,
        outcome_source=sources,
        alert_source=sources,
        thesis_source=sources,
        owner_authorizer=owner_is_active,
        clock=lambda: NOW + timedelta(days=1),
    )
    return service, repository, sources


def _create_snapshot(service: BriefingService):
    return service.generate(
        2,
        idempotency_key=str(uuid4()),
        window=BriefingWindow.SINCE_LAST_VISIT,
        observed_as_of=NOW,
    )


def _snapshot(export: dict[str, object]) -> dict[str, object]:
    value = export["snapshot"]
    assert isinstance(value, dict)
    return value


def test_json_export_contains_only_safe_frozen_snapshot_fields_and_is_deterministic(
    export_parts,
) -> None:
    service, _repository, sources = export_parts
    saved = _create_snapshot(service)
    source_calls = dict(sources.calls)

    exported = build_briefing_export(service, 2, saved.snapshot_id)
    encoded = serialize_briefing_export_json(exported)
    decoded = json.loads(encoded)

    assert encoded == serialize_briefing_export_json(exported)
    assert decoded["format"] == BRIEFING_EXPORT_FORMAT
    assert decoded["format_version"] == BRIEFING_EXPORT_VERSION
    snapshot = decoded["snapshot"]
    assert set(snapshot) == {
        "id",
        "generated_at",
        "version",
        "window",
        "baseline_at",
        "observed_as_of",
        "threshold_bps",
        "baseline_anchor_revision",
        "preference_revision",
        "price_changes",
        "outcome_changes",
        "triggered_alerts",
        "due_thesis_reviews",
    }
    assert snapshot["id"] == saved.snapshot_id
    assert snapshot["baseline_at"] is None
    assert snapshot["observed_as_of"] == NOW.isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
    assert snapshot["threshold_bps"] == 300
    assert snapshot["baseline_anchor_revision"] == 0
    assert snapshot["preference_revision"] == 0
    assert {item["state"] for item in snapshot["price_changes"]} == {
        "first_observation",
        "unavailable",
    }
    assert [item["state"] for item in snapshot["outcome_changes"]] == [
        "corrected",
        "unavailable",
        "incomparable",
        "manual_review",
    ]
    assert snapshot["outcome_changes"][0]["correction_of"] == "evidence:42-r1"
    assert snapshot["outcome_changes"][1]["observed_at"] is None
    assert sources.calls == source_calls
    for private_field in (
        "owner_user_id",
        "idempotency_key",
        "request_sha256",
        "balances",
        "headlines",
        "notification_address",
        "outbox",
        "jobs",
    ):
        assert private_field not in encoded
    assert saved.idempotency_key not in encoded
    assert saved.request_sha256 not in encoded


def test_old_export_keeps_its_baseline_and_threshold_after_current_settings_change(
    export_parts,
) -> None:
    service, _repository, sources = export_parts
    saved = _create_snapshot(service)
    first = serialize_briefing_export_json(build_briefing_export(service, 2, saved.snapshot_id))
    source_calls = dict(sources.calls)

    service.record_visit(2, saved.snapshot_id, expected_revision=0)
    service.update_preference(2, 500, expected_revision=0)
    sources.price_rows = ()
    sources.outcome_rows = ()
    sources.alert_rows = ()
    sources.review_rows = ()

    second = serialize_briefing_export_json(build_briefing_export(service, 2, saved.snapshot_id))

    assert second == first
    assert _snapshot(json.loads(second))["baseline_at"] is None
    assert _snapshot(json.loads(second))["threshold_bps"] == 300
    assert sources.calls == source_calls


def test_export_enforces_owner_isolation_and_current_active_owner(export_parts) -> None:
    service, repository, _sources = export_parts
    saved = _create_snapshot(service)

    with pytest.raises(BriefingExportNotFoundError, match="saved briefing is unavailable"):
        build_briefing_export(service, 3, saved.snapshot_id)
    with pytest.raises(BriefingExportNotFoundError, match="saved briefing is unavailable"):
        build_briefing_export(service, 2, "not-a-canonical-uuid-000000000000000000")

    with repository.connect() as connection:
        connection.execute("UPDATE users SET status='disabled' WHERE id=2")
        connection.commit()
    with pytest.raises(BriefingExportAccessError, match="active owner is unavailable"):
        build_briefing_export(service, 2, saved.snapshot_id)


def test_csv_sanitizes_nested_strings_and_keeps_json_cells_valid(export_parts) -> None:
    service, _repository, _sources = export_parts
    saved = _create_snapshot(service)
    projection = json.loads(
        serialize_briefing_export_json(build_briefing_export(service, 2, saved.snapshot_id))
    )
    snapshot = projection["snapshot"]
    assert isinstance(snapshot, dict)
    price_changes = snapshot["price_changes"]
    assert isinstance(price_changes, list)
    price_changes[0]["symbol"] = "=1+1"
    price_changes[0]["asset_type"] = "\t=1+1"
    price_changes[0]["provider"] = "\u200b@SUM(A1:A2)"
    price_changes[0]["currency"] = "München €"
    price_changes[0]["reason"] = '\r-HYPERLINK("https://example.invalid")'
    sanitized_inputs: list[object] = []

    def safe_cell(value: object) -> str:
        sanitized_inputs.append(value)
        return _safe_csv_cell(value)

    output = serialize_briefing_export_csv(projection, safe_cell=safe_cell)
    rows = list(csv.DictReader(io.StringIO(output)))
    first_price = next(row for row in rows if row["section"] == "price_changes")
    assert not first_price["record_json"].startswith("'")
    record = json.loads(first_price["record_json"])
    assert record["symbol"] == "'=1+1"
    assert record["asset_type"] == "'\t=1+1"
    assert record["provider"] == "'\u200b@SUM(A1:A2)"
    assert record["currency"] == "München €"
    assert record["reason"] == '\'\r-HYPERLINK("https://example.invalid")'
    assert "=1+1" in sanitized_inputs
    assert "München €" in sanitized_inputs
    assert "record_json" in sanitized_inputs
    assert "München €" in output


def test_serializers_reject_hidden_fields_invalid_cells_and_oversized_outputs(export_parts) -> None:
    service, _repository, _sources = export_parts
    saved = _create_snapshot(service)
    projection = build_briefing_export(service, 2, saved.snapshot_id)
    snapshot = _snapshot(projection)

    with pytest.raises(BriefingExportSerializationError, match="projection is invalid"):
        snapshot["owner_user_id"] = 2
        serialize_briefing_export_json(projection)
    snapshot.pop("owner_user_id")

    price_changes = snapshot["price_changes"]
    assert isinstance(price_changes, list)
    price_changes[0]["provider"] = "x" * (MAX_EXPORT_FIELD_BYTES + 1)
    with pytest.raises(BriefingExportTooLargeError, match="field above the export limit"):
        serialize_briefing_export_json(projection)

    snapshot["price_changes"] = [
        {**dict(price_changes[0]), "provider": "p" * 50_000} for _ in range(3)
    ]
    with pytest.raises(BriefingExportTooLargeError, match="exceeds the output limit"):
        serialize_briefing_export_json(projection)
    with pytest.raises(BriefingExportTooLargeError, match="exceeds the output limit"):
        serialize_briefing_export_csv(projection, safe_cell=_safe_csv_cell)

    snapshot["price_changes"] = []
    snapshot["outcome_changes"] = [
        {
            "resource_ref": "f",
            "source_ref": "e",
            "state": "observed",
            "revision": 1,
            "recorded_at": NOW.isoformat().replace("+00:00", "Z"),
            "observed_at": None,
            "correction_of": None,
        }
        for _ in range(101)
    ]
    with pytest.raises(BriefingExportSerializationError, match="projection is invalid"):
        serialize_briefing_export_json(projection)

    with pytest.raises(BriefingExportSerializationError, match="CSV safety callback failed"):
        serialize_briefing_export_csv(
            build_briefing_export(service, 2, saved.snapshot_id),
            safe_cell=lambda _value: (_ for _ in ()).throw(RuntimeError("private")),
        )
