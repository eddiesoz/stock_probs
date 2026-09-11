"""M01-M04 API tests cover the versioned boundary, audit matrix, and safe errors."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from uvicorn.protocols.http import h11_impl

from stock_probs.api import create_app
from stock_probs.backup import BackupError
from stock_probs.config import Settings
from stock_probs.provider import FixtureProvider
from stock_probs.repository import SCHEMA_VERSION, RepositoryError


def _forecast(client, symbol="ACDC", asset_type="stock"):
    """Submit through the public transport boundary rather than calling repositories."""

    return client.post("/api/v1/forecasts", json={"symbol": symbol, "asset_type": asset_type})


def test_health_readiness_and_security_headers(client):
    health = client.get("/api/v1/health")
    readiness = client.get("/api/v1/readiness")

    assert health.json() == {"status": "ok", "service": "stock-probs", "api_version": "v1"}
    assert readiness.json()["schema_version"] == SCHEMA_VERSION
    assert "default-src 'self'" in health.headers["content-security-policy"]
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["x-frame-options"] == "DENY"
    assert health.headers["cross-origin-resource-policy"] == "same-origin"
    contract = client.get("/api/v1/openapi.json").json()
    assert "/api/v1/forecasts" in contract["paths"]
    assert "/api/v1/operations/restores" in contract["paths"]
    assert all(path.startswith("/api/v1/") for path in contract["paths"])
    assert "database_path" not in str(contract) and "backup_dir" not in str(contract)


def test_readiness_is_fail_closed_until_lifespan_startup(settings):
    application = create_app(settings, FixtureProvider())
    not_started = TestClient(application)

    health = not_started.get("/api/v1/health")
    readiness = not_started.get("/api/v1/readiness")
    not_started.close()

    assert health.status_code == 200
    assert readiness.status_code == 503
    assert readiness.json() == {
        "error": {"code": "service_unavailable", "message": "The local service is not ready."}
    }
    assert not settings.database_path.exists()
    assert not settings.backup_dir.exists()


def test_openapi_uses_concrete_success_and_safe_error_schemas(client):
    """The published contract must match custom envelopes instead of FastAPI defaults."""

    contract = client.get("/api/v1/openapi.json").json()
    expected_success = {
        ("/api/v1/health", "get", "200"): "HealthResponse",
        ("/api/v1/readiness", "get", "200"): "ReadinessResponse",
        ("/api/v1/instruments", "get", "200"): "InstrumentLookupResponse",
        ("/api/v1/forecasts", "post", "201"): "ForecastCreationResponse",
        ("/api/v1/history", "get", "200"): "HistoryResponse",
        ("/api/v1/history-export.json", "get", "200"): "HistoryJsonExportResponse",
        ("/api/v1/history/{event_id}", "get", "200"): "ReconstructionResponse",
        ("/api/v1/saved-forecasts/{event_id}", "get", "200"): "SavedForecastResponse",
        (
            "/api/v1/history/{event_id}/reconstructions",
            "post",
            "201",
        ): "FreshReconstructionResponse",
        ("/api/v1/history/{event_id}/prices", "get", "200"): "HistoricalPricesResponse",
        ("/api/v1/forecasts/{result_id}", "get", "200"): "OriginalForecastResultResponse",
        ("/api/v1/forecasts/{result_id}/outcomes", "post", "201"): "OutcomeResponse",
        ("/api/v1/forecasts/{result_id}/corrections", "post", "201"): "OutcomeResponse",
        ("/api/v1/operations/backups", "post", "201"): "BackupCreatedResponse",
        ("/api/v1/operations/backups/status", "get", "200"): "BackupStatusResponse",
        ("/api/v1/operations/restores", "post", "200"): "RestoreResponse",
    }
    for (path, method, status), model in expected_success.items():
        schema = contract["paths"][path][method]["responses"][status]["content"][
            "application/json"
        ]["schema"]
        assert schema == {"$ref": f"#/components/schemas/{model}"}

    for path_item in contract["paths"].values():
        for operation in path_item.values():
            for status, response in operation["responses"].items():
                if int(status) >= 400:
                    assert response["content"]["application/json"]["schema"] == {
                        "$ref": "#/components/schemas/ErrorEnvelope"
                    }
    csv_success = contract["paths"]["/api/v1/history-export.csv"]["get"]["responses"]["200"]
    assert set(csv_success["content"]) == {"text/csv"}
    assert contract["components"]["schemas"]["ErrorEnvelope"]["required"] == ["error"]
    schemas = contract["components"]["schemas"]
    assert schemas["BackupCreatedResponse"]["additionalProperties"] is False
    assert set(schemas["BackupCreatedResponse"]["required"]) == {
        "created",
        "format",
        "format_version",
        "created_at",
        "checksum_algorithm",
        "content_checksum",
        "counts",
    }
    assert schemas["RestoreResponse"]["required"] == ["verified", "promoted", "counts"]


def test_openapi_descriptions_use_only_public_product_language(client):
    """Generated prose must describe behavior without naming implementation machinery."""

    contract = client.get("/api/v1/openapi.json").json()
    descriptions = []

    def collect(value):
        if isinstance(value, dict):
            descriptions.extend(
                item
                for key, item in value.items()
                if key == "description" and isinstance(item, str)
            )
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(contract)
    prose = "\n".join(descriptions)
    assert "SQLite-shaped rows" not in prose
    assert not re.search(
        r"(?i)\b(sqlite|sql|database|storage|persistence|repository|row|table|column)\b",
        prose,
    )
    assert "database_path" not in str(contract) and "backup_dir" not in str(contract)


def test_router_method_and_mounted_asset_errors_share_safe_envelope(client):
    """Starlette-generated failures must not regress to its unrelated detail payload."""

    unknown_api = client.get("/api/v1/not-a-route")
    wrong_method = client.post("/api/v1/health")
    missing_asset = client.get("/assets/not-present.css")
    wrong_asset_method = client.post("/assets/app.js")

    assert unknown_api.status_code == missing_asset.status_code == 404
    expected = {
        "error": {"code": "not_found", "message": "The requested resource was not found."}
    }
    assert unknown_api.json() == expected
    assert missing_asset.json() == expected
    assert wrong_method.status_code == 405
    assert wrong_method.json()["error"]["code"] == "method_not_allowed"
    assert wrong_method.headers["allow"] == "GET"
    assert wrong_asset_method.status_code == 405
    assert wrong_asset_method.json()["error"]["code"] == "method_not_allowed"
    for response in (unknown_api, wrong_method, missing_asset, wrong_asset_method):
        assert response.headers["content-type"] == "application/json"
        assert response.headers["content-security-policy"]


def test_dependency_free_api_docs_obey_the_strict_csp(client):
    """The docs replacement must not depend on scripts, inline policy exceptions, or a CDN."""

    response = client.get("/api/v1/docs")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["content-security-policy"].startswith("default-src 'self'")
    assert "/api/v1/openapi.json" in response.text
    assert "<script" not in response.text
    assert "https://" not in response.text


def test_company_and_fund_names_remain_attached_to_instrument_identity(settings):
    with TestClient(create_app(settings, FixtureProvider())) as isolated:
        stock = isolated.get("/api/v1/instruments", params={"query": "ProFrac", "limit": 1})
        fund = isolated.get("/api/v1/instruments", params={"query": "SPDR"})
        history = isolated.get("/api/v1/history").json()

    stock_identity = stock.json()["items"][0]
    fund_identity = fund.json()["items"][0]
    assert stock.json()["query"] == "ProFrac"
    assert stock.json()["limit"] == 1
    assert stock_identity["company_name"] == "ProFrac Holding Corp."
    assert stock_identity["canonical_symbol"] == "ACDC"
    assert stock_identity["asset_type"] == "stock"
    assert {
        key: stock_identity[key]
        for key in ("exchange", "currency", "timezone", "quote_type")
    } == {
        "exchange": "NMS",
        "currency": "USD",
        "timezone": "America/New_York",
        "quote_type": "EQUITY",
    }
    assert fund_identity["company_name"] == "SPDR S&P 500 ETF Trust"
    assert fund_identity["canonical_symbol"] == "SPY"
    assert fund_identity["asset_type"] == "etf"
    # Identity inspection is not a forecast submission and must not invent an audit event.
    assert history["total"] == 0


def test_instrument_lookup_routes_through_application_service(settings, monkeypatch):
    application = create_app(settings, FixtureProvider())
    calls = []

    def lookup(query, limit):
        calls.append((query, limit))
        return {"query": "service-result", "items": [], "total": 0, "limit": limit}

    monkeypatch.setattr(application.state.service, "lookup", lookup)
    with TestClient(application) as isolated:
        response = isolated.get(
            "/api/v1/instruments", params={"query": "provider-must-not-run", "limit": 2}
        )

    assert response.status_code == 200
    assert response.json() == {
        "query": "service-result",
        "items": [],
        "total": 0,
        "limit": 2,
    }
    assert calls == [("provider-must-not-run", 2)]


def test_instrument_lookup_is_bounded_and_provider_failures_are_safe(settings):
    class BrokenLookupProvider(FixtureProvider):
        def lookup(self, query, limit, now):
            raise RuntimeError("secret provider implementation detail")

    with TestClient(create_app(settings, FixtureProvider())) as isolated:
        no_match = isolated.get("/api/v1/instruments", params={"query": "unknown"})
        invalid_limit = isolated.get(
            "/api/v1/instruments", params={"query": "ACDC", "limit": 6}
        )
        provider_failure = isolated.get("/api/v1/instruments", params={"query": "FAIL"})
    with TestClient(create_app(settings, BrokenLookupProvider())) as isolated:
        unexpected = isolated.get("/api/v1/instruments", params={"query": "ACDC"})

    assert no_match.json()["items"] == []
    assert invalid_limit.status_code == 422
    assert invalid_limit.json()["error"]["code"] == "validation_error"
    assert provider_failure.status_code == 502
    assert provider_failure.json()["error"]["code"] == "provider_unavailable"
    assert unexpected.status_code == 502
    assert "secret" not in str(unexpected.json())


def test_success_repeat_failure_and_searchable_history(client):
    first = _forecast(client)
    repeated = _forecast(client)
    failed = _forecast(client, "FAIL")

    assert first.status_code == 201
    assert first.json()["event"]["status"] == "successful"
    assert first.json()["input"]["company_name"] == "ProFrac Holding Corp."
    assert first.json()["input"]["instrument_identity"]["canonical_symbol"] == "ACDC"
    assert repeated.json()["event"]["status"] == "repeated"
    assert repeated.json()["input"]["id"] == first.json()["input"]["id"]
    assert failed.status_code == 502
    assert failed.json()["error"]["code"] == "provider_unavailable"
    assert failed.json()["error"]["request_id"]

    history = client.get("/api/v1/history", params={"q": "ACD", "page_size": 1}).json()
    assert history["total"] == 2
    assert history["page_size"] == 1
    failures = client.get("/api/v1/history", params={"status": "failed"}).json()
    assert failures["items"][0]["submitted_symbol"] == "FAIL"


def test_history_status_filters_and_pagination_keep_repeat_semantics_exact(client):
    _forecast(client, "ACDC")
    _forecast(client, "ACDC")
    _forecast(client, "FAIL")
    _forecast(client, "FAIL")
    _forecast(client, "SPY", "etf")

    first_page = client.get("/api/v1/history", params={"page_size": 2, "page": 1}).json()
    second_page = client.get("/api/v1/history", params={"page_size": 2, "page": 2}).json()
    repeated = client.get("/api/v1/history", params={"status": "repeated"}).json()
    failures = client.get("/api/v1/history", params={"status": "failed"}).json()
    funds = client.get("/api/v1/history", params={"asset_type": "etf"}).json()

    assert first_page["total"] == second_page["total"] == 5
    assert {item["id"] for item in first_page["items"]}.isdisjoint(
        item["id"] for item in second_page["items"]
    )
    assert len(repeated["items"]) == 1
    assert repeated["items"][0]["status"] == "repeated"
    assert repeated["items"][0]["is_repeat"] is True
    # A failed repeat remains failed; is_repeat carries its independent repeat dimension.
    assert [item["is_repeat"] for item in failures["items"]] == [True, False]
    assert all(item["status"] == "failed" and item["run_id"] is None for item in failures["items"])
    assert funds["total"] == 1 and funds["items"][0]["normalized_symbol"] == "SPY"
    assert client.get("/api/v1/history", params={"q": "%"}).json()["total"] == 0


def test_invalid_symbol_is_an_audited_failure(client):
    response = _forecast(client, "../bad")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_symbol"
    item = client.get("/api/v1/history").json()["items"][0]
    assert item["status"] == "failed"
    assert item["normalized_symbol"] is None


def test_transport_invalid_search_is_also_an_audited_failure(client):
    response = client.post("/api/v1/forecasts", json={"symbol": "A" * 65})

    assert response.status_code == 422
    assert response.json()["error"]["request_id"]
    item = client.get("/api/v1/history").json()["items"][0]
    assert item["status"] == "failed"
    assert item["error_code"] == "validation_error"
    assert len(item["submitted_symbol"]) == 64


def test_oversized_search_is_rejected_before_json_parsing_and_audited(client):
    response = client.post(
        "/api/v1/forecasts",
        content="x" * 20_000,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"
    item = client.get("/api/v1/history").json()["items"][0]
    assert item["submitted_symbol"] == "<oversized request>"


def test_chunked_search_is_rejected_without_unbounded_buffering_and_audited(client):
    """A missing length must fail before an attacker can stream an unlimited JSON body."""

    response = client.post(
        "/api/v1/forecasts",
        content=iter([b'{"symbol":"AC', b'DC","asset_type":"stock"}']),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 411
    assert response.json()["error"]["code"] == "content_length_required"
    assert response.json()["error"]["request_id"]
    item = client.get("/api/v1/history").json()["items"][0]
    assert item["status"] == "failed"
    assert item["error_code"] == "content_length_required"
    assert item["submitted_symbol"] == "<unbounded request>"


@pytest.mark.parametrize("content_length", ["invalid", "-1", "+2", "1, 1", "0" * 21])
def test_invalid_content_length_is_a_single_audited_forecast_rejection(
    client, content_length
):
    before = client.get("/api/v1/history").json()["total"]

    response = client.post(
        "/api/v1/forecasts",
        content=b"{}",
        headers={"Content-Type": "application/json", "Content-Length": content_length},
    )
    history = client.get("/api/v1/history").json()

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_content_length"
    assert response.json()["error"]["request_id"]
    assert history["total"] == before + 1
    assert history["items"][0]["error_code"] == "invalid_content_length"


@pytest.mark.parametrize("declared_size", ["1", "100"])
def test_body_length_mismatch_reaching_the_app_is_audited_once(client, declared_size):
    """ASGI framing inconsistencies are bounded and rejected before service ownership."""

    body = b'{"symbol":"ACDC","asset_type":"stock"}'
    before = client.get("/api/v1/history").json()["total"]

    response = client.post(
        "/api/v1/forecasts",
        content=body,
        headers={"Content-Type": "application/json", "Content-Length": declared_size},
    )
    history = client.get("/api/v1/history").json()

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_body_framing"
    assert history["total"] == before + 1
    assert history["items"][0]["error_code"] == "invalid_body_framing"


def test_incomplete_asgi_body_framing_is_audited_once(client):
    """A disconnect delivered to FastAPI is distinct from a wire-parser rejection."""

    sent = []
    incoming = iter(
        [
            {"type": "http.request", "body": b'{"symbol":', "more_body": True},
            {"type": "http.disconnect"},
        ]
    )

    async def invoke():
        async def receive():
            return next(incoming)

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/forecasts",
            "raw_path": b"/api/v1/forecasts",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"testserver"),
                (b"content-type", b"application/json"),
                (b"content-length", b"100"),
            ],
            "client": ("testclient", 50_000),
            "server": ("testserver", 80),
            "state": {},
        }
        await client.app(scope, receive, send)

    assert client.portal is not None
    client.portal.call(invoke)
    history = client.get("/api/v1/history").json()

    response_start = next(message for message in sent if message["type"] == "http.response.start")
    assert response_start["status"] == 400
    assert history["total"] == 1
    assert history["items"][0]["error_code"] == "invalid_body_framing"


def test_malformed_forecast_json_is_a_single_audited_transport_failure(client):
    response = client.post(
        "/api/v1/forecasts",
        content=b'{"symbol":',
        headers={"Content-Type": "application/json"},
    )
    history = client.get("/api/v1/history").json()

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["request_id"]
    assert history["total"] == 1
    assert history["items"][0]["error_code"] == "validation_error"


def test_host_origin_and_cross_site_rejections_never_create_audit_events(client):
    """Security probes precede trusted application submission and cannot grow history."""

    payload = {"symbol": "ACDC", "asset_type": "stock"}
    responses = [
        client.post("/api/v1/forecasts", json=payload, headers={"Host": "attacker.example"}),
        client.post(
            "/api/v1/forecasts",
            json=payload,
            headers={"Origin": "https://attacker.example"},
        ),
        client.post(
            "/api/v1/forecasts", json=payload, headers={"Sec-Fetch-Site": "cross-site"}
        ),
    ]

    assert [response.status_code for response in responses] == [400, 403, 403]
    assert client.get("/api/v1/history").json()["total"] == 0


def test_uvicorn_rejects_wire_malformed_framing_before_the_asgi_application(client):
    """Uvicorn's h11 parser owns malformed HTTP that never reaches FastAPI."""

    parser = h11_impl.h11.Connection(h11_impl.h11.SERVER)
    malformed_wire_request = (
        b"POST /api/v1/forecasts HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\nContent-Length: invalid\r\n\r\n{}"
    )

    parser.receive_data(malformed_wire_request)
    with pytest.raises(h11_impl.h11.RemoteProtocolError):
        parser.next_event()
    # No ASGI call occurred, so wire rejection is deliberately outside query-audit ownership.
    assert client.get("/api/v1/history").json()["total"] == 0


