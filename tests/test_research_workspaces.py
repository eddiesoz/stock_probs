"""Exercise actual research persistence, ownership, provenance and HTTP validation."""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from stock_probs.api import create_app
from stock_probs.assistant.storage import AssistantStorage
from stock_probs.backup import BackupManager
from stock_probs.domain import DomainError
from stock_probs.provider import FixtureProvider
from stock_probs.repository import Repository
from stock_probs.research import ResearchStore, compare_series

NOW = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)


@pytest.fixture
def research_client(settings):
    app = create_app(
        replace(settings, research_features_enabled=True, research_features_canary_only=False),
        FixtureProvider(),
        lambda: NOW,
    )
    with TestClient(app) as client:
        yield client


@pytest.fixture
def local_auth_research_client(settings):
    """Provide a real local session for request-boundary authorization tests."""
    configured = replace(
        settings,
        auth_mode="local",
        auth_public_origin="http://testserver",
        research_features_enabled=True,
        research_features_canary_only=False,
        bootstrap_username="research-owner",
        bootstrap_password="research-development-owner-password",  # noqa: S106
    )
    app = create_app(configured, FixtureProvider(), lambda: NOW)
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/local/login",
            json={
                "username": "research-owner",
                "password": "research-development-owner-password",
            },
        )
        assert login.status_code == 200, login.text
        yield app, client, login.json()["csrf_token"]


