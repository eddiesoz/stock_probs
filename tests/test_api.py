"""M01-M04 API tests cover the versioned boundary, audit matrix, and safe errors."""

from __future__ import annotations

import base64
import csv
import io
import json
import re
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from uvicorn.protocols.http import h11_impl

from stock_probs.api import create_app
from stock_probs.backup import BackupError
from stock_probs.config import Settings
from stock_probs.domain import DomainError, calculate_forecasts
from stock_probs.provider import FixtureProvider
from stock_probs.repository import SCHEMA_VERSION, RepositoryError


def _forecast(client, symbol="ACDC", asset_type="stock"):
    """Submit through the public transport boundary rather than calling repositories."""

    return client.post("/api/v1/forecasts", json={"symbol": symbol, "asset_type": asset_type})


def _news_response(symbol="ACDC", limit=5, *, items=None, cache_state="miss"):
    selected = items if items is not None else []
    return {
        "query": {"symbol": symbol, "limit": limit},
        "provider": "Yahoo Finance",
        "as_of": "2025-01-10T12:03:00-05:00",
        "items": selected,
        "coverage": {
            "returned_count": len(selected),
            "partial_metadata": any(
                item["publisher"] is None or item["published_at"] is None for item in selected
            ),
            "refresh_failed": cache_state == "stale_fallback",
        },
        "cache_state": cache_state,
    }


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
        ("/api/v1/news", "get", "200"): "NewsResponse",
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


def test_openapi_publishes_concrete_dashboard_filter_and_download_contracts(client):
    contract = client.get("/api/v1/openapi.json").json()
    history = contract["paths"]["/api/v1/history"]["get"]
    csv_download = contract["paths"]["/api/v1/history-export.csv"]["get"]
    json_download = contract["paths"]["/api/v1/history-export.json"]["get"]
    parameters = {item["name"]: item for item in history["parameters"]}

    assert set(parameters) == {
        "q",
        "symbol",
        "company",
        "status",
        "asset_type",
        "analysis_kind",
        "submitted_from",
        "submitted_to",
        "model",
        "model_version",
        "horizon",
        "request_id",
        "event_id",
        "sort_by",
        "sort_order",
        "page",
        "page_size",
    }
    assert parameters["submitted_from"]["schema"]["anyOf"][0]["format"] == "date-time"
    assert parameters["page_size"]["schema"]["maximum"] == 100
    assert parameters["event_id"]["schema"]["anyOf"][0]["maximum"] == 2_147_483_647
    serialized_parameters = json.dumps(parameters)
    for value in (
        "successful",
        "failed",
        "repeated",
        "stock",
        "etf",
        "submitted_forecast",
        "fresh_historical_reconstruction",
        "close_to_close",
        "completed_5m_to_close",
        "company",
        "model",
        "request_id",
        "asc",
        "desc",
    ):
        assert value in serialized_parameters
    assert set(csv_download["responses"]["200"]["content"]) == {"text/csv"}
    assert set(csv_download["responses"]["200"]["headers"]) == {
        "Content-Disposition",
        "X-Export-Filters",
        "X-Export-Sort",
    }
    assert json_download["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HistoryJsonExportResponse"
    }
    assert set(json_download["responses"]["200"]["headers"]) == {
        "Content-Disposition",
        "X-Export-Filters",
        "X-Export-Sort",
    }
    forecast_created = contract["paths"]["/api/v1/forecasts"]["post"]["responses"]["201"]
    assert set(forecast_created["headers"]) == {"Location", "X-Request-ID"}
    history_schema = contract["components"]["schemas"]["HistoryResponse"]
    assert set(history_schema["required"]) >= {
        "items",
        "total",
        "total_pages",
        "has_previous",
        "has_next",
        "filters",
        "sort",
    }
    assert contract["components"]["schemas"]["HistoryJsonExportResponse"]["properties"][
        "generated_at"
    ]["format"] == "date-time"


def test_non_integer_history_details_are_safe_404s_not_export_aliases(client):
    invalid_details = {
        "/api/v1/history/export.json",
        "/api/v1/history/export.csv",
        "/api/v1/history/not-an-event",
        "/api/v1/history/123abc",
    }
    published = set(client.get("/api/v1/openapi.json").json()["paths"])

    assert invalid_details.isdisjoint(published)
    for path in invalid_details:
        response = client.get(path)
        assert response.status_code == 404
        assert response.json() == {
            "error": {"code": "not_found", "message": "The requested resource was not found."}
        }


def test_history_detail_keeps_typed_positive_ids_and_numeric_bounds(client):
    created = _forecast(client).json()

    detail = client.get(f"/api/v1/history/{created['event']['id']}")
    too_small = client.get("/api/v1/history/0")
    too_large = client.get("/api/v1/history/2147483648")

    assert detail.status_code == 200
    assert detail.json()["event"]["id"] == created["event"]["id"]
    for response in (too_small, too_large):
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"


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
    """The docs replacement uses only its early local theme script, never inline code or a CDN."""

    response = client.get("/api/v1/docs")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["content-security-policy"].startswith("default-src 'self'")
    assert "/api/v1/openapi.json" in response.text
    theme_script = '<script src="/assets/theme.js"></script>'
    assert response.text.count("<script") == 1
    assert theme_script in response.text
    assert response.text.index(theme_script) < response.text.index('<link rel="stylesheet"')
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


