"""Fixed, owner-aware MCP tools backed by existing application services."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from typing import cast

from stock_probs.assistant.feature_filters import (
    HISTORY_HORIZONS,
    HISTORY_SORTS,
    HISTORY_STATUSES,
    MARKET_QUOTE_FIELDS,
    MARKET_RANGES,
    MARKET_REFRESH_KINDS,
    MARKET_SORTS,
    InvalidFeatureFilter,
    history_date_bounds,
    normalize_history_filters,
)
from stock_probs.assistant.service import AssistantService, AssistantUnavailable
from stock_probs.assistant.storage import AssistantStorageNotFound

MAX_TOOL_RESULT_BYTES = 16_000
MAX_HISTORY_PAGE_SIZE = 10
_SYMBOL = re.compile(r"^[A-Z0-9.^-]{1,15}$")
_SAFE_HISTORY_FIELDS = frozenset(
    {
        "id",
        "request_id",
        "submitted_symbol",
        "normalized_symbol",
        "canonical_symbol",
        "company_name",
        "display_name",
        "exchange",
        "quote_type",
        "model_name",
        "model_version",
        "forecast_contract_version",
        "asset_type",
        "status",
        "is_repeat",
        "error_code",
        "submitted_at",
        "completed_at",
        "analysis_kind",
        "source_event_id",
        "requested_cutoff",
        "run_id",
        "forecast_available",
        "horizons",
        "outcome_count",
        "evaluation_statuses",
    }
)
_KNOWN_HORIZONS = frozenset(
    {
        "close_to_close",
        "completed_5m_to_close",
        "five_min_forward",
        "daily_1",
        "weekly_5",
        "monthly_21",
        "quarterly_63",
    }
)
_EVALUATION_STATUSES = frozenset({"available", "insufficient_history"})
_SAFE_SNAPSHOT_STRING_LIMITS = {
    "symbol": 15,
    "provider": 80,
    "exchange": 40,
    "company_name": 240,
    "currency": 12,
    "provider_as_of": 64,
    "forecast_contract_version": 80,
}
_SAFE_SERIES_FIELDS = frozenset(
    {
        "event_id",
        "symbol",
        "series",
        "interval",
        "currency",
        "provider_as_of",
        "quality",
        "items",
        "total_available",
        "truncated",
        "available",
    }
)
_SAFE_BAR_FIELDS = frozenset({"timestamp", "end", "close", "duration_seconds"})
_FORECAST_RESULT_FIELDS = frozenset(
    {
        "id",
        "recorded_at",
        "horizon",
        "interval",
        "availability",
        "unavailable_reason",
        "origin_timestamp",
        "origin_bar_end",
        "origin_price",
        "reference_timestamp",
        "reference_state",
        "target_timestamp",
        "target_state",
        "exchange_timezone",
        "stale_state",
        "session_state_at_request",
        "calculated_at",
        "definition",
        "target_session_rule",
        "target_selection",
        "evaluation",
        "direction_probabilities",
        "threshold_probabilities",
        "conditional_magnitudes",
        "magnitude_intervals",
        "sample_size",
        "sample_accounting",
        "probability_estimator",
        "distribution_definition",
        "flat_definition",
        "model_version",
        "forecast_contract_version",
        "model_fingerprint",
        "forecast_fingerprint",
        "requested_interval",
    }
)
_PROBABILITY_FIELDS = frozenset(
    {"down", "flat", "unchanged", "up", "unit", "definitions", "event_counts", "uncertainty"}
)
_THRESHOLD_FIELDS = frozenset(
    {
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
)
_CONDITIONAL_FIELDS = frozenset(
    {"condition", "observed_count", "sample_count", "expected", "median", "unit", "definition"}
)
_INTERVAL_FIELDS = frozenset({"level", "definition", "percent", "price"})
_SAMPLE_ACCOUNTING_FIELDS = frozenset(
    {
        "candidate_count",
        "eligible_count",
        "effective_count",
        "excluded_anomaly_count",
        "warmup_excluded_count",
        "overlap_stride",
        "overlap_adjusted_effective_count",
        "transformation",
        "filter",
    }
)
_EVALUATION_FIELDS = frozenset(
    {
        "version",
        "method",
        "status",
        "reason",
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
)
_SCORE_FIELDS = frozenset(
    {
        "name",
        "version",
        "definition",
        "direction_brier",
        "threshold_brier",
        "reliability",
        "interval_coverage",
    }
)
_BIN_FIELDS = frozenset(
    {
        "low",
        "high",
        "includes_high",
        "count",
        "mean_predicted_probability",
        "observed_frequency",
    }
)


def _safe_fields(value: object, allowed: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {key: item for key, item in value.items() if key in allowed}


def _safe_history_item(value: object) -> dict[str, object]:
    """Project the repository's closed history summary, including typed summary fields."""

    if not isinstance(value, Mapping):
        return {}
    summary_fields = {"horizons", "outcome_count", "evaluation_statuses"}
    result: dict[str, object] = {
        str(key): item
        for key, item in value.items()
        if key in _SAFE_HISTORY_FIELDS and key not in summary_fields
    }
    for key, maximum in (
        ("company_name", 240),
        ("display_name", 200),
        ("exchange", 40),
        ("quote_type", 40),
        ("model_name", 120),
        ("model_version", 80),
        ("forecast_contract_version", 80),
    ):
        item = result.get(key)
        if not isinstance(item, str) or len(item) > maximum:
            result.pop(key, None)
    for key in ("canonical_symbol",):
        item = result.get(key)
        if not isinstance(item, str) or _SYMBOL.fullmatch(item) is None:
            result.pop(key, None)
    horizons = value.get("horizons")
    if isinstance(horizons, list):
        result["horizons"] = [
            item for item in horizons[:16] if isinstance(item, str) and item in _KNOWN_HORIZONS
        ]
    statuses = value.get("evaluation_statuses")
    if isinstance(statuses, list):
        result["evaluation_statuses"] = [
            item for item in statuses[:16] if isinstance(item, str) and item in _EVALUATION_STATUSES
        ]
    outcome_count = value.get("outcome_count")
    if type(outcome_count) is int and outcome_count >= 0:
        result["outcome_count"] = outcome_count
    return result


