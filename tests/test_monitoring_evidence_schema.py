"""Outcome evidence must identify its own recorded forecast even within one owner."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture
def schema():
    connection = sqlite3.connect(":memory:")
    migrations = Path(__file__).parents[1] / "src/stock_probs/migrations"
    for path in sorted(migrations.glob("*.sql")):
        connection.executescript(path.read_text())
    now = "2026-10-13T20:00:00Z"
    connection.execute(
        "INSERT INTO users (id,display_name,role,status,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?)",
        (2, "Fixture member", "member", "active", now, now),
    )
    connection.execute(
        "INSERT INTO forecast_runs (id,symbol,asset_type,content_fingerprint,created_at) "
        "VALUES (?,?,?,?,?)",
        (1, "SPY", "stock", "fixture-run", now),
    )
    connection.execute(
        "INSERT INTO forecast_inputs (id,run_id,snapshot_json,created_at) VALUES (?,?,?,?)",
        (1, 1, "{}", now),
    )
    for result_id, horizon in [(1, "daily_1"), (2, "weekly_5")]:
        connection.execute(
            "INSERT INTO forecast_results (id,input_id,horizon,result_json,created_at) "
            "VALUES (?,?,?,?,?)",
            (result_id, 1, horizon, "{}", now),
        )
        connection.execute(
            "INSERT INTO forecast_result_owners (result_id,owner_user_id,assigned_at) "
            "VALUES (?,?,?)",
            (result_id, 1, now),
        )
    for result_id in (1, 2):
        connection.execute(
            "INSERT INTO forecast_result_owners (result_id,owner_user_id,assigned_at) "
            "VALUES (?,?,?)",
            (result_id, 2, now),
        )
    connection.execute(
        "INSERT INTO outcomes (id,result_id,observed_close,observed_return,observed_at,"
        "comparison_rule,state,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (1, 1, 105, 0.05, now, "fixture comparison", "observed", now),
    )
    connection.execute(
        "INSERT INTO outcome_owners (outcome_id,owner_user_id,assigned_at) VALUES (?,?,?)",
        (1, 1, now),
    )
    try:
        yield connection
    finally:
        connection.close()


def insert_evidence(connection, result_id, owner_id=1, prefix="INSERT"):
    statements = {
        "INSERT": "INSERT INTO collected_outcome_evidence "
        "(outcome_id,owner_user_id,result_id,state,payload_json,collected_at) "
        "VALUES (?,?,?,?,?,?)",
        "REPLACE": "INSERT OR REPLACE INTO collected_outcome_evidence "
        "(outcome_id,owner_user_id,result_id,state,payload_json,collected_at) "
        "VALUES (?,?,?,?,?,?)",
    }
    connection.execute(
        statements[prefix], (1, owner_id, result_id, "observed", "{}", "2026-10-13T20:00:00Z")
    )


def test_same_owner_cannot_attach_an_outcome_to_a_different_forecast(schema):
    with pytest.raises(sqlite3.IntegrityError, match="forecast|result"):
        insert_evidence(schema, 2)
    assert schema.execute("SELECT COUNT(*) FROM collected_outcome_evidence").fetchone() == (0,)
    assert schema.execute("SELECT result_id FROM outcomes WHERE id=1").fetchone() == (1,)


def test_correct_evidence_remains_append_only_and_foreign_owner_is_denied(schema):
    with pytest.raises(sqlite3.IntegrityError):
        insert_evidence(schema, 1, owner_id=2)
    insert_evidence(schema, 1)
    for statement in [
        "UPDATE collected_outcome_evidence SET result_id=2 WHERE outcome_id=1",
        "DELETE FROM collected_outcome_evidence WHERE outcome_id=1",
    ]:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            schema.execute(statement)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        insert_evidence(schema, 1, prefix="REPLACE")
    assert schema.execute(
        "SELECT outcome_id,owner_user_id,result_id FROM collected_outcome_evidence"
    ).fetchall() == [(1, 1, 1)]
    assert schema.execute("PRAGMA foreign_key_check").fetchall() == []


def test_monitoring_draft_is_disabled_and_job_leases_are_all_or_none(schema):
    assert schema.execute("SELECT enabled FROM monitoring_control WHERE id=1").fetchone() == (0,)
    schema.execute(
        "INSERT INTO notification_preferences(owner_user_id,revision,updated_at) VALUES (1,1,?)",
        ("2026-10-13T20:00:00Z",),
    )
    assert schema.execute(
        "SELECT alert_email,digest_email FROM notification_preferences WHERE owner_user_id=1"
    ).fetchone() == (0, 0)

    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        schema.execute(
            "INSERT INTO monitoring_jobs(id,owner_user_id,kind,resource_id,due_at,lease_token) "
            "VALUES (?,?,?,?,?,?)",
            (str(uuid4()), 1, "outcome", "outcome:1", "2026-10-13T20:00:00Z", str(uuid4())),
        )


def test_arm_snapshot_generation_requires_complete_request_receipt_marker(schema):
    alert_id = str(uuid4())
    schema.execute(
        "INSERT INTO price_alerts(id,owner_user_id,idempotency_key,request_sha256,revision,"
        "monitor_revision,payload_json,enabled,armed_at,arm_generation,check_stat"
        "e,created_at,updated_at) "
        "VALUES (?,?,?, ?,1,1,'{}',1,?,1,'arming',?,?)",
        (
            alert_id,
            1,
            str(uuid4()),
            "a" * 64,
            "2026-10-13T20:00:00Z",
            "2026-10-13T20:00:00Z",
            "2026-10-13T20:00:00Z",
        ),
    )
    with pytest.raises(sqlite3.IntegrityError):
        schema.execute(
            "UPDATE price_alerts SET arm_snapshot_generation=1,monitor_revision=2 WHERE id=?",
            (alert_id,),
        )


def test_unverified_address_cannot_enable_durable_email_preferences(schema):
    address_id = str(uuid4())
    schema.execute(
        "INSERT INTO notification_addresses(id,owner_user_id,address,created_at) VALUES (?,?,?,?)",
        (address_id, 1, "fixture@example.invalid", "2026-10-13T20:00:00Z"),
    )
    with pytest.raises(sqlite3.IntegrityError, match="verified owner address"):
        schema.execute(
            "INSERT INTO notification_preferences(owner_user_id,revision,address_id,a"
            "lert_email,updated_at) "
            "VALUES (1,1,?,1,?)",
            (address_id, "2026-10-13T20:00:00Z"),
        )


def test_outbox_sql_state_machine_keeps_submitted_attempts_uncertain_or_terminal(schema):
    now = "2026-10-13T20:00:00Z"
    address_id = str(uuid4())
    notification_id = str(uuid4())
    outbox_id = str(uuid4())
    job_id = str(uuid4())
    attempt_id = str(uuid4())
    lease_token = str(uuid4())
    schema.execute(
        "INSERT INTO notification_addresses(id,owner_user_id,address,verified_at,created_at) "
        "VALUES (?,?,?,?,?)",
        (address_id, 1, "fixture@example.invalid", now, now),
    )
    schema.execute(
        "INSERT INTO notification_preferences(owner_user_id,revision,address_id,alert_email,"
        "digest_email,updated_at) VALUES (1,1,?,1,0,?)",
        (address_id, now),
    )
    schema.execute(
        "INSERT INTO notifications(id,owner_user_id,dedupe_sha256,kind,payload_json,created_at) "
        "VALUES (?,1,?,'price_alert','{}',?)",
        (notification_id, "a" * 64, now),
    )
    schema.execute(
        "INSERT INTO monitoring_jobs(id,owner_user_id,kind,resource_id,due_at) "
        "VALUES (?,1,'mail',?,?)",
        (job_id, outbox_id, now),
    )
    schema.execute(
        "INSERT INTO notification_outbox(id,owner_user_id,notification_id,delivery_version,"
        "preference_revision,job_id,dedupe_sha256,address_id,kind,payload_json,next_attempt_at,"
        "created_at,transitioned_at) VALUES (?,1,?,1,1,?,? ,?,'price_alert','{}',?,?,?)",
        (outbox_id, notification_id, job_id, "b" * 64, address_id, now, now, now),
    )
    claim_time = "2026-10-13T20:00:01Z"
    expiry = "2026-10-13T20:00:06Z"
    schema.execute(
        "UPDATE notification_outbox SET state='claimed',attempts=1,attempt_revision=1,"
        "attempt_id=?,revision=revision+1,lease_token=?,lease_until=?,transitioned_at=? "
        "WHERE id=?",
        (attempt_id, lease_token, expiry, claim_time, outbox_id),
    )
    schema.execute(
        "UPDATE notification_outbox SET state='submitting',revision=revision+1,"
        "submission_started_at=?,transitioned_at=? WHERE id=?",
        ("2026-10-13T20:00:02Z", "2026-10-13T20:00:02Z", outbox_id),
    )
    schema.execute(
        "UPDATE notification_outbox SET state='uncertain',revision=revision+1,lease_token=NULL,"
        "lease_until=NULL,completed_at=?,transitioned_at=?,failure_code='smtp_result_unknown' "
        "WHERE id=?",
        ("2026-10-13T20:00:03Z", "2026-10-13T20:00:03Z", outbox_id),
    )
    with pytest.raises(sqlite3.IntegrityError, match="transition"):
        schema.execute(
            "UPDATE notification_outbox SET state='queued',failure_code=NULL,revision=revision+1,"
            "transitioned_at=? WHERE id=?",
            ("2026-10-13T20:00:04Z", outbox_id),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        schema.execute(
            "DELETE FROM notification_outbox_attempts WHERE outbox_id=?",
            (outbox_id,),
        )
    assert schema.execute(
        "SELECT state,attempts,attempt_id FROM notification_outbox WHERE id=?",
        (outbox_id,),
    ).fetchone() == ("uncertain", 1, attempt_id)
    assert schema.execute(
        "SELECT event_kind FROM notification_outbox_attempts WHERE outbox_id=? ORDER BY revision",
        (outbox_id,),
    ).fetchall() == [("claimed",), ("submission_started",), ("uncertain",)]
