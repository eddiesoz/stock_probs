"""M01-M04 API tests cover the versioned boundary, audit matrix, and safe errors."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from fastapi.testclient import TestClient

from stock_probs.api import create_app
from stock_probs.config import Settings
from stock_probs.provider import FixtureProvider


def _forecast(client, symbol="ACDC", asset_type="stock"):
    """Submit through the public transport boundary rather than calling repositories."""

    return client.post("/api/v1/forecasts", json={"symbol": symbol, "asset_type": asset_type})


def test_health_readiness_and_security_headers(client):
    health = client.get("/api/v1/health")
    readiness = client.get("/api/v1/readiness")

    assert health.json() == {"status": "ok", "service": "stock-probs", "api_version": "v1"}
    assert readiness.json()["schema_version"] == 1
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
        ("/api/v1/history/{event_id}", "get", "200"): "ReconstructionResponse",
        ("/api/v1/history/{event_id}/prices", "get", "200"): "HistoricalPricesResponse",
        ("/api/v1/forecasts/{result_id}", "get", "200"): "OriginalForecastResultResponse",
        ("/api/v1/forecasts/{result_id}/outcomes", "post", "201"): "OutcomeResponse",
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
