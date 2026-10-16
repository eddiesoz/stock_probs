"""Owner-scoped monitoring-history export tests."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from io import StringIO
from uuid import uuid4

import pytest

from stock_probs.api import _safe_csv_cell
from stock_probs.history_export import (
    HistoryExportError,
    build_owner_history_export,
    serialize_owner_history_csv,
    serialize_owner_history_json,
)
from stock_probs.monitoring_store import MonitoringStore
from stock_probs.provider import FixtureProvider
from stock_probs.repository import Repository
from stock_probs.service import ForecastService

NOW = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)


def test_owner_history_export_filters_records_and_formula_safe_csv(settings):
    repository = Repository(settings.database_path)
    repository.migrate()
    other_owner = repository.create_user(
        github_user_id=991,
        login="export-other",
        display_name="Other owner",
        password_hash=None,
        created_at=NOW,
    )["id"]
    store = MonitoringStore(repository)
    owner_alert = store.create_alert(
        1,
        str(uuid4()),
        {
            "symbol": "SPY",
            "currency": "USD",
            "threshold": "100",
            "direction": "above",
            "repeating": True,
        },
        NOW,
    )
    other_alert = store.create_alert(
        other_owner,
        str(uuid4()),
        {
            "symbol": "SHOP.TO",
            "currency": "CAD",
            "threshold": "100",
            "direction": "below",
            "repeating": False,
        },
        NOW,
    )

    service = ForecastService(repository, FixtureProvider(), lambda: NOW)
    created = service.search("ACDC", "stock", owner_user_id=1)
    result_id = created["results"][0]["id"]
    outcome_at = datetime(2026, 1, 10, 17, 3, tzinfo=UTC)
    outcome = service.append_outcome(
        result_id,
        24.0,
        outcome_at,
        "observed",
        '=HYPERLINK("https://bad.example.invalid","click")',
        owner_user_id=1,
    )
    assert outcome is not None
    with repository.connect() as connection:
        outcome_id = connection.execute(
            "SELECT id FROM outcomes WHERE result_id=? ORDER BY id DESC LIMIT 1", (result_id,)
        ).fetchone()["id"]
        connection.execute(
            "INSERT INTO collected_outcome_evidence"
            "(outcome_id,owner_user_id,result_id,state,payload_json,collected_at) "
            "VALUES (?,?,?,'observed',?,?)",
            (
                outcome_id,
                1,
                result_id,
                '{"provider":"fixture","close":"24.0"}',
                NOW.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO forecast_outcome_reviews"
            "(owner_user_id,result_id,revision,state,note,reviewed_at) "
            "VALUES (?, ?, 1, 'confirmed', ?, ?)",
            (
                1,
                result_id,
                '=HYPERLINK("https://bad.example.invalid","click")',
                NOW.isoformat(),
            ),
        )
        notification_id = str(uuid4())
        connection.execute(
            "INSERT INTO notifications(id,owner_user_id,dedupe_sha256,kind,payload_json,"
            "created_at) "
            "VALUES (?,?,?,'price_alert',?,?)",
            (
                notification_id,
                1,
                "a" * 64,
                json.dumps(
                    {
                        "alert_id": owner_alert["id"],
                        "symbol": "SPY",
                        "recipient": "private@example.invalid",
                        "lease_token": "outbox-lease-secret",
                    }
                ),
                NOW.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO notifications(id,owner_user_id,dedupe_sha256,kind,payload_json,"
            "created_at) "
            "VALUES (?,?,?,'price_alert',?,?)",
            (
                str(uuid4()),
                other_owner,
                "b" * 64,
                json.dumps({"alert_id": other_alert["id"], "symbol": "SHOP.TO"}),
                NOW.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO notification_addresses"
            "(id,owner_user_id,address,challenge_hash,challenge_expires_at,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                str(uuid4()),
                1,
                "private@example.invalid",
                "c" * 64,
                NOW.isoformat(),
                NOW.isoformat(),
            ),
        )
        connection.commit()

    projection = build_owner_history_export(
        repository,
        1,
        ["preferences", "evidence", "reviews", "rules", "notifications"],
        generated_at=NOW,
    )
    serialized = serialize_owner_history_json(projection)
    assert projection["sections"] == [
        "notifications",
        "rules",
        "reviews",
        "evidence",
        "preferences",
    ]
    assert [row["payload"]["symbol"] for row in projection["records"]["notifications"]] == ["SPY"]
    assert [
        row["id"] for row in projection["records"]["rules"] if row["record_type"] == "rule"
    ] == [owner_alert["id"]]
    assert "SHOP.TO" not in serialized
    assert "private@example.invalid" not in serialized
    assert "c" * 64 not in serialized
    assert "notification_addresses" not in serialized
    assert "notification_outbox" not in serialized
    assert "lease_token" not in serialized
    assert "job_id" not in serialized

    csv_projection = serialize_owner_history_csv(projection, safe_cell=_safe_csv_cell)
    rows = list(csv.DictReader(StringIO(csv_projection)))
    review = next(row for row in rows if row["record_type"] == "outcome_review")
    assert json.loads(review["record_json"])["note"].startswith("'=HYPERLINK(")
    assert "private@example.invalid" not in csv_projection
    assert "c" * 64 not in csv_projection


@pytest.mark.parametrize(
    "sections",
    [(), [], ["notifications", "notifications"], ["unknown"], "notifications"],
)
def test_owner_history_export_requires_bounded_explicit_section_selection(settings, sections):
    repository = Repository(settings.database_path)
    repository.migrate()

    with pytest.raises(HistoryExportError):
        build_owner_history_export(repository, 1, sections)


def test_owner_history_export_rejects_non_active_owner_and_excessive_limit(settings):
    repository = Repository(settings.database_path)
    repository.migrate()
    repository.create_user(
        github_user_id=992,
        login="disabled-export",
        display_name="Disabled export",
        password_hash=None,
        created_at=NOW,
        status="disabled",
    )

    with pytest.raises(HistoryExportError, match="active owner"):
        build_owner_history_export(repository, 2, ["notifications"])
    with pytest.raises(HistoryExportError, match="limit"):
        build_owner_history_export(repository, 1, ["notifications"], limit=101)


def test_csv_export_serialization_rejects_oversized_projection():
    projection = {
        "sections": ["notifications"],
        "records": {"notifications": [{"record_type": "notification", "payload": "x" * 3_000_000}]},
    }

    with pytest.raises(HistoryExportError, match="size limit"):
        serialize_owner_history_csv(projection, safe_cell=_safe_csv_cell)