def _safe_snapshot(value: Mapping[str, object]) -> dict[str, object]:
    """Keep only scalar fields emitted by the immutable forecast input snapshot."""

    result: dict[str, object] = {}
    snapshot_id = value.get("id")
    if type(snapshot_id) is int and snapshot_id > 0:
        result["id"] = snapshot_id
    symbol = value.get("symbol")
    if isinstance(symbol, str) and _SYMBOL.fullmatch(symbol) is not None:
        result["symbol"] = symbol
    asset_type = value.get("asset_type")
    if asset_type in {"stock", "etf"}:
        result["asset_type"] = asset_type
    for key, limit in _SAFE_SNAPSHOT_STRING_LIMITS.items():
        item = value.get(key)
        if isinstance(item, str) and len(item) <= limit:
            result[key] = item
    quality = value.get("quality")
    if isinstance(quality, str) and quality in {"current", "stale"}:
        result["quality"] = quality
    return result


def _safe_bar(value: object) -> dict[str, object]:
    """Project one repository bar without carrying unknown nested columns forward."""

    if not isinstance(value, Mapping):
        return {}
    result: dict[str, object] = {}
    for key in ("timestamp", "end"):
        item = value.get(key)
        if isinstance(item, str) and len(item) <= 64:
            result[key] = item
    close = value.get("close")
    if type(close) in {int, float} and math.isfinite(float(close)):
        result["close"] = close
    duration = value.get("duration_seconds")
    if type(duration) is int and 0 < duration <= 86_400:
        result["duration_seconds"] = duration
    return {key: result[key] for key in _SAFE_BAR_FIELDS if key in result}


def _safe_series(value: object, *, limit: int) -> dict[str, object] | None:
    """Project the exact bounded shape returned by Repository.historical_series."""

    if not isinstance(value, Mapping):
        return None
    result: dict[str, object] = {}
    event_id = value.get("event_id")
    if type(event_id) is int and event_id > 0:
        result["event_id"] = event_id
    symbol = value.get("symbol")
    if isinstance(symbol, str) and _SYMBOL.fullmatch(symbol) is not None:
        result["symbol"] = symbol
    series = value.get("series")
    if series in {"daily", "intraday"}:
        result["series"] = series
    interval = value.get("interval")
    if interval in {"1d", "5m"}:
        result["interval"] = interval
    currency = value.get("currency")
    if isinstance(currency, str) and len(currency) <= 12:
        result["currency"] = currency
    provider_as_of = value.get("provider_as_of")
    if isinstance(provider_as_of, str) and len(provider_as_of) <= 64:
        result["provider_as_of"] = provider_as_of
    quality = value.get("quality")
    if isinstance(quality, str) and quality in {"current", "stale"}:
        result["quality"] = quality
    total = value.get("total_available")
    if type(total) is int and total >= 0:
        result["total_available"] = total
    for key in ("truncated", "available"):
        flag = value.get(key)
        if type(flag) is bool:
            result[key] = flag
    raw_items = value.get("items")
    result["items"] = (
        [_safe_bar(item) for item in raw_items[-limit:]] if isinstance(raw_items, list) else []
    )
    return {key: result[key] for key in _SAFE_SERIES_FIELDS if key in result}


def _safe_probability(value: object) -> dict[str, object]:
    result = _safe_fields(value, _PROBABILITY_FIELDS)
    for key in ("definitions", "event_counts"):
        if key in result:
            result[key] = _safe_fields(
                result[key], frozenset({"down", "flat", "unchanged", "up", "sample_count"})
            )
    if "uncertainty" in result:
        result["uncertainty"] = _safe_fields(
            result["uncertainty"], frozenset({"down", "flat", "unchanged", "up"})
        )
        uncertainty = result["uncertainty"]
        if isinstance(uncertainty, Mapping):
            result["uncertainty"] = {
                key: _safe_fields(item, frozenset({"low", "high", "level", "method"}))
                for key, item in uncertainty.items()
            }
    return result


def _safe_evaluation(value: object) -> dict[str, object]:
    result = _safe_fields(value, _EVALUATION_FIELDS)
    for key in ("date_range", "training_sample_range"):
        if key in result:
            result[key] = _safe_fields(
                result[key],
                frozenset(
                    {
                        "first_origin",
                        "first_target",
                        "last_origin",
                        "last_target",
                        "minimum_effective_count",
                        "maximum_effective_count",
                    }
                ),
            )
    for key in ("forecast_model", "baseline"):
        if key in result:
            result[key] = _safe_score(result[key])
    return result