def test_news_normalizes_symbol_and_returns_only_the_typed_service_result(client, monkeypatch):
    calls = []
    items = [
        {
            "id": "story-1",
            "title": "ACDC reports results",
            "publisher": "Example Wire",
            "url": "https://example.com/news/story-1",
            "published_at": "2025-01-10T11:00:00-05:00",
            "related_symbols": ["ACDC", "SPY"],
        },
        {
            "id": "story-2",
            "title": "ACDC announces an update",
            "publisher": None,
            "url": "https://example.com/news/story-2",
            "published_at": None,
            "related_symbols": None,
        },
    ]

    def news(symbol, limit=5):
        calls.append((symbol, limit))
        return _news_response(symbol, limit, items=items)

    monkeypatch.setattr(client.app.state.service, "news", news, raising=False)
    response = client.get("/api/v1/news", params={"symbol": " acdc ", "limit": 2})

    assert response.status_code == 200
    assert calls == [("ACDC", 2)]
    assert response.json() == {
        **_news_response("ACDC", 2, items=items),
        "as_of": "2025-01-10T17:03:00Z",
        "items": [{**items[0], "published_at": "2025-01-10T16:00:00Z"}, items[1]],
    }
    assert set(response.json()) == {
        "query",
        "provider",
        "as_of",
        "items",
        "coverage",
        "cache_state",
    }
    assert client.get("/api/v1/history").json()["total"] == 0


def test_empty_news_is_a_success_and_uses_the_default_limit(client, monkeypatch):
    monkeypatch.setattr(
        client.app.state.service,
        "news",
        lambda symbol, limit=5: _news_response(symbol, limit),
        raising=False,
    )

    response = client.get("/api/v1/news", params={"symbol": "SPY"})

    assert response.status_code == 200
    assert response.json()["query"] == {"symbol": "SPY", "limit": 5}
    assert response.json()["items"] == []
    assert response.json()["coverage"]["returned_count"] == 0


def test_fixture_news_service_handoff_matches_the_public_contract(client):
    response = client.get("/api/v1/news", params={"symbol": "ACDC", "limit": 1})

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == {"symbol": "ACDC", "limit": 1}
    assert payload["coverage"]["returned_count"] == len(payload["items"]) == 1
    assert set(payload["items"][0]) == {
        "id",
        "title",
        "publisher",
        "url",
        "published_at",
        "related_symbols",
    }


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"symbol": ""},
        {"symbol": "../ACDC"},
        {"symbol": "ACDC", "limit": "five"},
        {"symbol": "ACDC", "limit": "5.0"},
        {"symbol": "ACDC", "limit": 0},
        {"symbol": "ACDC", "limit": 11},
        {"symbol": "ACDC", "unknown": "value"},
        [("symbol", "ACDC"), ("symbol", "SPY")],
        [("symbol", "ACDC"), ("limit", "2"), ("limit", "3")],
    ],
    ids=[
        "missing-symbol",
        "empty-symbol",
        "invalid-symbol",
        "non-integer-limit",
        "decimal-limit",
        "limit-too-small",
        "limit-too-large",
        "unknown-field",
        "duplicate-symbol",
        "duplicate-limit",
    ],
)
def test_news_rejects_invalid_unknown_and_duplicate_query_fields(client, monkeypatch, params):
    def unexpected_call(*_args, **_kwargs):
        raise AssertionError("invalid news query reached the service")

    monkeypatch.setattr(client.app.state.service, "news", unexpected_call, raising=False)

    response = client.get("/api/v1/news", params=params)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    ("service_code", "public_code", "status"),
    [
        ("provider_unavailable", "provider_unavailable", 502),
        ("provider_news_invalid", "provider_unavailable", 502),
        ("provider_busy", "provider_busy", 503),
    ],
)
def test_news_preserves_safe_provider_statuses(
    client, monkeypatch, service_code, public_code, status
):
    def failed_news(*_args, **_kwargs):
        raise DomainError(
            service_code,
            "https://upstream.invalid/private /home/user/data",
            status_code=status,
        )

    monkeypatch.setattr(client.app.state.service, "news", failed_news, raising=False)

    response = client.get("/api/v1/news", params={"symbol": "ACDC"})

    assert response.status_code == status
    assert response.json()["error"]["code"] == public_code
    assert "upstream.invalid" not in response.text
    assert "/home/user" not in response.text


def test_news_openapi_is_concrete_closed_and_has_no_empty_result_404(client):
    contract = client.get("/api/v1/openapi.json").json()
    operation = contract["paths"]["/api/v1/news"]["get"]
    schemas = contract["components"]["schemas"]
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}

    assert set(parameters) == {"symbol", "limit"}
    assert parameters["symbol"]["required"] is True
    assert {
        "type": "string",
        "minLength": 1,
        "maxLength": 15,
    }.items() <= parameters["symbol"]["schema"].items()
    assert {
        "type": "integer",
        "minimum": 1,
        "maximum": 10,
        "default": 5,
    }.items() <= parameters["limit"]["schema"].items()
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/NewsResponse"
    }
    assert "404" not in operation["responses"]
    assert {"422", "502", "503"} <= set(operation["responses"])
    for status in ("422", "502", "503"):
        assert operation["responses"][status]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorEnvelope"
        }
    for name in ("NewsQuery", "NewsItem", "NewsCoverage", "NewsResponse"):
        assert schemas[name]["additionalProperties"] is False
    item_properties = schemas["NewsItem"]["properties"]
    assert set(schemas["NewsItem"]["required"]) == {
        "id",
        "title",
        "publisher",
        "url",
        "published_at",
        "related_symbols",
    }
    assert (item_properties["id"]["minLength"], item_properties["id"]["maxLength"]) == (
        1,
        128,
    )
    assert (item_properties["title"]["minLength"], item_properties["title"]["maxLength"]) == (
        1,
        500,
    )
    assert item_properties["publisher"]["anyOf"][0]["maxLength"] == 200
    assert item_properties["url"]["format"] == "uri"
    assert item_properties["url"]["maxLength"] == 2048
    assert item_properties["published_at"]["anyOf"][0]["format"] == "date-time"
    assert item_properties["related_symbols"]["anyOf"][0]["maxItems"] == 32
    assert schemas["NewsResponse"]["properties"]["cache_state"]["enum"] == [
        "miss",
        "hit",
        "stale_fallback",
    ]