def test_reconstruction_and_append_only_outcome(client):
    created = _forecast(client).json()
    event_id = created["event"]["id"]
    result_id = created["results"][0]["id"]
    before = client.get(f"/api/v1/history/{event_id}").json()

    outcome = client.post(
        f"/api/v1/forecasts/{result_id}/outcomes",
        json={
            "observed_close": 24.75,
            "observed_at": "2025-01-13T16:00:00-05:00",
            "state": "observed",
            "note": "official close",
        },
    )
    after = client.get(f"/api/v1/history/{event_id}").json()

    assert outcome.status_code == 201
    assert outcome.json()["comparison_rule"].startswith("close divided")
    assert before["results"][0]["origin_price"] == after["results"][0]["origin_price"]
    assert len(after["results"][0]["outcomes"]) == 1

    too_early = client.post(
        f"/api/v1/forecasts/{result_id}/outcomes",
        json={
            "observed_close": 24.75,
            "observed_at": "2025-01-10T12:01:00-05:00",
            "state": "provisional",
        },
    )
    assert too_early.status_code == 422
    assert too_early.json()["error"]["code"] == "outcome_before_target"


def test_saved_reopen_never_calls_provider_but_fresh_cutoff_is_new_audited_analysis(settings):
    class CountingFixtureProvider(FixtureProvider):
        def __init__(self):
            self.fetch_calls = 0
            self.cutoff_calls = 0

        def fetch(self, symbol, asset_type, now):
            self.fetch_calls += 1
            return super().fetch(symbol, asset_type, now)

        def fetch_at_cutoff(self, symbol, asset_type, cutoff, now):
            self.cutoff_calls += 1
            return super().fetch_at_cutoff(symbol, asset_type, cutoff, now)

    provider = CountingFixtureProvider()
    now = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)
    with TestClient(create_app(settings, provider, lambda: now)) as isolated:
        created = _forecast(isolated).json()
        event_id = created["event"]["id"]
        calls_before_reopen = (provider.fetch_calls, provider.cutoff_calls)

        saved = isolated.get(f"/api/v1/saved-forecasts/{event_id}")
        fresh = isolated.post(
            f"/api/v1/history/{event_id}/reconstructions",
            json={
                "analysis_kind": "fresh_historical_reconstruction",
                "cutoff": "2025-01-10T16:55:00Z",
            },
        )
        fresh_history = isolated.get(
            "/api/v1/history",
            params={"analysis_kind": "fresh_historical_reconstruction"},
        ).json()

    assert saved.status_code == 200
    assert saved.json()["analysis_kind"] == "saved_recorded_forecast"
    assert saved.json()["immutable"] is True and saved.json()["recalculated"] is False
    assert saved.json()["input"] == created["input"]
    assert saved.json()["results"] == created["results"]
    assert calls_before_reopen == (1, 0)
    assert fresh.status_code == 201
    payload = fresh.json()
    assert payload["analysis_kind"] == "fresh_historical_reconstruction"
    assert payload["label"] == "Fresh historical-cutoff analysis"
    assert payload["source_event_id"] == event_id
    assert payload["event"]["id"] != event_id
    assert payload["event"]["source_event_id"] == event_id
    assert payload["event"]["status"] == "repeated"
    analysis = payload["provenance"]["analysis"]
    assert analysis["requested_cutoff"].endswith("+00:00")
    assert analysis["source_event_id"] == event_id
    assert provider.cutoff_calls == 1
    assert fresh_history["total"] == 1
    assert fresh_history["items"][0]["id"] == payload["event"]["id"]