def _safe_score(value: object) -> dict[str, object]:
    result = _safe_fields(value, _SCORE_FIELDS)
    if "direction_brier" in result:
        direction = _safe_fields(
            result["direction_brier"], frozenset({"multiclass_mean", "components", "definition"})
        )
        if "components" in direction:
            direction["components"] = _safe_fields(
                direction["components"], frozenset({"down", "unchanged", "up"})
            )
        result["direction_brier"] = direction
    for key in ("threshold_brier", "interval_coverage"):
        if key in result and isinstance(result[key], list):
            allowed = (
                frozenset({"operator", "threshold", "unit", "score"})
                if key == "threshold_brier"
                else frozenset({"level", "covered_count", "sample_count", "coverage", "definition"})
            )
            result[key] = [_safe_fields(item, allowed) for item in result[key][:32]]
    if "reliability" in result:
        reliability = _safe_fields(
            result["reliability"], frozenset({"bin_count", "direction", "thresholds"})
        )
        if "direction" in reliability and isinstance(reliability["direction"], Mapping):
            reliability["direction"] = {
                name: [_safe_fields(item, _BIN_FIELDS) for item in bins[:20]]
                for name, bins in reliability["direction"].items()
                if name in {"down", "unchanged", "up"} and isinstance(bins, list)
            }
        if "thresholds" in reliability and isinstance(reliability["thresholds"], list):
            reliability["thresholds"] = [
                {
                    **_safe_fields(item, frozenset({"operator", "threshold", "unit"})),
                    "bins": [
                        _safe_fields(bin_item, _BIN_FIELDS)
                        for bin_item in item.get("bins", [])[:20]
                    ]
                    if isinstance(item, Mapping) and isinstance(item.get("bins"), list)
                    else [],
                }
                for item in reliability["thresholds"][:32]
                if isinstance(item, Mapping)
            ]
        result["reliability"] = reliability
    return result


def _safe_forecast_result(value: object) -> dict[str, object]:
    result = _safe_fields(value, _FORECAST_RESULT_FIELDS)
    if "direction_probabilities" in result:
        result["direction_probabilities"] = _safe_probability(result["direction_probabilities"])
    if "threshold_probabilities" in result and isinstance(result["threshold_probabilities"], list):
        result["threshold_probabilities"] = [
            {
                **_safe_fields(item, _THRESHOLD_FIELDS),
                "uncertainty": _safe_fields(
                    item.get("uncertainty"), frozenset({"low", "high", "level", "method"})
                ),
            }
            for item in result["threshold_probabilities"][:32]
            if isinstance(item, Mapping)
        ]
    if "conditional_magnitudes" in result:
        result["conditional_magnitudes"] = {
            key: _safe_fields(item, _CONDITIONAL_FIELDS)
            for key, item in _safe_fields(
                result["conditional_magnitudes"], frozenset({"gain", "loss"})
            ).items()
        }
    if "magnitude_intervals" in result and isinstance(result["magnitude_intervals"], list):
        result["magnitude_intervals"] = [
            {
                **_safe_fields(item, frozenset({"level", "definition"})),
                "percent": _safe_fields(item.get("percent"), frozenset({"low", "high", "unit"})),
                "price": _safe_fields(item.get("price"), frozenset({"low", "high", "unit"})),
            }
            for item in result["magnitude_intervals"][:16]
            if isinstance(item, Mapping)
        ]
    if "sample_accounting" in result:
        accounting = _safe_fields(result["sample_accounting"], _SAMPLE_ACCOUNTING_FIELDS)
        if "filter" in accounting:
            accounting["filter"] = _safe_fields(
                accounting["filter"], frozenset({"version", "rule", "purpose"})
            )
        result["sample_accounting"] = accounting
    if "evaluation" in result:
        result["evaluation"] = _safe_evaluation(result["evaluation"])
    if "target_selection" in result:
        result["target_selection"] = _safe_fields(
            result["target_selection"],
            frozenset(
                {"rule", "request_session_state", "origin_session_date", "target_session_date"}
            ),
        )
    return result


def _schema(properties: Mapping[str, object], required: tuple[str, ...] = ()) -> dict[str, object]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(required),
        "additionalProperties": False,
    }


_STRING = {"type": "string"}
_INTEGER = {"type": "integer", "minimum": 1}
_ASSET = {"type": "string", "enum": ["stock", "etf"]}
_STATUS = {"type": "string", "enum": ["successful", "failed", "repeated"]}
_INSTRUMENT = {
    "symbol": {"type": "string", "minLength": 1, "maxLength": 15},
    "asset_type": _ASSET,
    "provider": {"type": "string", "minLength": 1, "maxLength": 80},
    "exchange": {"type": "string", "minLength": 1, "maxLength": 40},
}