def test_news_rejects_malformed_service_output_without_leaking_it(settings, monkeypatch):
    application = create_app(settings, FixtureProvider())
    malformed = _news_response(
        items=[
            {
                "id": "story-1",
                "title": "unsafe",
                "publisher": None,
                "url": "http://upstream.example/private?token=secret",
                "published_at": None,
                "related_symbols": None,
                "upstream_body": "do-not-leak",
            }
        ]
    )
    monkeypatch.setattr(
        application.state.service,
        "news",
        lambda *_args, **_kwargs: malformed,
        raising=False,
    )

    with TestClient(application, raise_server_exceptions=False) as isolated:
        response = isolated.get("/api/v1/news", params={"symbol": "ACDC"})

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "upstream.example" not in response.text
    assert "secret" not in response.text
    assert "do-not-leak" not in response.text


def test_success_repeat_failure_and_searchable_history(client, monkeypatch):
    first = _forecast(client)
    repeated = _forecast(client)
    monkeypatch.setattr("stock_probs.service.uuid4", lambda: "req-failure-fixed-0001")
    failed = _forecast(client, "FAIL")

    assert first.status_code == 201
    assert first.json()["event"]["status"] == "successful"
    assert first.headers["location"] == (
        f"/api/v1/saved-forecasts/{first.json()['event']['id']}"
    )
    assert first.headers["x-request-id"] == first.json()["event"]["request_id"]
    assert first.json()["input"]["company_name"] == "ProFrac Holding Corp."
    assert first.json()["input"]["instrument_identity"]["canonical_symbol"] == "ACDC"
    assert repeated.json()["event"]["status"] == "repeated"
    assert repeated.json()["input"]["id"] == first.json()["input"]["id"]
    assert failed.status_code == 502
    assert failed.json()["error"]["code"] == "provider_unavailable"
    assert failed.json()["error"]["request_id"] == "req-failure-fixed-0001"

    history = client.get("/api/v1/history", params={"q": "ACD", "page_size": 1}).json()
    assert history["total"] == 2
    assert history["page_size"] == 1
    assert history["items"][0]["id"] == repeated.json()["event"]["id"]
    assert history["items"][0]["status"] == "repeated"
    failures = client.get("/api/v1/history", params={"status": "failed"}).json()
    assert failures["total"] == 1
    assert failures["items"][0]["status"] == "failed"
    assert failures["items"][0]["submitted_symbol"] == "FAIL"