class _BlockedBody(httpx.AsyncByteStream):
    """Pause a bounded request after its first chunk until the test revokes its session."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.blocked = asyncio.Event()
        self.release = asyncio.Event()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        midpoint = max(1, len(self.body) // 2)
        yield self.body[:midpoint]
        self.blocked.set()
        await self.release.wait()
        yield self.body[midpoint:]

    async def aclose(self) -> None:
        """Finish without holding any resources."""


def thesis():
    return {
        "symbol": "SPY",
        "asset_type": "etf",
        "title": "My investment reasoning",
        "reasoning": "Long-term diversification",
        "risks": "Concentration",
        "invalidation": "Changed mandate",
        "evidence": [],
        "idempotency_key": str(uuid4()),
    }


def test_thesis_roundtrip_revision_conflict_and_history(research_client):
    response = research_client.post("/api/v1/theses", json=thesis())
    assert response.status_code == 201, response.text
    item = response.json()
    edited = {**thesis(), "reasoning": "Revised reasoning", "revision": item["revision"]}
    assert research_client.put(f"/api/v1/theses/{item['id']}", json=edited).status_code == 200
    assert research_client.put(f"/api/v1/theses/{item['id']}", json=edited).status_code == 409
    history = research_client.get(f"/api/v1/theses/{item['id']}/revisions").json()
    assert history["total"] == 2
    assert history["items"][1]["data"]["reasoning"] == "Long-term diversification"
    assert research_client.get("/api/v1/theses").json()["total"] == 1


def test_revoked_session_during_bounded_body_cannot_create_thesis(local_auth_research_client):
    app, client, csrf_token = local_auth_research_client
    body = json.dumps(thesis()).encode()
    blocked_body = _BlockedBody(body)

    async def submit_and_revoke() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            cookies=dict(client.cookies),
        ) as asynchronous_client:
            pending = asyncio.create_task(
                asynchronous_client.post(
                    "/api/v1/theses",
                    content=blocked_body,
                    headers={
                        "content-length": str(len(body)),
                        "content-type": "application/json",
                        "x-csrf-token": csrf_token,
                    },
                )
            )
            await asyncio.wait_for(blocked_body.blocked.wait(), timeout=2)
            app.state.service.repository.revoke_user_sessions(1, revoked_at=datetime.now(UTC))
            blocked_body.release.set()
            return await asyncio.wait_for(pending, timeout=5)

    response = asyncio.run(submit_and_revoke())
    assert response.status_code == 401, response.text
    with app.state.service.repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM research_theses").fetchone()[0] == 0


def test_revocation_before_store_transaction_cannot_create_thesis(
    local_auth_research_client, monkeypatch
):
    app, client, csrf_token = local_auth_research_client
    original_save = ResearchStore.save_thesis

    def revoke_before_store(
        store: ResearchStore,
        owner: int,
        payload: dict[str, object],
        now: datetime,
        **kwargs: object,
    ) -> dict[str, object]:
        store.repository.revoke_user_sessions(owner, revoked_at=datetime.now(UTC))
        return original_save(store, owner, payload, now, **kwargs)

    monkeypatch.setattr(ResearchStore, "save_thesis", revoke_before_store)
    response = client.post(
        "/api/v1/theses",
        json=thesis(),
        headers={"x-csrf-token": csrf_token},
    )
    assert response.status_code == 401, response.text
    with app.state.service.repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM research_theses").fetchone()[0] == 0


def test_archiving_appends_a_revision_and_preserves_prior_states(research_client):
    created = research_client.post("/api/v1/theses", json=thesis())
    assert created.status_code == 201, created.text
    item = created.json()

    active = research_client.put(
        f"/api/v1/theses/{item['id']}",
        json={**thesis(), "status": "active", "revision": item["revision"]},
    )
    assert active.status_code == 200, active.text
    assert active.json()["revision"] == 2

    archived = research_client.put(
        f"/api/v1/theses/{item['id']}",
        json={**thesis(), "status": "archived", "revision": active.json()["revision"]},
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["data"]["status"] == "archived"
    assert archived.json()["revision"] == 3

    history = research_client.get(f"/api/v1/theses/{item['id']}/revisions").json()
    assert history["total"] == 3
    assert [row["revision"] for row in history["items"]] == [3, 2, 1]
    assert [row["data"]["status"] for row in history["items"]] == [
        "archived",
        "active",
        "watching",
    ]
    stale = research_client.put(
        f"/api/v1/theses/{item['id']}",
        json={**thesis(), "status": "watching", "revision": 1},
    )
    assert stale.status_code == 409
    current = research_client.get(f"/api/v1/theses/{item['id']}").json()
    assert current["revision"] == 3
    assert current["data"]["status"] == "archived"
    assert research_client.get(f"/api/v1/theses/{item['id']}/revisions").json()["total"] == 3


def test_invalid_and_cross_owner_evidence_fails_before_save(research_client):
    assert (
        research_client.post("/api/v1/theses", json={**thesis(), "owner_user_id": 99}).status_code
        == 422
    )
    assert (
        research_client.post(
            "/api/v1/theses",
            json={**thesis(), "evidence": [{"kind": "assistant", "reference": str(uuid4())}]},
        ).status_code
        == 404
    )
    assert research_client.get("/api/v1/theses").json()["total"] == 0


def test_creation_key_replays_and_conflicting_body_does_not_duplicate(research_client):
    payload = thesis()
    first = research_client.post("/api/v1/theses", json=payload)
    second = research_client.post("/api/v1/theses", json=payload)
    assert first.json()["id"] == second.json()["id"]
    assert (
        research_client.post(
            "/api/v1/theses", json={**payload, "reasoning": "Different"}
        ).status_code
        == 409
    )
    assert research_client.get("/api/v1/theses").json()["total"] == 1


def test_disabled_feature_and_canary_fail_closed(settings):
    with TestClient(create_app(settings, FixtureProvider(), lambda: NOW)) as client:
        assert client.get("/api/v1/readiness").json()["research"] == {
            "enabled": False,
            "rollout_mode": "disabled",
        }
        assert client.get("/api/v1/research/features").json()["enabled"] is False
        assert client.post("/api/v1/theses", json=thesis()).status_code == 503


def test_comparison_is_provider_bound_and_saved_replay_is_provider_free(research_client):
    request = {
        "instruments": [
            {"symbol": "SPY", "asset_type": "etf"},
            {"symbol": "ACDC", "asset_type": "stock"},
        ],
        "range": "1mo",
    }
    preview = research_client.post("/api/v1/comparisons/preview", json=request)
    assert preview.status_code == 200, preview.text
    key = str(uuid4())
    payload = {"preview_id": preview.json()["preview_id"], "idempotency_key": key}
    saved = research_client.post("/api/v1/comparisons", json=payload)
    assert saved.status_code == 201, saved.text
    assert (
        research_client.post("/api/v1/comparisons", json=payload).json()["id"] == saved.json()["id"]
    )
    provider = research_client.app.state.service.provider
    original = provider.historical_bars

    def forbidden(*args, **kwargs):
        raise AssertionError("saved replay must not call the provider")

    provider.historical_bars = forbidden
    try:
        assert (
            research_client.get(f"/api/v1/comparisons/{saved.json()['id']}").json() == saved.json()
        )
    finally:
        provider.historical_bars = original
    assert (
        research_client.post(
            "/api/v1/comparisons", json={**payload, "data": {"price_change": 100}}
        ).status_code
        == 422
    )


def test_cross_owner_reads_are_absent_and_raw_revisions_cannot_be_replaced(settings):
    repo = Repository(settings.database_path)
    repo.migrate()
    store = ResearchStore(repo, allow_development_noauth=True)
    data = {**thesis(), "identity": {"symbol": "SPY"}}
    saved = store.save_thesis(1, data, NOW)
    assert store.get(2, "theses", saved["id"]) is None
    with pytest.raises(DomainError, match="unavailable"):
        store.revisions(2, saved["id"], 1, 20)
    import sqlite3

    with repo.connect() as connection, pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute(
            "UPDATE research_thesis_revisions SET payload_json = '{}' WHERE thesis_id = ?",
            (saved["id"],),
        )


def series(symbol, values, dates=None):
    if dates is None:
        dates = [
            "2026-10-01",
            "2026-10-02",
            "2026-10-05",
            "2026-10-06",
            "2026-10-07",
        ][: len(values)]
    return {
        "symbol": symbol,
        "identity": {"currency": "CAD"},
        "source": "fixture",
        "as_of": NOW.isoformat(),
        "adjustment_basis": "unadjusted",
        "label": "Simulated",
        "range": "1mo",
        "bars": [
            {"timestamp": f"{day}T12:00:00+00:00", "close": value}
            for day, value in zip(dates, values, strict=True)
        ],
        "session_completeness": {"status": "available", "missing_dates": []},
    }


def test_normalization_drawdown_and_discontinuity_are_honest():
    result = compare_series([series("A", [100, 110, 99]), series("B", [200, 210, 220])])
    assert result["instruments"][0]["normalized"][0]["value"] == 100
    assert result["instruments"][0]["max_drawdown"] == pytest.approx(-0.1)
    result = compare_series([series("A", [100, 40, 44]), series("B", [200, 210, 220])])
    assert result["instruments"][0]["price_change"] is None
    with pytest.raises(DomainError):
        compare_series([series("A", [100]), series("B", [200])])


def test_annualized_volatility_requires_complete_observed_sessions():
    complete = compare_series(
        [
            series("A", [100, 102, 98, 105, 107]),
            series("B", [200, 205, 199, 210, 207]),
        ]
    )
    complete_items = {item["symbol"]: item for item in complete["instruments"]}
    assert complete_items["B"]["missing_observations"] == 0
    assert complete_items["B"]["volatility"] is not None

    gap = series("B", [200, 205, 199, 210, 207])
    gap["bars"].pop(1)
    gap["session_completeness"]["missing_dates"] = ["2026-10-02"]
    result = compare_series([series("A", [100, 102, 98, 105, 107]), gap])
    items = {item["symbol"]: item for item in result["instruments"]}

    assert items["B"]["missing_observations"] == 1
    assert items["B"]["volatility"] is None
    assert items["B"]["price_change"] == pytest.approx(207 / 200 - 1)
    assert items["B"]["max_drawdown"] is not None
    assert items["A"]["missing_observations"] == 0
    assert items["A"]["volatility"] is not None


def test_calendar_identifies_a_session_omitted_by_every_series():
    dates = ["2026-10-01", "2026-10-02", "2026-10-06", "2026-10-07"]
    left = series("A", [100, 102, 104, 106], dates)
    right = series("B", [200, 201, 205, 207], dates)
    for item in (left, right):
        item["session_completeness"]["missing_dates"] = ["2026-10-05"]

    result = compare_series([left, right])
    items = {item["symbol"]: item for item in result["instruments"]}

    assert "2026-10-05" not in result["dates"]
    for item in items.values():
        assert item["missing_observations"] == 1
        assert item["session_completeness"] == {
            "status": "gaps_detected",
            "missing_scheduled_sessions": 1,
        }
        assert item["volatility"] is None


def test_calendar_gaps_outside_actual_common_coverage_are_excluded():
    left = series(
        "A",
        [100, 102, 104, 106, 108],
        ["2026-10-01", "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-09"],
    )
    left["session_completeness"]["missing_dates"] = ["2026-10-02", "2026-10-08"]
    right = series(
        "B",
        [200, 205, 207],
        ["2026-10-05", "2026-10-06", "2026-10-07"],
    )

    result = compare_series([left, right])
    items = {item["symbol"]: item for item in result["instruments"]}

    assert result["dates"] == ["2026-10-05", "2026-10-06", "2026-10-07"]
    assert items["A"]["missing_observations"] == 0
    assert items["A"]["session_completeness"]["status"] == "complete"
    assert items["A"]["volatility"] is not None


def test_unavailable_calendar_does_not_claim_complete_session_coverage():
    left = series("A", [100, 102, 104])
    right = series("B", [200, 205, 207])
    for item in (left, right):
        item["session_completeness"] = {"status": "unavailable", "missing_dates": None}

    result = compare_series([left, right])

    for item in result["instruments"]:
        assert item["session_completeness"] == {
            "status": "unavailable",
            "missing_scheduled_sessions": None,
        }
        assert item["volatility"] is None
        assert "could not be established" in item["metric_suppression_reason"]


@pytest.mark.parametrize("prices", [[1e-308, 1e308], [1e308, 1e-308]])
def test_extreme_provider_prices_do_not_produce_nonfinite_chart_values(prices):
    with pytest.raises(DomainError, match="normalized safely") as caught:
        compare_series([series("A", prices), series("B", [100, 101])])
    assert caught.value.status_code == 502


@pytest.mark.parametrize("timestamp", ["invalid", "2026-10-01T12:00:00"])
def test_invalid_or_ambiguous_provider_chart_dates_fail_explicitly(timestamp):
    invalid = series("A", [100, 101])
    invalid["bars"][0]["timestamp"] = timestamp
    with pytest.raises(DomainError, match="observation dates") as caught:
        compare_series([invalid, series("B", [100, 101])])
    assert caught.value.status_code == 502


def test_saved_previews_release_capacity_and_retry_keeps_identity(research_client):
    payload = {
        "instruments": [
            {"symbol": "ACDC", "asset_type": "stock"},
            {"symbol": "SPY", "asset_type": "etf"},
        ],
        "range": "5d",
    }
    for _ in range(5):
        preview = research_client.post("/api/v1/comparisons/preview", json=payload)
        assert preview.status_code == 200, preview.text
        save = {"preview_id": preview.json()["preview_id"], "idempotency_key": str(uuid4())}
        created = research_client.post("/api/v1/comparisons", json=save)
        assert created.status_code == 201, created.text
        assert research_client.post("/api/v1/comparisons", json=save).json() == created.json()
        assert (
            research_client.post(
                "/api/v1/comparisons", json={**save, "preview_id": str(uuid4())}
            ).status_code
            == 409
        )


def test_review_and_safe_csv_export_preserve_prior_revision(research_client):
    payload = {**thesis(), "title": "=HYPERLINK(fake)"}
    item = research_client.post("/api/v1/theses", json=payload).json()
    reviewed = research_client.post(
        f"/api/v1/theses/{item['id']}/review",
        json={"revision": 1, "next_review_date": "2026-12-01"},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["data"]["reviewed_at"] == NOW.isoformat()
    assert reviewed.json()["revision"] == 2
    exported = research_client.get("/api/v1/theses/export?format=csv")
    assert exported.status_code == 200
    assert "'=HYPERLINK(fake)" in exported.text
    import csv
    import io

    rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert len(rows) == 2
    assert [row["revision"] for row in rows] == ["1", "2"]
    assert all(row["thesis_id"] == item["id"] for row in rows)
    complete = research_client.get("/api/v1/theses/export?format=json").json()
    assert complete["format_version"] == 1
    assert len(complete["items"]) == 1 and len(complete["revisions"]) == 2
    assert complete["revisions"][0]["data"]["review_date"] is None
    assert complete["revisions"][1]["data"]["reviewed_at"] == NOW.isoformat()
    assert (
        research_client.get(f"/api/v1/theses/{item['id']}/revisions").json()["items"][-1]["data"][
            "review_date"
        ]
        is None
    )


def test_owned_failed_forecast_cannot_be_labelled_saved_evidence(research_client):
    repo = research_client.app.state.repository
    event_id = repo.record_failure(
        owner_user_id=1,
        request_id=str(uuid4()),
        submitted_symbol="MISSING",
        normalized_symbol=None,
        asset_type="stock",
        error_code="provider_unavailable",
        error_message="Fixture unavailable.",
        submitted_at=NOW,
        completed_at=NOW,
    )
    response = research_client.post(
        "/api/v1/theses",
        json={**thesis(), "evidence": [{"kind": "forecast", "reference": str(event_id)}]},
    )
    assert response.status_code == 404
    successful = research_client.post(
        "/api/v1/forecasts", json={"symbol": "SPY", "asset_type": "etf"}
    )
    assert successful.status_code == 201, successful.text
    response = research_client.post(
        "/api/v1/theses",
        json={
            **thesis(),
            "evidence": [{"kind": "forecast", "reference": str(successful.json()["event"]["id"])}],
        },
    )
    assert response.status_code == 201, response.text


def test_research_records_survive_signed_backup_restore(settings):
    repo = Repository(settings.database_path)
    repo.migrate()
    store = ResearchStore(repo, allow_development_noauth=True)
    saved = store.save_thesis(1, {**thesis(), "identity": {"symbol": "SPY"}}, NOW)
    edited = store.save_thesis(
        1, {**saved["data"], "status": "active"}, NOW, thesis_id=saved["id"], revision=1
    )
    preview_id = str(uuid4())
    comparison = store.save_comparison(
        1,
        str(uuid4()),
        {
            "preview_id": preview_id,
            "captured_at": NOW.isoformat(),
            "instruments": [{"symbol": "SPY"}, {"symbol": "ACDC"}],
        },
        NOW,
    )
    manager = BackupManager(repo, settings.backup_dir)
    artifact = manager.create("research-roundtrip.spbackup")
    assert manager.restore(artifact["name"])["verified"] is True
    manager.restore(artifact["name"], promote=True)
    assert store.get(1, "theses", saved["id"]) == edited
    assert store.revisions(1, saved["id"], 1, 20)["total"] == 2
    assert store.get(1, "comparisons", comparison["id"]) == comparison


@pytest.mark.parametrize(
    ("canary_only", "expected_rollout_mode", "member_enabled"),
    [(False, "invited", True), (True, "owner_canary", False)],
)
def test_authenticated_owner_csrf_and_member_isolation(
    settings, canary_only, expected_rollout_mode, member_enabled
):
    configured = replace(
        settings,
        auth_mode="local",
        auth_public_origin="http://testserver",
        research_features_enabled=True,
        research_features_canary_only=canary_only,
        bootstrap_username="owner",
        bootstrap_password="research-development-owner-password",  # noqa: S106
        bootstrap_member_username="member",
        bootstrap_member_password="research-development-member-password",  # noqa: S106
    )  # noqa: S106
    app = create_app(configured, FixtureProvider(), lambda: NOW)
    with TestClient(app) as owner:
        readiness = owner.get("/api/v1/readiness")
        assert readiness.status_code == 200
        assert readiness.json()["research"] == {
            "enabled": True,
            "rollout_mode": expected_rollout_mode,
        }
        assert "user" not in readiness.json() and "owner_user_id" not in readiness.json()
        assert owner.get("/api/v1/theses").status_code == 401
        login = owner.post(
            "/api/v1/auth/local/login",
            json={"username": "owner", "password": "research-development-owner-password"},
        )
        assert login.status_code == 200, login.text
        assert owner.get("/api/v1/research/features").json()["enabled"] is True
        assert owner.post("/api/v1/theses", json=thesis()).status_code == 403
        item = owner.post(
            "/api/v1/theses", json=thesis(), headers={"x-csrf-token": login.json()["csrf_token"]}
        )
        assert item.status_code == 201, item.text
        owner_csrf = {"x-csrf-token": login.json()["csrf_token"]}
        owned_forecast = owner.post(
            "/api/v1/forecasts",
            json={"symbol": "SPY", "asset_type": "etf"},
            headers=owner_csrf,
        )
        assert owned_forecast.status_code == 201, owned_forecast.text
        forecast_reference = str(owned_forecast.json()["event"]["id"])
        attached = owner.post(
            "/api/v1/theses",
            json={**thesis(), "evidence": [{"kind": "forecast", "reference": forecast_reference}]},
            headers=owner_csrf,
        )
        assert attached.status_code == 201, attached.text
        assert attached.json()["data"]["evidence"][0]["reference"] == forecast_reference
        with TestClient(app) as member:
            member_login = member.post(
                "/api/v1/auth/local/login",
                json={"username": "member", "password": "research-development-member-password"},
            )
            assert member_login.status_code == 200, member_login.text
            assert member.get("/api/v1/research/features").json()["enabled"] is member_enabled
            if not member_enabled:
                assert member.get("/api/v1/theses").status_code == 503
                assert (
                    member.post(
                        "/api/v1/theses",
                        json=thesis(),
                        headers={"x-csrf-token": member_login.json()["csrf_token"]},
                    ).status_code
                    == 503
                )
                return
            assert member.get("/api/v1/theses").json()["total"] == 0
            cross_owner_attachment = member.post(
                "/api/v1/theses",
                json={
                    **thesis(),
                    "evidence": [{"kind": "forecast", "reference": forecast_reference}],
                },
                headers={"x-csrf-token": member_login.json()["csrf_token"]},
            )
            assert cross_owner_attachment.status_code == 404
            assert member.get("/api/v1/theses").json()["total"] == 0
            assert member.get("/api/v1/theses/export?format=json").json()["revisions"] == []
            assert member.get(f"/api/v1/theses/{item.json()['id']}/revisions").status_code == 404
            attempted = member.put(
                f"/api/v1/theses/{item.json()['id']}",
                json={**thesis(), "revision": 1},
                headers={"x-csrf-token": member_login.json()["csrf_token"]},
            )
            assert attempted.status_code == 404


def test_selected_assistant_reply_is_owner_checked_draft_not_automatic_save(research_client):
    repo = research_client.app.state.service.repository
    chat, turn, prompt, reply = (str(uuid4()) for _ in range(4))
    with repo.connect() as connection:
        connection.execute(
            "INSERT INTO assistant_conversations "
            "(id, user_id, title, context_json, context_version, created_at, updated_at) "
            "VALUES (?, 1, 'Draft', '{}', ?, ?, ?)",
            (chat, "0" * 64, NOW.isoformat(), NOW.isoformat()),
        )
        connection.execute(
            "INSERT INTO assistant_turns "
            "(id, conversation_id, user_id, status, model_id, policy_version, context_json, "
            "context_version, created_at) VALUES "
            "(?, ?, 1, 'completed', 'fixture', 'v1', '{}', ?, ?)",
            (turn, chat, "0" * 64, NOW.isoformat()),
        )
        for message_id, role, sequence, content in (
            (prompt, "user", 1, "User prompt"),
            (reply, "assistant", 2, "Selected reply with risks."),
        ):
            connection.execute(
                "INSERT INTO assistant_messages VALUES (?, ?, ?, 1, ?, ?, ?, ?)",
                (message_id, chat, turn, sequence, role, content, NOW.isoformat()),
            )
        connection.commit()
    draft = research_client.get(f"/api/v1/theses/draft?message_id={reply}")
    assert draft.status_code == 200
    assert draft.json()["reasoning"] == "Selected reply with risks."
    assert research_client.get("/api/v1/theses").json()["total"] == 0
    assert research_client.get(f"/api/v1/theses/draft?message_id={prompt}").status_code == 404
    assert (
        research_client.post(
            "/api/v1/theses",
            json={**thesis(), "evidence": [{"kind": "assistant", "reference": prompt}]},
        ).status_code
        == 404
    )
    assert (
        research_client.post(
            "/api/v1/theses", json={**thesis(), **draft.json(), "truncated": False}
        ).status_code
        == 422
    )
    saved = research_client.post(
        "/api/v1/theses",
        json={
            **thesis(),
            "reasoning": draft.json()["reasoning"],
            "evidence": draft.json()["evidence"],
        },
    )
    assert saved.status_code == 201
    assert saved.json()["data"]["evidence"][0]["excerpt"] == "Selected reply with risks."
    manual = research_client.post(
        "/api/v1/theses", json={**thesis(), "evidence": [{"kind": "assistant", "reference": reply}]}
    )
    assert manual.status_code == 201
    assert manual.json()["data"]["evidence"][0]["excerpt"] == "Selected reply with risks."
    with pytest.raises(DomainError, match="Reload"):
        ResearchStore(repo, allow_development_noauth=True).save_thesis(
            1,
            {
                **thesis(),
                "evidence": [
                    {"kind": "assistant", "reference": reply, "excerpt": "Altered evidence"}
                ],
            },
            NOW,
        )
    AssistantStorage(repo).delete_conversation(
        1,
        chat,
        expected_revision=1,
        confirmation_phrase=f"DELETE {chat[-8:]}",
        deleted_at=NOW,
    )
    edited = research_client.put(
        f"/api/v1/theses/{saved.json()['id']}",
        json={
            **thesis(),
            "revision": 1,
            "reasoning": "Reviewed after chat deletion.",
            "evidence": saved.json()["data"]["evidence"],
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["data"]["evidence"] == saved.json()["data"]["evidence"]
    reviewed = research_client.post(
        f"/api/v1/theses/{saved.json()['id']}/review", json={"revision": 2}
    )
    assert reviewed.status_code == 200, reviewed.text
    forged = research_client.put(
        f"/api/v1/theses/{saved.json()['id']}",
        json={
            **thesis(),
            "revision": 3,
            "evidence": [{"kind": "assistant", "reference": reply, "excerpt": "Forged"}],
        },
    )
    assert forged.status_code == 404
    history = research_client.get("/api/v1/theses/export?format=json").json()["revisions"]
    assert all(
        item["data"]["evidence"][0]["excerpt"] == "Selected reply with risks." for item in history
    )


def _insert_assistant_reply(repo, owner_user_id, content):
    conversation_id, turn_id, message_id = (str(uuid4()) for _ in range(3))
    with repo.connect() as connection:
        connection.execute(
            "INSERT INTO assistant_conversations "
            "(id, user_id, title, context_json, context_version, created_at, updated_at) "
            "VALUES (?, ?, 'Boundary test', '{}', ?, ?, ?)",
            (conversation_id, owner_user_id, "0" * 64, NOW.isoformat(), NOW.isoformat()),
        )
        connection.execute(
            "INSERT INTO assistant_turns "
            "(id, conversation_id, user_id, status, model_id, policy_version, context_json, "
            "context_version, created_at) "
            "VALUES (?, ?, ?, 'completed', 'fixture', 'v1', '{}', ?, ?)",
            (turn_id, conversation_id, owner_user_id, "0" * 64, NOW.isoformat()),
        )
        connection.execute(
            "INSERT INTO assistant_messages VALUES (?, ?, ?, 1, ?, 'assistant', ?, ?)",
            (message_id, conversation_id, turn_id, owner_user_id, content, NOW.isoformat()),
        )
        connection.commit()
    return message_id


@pytest.mark.parametrize(("reply_length", "expected_truncated"), [(6000, False), (6001, True)])
def test_assistant_thesis_draft_honors_6000_character_boundary_and_requires_save(
    research_client, reply_length, expected_truncated
):
    repo = research_client.app.state.service.repository
    content = "R" * reply_length
    message_id = _insert_assistant_reply(repo, 1, content)

    response = research_client.get("/api/v1/theses/draft", params={"message_id": message_id})
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft["reasoning"] == content[:6000]
    assert draft["evidence"] == [
        {"kind": "assistant", "reference": message_id, "excerpt": content[:6000]}
    ]
    assert draft["truncated"] is expected_truncated
    assert research_client.get("/api/v1/theses").json()["total"] == 0

    if reply_length == 6001:
        too_long_reasoning = research_client.post(
            "/api/v1/theses", json={**thesis(), "reasoning": content}
        )
        too_long_excerpt = research_client.post(
            "/api/v1/theses",
            json={
                **thesis(),
                "evidence": [{"kind": "assistant", "reference": message_id, "excerpt": content}],
            },
        )
        assert too_long_reasoning.status_code == 422
        assert too_long_excerpt.status_code == 422
        assert research_client.get("/api/v1/theses").json()["total"] == 0

    saved = research_client.post(
        "/api/v1/theses",
        json={**thesis(), "reasoning": draft["reasoning"], "evidence": draft["evidence"]},
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["data"]["reasoning"] == content[:6000]
    assert saved.json()["data"]["evidence"][0]["excerpt"] == content[:6000]
    assert research_client.get("/api/v1/theses").json()["total"] == 1


def test_authenticated_member_cannot_read_or_attach_another_owners_assistant_reply(settings):
    configured = replace(
        settings,
        auth_mode="local",
        auth_public_origin="http://testserver",
        research_features_enabled=True,
        research_features_canary_only=False,
        bootstrap_username="owner",
        bootstrap_password="research-development-owner-password",  # noqa: S106
        bootstrap_member_username="member",
        bootstrap_member_password="research-development-member-password",  # noqa: S106
    )
    app = create_app(configured, FixtureProvider(), lambda: NOW)
    private_content = "Owner-only assistant reply with private reasoning."
    with TestClient(app) as owner:
        owner_login = owner.post(
            "/api/v1/auth/local/login",
            json={"username": "owner", "password": "research-development-owner-password"},
        )
        assert owner_login.status_code == 200, owner_login.text
        repo = app.state.service.repository
        with repo.connect() as connection:
            owner_user_id = connection.execute(
                "SELECT id FROM users WHERE login = ?", ("owner",)
            ).fetchone()[0]
        message_id = _insert_assistant_reply(repo, owner_user_id, private_content)
        owner_draft = owner.get("/api/v1/theses/draft", params={"message_id": message_id})
        assert owner_draft.status_code == 200
        assert owner_draft.json()["reasoning"] == private_content

        with TestClient(app) as member:
            member_login = member.post(
                "/api/v1/auth/local/login",
                json={"username": "member", "password": "research-development-member-password"},
            )
            assert member_login.status_code == 200, member_login.text
            member_draft = member.get("/api/v1/theses/draft", params={"message_id": message_id})
            assert member_draft.status_code == 404
            assert private_content not in member_draft.text
            attachment = member.post(
                "/api/v1/theses",
                json={
                    **thesis(),
                    "evidence": [
                        {
                            "kind": "assistant",
                            "reference": message_id,
                            "excerpt": private_content,
                        }
                    ],
                },
                headers={"x-csrf-token": member_login.json()["csrf_token"]},
            )
            assert attachment.status_code == 404
            assert private_content not in attachment.text
            assert member.get("/api/v1/theses").json()["total"] == 0


def test_preview_quota_rejects_before_provider_io(research_client):
    payload = {
        "instruments": [
            {"symbol": "SPY", "asset_type": "etf"},
            {"symbol": "ACDC", "asset_type": "stock"},
        ]
    }
    for _ in range(4):
        assert research_client.post("/api/v1/comparisons/preview", json=payload).status_code == 200
    provider = research_client.app.state.service.provider
    original = provider.historical_bars

    def forbidden(*args, **kwargs):
        raise AssertionError("over-quota previews must not contact providers")

    provider.historical_bars = forbidden
    try:
        assert research_client.post("/api/v1/comparisons/preview", json=payload).status_code == 503
    finally:
        provider.historical_bars = original


def test_saved_thesis_retry_and_direct_reopen_do_not_depend_on_provider(research_client):
    payload = thesis()
    first = research_client.post("/api/v1/theses", json=payload)
    assert first.status_code == 201
    service = research_client.app.state.service
    original = service.lookup

    def unavailable(*args, **kwargs):
        raise DomainError("provider_unavailable", "Provider unavailable.", status_code=502)

    service.lookup = unavailable
    try:
        retry = research_client.post("/api/v1/theses", json=payload)
        assert retry.status_code == 201, retry.text
        assert retry.json()["id"] == first.json()["id"]
        reopened = research_client.get(f"/api/v1/theses/{first.json()['id']}")
        assert reopened.status_code == 200
        assert reopened.json() == first.json()
        assert "request_sha256" not in reopened.json()
        assert research_client.get(f"/api/v1/theses/{uuid4()}").status_code == 404
        assert (
            research_client.post(
                "/api/v1/theses", json={**payload, "title": "Different"}
            ).status_code
            == 409
        )
        updated = research_client.put(
            f"/api/v1/theses/{first.json()['id']}",
            json={**payload, "revision": 1, "reasoning": "Reviewed while provider is offline."},
        )
        assert updated.status_code == 200, updated.text
    finally:
        service.lookup = original
    assert research_client.get("/api/v1/theses").json()["total"] == 1