_ACTION_TYPES = (
    "watchlist.add",
    "watchlist.remove",
    "portfolio.add",
    "portfolio.remove",
    "portfolio.set_quantity",
    "forecast.create",
    "outcome.record",
    "reconstruction.run",
    "invitation.create",
    "backup.create",
    "restore.promote",
    "provider.settings",
    "account.sessions.manage",
    "history.export.csv",
    "history.export.json",
    "theme.set",
    "filters.apply",
    "notes.set",
    "notes.clear",
    "alerts.add",
    "alerts.remove",
    "forecast.reopen",
    "market.open",
    "market.filters.apply",
    "market.chart_range.set",
    "market.columns.set",
    "market.refresh",
)
_ACTION_PAYLOAD_PROPERTIES = {
    "symbol": {"type": "string", "maxLength": 15},
    "asset_type": {"type": "string", "enum": ["", "etf", "stock"]},
    "provider": {"type": "string", "maxLength": 80},
    "exchange": {"type": "string", "maxLength": 40},
    "quantity": {"type": ["number", "null"], "minimum": 0},
    "result_id": _INTEGER,
    "event_id": _INTEGER,
    "event_version": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "observed_close": {"type": ["number", "null"], "minimum": 0},
    "observed_at": {"type": "string", "maxLength": 64},
    "state": {"type": "string", "maxLength": 40},
    "note": {"type": "string", "maxLength": 1000},
    "cutoff": {"type": "string", "maxLength": 64},
    "interval": {
        "type": "string",
        "enum": ["5min", "daily", "weekly", "monthly", "quarterly"],
    },
    "theme": {"type": "string", "enum": ["light", "dark", "system"]},
    "query": {"type": "string", "maxLength": 100},
    "status": {"type": "string", "maxLength": 40},
    "analysis_kind": {
        "type": "string",
        "enum": ["submitted_forecast", "fresh_historical_reconstruction"],
    },
    "submitted_from": {"type": "string", "format": "date"},
    "submitted_to": {"type": "string", "format": "date"},
    "model": {"type": "string", "maxLength": 120},
    "horizon": {"type": "string", "enum": sorted(HISTORY_HORIZONS)},
    "sort": {"type": "string", "enum": sorted(HISTORY_SORTS | MARKET_SORTS)},
    "page_size": {"type": "integer", "enum": [10, 20, 50]},
    "min_price": {"type": "string", "maxLength": 32},
    "max_price": {"type": "string", "maxLength": 32},
    "min_change": {"type": "string", "maxLength": 32},
    "max_change": {"type": "string", "maxLength": 32},
    "min_volume": {"type": "string", "maxLength": 32},
    "quote_field": {
        "type": "string",
        "enum": ["", *sorted(MARKET_QUOTE_FIELDS)],
    },
    "quote_min": {"type": "string", "maxLength": 32},
    "quote_max": {"type": "string", "maxLength": 32},
    "range": {"type": "string", "enum": ["5d", "1mo", "3mo", "6mo", "1y"]},
    "show_all_columns": {"type": "boolean"},
    "kind": {"type": "string", "enum": ["quotes", "watchlist", "chart"]},
    "threshold": {"type": "number", "exclusiveMinimum": 0, "maximum": 1000000000},
}
_ACTION_PAYLOAD = {"type": "object"}

_ACTION_FIELDS = {
    "watchlist.add": ("symbol", "asset_type", "provider", "exchange"),
    "watchlist.remove": ("symbol", "asset_type", "provider", "exchange"),
    "portfolio.add": ("symbol", "asset_type", "provider", "exchange", "quantity"),
    "portfolio.remove": ("symbol", "asset_type", "provider", "exchange"),
    "portfolio.set_quantity": (
        "symbol",
        "asset_type",
        "provider",
        "exchange",
        "quantity",
    ),
    "forecast.create": ("symbol", "asset_type", "provider", "exchange", "interval"),
    "outcome.record": ("result_id", "observed_close", "observed_at", "state", "note"),
    "reconstruction.run": ("event_id", "cutoff"),
    "invitation.create": (),
    "backup.create": (),
    "restore.promote": (),
    "provider.settings": (),
    "account.sessions.manage": (),
    "history.export.csv": (
        "query",
        "symbol",
        "asset_type",
        "status",
        "analysis_kind",
        "submitted_from",
        "submitted_to",
        "model",
        "horizon",
        "sort",
    ),
    "history.export.json": (
        "query",
        "symbol",
        "asset_type",
        "status",
        "analysis_kind",
        "submitted_from",
        "submitted_to",
        "model",
        "horizon",
        "sort",
    ),
    "theme.set": ("theme",),
    "filters.apply": (
        "query",
        "asset_type",
        "status",
        "analysis_kind",
        "submitted_from",
        "submitted_to",
        "model",
        "horizon",
        "sort",
        "page_size",
    ),
    "notes.set": ("symbol", "asset_type", "provider", "exchange"),
    "notes.clear": ("symbol", "asset_type", "provider", "exchange"),
    "alerts.add": ("symbol", "asset_type", "provider", "exchange", "threshold"),
    "alerts.remove": ("symbol", "asset_type", "provider", "exchange"),
    "forecast.reopen": ("event_id", "event_version"),
    "market.open": ("symbol", "asset_type", "provider", "exchange"),
    "market.filters.apply": (
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
    ),
    "market.chart_range.set": ("symbol", "asset_type", "provider", "exchange", "range"),
    "market.columns.set": ("show_all_columns",),
    "market.refresh": ("kind",),
}
_ACTION_REQUIRED_FIELDS = {
    "watchlist.add": ("symbol", "asset_type", "provider", "exchange"),
    "watchlist.remove": ("symbol", "asset_type", "provider", "exchange"),
    "portfolio.add": ("symbol", "asset_type", "provider", "exchange"),
    "portfolio.remove": ("symbol", "asset_type", "provider", "exchange"),
    "portfolio.set_quantity": ("symbol", "asset_type", "provider", "exchange", "quantity"),
    "forecast.create": ("symbol", "asset_type", "provider", "exchange"),
    "outcome.record": ("result_id", "observed_at", "state"),
    "reconstruction.run": ("event_id", "cutoff"),
    "theme.set": ("theme",),
    "filters.apply": ("query",),
    "notes.set": ("symbol", "asset_type", "provider", "exchange"),
    "notes.clear": ("symbol", "asset_type", "provider", "exchange"),
    "alerts.add": ("symbol", "asset_type", "provider", "exchange", "threshold"),
    "alerts.remove": ("symbol", "asset_type", "provider", "exchange"),
    "forecast.reopen": ("event_id", "event_version"),
    "market.open": ("symbol", "asset_type", "provider", "exchange"),
    "market.filters.apply": _ACTION_FIELDS["market.filters.apply"],
    "market.chart_range.set": ("symbol", "asset_type", "provider", "exchange", "range"),
    "market.columns.set": ("show_all_columns",),
    "market.refresh": ("kind",),
}
_HISTORY_ASSET = {"type": "string", "enum": ["", "etf", "stock"]}
_HISTORY_STATUS = {"type": "string", "enum": ["", *sorted(HISTORY_STATUSES)]}
_HISTORY_ANALYSIS_KIND = {
    "type": "string",
    "enum": ["", "fresh_historical_reconstruction", "submitted_forecast"],
}
_HISTORY_DATE = {
    "anyOf": [
        {"type": "string", "enum": [""]},
        {"type": "string", "format": "date"},
    ]
}
_HISTORY_HORIZON = {"type": "string", "enum": ["", *sorted(HISTORY_HORIZONS)]}
_HISTORY_SORT = {"type": "string", "enum": ["", *sorted(HISTORY_SORTS)]}
_MARKET_ASSET = {"type": "string", "enum": ["", "etf", "stock"]}
_MARKET_SORT = {"type": "string", "enum": sorted(MARKET_SORTS)}
_MARKET_QUOTE_FIELD = {"type": "string", "enum": ["", *sorted(MARKET_QUOTE_FIELDS)]}