def test_forecast_api_exposes_complete_typed_m03_contract(client):
    """Pin every forecast-facing field at the transport boundary, including B-owned metrics."""

    response = _forecast(client)
    assert response.status_code == 201
    payload = response.json()
    captured = payload["input"]
    assert set(captured) == {
        "id",
        "symbol",
        "canonical_symbol",
        "display_name",
        "company_name",
        "asset_type",
        "quote_type",
        "exchange",
        "exchange_timezone",
        "currency",
        "provider",
        "provider_as_of",
        "request_cutoff",
        "provider_query",
        "provider_metadata",
        "content_fingerprint",
        "instrument_identity",
        "identity_fingerprint",
        "captured_at",
        "selected_daily_bars",
        "selected_intraday_bars",
        "session_rule",
        "calendar",
        "limitations",
        "quality",
        "quality_reasons",
        "stale_state",
        "session_state_at_request",
        "forecast_contract_version",
        "model",
        "model_fingerprint",
        "parameters",
        "provenance",
    }
    assert set(captured["instrument_identity"]) == {
        "canonical_symbol",
        "display_name",
        "company_name",
        "exchange",
        "currency",
        "timezone",
        "quote_type",
        "asset_type",
        "provider",
        "provider_as_of",
    }
    assert captured["company_name"] == captured["instrument_identity"]["company_name"]
    assert captured["canonical_symbol"] == captured["instrument_identity"]["canonical_symbol"]
    assert captured["model"]["version"] == captured["provenance"]["model_version"]
    assert captured["model_fingerprint"] == captured["provenance"]["model_fingerprint"]
    assert captured["provider_query"] == captured["provenance"]["query"]
    assert captured["provider_as_of"] == captured["provenance"]["response_as_of"]
    assert set(captured["provider_query"]) == {
        "requested_as_of",
        "daily",
        "intraday",
        "mode",
        "data_cutoff",
        "fixture",
    }
    assert set(captured["provenance"]) == {
        "source",
        "query",
        "response_as_of",
        "content_fingerprint",
        "instrument_identity",
        "identity_fingerprint",
        "model_version",
        "forecast_contract_version",
        "evaluation_version",
        "calendar_version",
        "model_fingerprint",
    }
    assert set(captured["provider_metadata"]) == {
        "identity_source",
        "regular_session",
        "data_granularity",
        "exchange_timezone",
        "session_scope",
        "intraday_archive_limit",
        "daily_coverage",
        "intraday_coverage",
        "daily_returned_rows",
        "intraday_returned_rows",
        "daily_normalized_rows",
        "intraday_normalized_rows",
        "daily_rejected_rows",
        "intraday_rejected_rows",
        "daily_duplicate_timestamps",
        "intraday_duplicate_timestamps",
        "missing_daily_closes",
        "missing_daily_sessions",
        "missing_intraday_closes",
        "missing_intraday_intervals",
        "trailing_missing_intraday_intervals",
        "fixture",
        "fixture_contract",
        "fixture_base_symbol",
    }
    assert captured["provider_metadata"]["intraday_archive_limit"]["approximate_days"] == 60
    assert "approximately 60" in captured["provider_metadata"]["intraday_archive_limit"][
        "statement"
    ]
    assert captured["provider_metadata"]["session_scope"] == (
        "regular session only (prepost=False)"
    )
    assert captured["provider_metadata"]["exchange_timezone"] == captured[
        "exchange_timezone"
    ]
    for series in ("daily", "intraday"):
        coverage = captured["provider_metadata"][f"{series}_coverage"]
        assert set(coverage) == {"first", "last", "count"}
        assert coverage["first"] <= coverage["last"]
        assert coverage["count"] > 0
    assert set(captured["parameters"]) == {
        "daily_max_samples",
        "ewma_span_daily",
        "ewma_span_intraday",
        "flat_threshold",
        "maximum_absolute_training_return",
        "return_thresholds_percent",
        "evaluation_max_points",
        "reliability_bin_count",
    }

    common_result_fields = {
        "id",
        "recorded_at",
        "outcomes",
        "outcomes_truncated",
        "horizon",
        "origin_timestamp",
        "horizon_start_timestamp",
        "horizon_end_timestamp",
        "origin_price",
        "reference_timestamp",
        "reference_state",
        "target_timestamp",
        "target_state",
        "exchange_timezone",
        "stale_state",
        "calculated_at",
        "definition",
        "target_session_rule",
        "forecast_contract_version",
        "model_version",
        "model_fingerprint",
        "forecast_fingerprint",
        "direction_probabilities",
        "threshold_probabilities",
        "conditional_magnitudes",
        "magnitude_intervals",
        "sample_size",
        "sample_accounting",
        "probability_estimator",
        "distribution_definition",
        "evaluation",
    }
    by_horizon = {result["horizon"]: result for result in payload["results"]}
    assert set(by_horizon) == {"close_to_close", "completed_5m_to_close"}
    assert set(by_horizon["close_to_close"]) == common_result_fields
    assert set(by_horizon["completed_5m_to_close"]) == common_result_fields | {
        "origin_bar_end",
        "session_state_at_request",
        "target_selection",
    }

    for result in by_horizon.values():
        assert result["horizon_start_timestamp"] == result["reference_timestamp"]
        assert result["horizon_end_timestamp"] == result["target_timestamp"]
        assert result["origin_timestamp"] <= result["reference_timestamp"]
        assert result["reference_timestamp"] < result["target_timestamp"]
        direction = result["direction_probabilities"]
        assert set(direction) == {
            "down",
            "flat",
            "unchanged",
            "up",
            "unit",
            "definitions",
            "flat_definition",
            "event_counts",
            "uncertainty",
        }
        assert direction["flat"] == direction["unchanged"]
        assert sum(direction[key] for key in ("down", "unchanged", "up")) == pytest.approx(1)
        counts = direction["event_counts"]
        assert counts["sample_count"] == result["sample_size"]
        assert sum(counts[key] for key in ("down", "unchanged", "up")) == result[
            "sample_size"
        ]
        for uncertainty in direction["uncertainty"].values():
            assert set(uncertainty) == {"low", "high", "level", "method"}
            assert 0 <= uncertainty["low"] <= uncertainty["high"] <= 1

        expected_thresholds = [
            ("lte", -1.0),
            ("lte", -3.0),
            ("lte", -5.0),
            ("lte", -10.0),
            ("gte", 1.0),
            ("gte", 3.0),
            ("gte", 5.0),
            ("gte", 10.0),
        ]
        assert [(item["operator"], item["threshold"]) for item in result[
            "threshold_probabilities"
        ]] == expected_thresholds
        for threshold in result["threshold_probabilities"]:
            assert set(threshold) == {
                "operator",
                "threshold",
                "unit",
                "definition",
                "probability",
                "event_count",
                "sample_count",
                "uncertainty",
                "rare_event",
            }
            assert 0 <= threshold["probability"] <= 1
            assert threshold["event_count"] <= threshold["sample_count"] == result[
                "sample_size"
            ]
        for name, metric in result["conditional_magnitudes"].items():
            assert name in {"gain", "loss"}
            assert set(metric) == {
                "condition",
                "observed_count",
                "sample_count",
                "expected",
                "median",
                "unit",
                "definition",
            }
            assert metric["sample_count"] == result["sample_size"]
            assert metric["observed_count"] <= metric["sample_count"]
        assert [item["level"] for item in result["magnitude_intervals"]] == [0.5, 0.8, 0.95]
        for interval in result["magnitude_intervals"]:
            assert interval["percent"]["low"] <= interval["percent"]["high"]
            assert 0 < interval["price"]["low"] <= interval["price"]["high"]
        accounting = result["sample_accounting"]
        assert accounting["effective_count"] == result["sample_size"]
        assert accounting["eligible_count"] + accounting["excluded_anomaly_count"] == accounting[
            "candidate_count"
        ]

        evaluation = result["evaluation"]
        assert set(evaluation) == {
            "version",
            "method",
            "status",
            "evaluation_count",
            "eligible_realized_count",
            "excluded_anomaly_outcome_count",
            "date_range",
            "training_sample_range",
            "forecast_model",
            "baseline",
            "max_evaluation_points",
            "minimum_training_samples",
            "information_rule",
        }
        assert evaluation["status"] == "available"
        assert evaluation["date_range"]["first_origin"] <= evaluation["date_range"][
            "last_origin"
        ]
        for evaluated in (evaluation["forecast_model"], evaluation["baseline"]):
            assert set(evaluated["direction_brier"]["components"]) == {
                "down",
                "unchanged",
                "up",
            }
            assert 0 <= evaluated["direction_brier"]["multiclass_mean"] <= 2
            assert len(evaluated["threshold_brier"]) == 8
            assert evaluated["reliability"]["bin_count"] == 5
            assert len(evaluated["interval_coverage"]) == 3
            for coverage in evaluated["interval_coverage"]:
                assert coverage["coverage"] == pytest.approx(
                    coverage["covered_count"] / coverage["sample_count"]
                )