def test_transport_invalid_reconstruction_is_one_labelled_failed_event(client):
    source_event_id = _forecast(client).json()["event"]["id"]

    response = client.post(
        f"/api/v1/history/{source_event_id}/reconstructions",
        json={"cutoff": "2025-01-10T12:00:00"},
    )
    history = client.get(
        "/api/v1/history",
        params={"analysis_kind": "fresh_historical_reconstruction"},
    ).json()

    assert response.status_code == 422
    assert response.json()["error"]["request_id"]
    assert history["total"] == 1
    assert history["items"][0]["status"] == "failed"
    assert history["items"][0]["source_event_id"] == source_event_id
    assert history["items"][0]["error_code"] == "validation_error"


def test_oversized_reconstruction_is_rejected_and_audited_once_before_parsing(client):
    source_event_id = _forecast(client).json()["event"]["id"]

    response = client.post(
        f"/api/v1/history/{source_event_id}/reconstructions",
        content="x" * 20_000,
        headers={"Content-Type": "application/json"},
    )
    fresh_events = client.get(
        "/api/v1/history",
        params={"analysis_kind": "fresh_historical_reconstruction"},
    ).json()

    assert response.status_code == 413
    assert response.json()["error"]["request_id"]
    assert fresh_events["total"] == 1
    assert fresh_events["items"][0]["error_code"] == "request_too_large"
    assert fresh_events["items"][0]["source_event_id"] == source_event_id


