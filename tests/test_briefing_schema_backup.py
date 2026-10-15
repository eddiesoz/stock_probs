"""Schema-19 registration, historical count shapes, and no-rewind backup contracts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

import pytest

from stock_probs.backup import BackupError, BackupManager
from stock_probs.briefing_domain import BriefingWindow, PriceObservation
from stock_probs.briefing_service import BriefingService
from stock_probs.briefing_store import BriefingStore
from stock_probs.repository import (
    MIGRATION_SHA256,
    SCHEMA_VERSION,
    Repository,
    _is_representative_storage_counts,
    _representative_storage_tables,
)

NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)
_EXPECTED_MIGRATION_PINS = {
    16: "5e8505d115879cc5bd8db465b1afb213b7f7b07b008d264c28b0e373f30a03a7",
    17: "05d217d29f4c4f5befec771d6644b4fbf7d814fb3748075d75e5d6ab32d63442",
    18: "c152435ddf599a0715478e5863e5a2d2cd14b72fde5eca8d9a73900ff4981a63",
    19: "2334afa27679ea0c980f97e48897b8c043c2c390290c301618af72ca3019cb86",
}
_SCHEMA18_TABLES = {
    "notification_address_verifications",
    "notification_address_verification_recipients",
    "notification_address_verification_events",
}
_SCHEMA19_TABLES = {
    "briefing_preferences",
    "briefing_price_observations",
    "briefing_snapshots",
    "briefing_visit_anchors",
}


class _Sources:
    def list_price_observations(
        self, owner_user_id: int, *, observed_as_of: datetime, limit: int
    ) -> tuple[PriceObservation, ...]:
        return (
            PriceObservation(
                owner_user_id=owner_user_id,
                source_ref="fixture-briefing-observation",
                symbol="ACDC",
                asset_type="stock",
                provider="FixtureProvider",
                currency="USD",
                price=Decimal("125.50"),
                observed_at=observed_as_of - timedelta(minutes=1),
                received_at=observed_as_of,
                state="initial",
            ),
        )

    def list_outcome_changes(
        self,
        owner_user_id: int,
        *,
        baseline_at: datetime | None,
        observed_as_of: datetime,
        limit: int,
    ) -> tuple[()]:
        return ()

    def list_triggered_alerts(
        self,
        owner_user_id: int,
        *,
        baseline_at: datetime | None,
        observed_as_of: datetime,
        limit: int,
    ) -> tuple[()]:
        return ()

    def list_due_thesis_reviews(
        self, owner_user_id: int, *, observed_as_of: datetime, limit: int
    ) -> tuple[()]:
        return ()


def _insert_verification_rows(repository: Repository) -> None:
    verification_id = str(uuid4())
    address_id = str(uuid4())
    created = NOW.isoformat().replace("+00:00", "Z")
    expires = (NOW + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO notification_address_verifications "
            "(id,owner_user_id,address_id,idempotency_sha256,request_sha256,token_sha256,"
            "state,revision,requested_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                verification_id,
                1,
                address_id,
                "a" * 64,
                "b" * 64,
                "c" * 64,
                "queued",
                1,
                created,
                expires,
            ),
        )
        connection.execute(
            "INSERT INTO notification_address_verification_recipients "
            "(verification_id,owner_user_id,address,created_at,expires_at) VALUES(?,?,?,?,?)",
            (verification_id, 1, "briefing-fixture@example.invalid", created, expires),
        )
        connection.execute(
            "INSERT INTO notification_address_verification_events "
            "(verification_id,owner_user_id,revision,event_kind,occurred_at) VALUES(?,?,?,?,?)",
            (verification_id, 1, 1, "queued", created),
        )
        connection.commit()


def test_registered_schema19_preserves_historical_counts_and_exact_sql(settings) -> None:
    assert SCHEMA_VERSION == 19
    assert {version: MIGRATION_SHA256[version] for version in _EXPECTED_MIGRATION_PINS} == (
        _EXPECTED_MIGRATION_PINS
    )
    shapes = {version: set(_representative_storage_tables(version)) for version in range(15, 20)}
    assert shapes[15] == {
        "search_events",
        "forecast_runs",
        "forecast_inputs",
        "forecast_results",
        "outcomes",
    }
    assert shapes[16] == shapes[17]
    assert shapes[18] - shapes[17] == _SCHEMA18_TABLES
    assert shapes[19] - shapes[18] == _SCHEMA19_TABLES
    for version, shape in shapes.items():
        assert _is_representative_storage_counts(dict.fromkeys(shape, 0), version)
        invalid_shape = shape | ({"unexpected_table"} if version == 19 else _SCHEMA19_TABLES)
        assert not _is_representative_storage_counts(dict.fromkeys(invalid_shape, 0), version)

    migration_root = files("stock_probs.migrations")
    repository = Repository(settings.database_path)
    repository.migrate()
    with repository.connect() as connection:
        versions = [
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
        actual_tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert versions == list(range(1, 20))
    assert actual_tables >= (_SCHEMA18_TABLES | _SCHEMA19_TABLES)
    assert {
        name: repository.representative_counts()[name]
        for name in _SCHEMA18_TABLES | _SCHEMA19_TABLES
    } == dict.fromkeys(_SCHEMA18_TABLES | _SCHEMA19_TABLES, 0)
    migration_names = {
        16: "016_monitoring_and_report_cards.sql",
        17: "017_outcome_owner_replace_guard.sql",
        18: "018_notification_address_delivery.sql",
        19: "019_personal_briefings.sql",
    }
    for version, expected in _EXPECTED_MIGRATION_PINS.items():
        filename = migration_names[version]
        contents = migration_root.joinpath(filename).read_bytes()
        assert hashlib.sha256(contents).hexdigest() == expected
    draft = (
        Path(__file__).parents[1] / "src/stock_probs/migration_drafts/019_personal_briefings.sql"
    ).read_bytes()
    packaged = migration_root.joinpath("019_personal_briefings.sql").read_bytes()
    assert draft == packaged


def test_restore_rejects_rewind_of_schema18_address_and_schema19_briefing_effects(settings) -> None:
    repository = Repository(settings.database_path)
    repository.migrate()
    manager = BackupManager(repository, settings.backup_dir)
    store = BriefingStore(repository)

    before_address_state = manager.create("before-address-state.spbackup")
    _insert_verification_rows(repository)
    with pytest.raises(BackupError, match="notification consent, address verification"):
        manager.restore(before_address_state["name"], promote=True)

    before_briefing_state = manager.create("before-briefing-state.spbackup")
    preference = store.update_preference(1, 425, expected_revision=0, updated_at=NOW)
    assert preference.revision == 1
    sources = _Sources()
    service = BriefingService(
        store,
        price_source=sources,
        outcome_source=sources,
        alert_source=sources,
        thesis_source=sources,
        owner_authorizer=lambda owner: owner == 1,
        clock=lambda: NOW,
    )
    snapshot = service.generate(
        1,
        idempotency_key=str(uuid4()),
        window=BriefingWindow.LAST_24_HOURS,
        observed_as_of=NOW,
    )
    service.record_visit(1, snapshot.snapshot_id, expected_revision=0)

    with pytest.raises(BackupError, match="saved briefing history"):
        manager.restore(before_briefing_state["name"], promote=True)
    counts = repository.representative_counts()
    assert counts["notification_address_verifications"] == 1
    assert counts["notification_address_verification_recipients"] == 1
    assert counts["notification_address_verification_events"] == 1
    assert counts["briefing_preferences"] == 1
    assert counts["briefing_price_observations"] == 1
    assert counts["briefing_snapshots"] == 1
    assert counts["briefing_visit_anchors"] == 1