@pytest.mark.parametrize(
    ("symbol", "asset_type", "company_name", "quote_type"),
    [
        ("ACDC", "stock", "ProFrac Holding Corp.", "EQUITY"),
        ("SPY", "etf", "SPDR S&P 500 ETF Trust", "ETF"),
    ],
)
def test_forecast_horizons_remain_bound_to_selected_company_identity(
    settings, symbol, asset_type, company_name, quote_type
):
    fixed_now = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)
    with TestClient(create_app(settings, FixtureProvider(), lambda: fixed_now)) as isolated:
        payload = _forecast(isolated, symbol, asset_type).json()

    identity = payload["input"]["instrument_identity"]
    assert (identity["canonical_symbol"], identity["asset_type"], identity["company_name"]) == (
        symbol,
        asset_type,
        company_name,
    )
    assert identity["quote_type"] == quote_type
    assert len(payload["results"]) == 2
    assert all(
        result["model_fingerprint"] == payload["input"]["model_fingerprint"]
        for result in payload["results"]
    )


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda result: result["direction_probabilities"].__setitem__("up", 1.5),
        lambda result: result["threshold_probabilities"][0].__setitem__("sample_count", 0),
        lambda result: result["magnitude_intervals"][0]["percent"].update(
            {"low": 2.0, "high": 1.0}
        ),
        lambda result: result["evaluation"]["forecast_model"]["interval_coverage"][0].update(
            {"covered_count": 0, "coverage": 1.0}
        ),
    ],
    ids=["probability", "sample-count", "interval-order", "coverage-count"],
)
def test_forecast_api_rejects_invalid_numerical_service_results(settings, monkeypatch, corrupt):
    """Transport validates supplied calculations; it does not repair or silently publish them."""

    application = create_app(
        settings,
        FixtureProvider(),
        lambda: datetime(2025, 1, 10, 17, 3, tzinfo=UTC),
    )
    with TestClient(application, raise_server_exceptions=False) as isolated:
        valid = _forecast(isolated).json()
        invalid = json.loads(json.dumps(valid))
        corrupt(invalid["results"][0])
        monkeypatch.setattr(application.state.service, "search", lambda *_args: invalid)
        rejected = _forecast(isolated)

    assert rejected.status_code == 500
    assert rejected.json()["error"]["code"] == "internal_error"
    assert "input" not in rejected.json() and "results" not in rejected.json()


def test_malformed_service_forecast_without_event_is_failed_and_audited_once(
    settings, monkeypatch
):
    """Response validation owns an audit when a defective service returned no event at all."""

    application = create_app(settings, FixtureProvider())
    monkeypatch.setattr(
        application.state.service,
        "search",
        lambda *_args: {"event": None, "input": {"provider_secret": "do-not-leak"}},
    )
    with TestClient(application, raise_server_exceptions=False) as isolated:
        response = _forecast(isolated)
        history = isolated.get("/api/v1/history").json()
        recorded = isolated.get(f"/api/v1/history/{history['items'][0]['id']}").json()

    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "internal_error",
        "message": "The local service could not complete the request.",
        "request_id": history["items"][0]["request_id"],
    }
    assert "provider_secret" not in response.text and "do-not-leak" not in response.text
    assert history["total"] == 1
    assert history["items"][0]["status"] == "failed"
    assert history["items"][0]["error_code"] == "internal_error"
    assert recorded["input"] is None and recorded["results"] == []


def test_malformed_service_forecast_reuses_already_persisted_event_without_duplicate(
    settings, monkeypatch
):
    """The event request ID is an atomic idempotency key across service and API ownership."""

    application = create_app(settings, FixtureProvider())
    request_id = "service-audit-request"

    def malformed_after_audit(submitted_symbol, asset_type):
        now = datetime.now(UTC)
        event_id = application.state.repository.record_failure(
            request_id=request_id,
            submitted_symbol=submitted_symbol,
            normalized_symbol="ACDC",
            asset_type=asset_type,
            error_code="calculation_failure",
            error_message="The forecast calculation could not be completed.",
            submitted_at=now,
            completed_at=now,
        )
        # Preserve the normal event correlation fields while corrupting the success body.
        return {
            "event": {
                "id": event_id,
                "request_id": request_id,
                "status": "failed",
            },
            "input": {"implementation_detail": "do-not-leak"},
            "results": [],
        }

    monkeypatch.setattr(application.state.service, "search", malformed_after_audit)
    with TestClient(application, raise_server_exceptions=False) as isolated:
        response = _forecast(isolated)
        history = isolated.get("/api/v1/history").json()
        recorded = isolated.get(f"/api/v1/history/{history['items'][0]['id']}").json()

    assert response.status_code == 500
    assert response.json()["error"]["request_id"] == request_id
    assert response.json()["error"]["code"] == "internal_error"
    assert "implementation_detail" not in response.text and "do-not-leak" not in response.text
    assert history["total"] == 1
    assert history["items"][0]["request_id"] == request_id
    assert history["items"][0]["status"] == "failed"
    assert history["items"][0]["error_code"] == "calculation_failure"
    assert recorded["input"] is None and recorded["results"] == []