def test_unknown_reconstruction_transport_failures_are_safe_and_audited_once(settings):
    """Requested IDs remain metadata; unknown IDs never become source relationships."""

    class NoHistoricalFetchProvider(FixtureProvider):
        def __init__(self):
            self.cutoff_calls = 0

        def fetch_at_cutoff(self, symbol, asset_type, cutoff, now):
            self.cutoff_calls += 1
            raise AssertionError("unknown reconstruction reached the provider")

    provider = NoHistoricalFetchProvider()
    application = create_app(settings, provider)
    with TestClient(application) as isolated:
        unknown = isolated.post(
            "/api/v1/history/900001/reconstructions",
            json={"cutoff": "2025-01-10T16:55:00Z"},
        )
        oversized = isolated.post(
            "/api/v1/history/900002/reconstructions",
            content=b"x" * 20_000,
            headers={"Content-Type": "application/json"},
        )
        malformed_json = isolated.post(
            "/api/v1/history/900003/reconstructions",
            content=b'{"cutoff":',
            headers={"Content-Type": "application/json"},
        )
        malformed_length = isolated.post(
            "/api/v1/history/900004/reconstructions",
            content=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": "invalid"},
        )
        history = isolated.get(
            "/api/v1/history",
            params={"analysis_kind": "fresh_historical_reconstruction"},
        ).json()

    assert [
        unknown.status_code,
        oversized.status_code,
        malformed_json.status_code,
        malformed_length.status_code,
    ] == [404, 413, 422, 400]
    assert [
        unknown.json()["error"]["code"],
        oversized.json()["error"]["code"],
        malformed_json.json()["error"]["code"],
        malformed_length.json()["error"]["code"],
    ] == [
        "historical_source_unavailable",
        "request_too_large",
        "validation_error",
        "invalid_content_length",
    ]
    assert all(response.json()["error"]["request_id"] for response in (
        unknown,
        oversized,
        malformed_json,
        malformed_length,
    ))
    assert history["total"] == 4
    assert all(item["status"] == "failed" for item in history["items"])
    assert all(item["source_event_id"] is None for item in history["items"])
    assert {item["requested_source_event_id"] for item in history["items"]} == {
        900001,
        900002,
        900003,
        900004,
    }
    events_by_requested_id = {
        item["requested_source_event_id"]: item for item in history["items"]
    }
    assert events_by_requested_id[900001]["requested_cutoff"] == "2025-01-10T16:55:00+00:00"
    assert provider.cutoff_calls == 0


