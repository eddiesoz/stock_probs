"""HTTP authentication, feature-gate, and review CAS contract for report cards."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from _auth_body_barrier import request_with_body_barrier
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stock_probs.api import create_app
from stock_probs.auth import SESSION_COOKIE_NAME
from stock_probs.config import Settings
from stock_probs.provider import FixtureProvider
from stock_probs.report_api import create_report_router
from stock_probs.report_store import ReportCardStore
from stock_probs.repository import Repository
from stock_probs.totp import code_for_step, time_step

NOW = datetime(2026, 10, 12, 22, tzinfo=UTC)
TARGET = datetime(2026, 10, 12, 20, tzinfo=UTC)
PROVIDER = "FixtureMarketProvider"
ADJUSTMENT = "unadjusted provider closes (actions=False, auto_adjust=False)"
_LOCAL_PASSWORD = "r3-report-review-admin-password"  # noqa: S105


def _manual_forecast() -> dict[str, object]:
    origin = TARGET - timedelta(minutes=5)
    return {
        "horizon": "five_min_forward",
        "canonical_symbol": "SPY",
        "currency": "USD",
        "origin_timestamp": origin.isoformat(),
        "model": {"version": "report-api-fixture-v1"},
        "provenance": {
            "model_version": "report-api-fixture-v1",
            "source": PROVIDER,
            "instrument_identity": {
                "canonical_symbol": "SPY",
                "currency": "USD",
                "provider": PROVIDER,
            },
        },
        "origin_price": 100.0,
        "adjustment_basis": ADJUSTMENT,
        "target_timestamp": TARGET.isoformat(),
        "direction_probabilities": {"down": 0.1, "unchanged": 0.2, "up": 0.7},
        "magnitude_intervals": [{"level": 0.8, "price": {"low": 90.0, "high": 110.0}}],
    }


def _manual_comparability() -> dict[str, object]:
    origin = TARGET - timedelta(minutes=5)
    return {
        "schema": "forecast-outcome-comparability-v1",
        "state": "comparable",
        "provider": PROVIDER,
        "symbol": "SPY",
        "currency": "USD",
        "adjustment_basis": ADJUSTMENT,
        "origin": {"timestamp": origin.isoformat(), "close": 100.0},
        "target": {"timestamp": TARGET.isoformat(), "close": 105.0},
        "corporate_actions": {
            "state": "checked",
            "provider": PROVIDER,
            "symbol": "SPY",
            "currency": "USD",
            "from_timestamp": origin.isoformat(),
            "through_timestamp": TARGET.isoformat(),
            "events": [],
        },
    }


@pytest.fixture
def report_app(tmp_path) -> tuple[Repository, TestClient]:
    """Wire an isolated router to a test-only session resolver and current schema."""
    repository = Repository(tmp_path / "report-api.sqlite3")
    repository.migrate()
    for user_id in (1, 2):
        repository.create_user(
            github_user_id=2000 + user_id,
            login=f"report-api-user-{user_id}",
            display_name=f"Report API User {user_id}",
            password_hash=None,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    app = FastAPI()

    @app.middleware("http")
    async def test_session(request, call_next):
        token = request.cookies.get("test-owner")
        request.state.test_owner = int(token) if token and token.isdigit() else None
        return await call_next(request)

    app.include_router(
        create_report_router(
            ReportCardStore(repository, write_authorization_mode="test_no_auth"),
            lambda request: request.state.test_owner,
            enabled=True,
            clock=lambda: NOW,
        )
    )
    return repository, TestClient(app)


def _add_manual_record(
    repository: Repository,
    owner: int = 1,
    *,
    evidence_collected_at: str | None = None,
    evidence_payload_json: str | None = None,
) -> None:
    recorded = TARGET - timedelta(hours=1)
    forecast = _manual_forecast()
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO forecast_runs(id,symbol,asset_type,content_fingerprint,created_at) "
            "VALUES(?,?,?,?,?)",
            (1, "SPY", "stock", "api-manual-record", recorded.isoformat()),
        )
        connection.execute(
            "INSERT INTO forecast_run_owners(run_id,owner_user_id,assigned_at) VALUES(?,?,?)",
            (1, owner, recorded.isoformat()),
        )
        connection.execute(
            "INSERT INTO forecast_inputs(id,run_id,snapshot_json,created_at) VALUES(?,?,?,?)",
            (1, 1, "{}", recorded.isoformat()),
        )
        connection.execute(
            "INSERT INTO forecast_results(id,input_id,horizon,result_json,created_at) "
            "VALUES(?,?,?,?,?)",
            (
                1,
                1,
                "five_min_forward",
                json.dumps(forecast, separators=(",", ":")),
                recorded.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO forecast_result_owners(result_id,owner_user_id,assigned_at) VALUES(?,?,?)",
            (1, owner, recorded.isoformat()),
        )
        connection.execute(
            "INSERT INTO search_events(id,request_id,submitted_symbol,normalized_symbol,asset_type,"
            "status,"
            "is_repeat,error_code,error_message,run_id,submitted_at,completed_at,analysis_kind) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                1,
                "report-api-request-1",
                "SPY",
                "SPY",
                "stock",
                "successful",
                0,
                None,
                None,
                1,
                recorded.isoformat(),
                recorded.isoformat(),
                "submitted_forecast",
            ),
        )
        connection.execute(
            "INSERT INTO search_event_owners(event_id,owner_user_id,assigned_at) VALUES(?,?,?)",
            (1, owner, recorded.isoformat()),
        )
        outcome_created = TARGET + timedelta(seconds=1)
        connection.execute(
            "INSERT INTO outcomes(id,result_id,observed_close,observed_return,observed_at,"
            "comparison_rule,state,note,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                1,
                1,
                105.0,
                0.05,
                TARGET.isoformat(),
                "close divided by immutable origin price minus one",
                "observed",
                "",
                outcome_created.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO outcome_owners(outcome_id,owner_user_id,assigned_at) VALUES(?,?,?)",
            (1, owner, outcome_created.isoformat()),
        )
        source = {
            "method": "manual_review",
            "review_revision": 1,
            "comparability": _manual_comparability(),
        }
        connection.execute(
            "INSERT INTO collected_outcome_evidence(outcome_id,owner_user_id,result_id,state,"
            "payload_json,collected_at) "
            "VALUES(?,?,?,?,?,?)",
            (
                1,
                owner,
                1,
                "observed",
                evidence_payload_json or json.dumps(source, separators=(",", ":")),
                evidence_collected_at or (outcome_created + timedelta(seconds=1)).isoformat(),
            ),
        )
        connection.commit()


def test_report_routes_return_auth_disabled_empty_and_owner_safe_responses(report_app) -> None:
    repository, client = report_app
    no_session = client.get("/api/v1/report-cards")
    assert no_session.status_code == 401
    assert no_session.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

    empty = client.get("/api/v1/report-cards", cookies={"test-owner": "1"})
    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert empty.json()["counts"] == {
        "scored": 0,
        "pending": 0,
        "unavailable": 0,
        "disputed": 0,
        "incomparable": 0,
    }
    assert empty.json()["denominator_scope"] == "current_page"

    _add_manual_record(repository)
    cross_owner = client.get("/api/v1/report-cards/1/reviews", cookies={"test-owner": "2"})
    absent = client.get("/api/v1/report-cards/999/reviews", cookies={"test-owner": "1"})
    cross_owner_write = client.post(
        "/api/v1/report-cards/1/reviews",
        json={"expected_revision": 0, "state": "confirmed", "note": "forged"},
        cookies={"test-owner": "2"},
    )
    assert cross_owner.status_code == absent.status_code == cross_owner_write.status_code == 404
    assert cross_owner.json()["error"]["code"] == "REPORT_NOT_FOUND"


def test_feature_disable_returns_503_without_opening_the_report_store(tmp_path) -> None:
    repository = Repository(tmp_path / "disabled.sqlite3")
    app = FastAPI()
    app.include_router(
        create_report_router(
            ReportCardStore(repository, write_authorization_mode="test_no_auth"),
            lambda request: 1,
            enabled=lambda: False,
            clock=lambda: NOW,
        )
    )

    response = TestClient(app).get("/api/v1/report-cards")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "REPORT_CARDS_UNAVAILABLE"


def test_review_write_is_explicit_append_only_and_revision_checked(report_app) -> None:
    repository, client = report_app
    _add_manual_record(repository)
    payload = {"expected_revision": 0, "state": "confirmed", "note": "Checked endpoints."}

    confirmed = client.post(
        "/api/v1/report-cards/1/reviews", json=payload, cookies={"test-owner": "1"}
    )
    stale = client.post(
        "/api/v1/report-cards/1/reviews",
        json={"expected_revision": 0, "state": "disputed", "note": "stale"},
        cookies={"test-owner": "1"},
    )
    confirmed_report = client.get("/api/v1/report-cards", cookies={"test-owner": "1"})
    disputed = client.post(
        "/api/v1/report-cards/1/reviews",
        json={"expected_revision": 1, "state": "disputed", "note": "Source needs review."},
        cookies={"test-owner": "1"},
    )
    disputed_report = client.get("/api/v1/report-cards", cookies={"test-owner": "1"})
    history = client.get("/api/v1/report-cards/1/reviews", cookies={"test-owner": "1"})

    assert confirmed.status_code == 201
    assert confirmed.json()["revision"] == 1
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "REPORT_CONFLICT"
    assert confirmed_report.json()["counts"]["scored"] == 1
    assert confirmed_report.json()["items"][0]["source"]["method"] == "manual_review"
    assert disputed.status_code == 201
    assert disputed.json()["revision"] == 2
    assert disputed_report.json()["counts"]["disputed"] == 1
    assert history.status_code == 200
    assert history.json()["items"] == [
        {
            "revision": 2,
            "state": "disputed",
            "note": "Source needs review.",
            "reviewed_at": NOW.isoformat().replace("+00:00", "Z"),
        },
        {
            "revision": 1,
            "state": "confirmed",
            "note": "Checked endpoints.",
            "reviewed_at": NOW.isoformat().replace("+00:00", "Z"),
        },
    ]
    with repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM collected_outcome_evidence").fetchone()[0] == 1
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM forecast_outcome_reviews").fetchone()[0] == 2
        )


def test_manual_review_rejects_session_revoked_during_body_read(settings: Settings) -> None:
    """The report-review write binds the cached pre-body session in its SQLite transaction."""

    configured = replace(
        settings,
        auth_mode="local",
        auth_session_secret="q" * 48,
        auth_public_origin="http://testserver",
        bootstrap_username="admin",
        bootstrap_password=_LOCAL_PASSWORD,
        monitoring_features_enabled=True,
    )
    application = create_app(configured, FixtureProvider(), lambda: datetime.now(UTC))
    with TestClient(application) as client:
        login = client.post(
            "/api/v1/auth/local/login",
            json={"username": "admin", "password": _LOCAL_PASSWORD},
        )
        assert login.status_code == 200, login.text
        csrf_token = login.json()["csrf_token"]
        started = client.post(
            "/api/v1/auth/totp/enroll/start", headers={"x-csrf-token": csrf_token}
        )
        assert started.status_code == 200, started.text
        finished = client.post(
            "/api/v1/auth/totp/enroll/finish",
            json={"code": code_for_step(started.json()["secret"], time_step())},
            headers={"x-csrf-token": csrf_token},
        )
        assert finished.status_code == 200, finished.text
        csrf_token = finished.json()["csrf_token"]
        session_token = client.cookies.get(SESSION_COOKIE_NAME)
        assert isinstance(session_token, str)
        context = application.state.auth.authenticate(session_token, datetime.now(UTC))
        _add_manual_record(application.state.repository, owner=context.user.id)

        def revoke_session() -> None:
            application.state.auth.store.auth_revoke_session_by_id(
                context.user.id, context.session_id, datetime.now(UTC).isoformat()
            )

        status, body = asyncio.run(
            request_with_body_barrier(
                application,
                session_token,
                csrf_token,
                method="POST",
                path="/api/v1/report-cards/1/reviews",
                body=b'{"expected_revision":0,"state":"confirmed","note":"review"}',
                on_body_paused=revoke_session,
            )
        )

        assert status == 401, body
        with application.state.repository.connect() as connection:
            assert (
                connection.execute(
                    "SELECT count(*) FROM forecast_outcome_reviews WHERE owner_user_id=?",
                    (context.user.id,),
                ).fetchone()[0]
                == 0
            )


def test_review_route_uses_actual_offset_instant_for_source_evidence(report_app) -> None:
    repository, client = report_app
    _add_manual_record(repository, evidence_collected_at="2026-10-12T23:00:00+02:00")
    accepted = client.post(
        "/api/v1/report-cards/1/reviews",
        json={"expected_revision": 0, "state": "confirmed", "note": "Past source."},
        cookies={"test-owner": "1"},
    )
    assert accepted.status_code == 201

    with repository.connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM forecast_outcome_reviews").fetchone()[0] == 1
        )


def test_review_route_rejects_future_offset_source_evidence(report_app) -> None:
    repository, client = report_app
    _add_manual_record(repository, evidence_collected_at="2026-10-12T21:30:00-02:00")
    rejected = client.post(
        "/api/v1/report-cards/1/reviews",
        json={"expected_revision": 0, "state": "confirmed", "note": "Future source."},
        cookies={"test-owner": "1"},
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "REPORT_CONFLICT"
    with repository.connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM forecast_outcome_reviews").fetchone()[0] == 0
        )


def test_report_route_returns_incomparable_for_deep_bounded_evidence_json(report_app) -> None:
    repository, client = report_app
    nested = "[" * 2207 + "0" + "]" * 2207
    assert len(nested.encode("utf-8")) < 262_144
    _add_manual_record(repository, evidence_payload_json=nested)

    response = client.get("/api/v1/report-cards", cookies={"test-owner": "1"})

    assert response.status_code == 200
    assert response.json()["counts"]["incomparable"] == 1
    assert nested not in response.text
    assert "RecursionError" not in response.text