def test_openapi_forecast_contract_is_closed_and_timestamp_typed(client):
    contract = client.get("/api/v1/openapi.json").json()
    schemas = contract["components"]["schemas"]
    forecast_schema_names = {
        name
        for name in schemas
        if any(
            term in name
            for term in (
                "Forecast",
                "Direction",
                "Threshold",
                "Interval",
                "Reliability",
                "Evaluation",
                "Provider",
                "Sample",
                "Conditional",
            )
        )
    }
    assert forecast_schema_names
    assert all(schemas[name].get("additionalProperties") is False for name in forecast_schema_names)
    result = schemas["RecordedForecastResultResponse"]
    assert result["properties"]["origin_timestamp"]["format"] == "date-time"
    assert result["properties"]["horizon_start_timestamp"]["format"] == "date-time"
    assert result["properties"]["horizon_end_timestamp"]["format"] == "date-time"
    assert set(result["required"]) >= {
        "horizon",
        "horizon_start_timestamp",
        "horizon_end_timestamp",
        "direction_probabilities",
        "threshold_probabilities",
        "conditional_magnitudes",
        "magnitude_intervals",
        "sample_accounting",
        "evaluation",
    }
    serialized = json.dumps({name: schemas[name] for name in forecast_schema_names}).lower()
    assert not re.search(r"\b(sqlite|sql|database|repository|dataframe)\b", serialized)


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


def test_dashboard_history_filters_every_public_facet_and_reports_stable_paging(client):
    acdc = _forecast(client, "ACDC").json()
    repeated = _forecast(client, "ACDC").json()
    spy = _forecast(client, "SPY", "etf").json()
    _forecast(client, "FAIL")

    by_company = client.get("/api/v1/history", params={"company": "profrac"}).json()
    by_symbol = client.get("/api/v1/history", params={"symbol": "SPY"}).json()
    by_model = client.get(
        "/api/v1/history", params={"model_version": acdc["input"]["model"]["version"]}
    ).json()
    by_horizon = client.get(
        "/api/v1/history", params={"horizon": "completed_5m_to_close"}
    ).json()
    by_request = client.get(
        "/api/v1/history", params={"request_id": repeated["event"]["request_id"]}
    ).json()
    by_event = client.get(
        "/api/v1/history", params={"event_id": spy["event"]["id"]}
    ).json()
    by_date = client.get(
        "/api/v1/history",
        params={
            "submitted_from": "2025-01-10T17:02:59Z",
            "submitted_to": "2025-01-10T17:03:01Z",
            "sort_by": "company",
            "sort_order": "asc",
            "page_size": 2,
        },
    ).json()

    assert by_company["total"] == 2
    assert all(item["company_name"] == "ProFrac Holding Corp." for item in by_company["items"])
    assert by_symbol["total"] == 1
    assert by_symbol["items"][0]["quote_type"] == "ETF"
    assert by_model["total"] == by_horizon["total"] == 3
    assert all(
        item["horizons"] == ["close_to_close", "completed_5m_to_close"]
        for item in by_horizon["items"]
    )
    assert [item["id"] for item in by_request["items"]] == [repeated["event"]["id"]]
    assert [item["id"] for item in by_event["items"]] == [spy["event"]["id"]]
    assert by_date["filters"]["submitted_from"] == "2025-01-10T17:02:59Z"
    assert by_date["sort"] == {"field": "company", "direction": "asc"}
    assert by_date["total_pages"] == 2
    assert by_date["has_previous"] is False and by_date["has_next"] is True


def test_failed_history_detail_never_fabricates_identity_forecast_or_evaluation(client):
    failed = _forecast(client, "FAIL")
    event = client.get("/api/v1/history", params={"status": "failed"}).json()["items"][0]
    detail = client.get(f"/api/v1/history/{event['id']}")

    assert failed.status_code == 502
    assert event["forecast_available"] is False
    assert event["company_name"] is None
    assert event["model_version"] is None
    assert event["horizons"] == []
    assert event["outcome_count"] == 0
    assert event["evaluation_statuses"] == []
    assert detail.json()["record_kind"] == "failed_search"
    assert detail.json()["immutable"] is True
    assert detail.json()["forecast_available"] is False
    assert detail.json()["input"] is None and detail.json()["results"] == []