def test_explicit_correction_route_appends_without_rewriting_prior_outcome(client):
    created = _forecast(client).json()
    event_id = created["event"]["id"]
    result_id = created["results"][0]["id"]
    observed = client.post(
        f"/api/v1/forecasts/{result_id}/outcomes",
        json={
            "observed_close": 24.0,
            "observed_at": "2025-01-13T16:01:00-05:00",
            "state": "observed",
            "note": "initial close",
        },
    ).json()

    correction = client.post(
        f"/api/v1/forecasts/{result_id}/corrections",
        json={
            "observed_close": 24.1,
            "observed_at": "2025-01-13T16:02:00-05:00",
            "note": "official correction",
        },
    )
    outcomes = client.get(f"/api/v1/history/{event_id}").json()["results"][0]["outcomes"]

    assert correction.status_code == 201
    assert correction.json()["state"] == "corrected"
    assert correction.json()["id"] != observed["id"]
    assert [(item["state"], item["observed_close"]) for item in outcomes] == [
        ("observed", 24.0),
        ("corrected", 24.1),
    ]


def test_validation_and_not_found_errors_share_safe_envelope(client):
    invalid = client.get("/api/v1/history", params={"page_size": 101})
    missing = client.get("/api/v1/history/999999")
    naive_time = client.post(
        "/api/v1/forecasts/1/outcomes",
        json={"observed_close": 10, "observed_at": "2025-01-01T12:00:00", "state": "observed"},
    )

    assert invalid.json()["error"]["code"] == "validation_error"
    assert missing.json()["error"]["code"] == "not_found"
    assert naive_time.json()["error"]["code"] == "validation_error"
    assert str(Path.cwd()) not in str(invalid.json())