def _action_payload_schema(action_type: str) -> dict[str, object]:
    """Describe one action's closed payload shape for tool discovery."""

    properties = {key: _ACTION_PAYLOAD_PROPERTIES[key] for key in _ACTION_FIELDS[action_type]}
    if action_type in {"history.export.csv", "history.export.json", "filters.apply"}:
        properties.update(
            {
                "query": {"type": "string", "maxLength": 30},
                "asset_type": _HISTORY_ASSET,
                "status": _HISTORY_STATUS,
                "analysis_kind": _HISTORY_ANALYSIS_KIND,
                "submitted_from": _HISTORY_DATE,
                "submitted_to": _HISTORY_DATE,
                "model": {"type": "string", "maxLength": 120},
                "horizon": _HISTORY_HORIZON,
                "sort": _HISTORY_SORT,
            }
        )
        if action_type == "filters.apply":
            properties["page_size"] = {"type": "integer", "enum": [10, 20, 50]}
    elif action_type == "market.filters.apply":
        properties.update(
            {
                "query": {"type": "string", "maxLength": 80},
                "exchange": {"type": "string", "maxLength": 40},
                "asset_type": _MARKET_ASSET,
                "sort": _MARKET_SORT,
                "quote_field": _MARKET_QUOTE_FIELD,
            }
        )
    elif action_type == "market.refresh":
        properties["kind"] = {"type": "string", "enum": sorted(MARKET_REFRESH_KINDS)}
    elif action_type == "market.chart_range.set":
        properties["range"] = {"type": "string", "enum": sorted(MARKET_RANGES)}
    for key in ("symbol", "provider"):
        if key in properties:
            properties[key] = _INSTRUMENT[key]
    if "exchange" in properties and action_type != "market.filters.apply":
        properties["exchange"] = _INSTRUMENT["exchange"]
    if "asset_type" in properties and action_type not in {
        "history.export.csv",
        "history.export.json",
        "filters.apply",
        "market.filters.apply",
    }:
        properties["asset_type"] = _ASSET
    return _schema(properties, _ACTION_REQUIRED_FIELDS.get(action_type, ()))


_ACTION_INPUT_SCHEMA = _schema(
    {
        "action_type": {"type": "string", "enum": list(_ACTION_TYPES)},
        "payload": _ACTION_PAYLOAD,
    },
    ("action_type", "payload"),
)
_ACTION_INPUT_SCHEMA["anyOf"] = [
    _schema(
        {
            "action_type": {"type": "string", "enum": [action_type]},
            "payload": _action_payload_schema(action_type),
        },
        ("action_type", "payload"),
    )
    for action_type in _ACTION_TYPES
]


_TOOLS: tuple[dict[str, object], ...] = (
    {
        "name": "workspace.summary",
        "description": (
            "Read small aggregate counts for this authenticated owner's saved workspace."
        ),
        "inputSchema": _schema({}),
    },
    {
        "name": "workspace.instrument_lists",
        "description": "Read the authenticated owner's portfolio and watchlist instruments.",
        "inputSchema": _schema(
            {"kind": {"type": "string", "enum": ["portfolio", "watchlist", "all"]}}
        ),
    },
    {
        "name": "history.search",
        "description": "Search a bounded page of the authenticated owner's saved forecast history.",
        "inputSchema": _schema(
            {
                # Match the existing bounded history form and owner-aware service filters.
                "query": {"type": "string", "maxLength": 30},
                "status": _STATUS,
                "asset_type": _ASSET,
                "symbol": {"type": "string", "maxLength": 15},
                "analysis_kind": {
                    "type": "string",
                    "enum": ["submitted_forecast", "fresh_historical_reconstruction"],
                },
                "submitted_from": {"type": "string", "format": "date"},
                "submitted_to": {"type": "string", "format": "date"},
                "model": {"type": "string", "maxLength": 120},
                "horizon": {"type": "string", "enum": sorted(HISTORY_HORIZONS)},
                "sort": {"type": "string", "enum": sorted(HISTORY_SORTS)},
                "page": {"type": "integer", "minimum": 1, "maximum": 10000},
                "page_size": {"type": "integer", "minimum": 1, "maximum": MAX_HISTORY_PAGE_SIZE},
            }
        ),
    },
    {
        "name": "history.saved_forecast",
        "description": (
            "Read one owner-validated immutable saved forecast and bounded price series."
        ),
        "inputSchema": _schema(
            {
                "event_id": {"type": "integer", "minimum": 1},
                "series": {"type": "string", "enum": ["daily", "intraday"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 120},
            },
            ("event_id",),
        ),
    },
    {
        "name": "history.outcomes",
        "description": "Read a bounded page of observations for an owner's saved forecast result.",
        "inputSchema": _schema(
            {
                "result_id": {"type": "integer", "minimum": 1},
                "page": {"type": "integer", "minimum": 1, "maximum": 10000},
                "page_size": {"type": "integer", "minimum": 1, "maximum": MAX_HISTORY_PAGE_SIZE},
            },
            ("result_id",),
        ),
    },
    {
        "name": "market.instrument_search",
        "description": "Find public stock and ETF identities using the configured market provider.",
        "inputSchema": _schema(
            {"query": {"type": "string", "minLength": 1, "maxLength": 80}}, ("query",)
        ),
    },
    {
        "name": "market.quote",
        "description": "Read a public quote for an exact validated provider/exchange instrument.",
        "inputSchema": _schema(_INSTRUMENT, tuple(_INSTRUMENT)),
    },
    {
        "name": "market.bars",
        "description": (
            "Read bounded public daily bars for an exact instrument and supported range."
        ),
        "inputSchema": _schema(
            {
                **_INSTRUMENT,
                "interval": {"type": "string", "enum": ["daily"]},
                "range": {"type": "string", "enum": ["5d", "1mo", "3mo", "6mo", "1y"]},
            },
            (*_INSTRUMENT, "interval"),
        ),
    },
    {
        "name": "market.compare",
        "description": "Compare public quotes for two to five exact validated instruments.",
        "inputSchema": _schema(
            {
                "instruments": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 5,
                    "items": _schema(_INSTRUMENT, tuple(_INSTRUMENT)),
                }
            },
            ("instruments",),
        ),
    },
    {
        "name": "market.news",
        "description": (
            "Read up to five current public headlines for an exact validated instrument."
        ),
        "inputSchema": _schema(_INSTRUMENT, tuple(_INSTRUMENT)),
    },
    {
        "name": "assistant.propose_action",
        "description": (
            "Propose one typed change or secure browser handoff. This never executes it; the "
            "signed-in user must review and confirm the exact card in the browser."
        ),
        "inputSchema": _ACTION_INPUT_SCHEMA,
    },
)
_TOOL_BY_NAME = {str(item["name"]): item for item in _TOOLS}
_PUBLIC_TOOLS = frozenset(
    {
        "market.instrument_search",
        "market.quote",
        "market.bars",
        "market.compare",
        "market.news",
        "assistant.propose_action",
    }
)