def test_history_date_ranges_and_sort_values_are_strictly_bounded(client):
    naive = client.get("/api/v1/history", params={"submitted_from": "2025-01-10T00:00:00"})
    reversed_range = client.get(
        "/api/v1/history",
        params={
            "submitted_from": "2025-01-11T00:00:00Z",
            "submitted_to": "2025-01-10T00:00:00Z",
        },
    )
    invalid_sort = client.get("/api/v1/history", params={"sort_by": "result_json"})
    invalid_horizon = client.get("/api/v1/history", params={"horizon": "tomorrow"})

    assert naive.status_code == reversed_range.status_code == 422
    assert naive.json()["error"]["code"] == "invalid_history_date"
    assert reversed_range.json()["error"]["code"] == "invalid_history_date_range"
    assert invalid_sort.json()["error"]["code"] == "validation_error"
    assert invalid_horizon.json()["error"]["code"] == "validation_error"


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
    assert after["record_kind"] == "recorded_forecast"
    assert after["immutable"] is True and after["forecast_available"] is True
    assert before["results"][0]["origin_price"] == after["results"][0]["origin_price"]
    assert len(after["results"][0]["outcomes"]) == 1
    assert after["results"][0]["evaluation"]["status"] == "available"

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
    assert fresh.headers["location"] == f"/api/v1/saved-forecasts/{payload['event']['id']}"
    assert fresh.headers["x-request-id"] == payload["event"]["request_id"]
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
    exported = client.get("/api/v1/history-export.csv")

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
    assert [json.loads(row["record_json"]) for row in csv_rows] == [
        record["data"] for record in payload["records"]
    ]
    assert datetime.fromisoformat(payload["generated_at"]).utcoffset() == timedelta(0)
    assert {
        record["data"]["horizon"]
        for record in payload["records"]
        if record["record_type"] == "result"
    } == {"close_to_close", "completed_5m_to_close"}
    assert "database_path" not in json_export.text and "database_path" not in csv_export.text


def test_http_bulk_exports_keep_five_reads_for_one_hundred_unique_runs(client, monkeypatch):
    """The HTTP adapters must consume one bulk service stream, never reconstruct each event."""

    repository = client.app.state.repository
    now = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)
    snapshot, results = calculate_forecasts(FixtureProvider().fetch("ACDC", "stock", now), now)
    for index in range(100):
        unique_snapshot = deepcopy(snapshot)
        fingerprint = f"{index + 1:064x}"
        unique_snapshot["content_fingerprint"] = fingerprint
        unique_snapshot["provenance"]["content_fingerprint"] = fingerprint
        repository.record_success(
            request_id=f"http-bulk-{index}",
            submitted_symbol="ACDC",
            asset_type="stock",
            input_snapshot=unique_snapshot,
            results=results,
            submitted_at=now + timedelta(seconds=index),
            completed_at=now + timedelta(seconds=index + 1),
        )

    statements: list[str] = []
    original_connect = repository.connect

    @contextmanager
    def traced_connect():
        with original_connect() as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(repository, "connect", traced_connect)
    json_export = client.get("/api/v1/history-export.json")
    json_reads = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith(("SELECT", "WITH"))
    ]
    statements.clear()
    csv_export = client.get("/api/v1/history-export.csv")
    csv_reads = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith(("SELECT", "WITH"))
    ]

    assert json_export.status_code == csv_export.status_code == 200
    assert len(json_reads) == 5
    assert len(csv_reads) == 5
    assert json_export.json()["counts"] == {"events": 100, "runs": 100, "results": 200}
    assert len(list(csv.DictReader(io.StringIO(csv_export.text, newline="")))) == 400


def test_history_downloads_apply_identical_filters_sort_and_safe_attachment_contract(client):
    acdc = _forecast(client, "ACDC").json()
    _forecast(client, "SPY", "etf")
    _forecast(client, "FAIL")
    params = {
        "symbol": "ACDC",
        "asset_type": "stock",
        "status": "successful",
        "model_version": acdc["input"]["model"]["version"],
        "horizon": "close_to_close",
        "request_id": acdc["event"]["request_id"],
        "event_id": acdc["event"]["id"],
        "submitted_from": "2025-01-10T17:02:59Z",
        "submitted_to": "2025-01-10T17:03:01Z",
        "sort_by": "request_id",
        "sort_order": "asc",
    }

    json_export = client.get("/api/v1/history-export.json", params=params)
    csv_export = client.get("/api/v1/history-export.csv", params=params)
    payload = json_export.json()
    csv_rows = list(csv.DictReader(io.StringIO(csv_export.text, newline="")))

    assert payload["counts"] == {"events": 1, "runs": 1, "results": 2}
    assert payload["filters"]["symbol"] == "ACDC"
    assert payload["filters"]["submitted_from"] == "2025-01-10T17:02:59Z"
    assert payload["sort"] == {"field": "request_id", "direction": "asc"}
    assert {
        row["event_id"] for row in csv_rows if row["record_type"] == "event"
    } == {str(acdc["event"]["id"])}
    assert all(json.loads(row["export_filters"])["symbol"] == "ACDC" for row in csv_rows)
    assert all(
        json.loads(row["export_sort"]) == {"field": "request_id", "direction": "asc"}
        for row in csv_rows
    )
    for response, suffix, media_type in (
        (json_export, "json", "application/json"),
        (csv_export, "csv", "text/csv"),
    ):
        assert response.headers["content-type"].startswith(media_type)
        assert response.headers["content-disposition"] == (
            f'attachment; filename="stock-probs-history.{suffix}"'
        )
        assert re.fullmatch(r"[A-Za-z0-9_-]+", response.headers["x-export-filters"])
        encoded = response.headers["x-export-filters"]
        decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        assert json.loads(decoded)["symbol"] == "ACDC"