def test_loopback_origin_and_host_are_enforced(client):
    rejected_origin = client.post(
        "/api/v1/forecasts",
        headers={"Origin": "https://attacker.example"},
        json={"symbol": "ACDC", "asset_type": "stock"},
    )
    rejected_host = client.get("/api/v1/health", headers={"Host": "attacker.example"})
    malformed_host = client.get("/api/v1/health", headers={"Host": "localhost:not-a-port"})
    malformed_origin = client.get("/api/v1/health", headers={"Origin": "http://[::1"})

    assert rejected_origin.status_code == 403
    assert rejected_origin.json()["error"]["code"] == "origin_rejected"
    assert rejected_host.status_code == 400
    assert rejected_host.json()["error"]["code"] == "host_rejected"
    assert rejected_host.headers["content-security-policy"]
    assert malformed_host.json()["error"]["code"] == "host_rejected"
    assert malformed_origin.json()["error"]["code"] == "origin_rejected"
    assert rejected_origin.headers["x-content-type-options"] == "nosniff"

    wrong_loopback_port = client.get(
        "/api/v1/health", headers={"Origin": "http://testserver:9999"}
    )
    zero_loopback_port = client.get(
        "/api/v1/health", headers={"Origin": "http://localhost:0", "Host": "localhost"}
    )
    cross_site_fetch = client.get(
        "/api/v1/health", headers={"Sec-Fetch-Site": "cross-site"}
    )
    same_origin = client.get("/api/v1/health", headers={"Origin": "http://testserver"})
    assert wrong_loopback_port.status_code == 403
    assert zero_loopback_port.status_code == 403
    assert cross_site_fetch.json()["error"]["code"] == "origin_rejected"
    # testserver is accepted as a target host but never as a browser origin.
    assert same_origin.status_code == 403


def test_frontend_assets_use_only_versioned_api_for_application_data(client):
    html = client.get("/").text
    javascript = client.get("/assets/app.js").text

    assert 'const apiRoot = "/api/v1"' in javascript
    assert "sqlite" not in javascript.lower()
    assert "yahoo.com" not in javascript.lower()
    assert ".style." not in javascript.lower()
    assert "/api/v1/history-export.csv" in html
    assert client.get("/assets/favicon.svg").status_code == 200


def test_forecast_failure_announces_then_focuses_scrollable_result(client):
    """Keyboard users retain a live message while mobile focus moves the result into view."""

    html = client.get("/").text
    javascript = client.get("/assets/app.js").text
    rendered = javascript.index(
        "renderError(error);", javascript.index("forecastForm.addEventListener")
    )
    announced = javascript.index("Forecast failed:", rendered)
    focused = javascript.index("focusResultSection();", announced)

    assert rendered < announced < focused
    assert 'id="announcement" class="sr-only" aria-live="polite"' in html
    assert 'id="result-section"' in html and 'tabindex="-1"' in html
    assert 'section.scrollIntoView({ block: "start" });' in javascript


def test_original_result_and_captured_prices_have_bounded_read_interfaces(client):
    created = _forecast(client).json()
    event_id = created["event"]["id"]
    result_id = created["results"][0]["id"]

    original = client.get(f"/api/v1/forecasts/{result_id}")
    prices = client.get(
        f"/api/v1/history/{event_id}/prices", params={"series": "intraday", "limit": 3}
    )

    assert original.status_code == 200
    assert original.json()["immutable"] is True
    assert "outcomes" not in original.json()
    assert prices.json()["series"] == "intraday"
    assert len(prices.json()["items"]) == 3
    assert prices.json()["total_available"] > 3
    assert prices.json()["truncated"] is True
    assert "path" not in str(prices.json()).lower()


def test_failed_search_prices_and_path_bounds_use_structured_errors(client):
    _forecast(client, "FAIL")
    failed_event = client.get("/api/v1/history").json()["items"][0]["id"]

    no_prices = client.get(f"/api/v1/history/{failed_event}/prices")
    invalid_id = client.get("/api/v1/forecasts/0")
    invalid_limit = client.get(
        f"/api/v1/history/{failed_event}/prices", params={"limit": 501}
    )

    assert no_prices.status_code == 409
    assert no_prices.json()["error"]["code"] == "forecast_unavailable"
    assert invalid_id.json()["error"]["code"] == "validation_error"
    assert invalid_limit.json()["error"]["code"] == "validation_error"


def test_backup_status_and_export_do_not_expose_server_storage(client):
    _forecast(client)

    status = client.get("/api/v1/operations/backups/status")
    exported = client.get("/api/v1/history/export.csv")

    assert status.json() == {
        "status": "available",
        "managed_names_only": True,
        "verification_required": True,
        "promotion_default": False,
        "max_artifact_bytes": 64 * 1024 * 1024,
    }
    assert "path" not in str(status.json()).lower()
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")


