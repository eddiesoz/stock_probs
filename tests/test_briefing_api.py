"""Standalone HTTP contract tests for the draft owner-scoped briefing router."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from stock_probs.briefing_api import create_briefing_router
from stock_probs.briefing_domain import (
    DueThesisReviewSummary,
    ForecastOutcomeChange,
    PriceObservation,
    TriggeredAlertSummary,
)
from stock_probs.briefing_service import BriefingService
from stock_probs.briefing_store import BriefingStore
from stock_probs.domain import DomainError
from stock_probs.repository import Repository

NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)


class EmptySources:
    def __init__(self) -> None:
        self.calls = 0
        self.fail_with_private_detail = False

    def _read(self) -> None:
        self.calls += 1
        if self.fail_with_private_detail:
            raise RuntimeError("synthetic internal adapter detail")

    def list_price_observations(
        self, owner_user_id: int, *, observed_as_of: datetime, limit: int
    ) -> Sequence[PriceObservation]:
        self._read()
        return ()

    def list_outcome_changes(
        self,
        owner_user_id: int,
        *,
        baseline_at: datetime | None,
        observed_as_of: datetime,
        limit: int,
    ) -> Sequence[ForecastOutcomeChange]:
        self._read()
        return ()

    def list_triggered_alerts(
        self,
        owner_user_id: int,
        *,
        baseline_at: datetime | None,
        observed_as_of: datetime,
        limit: int,
    ) -> Sequence[TriggeredAlertSummary]:
        self._read()
        return ()

    def list_due_thesis_reviews(
        self, owner_user_id: int, *, observed_as_of: datetime, limit: int
    ) -> Sequence[DueThesisReviewSummary]:
        self._read()
        return ()


FixtureParts = tuple[TestClient, Repository, EmptySources, dict[str, bool]]


@pytest.fixture
def app_parts(tmp_path: Path) -> FixtureParts:
    repository = Repository(tmp_path / "briefing-api.sqlite3")
    repository.migrate()
    with repository.connect() as connection:
        for user_id, role in ((2, "member"), (3, "admin")):
            connection.execute(
                "INSERT INTO users(id,display_name,role,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?)",
                (
                    user_id,
                    f"Fixture {user_id}",
                    role,
                    "active",
                    "2026-10-15T00:00:00Z",
                    "2026-10-15T00:00:00Z",
                ),
            )
        connection.commit()

    def active(owner: int) -> bool:
        with repository.connect() as connection:
            row = connection.execute("SELECT status FROM users WHERE id=?", (owner,)).fetchone()
        return row is not None and row["status"] == "active"

    sources = EmptySources()
    service = BriefingService(
        BriefingStore(repository),
        price_source=sources,
        outcome_source=sources,
        alert_source=sources,
        thesis_source=sources,
        owner_authorizer=active,
        clock=lambda: NOW,
    )
    gates = {"enabled": True}
    app = FastAPI()

    @app.exception_handler(DomainError)
    async def domain_error(_request: Request, error: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={"error": {"code": error.code, "message": error.message}},
        )

    def owner_for_request(request: Request) -> int | None:
        raw = request.headers.get("x-fixture-owner")
        return int(raw) if raw and raw.isascii() and raw.isdecimal() else None

    def csrf_guard(request: Request) -> bool:
        return request.headers.get("x-fixture-csrf") == "fixture-csrf"

    def enabled(_request: Request) -> bool:
        return gates["enabled"]

    def canary(request: Request) -> bool:
        return request.headers.get("x-fixture-canary") == "yes"

    app.include_router(
        create_briefing_router(
            service,
            owner_for_request=owner_for_request,
            active_owner=active,
            csrf_guard=csrf_guard,
            feature_enabled=enabled,
            canary_allowed=canary,
            clock=lambda: NOW,
        )
    )
    return TestClient(app), repository, sources, gates


def _headers(owner: int = 2, *, csrf: bool = False, canary: bool = True) -> dict[str, str]:
    result = {"X-Fixture-Owner": str(owner)}
    if csrf:
        result["X-Fixture-CSRF"] = "fixture-csrf"
    if canary:
        result["X-Fixture-Canary"] = "yes"
    return result


def _create(
    client: TestClient, *, owner: int = 2, as_of: datetime | None = None
) -> dict[str, object]:
    selected = as_of or (NOW - timedelta(hours=1))
    response = client.post(
        "/api/v1/briefings",
        headers={**_headers(owner, csrf=True), "Idempotency-Key": str(uuid4())},
        json={
            "window": "since_last_visit",
            "observed_as_of": selected.isoformat().replace("+00:00", "Z"),
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


def test_state_and_navigation_are_read_only_and_dependant_features_stay_off(
    app_parts: FixtureParts,
) -> None:
    client, repository, sources, _gates = app_parts
    state = client.get("/api/v1/briefing-state", headers=_headers()).json()
    assert state == {
        "features": {
            "enabled": True,
            "headlines_available": False,
            "digest_available": False,
            "assistant_available": False,
        },
        "server_time": "2026-10-15T12:00:00.000000Z",
        "preference": {"revision": 0, "threshold_bps": 300, "updated_at": None},
        "visit_anchor": {
            "revision": 0,
            "baseline_at": None,
            "snapshot_id": None,
            "visited_at": None,
        },
    }
    assert client.get("/api/v1/briefings", headers=_headers()).json() == {
        "items": [],
        "next_cursor": None,
    }
    assert sources.calls == 0
    with repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM briefing_snapshots").fetchone()[0] == 0


def test_create_replay_safe_projection_and_explicit_gets(app_parts: FixtureParts) -> None:
    client, repository, sources, _gates = app_parts
    key = str(uuid4())
    body = {"window": "last_24_hours", "observed_as_of": "2026-10-15T11:00:00Z"}
    headers = {**_headers(csrf=True), "Idempotency-Key": key}

    created = client.post("/api/v1/briefings", headers=headers, json=body)
    replay = client.post("/api/v1/briefings", headers=headers, json=body)
    assert created.status_code == 201
    assert replay.status_code == 200
    assert created.json() == replay.json()
    assert created.headers["location"] == f"/api/v1/briefings/{created.json()['id']}"
    payload = created.json()
    assert payload["window"] == "last_24_hours"
    assert payload["id"]
    assert payload["baseline_anchor_revision"] == 0
    assert payload["preference_revision"] == 0
    assert not {"owner_user_id", "idempotency_key", "request_sha256"} & payload.keys()
    assert sources.calls == 4

    listed = client.get("/api/v1/briefings", headers=_headers()).json()
    assert listed["items"] == [payload]
    reopened = client.get(f"/api/v1/briefings/{payload['id']}", headers=_headers())
    assert reopened.status_code == 200
    assert reopened.json() == payload
    assert sources.calls == 4
    with repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM briefing_snapshots").fetchone()[0] == 1


def test_idempotency_body_conflict_and_cross_owner_reads_are_closed(
    app_parts: FixtureParts,
) -> None:
    client, _repository, _sources, _gates = app_parts
    key = str(uuid4())
    headers = {**_headers(csrf=True), "Idempotency-Key": key}
    assert (
        client.post(
            "/api/v1/briefings",
            headers=headers,
            json={"window": "last_24_hours", "observed_as_of": "2026-10-15T11:00:00Z"},
        ).status_code
        == 201
    )
    changed = client.post(
        "/api/v1/briefings",
        headers=headers,
        json={"window": "last_7_days", "observed_as_of": "2026-10-15T11:00:00Z"},
    )
    assert changed.status_code == 409
    snapshot_id = client.get("/api/v1/briefings", headers=_headers()).json()["items"][0]["id"]
    foreign = client.get(f"/api/v1/briefings/{snapshot_id}", headers=_headers(owner=3))
    assert foreign.status_code == 404
    assert foreign.json()["error"]["message"] == "The briefing is unavailable."
    assert (
        client.get(
            "/api/v1/briefings?cursor=00000000-0000-0000-0000-000000000000",
            headers=_headers(owner=3),
        ).status_code
        == 404
    )


def test_preference_and_visit_use_compare_and_swap_and_only_explicit_posts(
    app_parts: FixtureParts,
) -> None:
    client, repository, _sources, _gates = app_parts
    preference = client.patch(
        "/api/v1/briefing-preference",
        headers=_headers(csrf=True),
        json={"threshold_bps": 500, "expected_revision": 0},
    )
    assert preference.status_code == 200
    assert preference.json() == {
        "revision": 1,
        "threshold_bps": 500,
        "updated_at": "2026-10-15T12:00:00.000000Z",
    }
    stale_preference = client.patch(
        "/api/v1/briefing-preference",
        headers=_headers(csrf=True),
        json={"threshold_bps": 600, "expected_revision": 0},
    )
    assert stale_preference.status_code == 409

    snapshot = _create(client)
    visit_url = f"/api/v1/briefings/{snapshot['id']}/visits"
    first_visit = client.post(visit_url, headers=_headers(csrf=True), json={"expected_revision": 0})
    assert first_visit.status_code == 200
    assert first_visit.json()["revision"] == 1
    assert first_visit.json()["snapshot_id"] == snapshot["id"]
    stale_visit = client.post(visit_url, headers=_headers(csrf=True), json={"expected_revision": 0})
    assert stale_visit.status_code == 409
    state = client.get("/api/v1/briefing-state", headers=_headers()).json()
    assert state["visit_anchor"]["revision"] == 1
    with repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM briefing_preferences").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM briefing_visit_anchors").fetchone()[0] == 1


def test_authentication_revocation_csrf_and_release_gates_fail_closed(
    app_parts: FixtureParts,
) -> None:
    client, repository, sources, gates = app_parts
    assert client.get("/api/v1/briefing-state").status_code == 401
    assert client.get("/api/v1/briefing-state", headers=_headers(owner=999)).status_code == 403
    with repository.connect() as connection:
        connection.execute("UPDATE users SET status='disabled' WHERE id=2")
        connection.commit()
    assert client.get("/api/v1/briefing-state", headers=_headers()).status_code == 403
    with repository.connect() as connection:
        connection.execute("UPDATE users SET status='active' WHERE id=2")
        connection.commit()

    body = {"window": "last_24_hours", "observed_as_of": "2026-10-15T11:00:00Z"}
    no_csrf = client.post(
        "/api/v1/briefings",
        headers={**_headers(), "Idempotency-Key": str(uuid4())},
        json=body,
    )
    assert no_csrf.status_code == 403
    gates["enabled"] = False
    state = client.get("/api/v1/briefing-state", headers=_headers()).json()
    assert state["features"]["enabled"] is False
    disabled = client.post(
        "/api/v1/briefings",
        headers={**_headers(csrf=True), "Idempotency-Key": str(uuid4())},
        json=body,
    )
    assert disabled.status_code == 503
    gates["enabled"] = True
    assert client.get("/api/v1/briefings", headers=_headers(canary=False)).status_code == 503
    assert sources.calls == 0


def test_request_bounds_strict_fields_query_and_idempotency_header(
    app_parts: FixtureParts,
) -> None:
    client, _repository, sources, _gates = app_parts
    headers = {**_headers(csrf=True), "Idempotency-Key": str(uuid4())}
    invalid_owner = client.post(
        "/api/v1/briefings",
        headers=headers,
        json={
            "window": "last_24_hours",
            "observed_as_of": "2026-10-15T11:00:00Z",
            "owner_user_id": 3,
        },
    )
    assert invalid_owner.status_code == 422
    assert (
        client.post(
            "/api/v1/briefings",
            headers=_headers(csrf=True),
            json={"window": "last_24_hours", "observed_as_of": "2026-10-15T11:00:00Z"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/briefings",
            headers={
                **_headers(csrf=True),
                "Idempotency-Key": "ABCDEF00-0000-0000-0000-000000000000",
            },
            json={"window": "last_24_hours", "observed_as_of": "2026-10-15T11:00:00Z"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/briefings",
            headers={**_headers(csrf=True), "Idempotency-Key": str(uuid4())},
            json={"window": "last_24_hours", "observed_as_of": "2026-10-15T11:00:00+00:00"},
        ).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/v1/briefing-preference",
            headers=_headers(csrf=True),
            json={"threshold_bps": 500, "expected_revision": True},
        ).status_code
        == 422
    )
    large = client.post(
        "/api/v1/briefings",
        headers={**_headers(csrf=True), "Idempotency-Key": str(uuid4())},
        content=b" " * 5_000,
    )
    assert large.status_code == 413
    assert client.get("/api/v1/briefings?limit=51", headers=_headers()).status_code == 422
    assert client.get("/api/v1/briefings?limit=2&limit=3", headers=_headers()).status_code == 422
    assert client.get("/api/v1/briefings?admin=true", headers=_headers()).status_code == 422
    assert client.get("/api/v1/briefings/NOT-A-UUID", headers=_headers()).status_code == 404
    assert sources.calls == 0


def test_duplicate_json_keys_and_wrong_content_type_are_rejected(
    app_parts: FixtureParts,
) -> None:
    client, _repository, sources, _gates = app_parts
    common = {**_headers(csrf=True), "Idempotency-Key": str(uuid4())}
    duplicate = client.post(
        "/api/v1/briefings",
        headers={**common, "Content-Type": "application/json"},
        content=b'{"window":"last_24_hours","window":"last_7_days","observed_as_of":"2026-10-15T11:00:00Z"}',
    )
    assert duplicate.status_code == 400
    wrong_type = client.post(
        "/api/v1/briefings",
        headers={**common, "Content-Type": "text/plain"},
        content=b"{}",
    )
    assert wrong_type.status_code == 415
    assert sources.calls == 0


def test_service_failures_are_classified_without_exposing_adapter_details(
    app_parts: FixtureParts,
) -> None:
    client, repository, sources, _gates = app_parts
    sources.fail_with_private_detail = True
    response = client.post(
        "/api/v1/briefings",
        headers={**_headers(csrf=True), "Idempotency-Key": str(uuid4())},
        json={"window": "last_24_hours", "observed_as_of": "2026-10-15T11:00:00Z"},
    )
    assert response.status_code == 503
    assert "synthetic internal adapter detail" not in response.text
    assert response.json()["error"]["code"] == "briefing_source_unavailable"
    with repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM briefing_snapshots").fetchone()[0] == 0