def test_exact_event_downloads_filter_before_cap_and_keep_json_csv_parity(client):
    oldest = _forecast(client, "ACDC").json()
    repository = client.app.state.repository
    failed_id = None
    now = datetime(2025, 1, 10, 17, 4, tzinfo=UTC)
    for index in range(100):
        failed_id = repository.record_failure(
            request_id=f"newer-failure-{index}",
            submitted_symbol="FAIL",
            normalized_symbol="FAIL",
            asset_type="stock",
            error_code="provider_unavailable",
            error_message="Fixture provider failure.",
            submitted_at=now + timedelta(seconds=index),
            completed_at=now + timedelta(seconds=index + 1),
        )

    assert client.get("/api/v1/history", params={"page_size": 1}).json()["total"] == 101
    assert failed_id is not None
    cases = (
        (
            {"event_id": oldest["event"]["id"]},
            {"events": 1, "runs": 1, "results": 2},
            oldest["event"]["id"],
        ),
        (
            {"event_id": oldest["event"]["id"], "status": "failed"},
            {"events": 0, "runs": 0, "results": 0},
            None,
        ),
        (
            {"event_id": 2_147_483_647},
            {"events": 0, "runs": 0, "results": 0},
            None,
        ),
        (
            {"event_id": failed_id},
            {"events": 1, "runs": 0, "results": 0},
            failed_id,
        ),
    )
    for params, expected_counts, expected_event_id in cases:
        json_export = client.get("/api/v1/history-export.json", params=params)
        csv_export = client.get("/api/v1/history-export.csv", params=params)
        payload = json_export.json()
        csv_rows = list(csv.DictReader(io.StringIO(csv_export.text, newline="")))

        assert json_export.status_code == csv_export.status_code == 200
        assert payload["filters"]["event_id"] == params["event_id"]
        assert payload["counts"] == expected_counts
        assert payload["total_events"] == payload["exported_events"] == expected_counts["events"]
        assert payload["truncated"] is False
        assert [json.loads(row["record_json"]) for row in csv_rows] == [
            record["data"] for record in payload["records"]
        ]
        exported_ids = [
            record["event_id"]
            for record in payload["records"]
            if record["record_type"] == "event"
        ]
        assert exported_ids == ([] if expected_event_id is None else [expected_event_id])


def test_empty_csv_download_still_carries_exact_non_reflected_filters(client):
    hostile_company = "=No Match"
    response = client.get(
        "/api/v1/history-export.csv",
        params={"company": hostile_company, "sort_by": "company", "sort_order": "desc"},
    )
    encoded = response.headers["x-export-filters"]
    decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))

    assert response.status_code == 200
    assert len(list(csv.DictReader(io.StringIO(response.text, newline="")))) == 0
    assert hostile_company not in str(response.headers)
    assert json.loads(decoded)["company"] == hostile_company
    assert re.fullmatch(r"[A-Za-z0-9_-]+", response.headers["x-export-sort"])

    control = client.get(
        "/api/v1/history-export.csv", params={"company": "No Match\r\nX-Fake: injected"}
    )
    assert control.status_code == 422
    assert control.json()["error"]["code"] == "invalid_history_filter"
    assert "X-Fake" not in str(control.headers)


def test_history_exports_are_capped_and_report_truncation(client):
    for _ in range(101):
        _forecast(client, "../invalid")

    exported = client.get("/api/v1/history-export.json").json()

    assert exported["total_events"] == 101
    assert exported["exported_events"] == exported["counts"]["events"] == 100
    assert exported["counts"]["runs"] == exported["counts"]["results"] == 0
    assert exported["truncated"] is True
    assert len(exported["records"]) == 100


def test_history_exports_sort_all_matches_before_the_hundred_event_cap(client, monkeypatch):
    repository = client.app.state.repository
    now = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)
    expected_ids = []
    for index in range(101):
        event_id = repository.record_failure(
            request_id=f"sorted-{index:03d}",
            submitted_symbol="FAIL",
            normalized_symbol="FAIL",
            asset_type="stock",
            error_code="provider_unavailable",
            error_message="Fixture provider failure.",
            submitted_at=now + timedelta(seconds=index),
            completed_at=now + timedelta(seconds=index + 1),
        )
        if index < 100:
            expected_ids.append(event_id)

    statements: list[str] = []
    original_connect = repository.connect

    @contextmanager
    def traced_connect():
        with original_connect() as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(repository, "connect", traced_connect)
    params = {"sort_by": "request_id", "sort_order": "asc"}
    json_export = client.get("/api/v1/history-export.json", params=params)
    json_reads = sum(
        statement.lstrip().upper().startswith(("SELECT", "WITH")) for statement in statements
    )
    statements.clear()
    csv_export = client.get("/api/v1/history-export.csv", params=params)
    csv_reads = sum(
        statement.lstrip().upper().startswith(("SELECT", "WITH")) for statement in statements
    )
    payload = json_export.json()
    json_ids = [
        record["event_id"] for record in payload["records"] if record["record_type"] == "event"
    ]
    csv_ids = [
        int(row["event_id"])
        for row in csv.DictReader(io.StringIO(csv_export.text, newline=""))
        if row["record_type"] == "event"
    ]

    assert json_export.status_code == csv_export.status_code == 200
    assert json_ids == csv_ids == expected_ids
    assert payload["total_events"] == 101
    assert payload["exported_events"] == 100 and payload["truncated"] is True
    assert json_reads == csv_reads == 2


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
        failed_record = isolated.get(f"/api/v1/history/{history['items'][0]['id']}").json()

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "provider_unavailable"
    assert "secret" not in str(response.json())
    assert history["items"][0]["status"] == "failed"
    assert history["items"][0]["run_id"] is None
    assert failed_record["input"] is None and failed_record["results"] == []