def test_backup_and_restore_successes_expose_only_api_neutral_integrity_fields(client):
    """Operational adapters may return internal metadata, but the browser contract may not."""

    _forecast(client)
    created = client.post(
        "/api/v1/operations/backups", json={"name": "api-round-trip.spbackup"}
    )
    restored = client.post(
        "/api/v1/operations/restores",
        json={"name": "api-round-trip.spbackup", "promote": False},
    )
    promoted = client.post(
        "/api/v1/operations/restores",
        json={"name": "api-round-trip.spbackup", "promote": True},
    )

    assert created.status_code == 201
    assert set(created.json()) == {
        "created",
        "format",
        "format_version",
        "created_at",
        "checksum_algorithm",
        "content_checksum",
        "counts",
    }
    assert created.json()["created"] is True
    assert created.json()["checksum_algorithm"] == "sha256"
    assert re.fullmatch(r"[0-9a-f]{64}", created.json()["content_checksum"])
    assert restored.status_code == 200
    assert set(restored.json()) == {"verified", "promoted", "counts"}
    assert restored.json()["verified"] is True
    assert restored.json()["promoted"] is False
    assert promoted.status_code == 200
    assert promoted.json()["verified"] is True
    assert promoted.json()["promoted"] is True

    expected_counts = {
        "searches": 1,
        "forecast_analyses": 1,
        "market_data_snapshots": 1,
        "probability_results": 2,
        "outcome_observations": 0,
    }
    assert created.json()["counts"] == expected_counts
    assert restored.json()["counts"] == expected_counts
    assert promoted.json()["counts"] == expected_counts

    public_payloads = json.dumps([created.json(), restored.json(), promoted.json()])
    assert "api-round-trip.spbackup" not in public_payloads
    assert not re.search(
        r"(?i)\b(sqlite|sql|database|repository|filesystem|filename)\b", public_payloads
    )
    assert str(client.app.state.repository.database_path) not in public_payloads


def test_backup_count_schema_and_all_success_responses_hide_internal_identifiers(client):
    """Integrity totals retain their values without publishing implementation identifiers."""

    _forecast(client)
    responses = [
        client.post("/api/v1/operations/backups", json={"name": "count-scan.spbackup"}),
        client.post(
            "/api/v1/operations/restores",
            json={"name": "count-scan.spbackup", "promote": False},
        ),
        client.post(
            "/api/v1/operations/restores",
            json={"name": "count-scan.spbackup", "promote": True},
        ),
    ]
    contract = client.get("/api/v1/openapi.json").json()
    operation_schemas = {
        name: schema
        for name, schema in contract["components"]["schemas"].items()
        if name.startswith(("Backup", "Restore"))
    }
    schemas_and_responses = json.dumps(
        {"schemas": operation_schemas, "responses": [r.json() for r in responses]}
    )
    internal_identifiers = {
        "search_events",
        "forecast_runs",
        "forecast_inputs",
        "forecast_results",
        "outcomes",
    }

    assert [response.status_code for response in responses] == [201, 200, 200]
    assert all(identifier not in schemas_and_responses for identifier in internal_identifiers)
    assert [sum(response.json()["counts"].values()) for response in responses] == [5, 5, 5]


def test_backup_and_repository_failures_are_stable_safe_and_correlated(
    settings, monkeypatch, caplog
):
    """Adapter text may be hostile; response and ordinary diagnostics remain bounded and safe."""

    application = create_app(settings, FixtureProvider())
    adversarial = "SQLite database /srv/private/main.sqlite3 failed: SELECT * FROM secrets"

    def fail_backup(_name):
        raise BackupError(adversarial)

    def fail_restore(_name, *, promote):
        raise RepositoryError(adversarial)

    monkeypatch.setattr(application.state.backups, "create", fail_backup)
    monkeypatch.setattr(application.state.backups, "restore", fail_restore)
    caplog.set_level("ERROR", logger="stock_probs.api")
    with TestClient(application) as isolated:
        backup = isolated.post(
            "/api/v1/operations/backups", json={"name": "safe-name.spbackup"}
        )
        restore = isolated.post(
            "/api/v1/operations/restores",
            json={"name": "safe-name.spbackup", "promote": True},
        )

    assert backup.status_code == 422
    assert backup.json()["error"]["code"] == "backup_creation_failed"
    assert backup.json()["error"]["message"] == "The backup artifact could not be created."
    assert restore.status_code == 503
    assert restore.json()["error"]["code"] == "operation_unavailable"
    assert restore.json()["error"]["message"] == (
        "The requested backup operation is temporarily unavailable."
    )
    for response in (backup, restore):
        assert re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            response.json()["error"]["request_id"],
        )
        assert adversarial not in response.text
    assert "backup_creation_failed" in caplog.text
    assert "operation_unavailable" in caplog.text
    assert adversarial not in caplog.text


def test_unexpected_backup_and_restore_failures_are_generic_correlated_and_safely_logged(
    settings, monkeypatch, caplog
):
    """Catch-all operation failures must retain correlation without diagnostic disclosure."""

    application = create_app(settings, FixtureProvider())
    adversarial = "SQLite /srv/private/main.sqlite3 SELECT credentials token=do-not-publish"

    def fail_unexpected(*_args, **_kwargs):
        raise RuntimeError(adversarial)

    monkeypatch.setattr(application.state.backups, "create", fail_unexpected)
    monkeypatch.setattr(application.state.backups, "restore", fail_unexpected)
    caplog.set_level("ERROR", logger="stock_probs.api")
    with TestClient(application, raise_server_exceptions=False) as isolated:
        backup = isolated.post(
            "/api/v1/operations/backups", json={"name": "safe-name.spbackup"}
        )
        restore = isolated.post(
            "/api/v1/operations/restores",
            json={"name": "safe-name.spbackup", "promote": False},
        )

    assert backup.status_code == restore.status_code == 500
    assert backup.json()["error"]["code"] == "internal_error"
    assert restore.json()["error"]["code"] == "internal_error"
    assert backup.json()["error"]["message"] == restore.json()["error"]["message"] == (
        "The local service could not complete the request."
    )
    for response in (backup, restore):
        assert re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            response.json()["error"]["request_id"],
        )
        assert adversarial not in response.text
    assert "operation=backup-create" in caplog.text
    assert "operation=restore" in caplog.text
    assert "code=internal_error" in caplog.text
    assert adversarial not in caplog.text


