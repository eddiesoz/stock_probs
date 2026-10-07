"""Focused regressions for the assistant's existing history and Markets controls."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from stock_probs.assistant.feature_filters import (
    MARKET_QUOTE_FIELDS,
    MARKET_SORTS,
    InvalidFeatureFilter,
    normalize_history_action_filters,
    normalize_history_filters,
    normalize_history_form_filters,
    normalize_market_chart_range,
    normalize_market_filters,
)
from stock_probs.assistant.native_provider_adapters import project_gemini_tool_schema
from stock_probs.assistant.service import (
    AssistantService,
    AssistantStorageConflict,
    AssistantUnavailable,
)
from stock_probs.assistant.storage import (
    AssistantStorage,
    AssistantStorageNotFound,
)
from stock_probs.assistant.storage import (
    AssistantStorageConflict as StorageConflict,
)
from stock_probs.assistant.tools import AssistantToolGateway
from stock_probs.domain import calculate_forecasts
from stock_probs.provider import FIXTURE_PROVIDER_NAME, FixtureProvider
from stock_probs.repository import Repository
from stock_probs.service import ForecastService

NOW = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)
CONTEXT_VERSION = "a" * 64


def _schema_accepts(schema: object, value: object) -> bool:
    """Check the exercised schema subset; this is not a complete JSON Schema validator."""

    if not isinstance(schema, dict):
        return False
    if "allOf" in schema and not all(_schema_accepts(item, value) for item in schema["allOf"]):
        return False
    if "anyOf" in schema and not any(_schema_accepts(item, value) for item in schema["anyOf"]):
        return False
    expected_type = schema.get("type")
    if expected_type is not None:
        types = expected_type if isinstance(expected_type, list) else [expected_type]
        checks = {
            "object": lambda item: isinstance(item, dict),
            "string": lambda item: isinstance(item, str),
            "integer": lambda item: type(item) is int,
            "number": lambda item: type(item) in {int, float},
            "boolean": lambda item: type(item) is bool,
            "array": lambda item: isinstance(item, list),
            "null": lambda item: item is None,
        }
        if not any(kind in checks and checks[kind](value) for kind in types):
            return False
    if "const" in schema and value != schema["const"]:
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if isinstance(value, dict):
        if not set(schema.get("required", ())) <= set(value):
            return False
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            return False
        if any(
            key in properties and not _schema_accepts(properties[key], item)
            for key, item in value.items()
        ):
            return False
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            return False
        if len(value) > schema.get("maxLength", float("inf")):
            return False
        pattern = schema.get("pattern")
        if pattern is not None and re.fullmatch(pattern, value) is None:
            return False
        if schema.get("format") == "date":
            try:
                if date.fromisoformat(value).isoformat() != value:
                    return False
            except ValueError:
                return False
    if type(value) in {int, float}:
        if "minimum" in schema and value < schema["minimum"]:
            return False
        if "maximum" in schema and value > schema["maximum"]:
            return False
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            return False
    return True


def _proposal_schema() -> dict[str, object]:
    tool = next(
        item
        for item in AssistantToolGateway.list_tools()
        if item["name"] == "assistant.propose_action"
    )
    return tool["inputSchema"]


def _market_filter_payload(sort: str, *, asset_type: str = "", quote_field: str = ""):
    return {
        "query": "",
        "exchange": "",
        "asset_type": asset_type,
        "sort": sort,
        "min_price": "",
        "max_price": "",
        "min_change": "",
        "max_change": "",
        "min_volume": "",
        "quote_field": quote_field,
        "quote_min": "",
        "quote_max": "",
    }


def _owner(repository: Repository, github_id: int) -> int:
    row = repository.create_user(
        github_user_id=github_id,
        login=f"feature-owner-{github_id}",
        display_name=f"Feature owner {github_id}",
        password_hash=None,
        created_at=NOW,
    )
    return int(row["id"])


def _record_success(
    repository: Repository,
    provider: FixtureProvider,
    owner_id: int,
    symbol: str,
    asset_type: str,
    submitted_at: datetime,
) -> int:
    market = provider.fetch(symbol, asset_type, submitted_at)
    snapshot, results = calculate_forecasts(market, submitted_at, interval="daily")
    event_id, _run_id, _repeated, _reused = repository.record_success(
        owner_user_id=owner_id,
        request_id=f"assistant-feature-{owner_id}-{symbol}-{submitted_at:%Y%m%d%H%M%S}",
        submitted_symbol=symbol,
        asset_type=asset_type,
        input_snapshot=snapshot,
        results=results,
        submitted_at=submitted_at,
        completed_at=submitted_at + timedelta(seconds=1),
    )
    return event_id


def _tool_gateway(repository: Repository, service: ForecastService) -> AssistantToolGateway:
    class ToolAssistant:
        def __init__(self) -> None:
            self.forecast_service = service
            self.repository = repository

        def _resolve_identity(
            self, symbol: str, asset_type: str, provider: str, exchange: str
        ) -> dict[str, object]:
            lookup = service.lookup(symbol, 1)
            items = lookup.get("items", [])
            identity = next(
                (
                    item
                    for item in items
                    if isinstance(item, dict)
                    and item.get("canonical_symbol") == symbol.upper()
                    and item.get("asset_type") == asset_type
                    and item.get("provider") == provider
                    and item.get("exchange") == exchange
                ),
                None,
            )
            if identity is None:
                raise AssistantStorageConflict("action_target_changed")
            return identity

    return AssistantToolGateway(ToolAssistant())


def test_history_search_uses_owner_aware_filters_and_keeps_mcp_pages_bounded(settings):
    repository = Repository(settings.database_path)
    repository.migrate()
    owner_id = _owner(repository, 99001)
    other_id = _owner(repository, 99002)
    # Use a completed-session cutoff so the legacy forecast pair has its daily sample history.
    history_now = NOW + timedelta(hours=5)
    provider = FixtureProvider(lambda: history_now)
    acdc_id = _record_success(
        repository, provider, owner_id, "ACDC", "stock", history_now - timedelta(days=2)
    )
    spy_id = _record_success(
        repository, provider, owner_id, "SPY", "etf", history_now - timedelta(days=1)
    )
    other_acdc_id = _record_success(
        repository, provider, other_id, "ACDC", "stock", history_now - timedelta(days=2)
    )
    service = ForecastService(repository, provider, clock=lambda: history_now)
    gateway = _tool_gateway(repository, service)
    lease = {"user_id": owner_id}

    unfiltered = gateway.call(
        lease=lease, name="history.search", arguments={"page": 1, "page_size": 10}
    )
    assert unfiltered["total"] == 2
    acdc = next(item for item in unfiltered["items"] if item["id"] == acdc_id)
    repository_history = repository.history
    history_calls = []

    def record_history_call(**kwargs):
        history_calls.append(dict(kwargs))
        return repository_history(**kwargs)

    repository.history = record_history_call
    model_filter = str(acdc.get("model_version") or acdc.get("model_name"))
    horizon_filter = str(acdc["horizons"][0])
    filtered = gateway.call(
        lease=lease,
        name="history.search",
        arguments={
            "query": "",
            "status": "successful",
            "asset_type": "",
            "analysis_kind": "submitted_forecast",
            "submitted_from": "2025-01-08",
            "submitted_to": "2025-01-10",
            "model": model_filter,
            "horizon": horizon_filter,
            "sort": "symbol:asc",
            "page": 1,
            "page_size": 10,
        },
    )
    assert filtered["total"] == 2
    assert [item["normalized_symbol"] for item in filtered["items"]] == ["ACDC", "SPY"]
    assert {item["id"] for item in filtered["items"]} == {acdc_id, spy_id}
    assert filtered["page_size"] == 10
    assert len(history_calls) == 1
    indexed_call = history_calls[0]
    assert indexed_call["owner_user_id"] == owner_id
    assert indexed_call["analysis_kind"] == "submitted_forecast"
    assert indexed_call["date_from"] == datetime(2025, 1, 8, tzinfo=UTC)
    assert indexed_call["date_to"] == datetime(2025, 1, 10, 23, 59, 59, 999000, tzinfo=UTC)
    assert indexed_call["model"] == model_filter
    assert indexed_call["horizon"] == horizon_filter
    assert indexed_call["sort_by"] == "symbol"
    assert indexed_call["sort_order"] == "asc"
    assert indexed_call["page"] == 1 and indexed_call["page_size"] == 10

    other = gateway.call(
        lease={"user_id": other_id},
        name="history.search",
        arguments={"query": "ACDC", "page": 1, "page_size": 10},
    )
    assert other["total"] == 1
    assert [item["id"] for item in other["items"]] == [other_acdc_id]
    with pytest.raises(AssistantStorageNotFound):
        gateway.call(
            lease={"user_id": other_id},
            name="history.saved_forecast",
            arguments={"event_id": acdc_id},
        )

    for forged in (
        {"status": "success"},
        {"analysis_kind": "reconstruction"},
        {"submitted_from": "2025-02-30"},
        {"sort": "event_id:desc "},
        {"submitted_from": "2025-01-10", "submitted_to": "2025-01-09"},
        {"horizon": "arbitrary"},
        {"sort": "request_id:asc"},
        {"page_size": 11},
        {"page_size": True},
        {"event_id": acdc_id},
    ):
        with pytest.raises(AssistantUnavailable, match="invalid_tool_arguments"):
            gateway.call(
                lease=lease,
                name="history.search",
                arguments={"page": 1, "page_size": 10, **forged},
            )


def test_history_form_and_market_filters_reject_unrepresentable_or_forged_values():
    form = {
        "query": "ACDC",
        "status": "successful",
        "asset_type": "stock",
        "analysis_kind": "submitted_forecast",
        "submitted_from": "2025-01-01",
        "submitted_to": "2025-01-31",
        "model": "existing model filter",
        "horizon": "daily_1",
        "sort": "symbol:asc",
        "page_size": 50,
    }
    normalized = normalize_history_form_filters(form)
    assert normalized["query"] == "ACDC"
    assert normalized["page_size"] == 50
    assert "symbol" not in normalized
    with pytest.raises(InvalidFeatureFilter):
        normalize_history_form_filters({**form, "page_size": "20"})
    with pytest.raises(InvalidFeatureFilter):
        normalize_history_filters(
            {**form, "page_size": "20"}, include_page_size=True, require_query=True
        )
    projected_action = {**form, "page_size": "20"}
    normalized_action = normalize_history_action_filters(projected_action)
    assert normalized_action == {**normalized, "page_size": 20}
    assert type(normalized_action["page_size"]) is int
    assert AssistantService._validate_action_payload("filters.apply", projected_action) == (
        normalized_action
    )
    for invalid_page_size in ("11", "020", "20.0", "", True, 20.0):
        invalid_action = {**form, "page_size": invalid_page_size}
        with pytest.raises(InvalidFeatureFilter):
            normalize_history_action_filters(invalid_action)
        with pytest.raises(AssistantUnavailable, match="invalid_runtime_event"):
            AssistantService._validate_action_payload("filters.apply", invalid_action)
    with pytest.raises(InvalidFeatureFilter):
        normalize_history_form_filters({**form, "symbol": "SPY"})
    with pytest.raises(AssistantUnavailable, match="invalid_runtime_event"):
        AssistantService._validate_action_payload("filters.apply", {**form, "event_id": 1})
    with pytest.raises(AssistantUnavailable, match="invalid_runtime_event"):
        AssistantService._validate_action_payload("filters.apply", {**form, "symbol": "SPY"})

    market = {
        "query": " ACDC ",
        "exchange": "NASDAQ",
        "asset_type": "stock",
        "sort": "change:desc",
        "min_price": "0.00",
        "max_price": "10.25",
        "min_change": "-8.5",
        "max_change": "2.00",
        "min_volume": "10",
        "quote_field": "change_percent",
        "quote_min": "-9.5",
        "quote_max": "4.25",
    }
    normalized_market = normalize_market_filters(market)
    assert normalized_market["query"] == "ACDC"
    assert normalized_market["min_price"] == "0"
    assert normalized_market["min_change"] == "-8.5"
    assert normalized_market["quote_min"] == "-9.5"
    for forged in (
        {**market, "quote_field": "arbitrary"},
        {**market, "min_price": "NaN"},
        {**market, "min_volume": "1.5"},
        {**market, "min_price": "20", "max_price": "10"},
        {**market, "quote_min": "9", "quote_max": "2"},
        {**market, "new_control": "ignored"},
    ):
        with pytest.raises(InvalidFeatureFilter):
            normalize_market_filters(forged)


def test_market_bars_uses_selected_daily_range_and_revalidates_identity(settings):
    repository = Repository(settings.database_path)
    repository.migrate()
    owner_id = _owner(repository, 99003)
    provider = FixtureProvider(lambda: NOW)
    service = ForecastService(repository, provider, clock=lambda: NOW)
    gateway = _tool_gateway(repository, service)
    identity = service.lookup("ACDC", 1)["items"][0]
    arguments = {
        "symbol": "ACDC",
        "asset_type": "stock",
        "provider": FIXTURE_PROVIDER_NAME,
        "exchange": identity["exchange"],
        "interval": "daily",
        "range": "5d",
    }
    bars = gateway.call(lease={"user_id": owner_id}, name="market.bars", arguments=arguments)
    assert bars["instrument"] == {
        "symbol": identity["canonical_symbol"],
        "asset_type": identity["asset_type"],
        "provider": identity["provider"],
        "exchange": identity["exchange"],
        "display_name": identity["display_name"],
    }
    chart = bars["data"]
    assert chart["range"] == "5d"
    assert chart["interval"] == "1d"
    assert 0 < len(chart["bars"]) <= 50
    with pytest.raises(AssistantUnavailable, match="invalid_tool_arguments"):
        gateway.call(
            lease={"user_id": owner_id},
            name="market.bars",
            arguments={**arguments, "range": ["5d"]},
        )
    with pytest.raises(AssistantUnavailable, match="invalid_tool_arguments"):
        gateway.call(
            lease={"user_id": owner_id},
            name="market.bars",
            arguments={**arguments, "range": "2y"},
        )
    with pytest.raises(AssistantStorageConflict, match="action_target_changed"):
        gateway.call(
            lease={"user_id": owner_id},
            name="market.bars",
            arguments={**arguments, "provider": "unrelated provider"},
        )


def test_discovered_action_schemas_are_closed_and_cover_market_resets():
    schema = _proposal_schema()
    action_types = schema["properties"]["action_type"]["enum"]
    assert len(action_types) == 27
    assert len(set(action_types)) == 27
    assert schema["properties"]["payload"] == {"type": "object"}
    branches = schema["anyOf"]
    assert len(branches) == len(action_types)
    for action_type in action_types:
        branch = next(
            item for item in branches if item["properties"]["action_type"]["enum"] == [action_type]
        )
        payload_schema = branch["properties"]["payload"]
        assert payload_schema["type"] == "object"
        assert payload_schema["additionalProperties"] is False
        assert set(payload_schema["required"]) <= set(payload_schema["properties"])

    market_branch = next(
        item
        for item in branches
        if item["properties"]["action_type"]["enum"] == ["market.filters.apply"]
    )
    market_payload_schema = market_branch["properties"]["payload"]
    expected_market_fields = {
        "query",
        "exchange",
        "asset_type",
        "sort",
        "min_price",
        "max_price",
        "min_change",
        "max_change",
        "min_volume",
        "quote_field",
        "quote_min",
        "quote_max",
    }
    assert set(market_payload_schema["properties"]) == expected_market_fields
    assert set(market_payload_schema["required"]) == expected_market_fields

    for market_sort in MARKET_SORTS:
        payload = _market_filter_payload(
            market_sort,
            asset_type="",
            quote_field="",
        )
        request = {"action_type": "market.filters.apply", "payload": payload}
        assert _schema_accepts(schema, request)
        assert (
            AssistantService._validate_action_payload("market.filters.apply", payload)["sort"]
            == market_sort
        )
    for asset_type in ("", "stock", "etf"):
        payload = _market_filter_payload("symbol:asc", asset_type=asset_type)
        assert _schema_accepts(schema, {"action_type": "market.filters.apply", "payload": payload})
    for quote_field in ("", *MARKET_QUOTE_FIELDS):
        payload = _market_filter_payload("symbol:asc", quote_field=quote_field)
        assert _schema_accepts(schema, {"action_type": "market.filters.apply", "payload": payload})

    history_reset = {
        "query": "",
        "asset_type": "",
        "status": "",
        "analysis_kind": "",
        "submitted_from": "",
        "submitted_to": "",
        "model": "",
        "horizon": "",
        "sort": "event_id:desc",
        "page_size": 10,
    }
    history_request = {"action_type": "filters.apply", "payload": history_reset}
    assert _schema_accepts(schema, history_request)
    normalized_history = normalize_history_form_filters(history_reset)
    assert normalized_history["sort"] == "event_id:desc"
    assert normalized_history["page_size"] == 10
    assert all(
        normalized_history[field] == ""
        for field in (
            "query",
            "asset_type",
            "status",
            "analysis_kind",
            "submitted_from",
            "submitted_to",
            "model",
            "horizon",
        )
    )

    incomplete = _market_filter_payload("symbol:asc")
    incomplete.pop("quote_max")
    assert not _schema_accepts(
        schema, {"action_type": "market.filters.apply", "payload": incomplete}
    )
    assert not _schema_accepts(
        schema,
        {
            "action_type": "market.filters.apply",
            "payload": {**_market_filter_payload("symbol:asc"), "analysis_kind": ""},
        },
    )
    assert not _schema_accepts(
        schema,
        {
            "action_type": "filters.apply",
            "payload": {"query": "ACDC", "sort": "price:desc"},
        },
    )
    assert not _schema_accepts(
        schema,
        {
            "action_type": "market.filters.apply",
            "payload": _market_filter_payload("event_id:desc"),
        },
    )
    assert not _schema_accepts(
        schema,
        {
            "action_type": "market.open",
            "payload": {
                "symbol": "ACDC",
                "asset_type": "",
                "provider": FIXTURE_PROVIDER_NAME,
                "exchange": "NASDAQ",
            },
        },
    )

    with pytest.raises(AssistantUnavailable, match="invalid_runtime_event"):
        AssistantService._validate_action_payload(
            "filters.apply", {"query": "ACDC", "sort": "price:desc"}
        )
    with pytest.raises(AssistantUnavailable, match="invalid_runtime_event"):
        AssistantService._validate_action_payload(
            "market.filters.apply", _market_filter_payload("event_id:desc")
        )
    with pytest.raises(AssistantUnavailable, match="invalid_runtime_event"):
        AssistantService._validate_action_payload("market.filters.apply", incomplete)
    with pytest.raises(AssistantUnavailable, match="invalid_runtime_event"):
        AssistantService._validate_action_payload(
            "market.open",
            {
                "symbol": "ACDC",
                "asset_type": "",
                "provider": FIXTURE_PROVIDER_NAME,
                "exchange": "NASDAQ",
            },
        )

    projected = project_gemini_tool_schema(schema)
    assert isinstance(projected, dict)
    projected_branches = projected["anyOf"]
    assert len(projected_branches) == 27
    projected_types = {
        branch["properties"]["action_type"]["enum"][0] for branch in projected_branches
    }
    assert projected_types == set(action_types)
    projected_by_type = {
        branch["properties"]["action_type"]["enum"][0]: branch for branch in projected_branches
    }
    assert len(projected_by_type) == 27
    raw_by_type = {branch["properties"]["action_type"]["enum"][0]: branch for branch in branches}
    for action_type in action_types:
        raw_payload_schema = raw_by_type[action_type]["properties"]["payload"]
        projected_branch = projected_by_type[action_type]
        assert projected_branch["properties"]["action_type"]["enum"] == [action_type]
        assert set(projected_branch["properties"]) == {"action_type", "payload"}
        projected_payload_schema = projected_branch["properties"]["payload"]
        assert projected_payload_schema["type"] == "object"
        assert projected_payload_schema["required"] == raw_payload_schema["required"]
        assert set(projected_payload_schema["properties"]) == set(raw_payload_schema["properties"])
        assert all(
            isinstance(projected_payload_schema["properties"][field], dict)
            for field in raw_payload_schema["properties"]
        )
    raw_page_size = raw_by_type["filters.apply"]["properties"]["payload"]["properties"]["page_size"]
    projected_page_size = projected_by_type["filters.apply"]["properties"]["payload"]["properties"][
        "page_size"
    ]
    assert raw_page_size == {"type": "integer", "enum": [10, 20, 50]}
    assert projected_page_size == {"type": "string", "enum": ["10", "20", "50"]}
    raw_export_payload = raw_by_type["history.export.csv"]["properties"]["payload"]
    raw_date_schema = raw_export_payload["properties"]["submitted_from"]
    projected_export_payload = projected_by_type["history.export.csv"]["properties"]["payload"]
    projected_date_schema = projected_export_payload["properties"]["submitted_from"]
    assert raw_date_schema["anyOf"][0]["enum"] == [""]
    assert projected_date_schema["anyOf"][0]["enum"] == [""]
    assert projected_date_schema["anyOf"][1]["format"] == "date"
    for date_value in ("", "2025-01-31"):
        date_request = {
            "action_type": "history.export.csv",
            "payload": {"submitted_from": date_value, "submitted_to": date_value},
        }
        assert _schema_accepts(schema, date_request)
        assert _schema_accepts(projected, date_request)
    invalid_date_request = {
        "action_type": "history.export.csv",
        "payload": {"submitted_from": "2025-02-30", "submitted_to": ""},
    }
    assert not _schema_accepts(schema, invalid_date_request)
    assert not _schema_accepts(projected, invalid_date_request)
    for market_sort in MARKET_SORTS:
        projected_request = {
            "action_type": "market.filters.apply",
            "payload": _market_filter_payload(
                market_sort,
                asset_type="",
                quote_field="",
            ),
        }
        assert _schema_accepts(projected, projected_request)
    assert _schema_accepts(
        projected,
        {
            "action_type": "filters.apply",
            "payload": {**history_reset, "page_size": str(history_reset["page_size"])},
        },
    )
    assert not _schema_accepts(
        projected,
        {
            "action_type": "market.filters.apply",
            "payload": _market_filter_payload("event_id:desc"),
        },
    )
    assert not _schema_accepts(
        projected,
        {
            "action_type": "filters.apply",
            "payload": {**history_reset, "sort": "price:desc"},
        },
    )


def test_action_previews_context_checks_and_export_urls_are_exact():
    form_action = AssistantService._validate_action_payload(
        "filters.apply",
        {
            "query": "ACDC",
            "status": "successful",
            "asset_type": "stock",
            "analysis_kind": "submitted_forecast",
            "submitted_from": "2025-01-01",
            "submitted_to": "2025-01-31",
            "model": "model filter from form data",
            "horizon": "daily_1",
            "sort": "event_id:desc",
            "page_size": 20,
        },
    )
    form_card = AssistantService._safe_action_card("filters.apply", form_action)
    form_changes = {item["label"]: item["after"] for item in form_card["changes"]}
    assert form_card["title"] == "Apply research filters"
    assert form_changes["Search query"] == "ACDC"
    assert form_changes["Rows per page"] == "20"
    assert form_changes["Model name or version"] == "model filter from form data"

    market_action = AssistantService._validate_action_payload(
        "market.filters.apply",
        {
            "query": "ACDC",
            "exchange": "NASDAQ",
            "asset_type": "stock",
            "sort": "symbol:asc",
            "min_price": "",
            "max_price": "12.50",
            "min_change": "-4",
            "max_change": "",
            "min_volume": "100",
            "quote_field": "volume",
            "quote_min": "100",
            "quote_max": "200",
        },
    )
    market_card = AssistantService._safe_action_card("market.filters.apply", market_action)
    market_changes = {item["label"]: item["after"] for item in market_card["changes"]}
    assert market_changes["Minimum price"] == "(empty; clear this control)"
    assert market_changes["Maximum percent change"] == "(empty; clear this control)"
    assert market_changes["Additional quote metric"] == "volume"

    chart = normalize_market_chart_range(
        {
            "symbol": "acdc",
            "asset_type": "stock",
            "provider": FIXTURE_PROVIDER_NAME,
            "exchange": "NASDAQ",
            "range": "3mo",
        }
    )
    AssistantService._validate_action_context(
        "market.chart_range.set",
        chart,
        {
            "route": "/tools/markets",
            "instrument": {
                "symbol": "ACDC",
                "asset_type": "stock",
                "provider": FIXTURE_PROVIDER_NAME,
                "exchange": "NASDAQ",
            },
        },
    )
    with pytest.raises(AssistantStorageConflict, match="action_context_stale"):
        AssistantService._validate_action_context(
            "market.chart_range.set",
            chart,
            {
                "route": "/tools/markets",
                "instrument": {
                    "symbol": "SPY",
                    "asset_type": "stock",
                    "provider": FIXTURE_PROVIDER_NAME,
                    "exchange": "NASDAQ",
                },
            },
        )
    with pytest.raises(AssistantStorageConflict, match="action_context_stale"):
        AssistantService._validate_action_context(
            "market.refresh", {"kind": "quotes"}, {"route": "/"}
        )
    AssistantService._validate_action_context("filters.apply", form_action, {"route": "/"})
    with pytest.raises(AssistantStorageConflict, match="action_context_stale"):
        AssistantService._validate_action_context(
            "filters.apply", form_action, {"route": "/tools/markets"}
        )

    assistant = object.__new__(AssistantService)
    assistant.can_access = lambda context: True
    auth = SimpleNamespace(user=SimpleNamespace(id=99004))
    for action_type, payload, preview_label, preview_value in (
        ("market.chart_range.set", chart, "Chart range", "3mo"),
        ("market.columns.set", {"show_all_columns": True}, "Show all quote columns", "true"),
        ("market.refresh", {"kind": "chart"}, "Refresh target", "chart"),
    ):
        safe_payload = AssistantService._validate_action_payload(action_type, payload)
        card = AssistantService._safe_action_card(action_type, safe_payload)
        changes = {item["label"]: item["after"] for item in card["changes"]}
        assert changes[preview_label] == preview_value
        outcome, detail = assistant.dispatch_confirmed_action(
            99004, action_type, safe_payload, confirmed_by=auth
        )
        assert outcome == "handed_off"
        browser_action = detail["browser_action"]
        assert browser_action["type"] == action_type
        assert browser_action["payload"] == safe_payload
        assert browser_action["destination"] == {
            "kind": "current-page",
            "route": "/tools/markets",
        }
        assert AssistantService._safe_browser_action(browser_action) == browser_action
        assert (
            AssistantService._safe_browser_action(
                {
                    **browser_action,
                    "destination": {**browser_action["destination"], "unexpected": True},
                }
            )
            is None
        )

    export = AssistantService._validate_action_payload(
        "history.export.csv",
        {
            "query": "ACDC",
            "symbol": "SPY",
            "status": "successful",
            "asset_type": "etf",
            "analysis_kind": "fresh_historical_reconstruction",
            "submitted_from": "2025-01-01",
            "submitted_to": "2025-01-31",
            "model": "model filter from stored data",
            "horizon": "weekly_5",
            "sort": "company:asc",
        },
    )
    outcome, detail = assistant.dispatch_confirmed_action(
        99004, "history.export.csv", export, confirmed_by=auth
    )
    assert outcome == "handed_off"
    destination = str(detail["destination"])
    parsed = urlsplit(destination)
    query = parse_qs(parsed.query, keep_blank_values=True)
    assert parsed.path == "/api/v1/history-export.csv"
    assert query == {
        "q": ["ACDC"],
        "symbol": ["SPY"],
        "status": ["successful"],
        "asset_type": ["etf"],
        "analysis_kind": ["fresh_historical_reconstruction"],
        "submitted_from": ["2025-01-01T00:00:00Z"],
        "submitted_to": ["2025-01-31T23:59:59.999Z"],
        "model": ["model filter from stored data"],
        "horizon": ["weekly_5"],
        "sort_by": ["company"],
        "sort_order": ["asc"],
    }
    assert "page" not in query and "page_size" not in query
    assert AssistantStorage._safe_destination(destination) == destination
    assert AssistantStorage._safe_destination(destination + "&event_id=1") is None
    assert AssistantStorage._safe_destination(destination + "&q=SECOND") is None
    assert (
        AssistantStorage._safe_destination(
            destination.replace("2025-01-01T00%3A00%3A00Z", "2025-02-30T00%3A00%3A00Z")
        )
        is None
    )
    assert (
        AssistantStorage._safe_destination(
            destination.replace("sort_by=company", "sort_by=request_id")
        )
        is None
    )
    json_outcome, json_detail = assistant.dispatch_confirmed_action(
        99004, "history.export.json", export, confirmed_by=auth
    )
    json_destination = str(json_detail["destination"])
    assert json_outcome == "handed_off"
    assert urlsplit(json_destination).path == "/api/v1/history-export.json"
    assert parse_qs(urlsplit(json_destination).query) == query
    assert AssistantStorage._safe_destination(json_destination) == json_destination


def test_market_receipts_round_trip_closed_payloads_and_approval_is_single_use(settings):
    repository = Repository(settings.database_path)
    repository.migrate()
    owner_id = _owner(repository, 99005)
    other_id = _owner(repository, 99006)
    storage = AssistantStorage(repository)
    conversation = storage.create_conversation(
        owner_id,
        title="Feature boundary receipt",
        context={"route": "/tools/markets"},
        context_version=CONTEXT_VERSION,
        created_at=NOW,
    )["conversation"]
    conversation_id = str(conversation["id"])
    session_id = "feature-owner-session-0005"
    turn = storage.create_turn(
        owner_id,
        conversation_id,
        prompt="Review one market chart control.",
        model_id="fixture/free-model",
        policy_version="fixture-policy-v1",
        context={"route": "/tools/markets"},
        context_version=CONTEXT_VERSION,
        session_id=session_id,
        session_token_hash="b" * 64,
        capability="fixture-capability-" + "c" * 40,
        now=NOW,
        expires_at=NOW + timedelta(seconds=120),
    )
    payload = {
        "symbol": "acdc",
        "asset_type": "stock",
        "provider": FIXTURE_PROVIDER_NAME,
        "exchange": "NASDAQ",
        "range": "1y",
    }
    action = storage.create_action(
        owner_id,
        conversation_id,
        str(turn["id"]),
        action_type="market.chart_range.set",
        payload=payload,
        action_version=1,
        session_id=session_id,
        context_version=CONTEXT_VERSION,
        execution_id=str(turn["execution_id"]),
        confirmation_phrase="ignored in favor of generated phrase",
        now=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    claimed = storage.claim_action(
        owner_id,
        str(action["id"]),
        action_version=1,
        confirmation_phrase=str(action["confirmation_phrase"]),
        session_id=session_id,
        context_version=CONTEXT_VERSION,
        now=NOW + timedelta(seconds=1),
    )
    assert claimed["status"] == "pending"
    assert storage.get_action(owner_id, str(action["id"]))["status"] == "executing"
    executing_receipt = storage.get_action_receipt(owner_id, str(action["id"]))
    assert executing_receipt is not None
    assert executing_receipt["outcome"] == "executing"
    with pytest.raises(StorageConflict, match="action_replayed"):
        storage.claim_action(
            owner_id,
            str(action["id"]),
            action_version=1,
            confirmation_phrase=str(action["confirmation_phrase"]),
            session_id=session_id,
            context_version=CONTEXT_VERSION,
            now=NOW + timedelta(seconds=2),
        )
    result = storage.finish_action(
        owner_id,
        str(action["id"]),
        outcome="handed_off",
        result={
            "message": "The current Markets chart action is ready.",
            "browser_action": {
                "type": "market.chart_range.set",
                "payload": payload,
                "destination": {"kind": "current-page", "route": "/tools/markets"},
            },
        },
        now=NOW + timedelta(seconds=3),
    )
    assert result["outcome"] == "handed_off"
    receipt = storage.get_action_receipt(owner_id, str(action["id"]))
    assert receipt is not None
    projected = AssistantStorage._safe_receipt_browser_action(
        receipt["result"].get("browser_action")
    )
    assert projected == {
        "type": "market.chart_range.set",
        "payload": {
            "symbol": "ACDC",
            "asset_type": "stock",
            "provider": FIXTURE_PROVIDER_NAME,
            "exchange": "NASDAQ",
            "range": "1y",
        },
        "destination": {"kind": "current-page", "route": "/tools/markets"},
    }
    assert storage.get_action_receipt(other_id, str(action["id"])) is None

    invalid_receipts = (
        {
            "type": "market.chart_range.set",
            "payload": {**payload, "range": "2y"},
            "destination": {"kind": "current-page", "route": "/tools/markets"},
        },
        {
            "type": "market.chart_range.set",
            "payload": {**payload, "extra": "forged"},
            "destination": {"kind": "current-page", "route": "/tools/markets"},
        },
        {
            "type": "market.chart_range.set",
            "payload": payload,
            "destination": {
                "kind": "current-page",
                "route": "/tools/markets",
                "unexpected": True,
            },
        },
        {
            "type": "market.columns.set",
            "payload": {"show_all_columns": 1},
            "destination": {"kind": "current-page", "route": "/tools/markets"},
        },
    )
    for invalid in invalid_receipts:
        assert AssistantStorage._safe_receipt_browser_action(invalid) is None

    valid_filters = {
        "query": "ACDC",
        "exchange": "NASDAQ",
        "asset_type": "stock",
        "sort": "symbol:asc",
        "min_price": "",
        "max_price": "10.25",
        "min_change": "-2.5",
        "max_change": "",
        "min_volume": "100",
        "quote_field": "volume",
        "quote_min": "100",
        "quote_max": "200",
    }
    assert (
        AssistantStorage._safe_receipt_browser_action(
            {
                "type": "market.filters.apply",
                "payload": valid_filters,
                "destination": {"kind": "current-page", "route": "/tools/markets"},
            }
        )
        is not None
    )
    assert (
        AssistantStorage._safe_receipt_browser_action(
            {
                "type": "filters.apply",
                "payload": {
                    "query": "ACDC",
                    "status": "successful",
                    "asset_type": "stock",
                    "analysis_kind": "submitted_forecast",
                    "submitted_from": "2025-01-01",
                    "submitted_to": "2025-01-31",
                    "model": "existing form model",
                    "horizon": "daily_1",
                    "sort": "symbol:asc",
                    "page_size": 20,
                },
                "destination": {"kind": "current-page", "route": "/"},
            }
        )
        is not None
    )
    for action_type, payload in (
        ("market.columns.set", {"show_all_columns": True}),
        ("market.refresh", {"kind": "watchlist"}),
    ):
        assert AssistantStorage._safe_receipt_browser_action(
            {
                "type": action_type,
                "payload": payload,
                "destination": {"kind": "current-page", "route": "/tools/markets"},
            }
        ) == {
            "type": action_type,
            "payload": payload,
            "destination": {"kind": "current-page", "route": "/tools/markets"},
        }