class AssistantToolGateway:
    """Dispatch the narrow app MCP catalog with the owner ID from its validated lease."""

    def __init__(self, assistant: AssistantService):
        self.assistant = assistant

    @staticmethod
    def list_tools() -> list[dict[str, object]]:
        """Return fresh data-only schemas; no provider/session metadata is exposed."""

        return [dict(tool) for tool in _TOOLS]

    @staticmethod
    def is_private_read(name: str) -> bool:
        return name not in _PUBLIC_TOOLS

    @staticmethod
    def _arguments(value: object) -> Mapping[str, object]:
        if not isinstance(value, Mapping) or len(value) > 16:
            raise AssistantUnavailable("invalid_tool_arguments", 422)
        return value

    @staticmethod
    def _bounded_json(
        value: object,
    ) -> dict[str, object] | list[object] | str | int | float | bool | None:
        serialized = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(serialized.encode("utf-8")) > MAX_TOOL_RESULT_BYTES:
            raise AssistantUnavailable("tool_result_too_large", 413)
        if AssistantService.contains_known_secret_text(value):
            raise AssistantUnavailable("sensitive_output_rejected", 502)
        return cast(dict[str, object] | list[object] | str | int | float | bool | None, value)

    def _instrument(self, args: Mapping[str, object]) -> dict[str, str]:
        expected = set(_INSTRUMENT)
        if set(args) != expected:
            raise AssistantUnavailable("invalid_tool_arguments", 422)
        symbol = args.get("symbol")
        asset_type = args.get("asset_type")
        provider = args.get("provider")
        exchange = args.get("exchange")
        if (
            not isinstance(symbol, str)
            or _SYMBOL.fullmatch(symbol.upper()) is None
            or asset_type not in {"stock", "etf"}
            or not isinstance(provider, str)
            or not 1 <= len(provider) <= 80
            or re.fullmatch(r"[A-Za-z0-9 ._-]+", provider) is None
            or not isinstance(exchange, str)
            or not 1 <= len(exchange) <= 40
            or re.fullmatch(r"[A-Za-z0-9 ._-]+", exchange) is None
        ):
            raise AssistantUnavailable("invalid_tool_arguments", 422)
        identity = self.assistant._resolve_identity(
            symbol.upper(), str(asset_type), provider, exchange
        )
        return {
            "symbol": str(identity["canonical_symbol"]),
            "asset_type": str(identity["asset_type"]),
            "provider": str(identity["provider"]),
            "exchange": str(identity["exchange"]),
            "display_name": str(identity["display_name"]),
        }

    @staticmethod
    def _history_item(value: object) -> dict[str, object]:
        if not isinstance(value, Mapping):
            return {}
        # Explicit field allowlist avoids outcome notes, account details, and future private
        # repository fields silently crossing the model boundary.
        return _safe_history_item(value)

    def _read_saved_forecast(
        self, user_id: int, event_id: int, *, series: str, limit: int
    ) -> dict[str, object]:
        recorded = self.assistant.forecast_service.saved_forecast(event_id, owner_user_id=user_id)
        if not isinstance(recorded, Mapping):
            raise AssistantStorageNotFound()
        event = recorded.get("event")
        snapshot = recorded.get("input")
        results = recorded.get("results")
        if not isinstance(event, Mapping):
            raise AssistantStorageNotFound()
        safe_event = {
            key: event[key]
            for key in (
                "id",
                "submitted_symbol",
                "normalized_symbol",
                "asset_type",
                "status",
                "is_repeat",
                "submitted_at",
                "completed_at",
                "analysis_kind",
            )
            if key in event
        }
        safe_snapshot: dict[str, object] | None = None
        if isinstance(snapshot, Mapping):
            safe_snapshot = _safe_snapshot(snapshot)
        safe_results: list[dict[str, object]] = []
        if isinstance(results, list):
            for result in results[:20]:
                if not isinstance(result, Mapping):
                    continue
                safe_results.append(_safe_forecast_result(result))
        series_data = self.assistant.repository.historical_series(
            user_id, event_id, series=series, limit=limit
        )
        safe_series = _safe_series(series_data, limit=limit)
        return {
            "analysis_kind": "saved_recorded_forecast",
            "immutable": True,
            "recalculated": False,
            "event": safe_event,
            "input": safe_snapshot,
            "results": safe_results,
            "price_series": safe_series,
        }

    def call(
        self, *, lease: Mapping[str, object], name: str, arguments: object
    ) -> dict[str, object] | list[object]:
        """Execute one validated call through app services with lease-derived ownership."""

        if name not in _TOOL_BY_NAME:
            raise AssistantUnavailable("tool_unavailable", 404)
        args = self._arguments(arguments)
        user_id = lease.get("user_id")
        if type(user_id) is not int:
            raise AssistantUnavailable("session_revoked", 403)
        service = self.assistant.forecast_service
        repository = self.assistant.repository

        if name == "assistant.propose_action":
            if set(args) != {"action_type", "payload"}:
                raise AssistantUnavailable("invalid_tool_arguments", 422)
            action_type = args.get("action_type")
            payload = args.get("payload")
            if (
                not isinstance(action_type, str)
                or action_type not in _ACTION_TYPES
                or not isinstance(payload, Mapping)
            ):
                raise AssistantUnavailable("invalid_tool_arguments", 422)
            conversation_id = lease.get("conversation_id")
            turn_id = lease.get("turn_id")
            execution_id = lease.get("execution_id")
            if not all(isinstance(item, str) for item in (conversation_id, turn_id, execution_id)):
                raise AssistantUnavailable("session_revoked", 403)
            event_type, card = self.assistant._normalize_runtime_event(
                "proposed_action",
                {"action_type": action_type, "payload": payload},
                user_id,
                str(conversation_id),
                str(turn_id),
                execution_id=str(execution_id),
            )
            self.assistant.storage.append_event(
                user_id,
                str(conversation_id),
                str(turn_id),
                event_type=event_type,
                data=card,
                now=self.assistant.now(),
            )
            # Do not return the browser-only confirmation phrase to the model. The persisted
            # event reaches the owner-scoped UI, and only its same-session UI may approve it.
            return cast(
                dict[str, object],
                self._bounded_json(
                    {
                        "action_id": card.get("action_id"),
                        "action_type": action_type,
                        "status": "pending_user_confirmation",
                        "summary": card.get("summary"),
                    }
                ),
            )

        if name == "workspace.summary":
            if args:
                raise AssistantUnavailable("invalid_tool_arguments", 422)
            history = service.history(owner_user_id=user_id, page=1, page_size=1)
            lists = repository.instrument_list_items(user_id)
            return self._bounded_json(
                {
                    "saved_searches": int(history.get("total", 0)),
                    "watchlist_items": sum(item.get("kind") == "watchlist" for item in lists),
                    "portfolio_items": sum(item.get("kind") == "portfolio" for item in lists),
                }
            )
        if name == "workspace.instrument_lists":
            if set(args) - {"kind"}:
                raise AssistantUnavailable("invalid_tool_arguments", 422)
            kind = args.get("kind", "all")
            if kind not in {"all", "portfolio", "watchlist"}:
                raise AssistantUnavailable("invalid_tool_arguments", 422)
            selected = None if kind == "all" else str(kind)
            rows = repository.instrument_list_items(user_id, selected)
            items = [
                {
                    key: row.get(key)
                    for key in (
                        "kind",
                        "canonical_symbol",
                        "asset_type",
                        "provider",
                        "exchange",
                        "display_name",
                        "quantity",
                        "added_at",
                    )
                }
                for row in rows[:200]
            ]
            return cast(dict[str, object], self._bounded_json({"items": items, "total": len(rows)}))
        if name == "history.search":
            try:
                filters = normalize_history_filters(args, allow_page=True)
            except InvalidFeatureFilter as exc:
                raise AssistantUnavailable("invalid_tool_arguments", 422) from exc
            start, end = history_date_bounds(filters)
            page, page_size = int(filters["page"]), int(filters["page_size"])
            if page_size > MAX_HISTORY_PAGE_SIZE:
                raise AssistantUnavailable("invalid_tool_arguments", 422)
            sort_field, sort_direction = str(filters["sort"]).split(":", maxsplit=1)
            indexed_filters = {
                "query": str(filters["query"]),
                "status": str(filters["status"]) or None,
                "asset_type": str(filters["asset_type"]) or None,
                "symbol": str(filters["symbol"]) or None,
                "analysis_kind": str(filters["analysis_kind"]) or None,
                "date_from": start,
                "date_to": end,
                "model": str(filters["model"]) or None,
                "horizon": str(filters["horizon"]) or None,
                "sort_by": sort_field,
                "sort_order": sort_direction,
            }
            try:
                response = service.history(
                    owner_user_id=user_id,
                    page=page,
                    page_size=page_size,
                    **indexed_filters,
                )
            except ValueError as exc:
                raise AssistantUnavailable("invalid_tool_arguments", 422) from exc
            rows = response.get("items", [])
            total = response.get("total", 0)
            if not isinstance(rows, list) or type(total) is not int or total < 0:
                raise AssistantUnavailable("tool_failed", 502)
            return cast(
                dict[str, object],
                self._bounded_json(
                    {
                        "items": [self._history_item(row) for row in rows[:page_size]],
                        "page": page,
                        "page_size": page_size,
                        "total": total,
                    }
                ),
            )
        if name == "history.saved_forecast":
            event_id = args.get("event_id")
            series = args.get("series", "daily")
            limit = args.get("limit", 120)
            if (
                set(args) - {"event_id", "series", "limit"}
                or type(event_id) is not int
                or event_id < 1
                or series not in {"daily", "intraday"}
                or type(limit) is not int
                or not 1 <= limit <= 120
            ):
                raise AssistantUnavailable("invalid_tool_arguments", 422)
            return cast(
                dict[str, object],
                self._bounded_json(
                    self._read_saved_forecast(user_id, event_id, series=str(series), limit=limit)
                ),
            )
        if name == "history.outcomes":
            result_id, page, page_size = (
                args.get("result_id"),
                args.get("page", 1),
                args.get("page_size", 10),
            )
            if (
                set(args) - {"result_id", "page", "page_size"}
                or type(result_id) is not int
                or result_id < 1
                or type(page) is not int
                or not 1 <= page <= 10000
                or type(page_size) is not int
                or not 1 <= page_size <= MAX_HISTORY_PAGE_SIZE
            ):
                raise AssistantUnavailable("invalid_tool_arguments", 422)
            result = repository.forecast_result(user_id, result_id)
            if result is None:
                raise AssistantStorageNotFound()
            outcomes = repository.outcome_history(
                user_id, result_id, page=page, page_size=page_size
            )
            items = [
                {
                    key: item.get(key)
                    for key in (
                        "id",
                        "result_id",
                        "observed_close",
                        "observed_return",
                        "observed_at",
                        "comparison_rule",
                        "state",
                        "created_at",
                    )
                }
                for item in outcomes.get("items", [])
                if isinstance(item, Mapping)
            ]
            return cast(
                dict[str, object],
                self._bounded_json(
                    {
                        "items": items,
                        "page": page,
                        "page_size": page_size,
                        "total": outcomes.get("total", 0),
                    }
                ),
            )
        if name == "market.instrument_search":
            query = args.get("query")
            if (
                set(args) != {"query"}
                or not isinstance(query, str)
                or not 1 <= len(query.strip()) <= 80
            ):
                raise AssistantUnavailable("invalid_tool_arguments", 422)
            result = service.lookup(query, 5)
            raw = result.get("items", [])
            items = [
                {
                    key: item.get(key)
                    for key in (
                        "canonical_symbol",
                        "asset_type",
                        "provider",
                        "exchange",
                        "display_name",
                    )
                }
                for item in raw
                if isinstance(item, Mapping)
            ][:5]
            return cast(
                dict[str, object],
                self._bounded_json({"query": result.get("query"), "items": items}),
            )
        if name in {"market.quote", "market.bars", "market.news"}:
            identity = self._instrument(
                args
                if name != "market.bars"
                else {key: value for key, value in args.items() if key not in {"interval", "range"}}
            )
            if name == "market.quote":
                raw = service.quote_snapshot(identity["symbol"], identity["asset_type"])
            elif name == "market.bars":
                chart_range = args.get("range", "1mo")
                if (
                    set(args) - {*_INSTRUMENT, "interval", "range"}
                    or args.get("interval") != "daily"
                    or not isinstance(chart_range, str)
                    or chart_range not in {"5d", "1mo", "3mo", "6mo", "1y"}
                ):
                    raise AssistantUnavailable("invalid_tool_arguments", 422)
                raw = service._provider_capability(  # noqa: SLF001
                    lambda requested_at: service.provider.historical_bars(
                        identity["symbol"],
                        identity["asset_type"],
                        requested_at,
                        range=str(chart_range),
                    ).as_dict(),
                    "The chart provider failed unexpectedly.",
                )
                if not isinstance(raw, Mapping) or not isinstance(raw.get("bars"), list):
                    raise AssistantUnavailable("tool_failed", 502)
                raw = {
                    key: raw[key]
                    for key in (
                        "range",
                        "interval",
                        "adjustment_basis",
                        "provider",
                        "as_of",
                        "delayed",
                        "delay_minutes",
                        "label",
                        "bars",
                    )
                    if key in raw
                }
                bars = raw.get("bars", [])
                raw["bars"] = [_safe_bar(bar) for bar in bars[-50:]]
                raw["total_available"] = len(bars)
                raw["truncated"] = len(bars) > 50
            else:
                if set(args) != set(_INSTRUMENT):
                    raise AssistantUnavailable("invalid_tool_arguments", 422)
                raw = service.news(identity["symbol"], 5)
            return cast(
                dict[str, object], self._bounded_json({"instrument": identity, "data": raw})
            )
        if name == "market.compare":
            if (
                set(args) != {"instruments"}
                or not isinstance(args.get("instruments"), list)
                or not 2 <= len(cast(list[object], args["instruments"])) <= 5
            ):
                raise AssistantUnavailable("invalid_tool_arguments", 422)
            compared: list[dict[str, object]] = []
            for entry in cast(list[object], args["instruments"]):
                instrument = self._instrument(self._arguments(entry))
                compared.append(
                    {
                        "instrument": instrument,
                        "quote": service.quote_snapshot(
                            instrument["symbol"], instrument["asset_type"]
                        ),
                    }
                )
            return cast(dict[str, object], self._bounded_json({"items": compared}))
        raise AssistantUnavailable("tool_unavailable", 404)


__all__ = ["AssistantToolGateway", "MAX_TOOL_RESULT_BYTES"]