def test_operational_validation_does_not_reflect_adversarial_field_names(client):
    adversarial = {
        "database_path": "/srv/private/main.sqlite3",
        "sql": "SELECT * FROM secrets",
        "filename": "private.spbackup",
    }

    for endpoint in ("/api/v1/operations/backups", "/api/v1/operations/restores"):
        response = client.post(endpoint, json=adversarial)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"
        assert response.json()["error"]["request_id"]
        assert "details" not in response.json()["error"]
        assert not any(value in response.text for value in adversarial)


def test_docs_openapi_and_operational_contract_omit_internal_data_terms(client):
    """Scan rendered docs and the complete machine contract, not selected descriptions only."""

    docs = client.get("/api/v1/docs")
    contract = client.get("/api/v1/openapi.json")
    public_contract = docs.text + contract.text

    assert docs.status_code == contract.status_code == 200
    assert not re.search(
        r"(?i)\b(sqlite|sql|database|repository|filesystem|filename)\b", public_contract
    )
    assert str(client.app.state.repository.database_path) not in public_contract


def test_json_and_csv_exports_preserve_identity_and_distinguish_audit_records(client):
    _forecast(client, "ACDC")
    _forecast(client, "ACDC")
    _forecast(client, "FAIL")

    json_export = client.get("/api/v1/history-export.json")
    csv_export = client.get("/api/v1/history-export.csv")
    payload = json_export.json()
    csv_rows = list(csv.DictReader(io.StringIO(csv_export.text, newline="")))

    assert json_export.status_code == csv_export.status_code == 200
    assert payload["format"] == "stock-probs-history"
    assert payload["counts"] == {"events": 3, "runs": 1, "results": 2}
    assert payload["truncated"] is False
    assert {record["record_type"] for record in payload["records"]} == {
        "event",
        "run",
        "result",
    }
    run = next(record for record in payload["records"] if record["record_type"] == "run")
    assert run["data"]["instrument_identity"]["canonical_symbol"] == "ACDC"
    assert run["data"]["instrument_identity"]["company_name"] == "ProFrac Holding Corp."
    assert {row["record_type"] for row in csv_rows} == {"event", "run", "result"}
    assert all(row["run_id"] for row in csv_rows if row["record_type"] != "event")
    assert "database_path" not in json_export.text and "database_path" not in csv_export.text


def test_history_exports_are_capped_and_report_truncation(client):
    for _ in range(101):
        _forecast(client, "../invalid")

    exported = client.get("/api/v1/history-export.json").json()

    assert exported["total_events"] == 101
    assert exported["exported_events"] == exported["counts"]["events"] == 100
    assert exported["counts"]["runs"] == exported["counts"]["results"] == 0
    assert exported["truncated"] is True
    assert len(exported["records"]) == 100


def test_environment_host_setting_fails_closed_without_cli_acknowledgement(monkeypatch):
    # Settings have no broad-bind escape hatch; only the explicit CLI flag owns that decision.
    monkeypatch.setenv("STOCK_PROBS_HOST", "0.0.0.0")  # noqa: S104

    try:
        Settings.from_env()
    except ValueError as exc:
        assert "loopback" in str(exc)
    else:  # pragma: no cover - this branch makes the security assertion's intent explicit.
        raise AssertionError("non-loopback environment host was accepted")


def test_history_csv_neutralizes_spreadsheet_formulas(client):
    # Formula leaders remain dangerous when a spreadsheet strips controls or invisible marks.
    attacks = [
        "-FORMULA",
        "\n=LINEFEED()",
        "\r+RETURN()",
        "\t@TAB()",
        " \ufeff-HIDDEN()",
        "\u200b\t=OBSCURED()",
    ]
    for attack in attacks:
        _forecast(client, attack)
    _forecast(client, " ACDC")
    exported = client.get("/api/v1/history-export.csv")

    assert exported.status_code == 200
    rows = list(csv.DictReader(io.StringIO(exported.text, newline="")))
    exported_symbols = {row["submitted_symbol"] for row in rows}
    assert {"'" + attack for attack in attacks} <= exported_symbols
    assert " ACDC" in exported_symbols


def test_unexpected_provider_failure_is_safe_and_audited(settings):
    class BrokenProvider:
        """Represent an adapter defect rather than a classified provider response."""

        def fetch(self, symbol, asset_type, now):
            raise RuntimeError("secret provider detail")

    with TestClient(create_app(settings, BrokenProvider())) as isolated:
        response = _forecast(isolated)
        history = isolated.get("/api/v1/history").json()

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "provider_unavailable"
    assert "secret" not in str(response.json())
    assert history["items"][0]["status"] == "failed"
