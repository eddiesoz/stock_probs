"""Describe the native V2 provider protocols and observed connection methods."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from importlib.resources import files
from typing import Literal

_MAX_INTEGRATION_ROWS = 512
_MAX_METHOD_ROWS = 32
_MAX_NATIVE_TEXT = 256
_MAX_NATIVE_OUTPUT_TOKEN_BUDGET = 4096
_NATIVE_ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_GEMINI_SCHEMA_FIELDS = frozenset(
    {
        "description",
        "required",
        "format",
        "type",
        "nullable",
        "enum",
        "properties",
        "items",
        "allOf",
        "anyOf",
        "oneOf",
        "minLength",
    }
)
_GEMINI_SCHEMA_INTENT_FIELDS = frozenset(
    {
        "type",
        "properties",
        "items",
        "prefixItems",
        "enum",
        "const",
        "$ref",
        "additionalProperties",
        "patternProperties",
        "required",
        "not",
        "if",
        "then",
        "else",
        "anyOf",
        "oneOf",
        "allOf",
    }
)
# The parameter description is independently pinned in `_NATIVE_WEBSEARCH_SCHEMA`.
_NATIVE_WEBSEARCH_DESCRIPTION_PREFIX = (
    "Search the web using the user's selected search integration. Use this for current "
    "information beyond knowledge cutoff.\n\nThe current year is "
)
_NATIVE_WEBSEARCH_DESCRIPTION_SUFFIX = (
    ". Use this year when searching for recent information or current events."
)
NATIVE_WEBFETCH_DESCRIPTION_SHA256 = (
    "b958b70f4a4edd3ce9add115a5d127f6a7948e65f95c0793f11c871456d59d8c"
)
_NATIVE_WEBSEARCH_SCHEMA: dict[str, object] = {
    "type": "object",
    # The pinned 2.0.7 wire capture includes this native parameter description.
    "properties": {"query": {"type": "string", "description": "Websearch query"}},
    "required": ["query"],
    "additionalProperties": False,
}
_NATIVE_WEBFETCH_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "The HTTP or HTTPS URL to fetch content from",
        },
        "format": {
            "type": "string",
            "enum": ["text", "markdown", "html"],
            "description": "The format to return the content in. Defaults to markdown.",
        },
        "timeout": {
            "type": "number",
            "exclusiveMinimum": 0,
            "maximum": 120,
            "description": "Optional timeout in seconds (maximum: 120)",
        },
    },
    "required": ["url"],
    "additionalProperties": False,
}


def native_websearch_description_sha256(year: int | None = None) -> str:
    """Hash the exact pinned V2 description while deriving its native current-year suffix."""

    if year is None:
        year = datetime.now(UTC).year
    if type(year) is not int or not 1 <= year <= 9999:
        raise ValueError("native websearch year is invalid")
    description = (
        f"{_NATIVE_WEBSEARCH_DESCRIPTION_PREFIX}{year}{_NATIVE_WEBSEARCH_DESCRIPTION_SUFFIX}"
    )
    return hashlib.sha256(description.encode("utf-8")).hexdigest()


AuthMethodKind = Literal["oauth"]
ApplicationConnectionState = Literal["oauth_handoff_pending"]


class NativeProviderDescriptorError(ValueError):
    """Raised when a native provider descriptor is unknown or malformed."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def output_token_budget_from_catalog(catalog: object) -> int:
    """Read the maintained output budget from one catalog-shaped policy object."""

    if not isinstance(catalog, Mapping):
        raise ValueError("assistant_output_policy_invalid")
    runtime_policy = catalog.get("runtime_policy")
    if not isinstance(runtime_policy, Mapping):
        raise ValueError("assistant_output_policy_invalid")
    budget = runtime_policy.get("native_output_token_budget")
    if type(budget) is not int or not 1 <= budget <= _MAX_NATIVE_OUTPUT_TOKEN_BUDGET:
        raise ValueError("assistant_output_policy_invalid")
    return budget


@lru_cache(maxsize=1)
def native_output_token_budget() -> int:
    """Load the maintained policy on demand so disabled assistant startup stays unaffected."""

    try:
        catalog = json.loads(
            files("stock_probs.assistant")
            .joinpath("assistant_catalog.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise ValueError("assistant_output_policy_invalid") from exc
    return output_token_budget_from_catalog(catalog)


def validated_output_token_count(value: object, *, budget: int | None = None) -> int | None:
    """Return a positive integer within the maintained budget; reject bools and coercions."""

    limit = native_output_token_budget() if budget is None else budget
    if type(limit) is not int or not 1 <= limit <= _MAX_NATIVE_OUTPUT_TOKEN_BUDGET:
        raise ValueError("assistant_output_policy_invalid")
    if type(value) is not int or not 1 <= value <= limit:
        return None
    return value


def native_output_token_body(protocol: str, *, budget: int | None = None) -> dict[str, object]:
    """Build the fixed provider-shaped body override for the native model alias."""

    limit = native_output_token_budget() if budget is None else budget
    if type(limit) is not int or not 1 <= limit <= _MAX_NATIVE_OUTPUT_TOKEN_BUDGET:
        raise ValueError("assistant_output_policy_invalid")
    if protocol in {"openai-compatible-chat", "anthropic-messages"}:
        return {"max_tokens": limit}
    if protocol == "openai-responses":
        return {"max_output_tokens": limit}
    if protocol == "google-generative-language":
        return {"generationConfig": {"maxOutputTokens": limit}}
    raise ValueError("assistant_output_protocol_unsupported")


@dataclass(frozen=True, slots=True)
class NativeAdapterDescriptor:
    """Closed, reviewed wire metadata for one pinned native provider package."""

    adapter_id: str
    native_provider_id: str
    package_id: str
    protocol: str
    route_suffix: str
    fixed_query: tuple[tuple[str, str], ...]
    upstream_query: tuple[tuple[str, str], ...]
    native_capability_header: Literal["Authorization"]
    native_capability_scheme: Literal["bearer"]
    upstream_auth_header: str
    upstream_auth_scheme: Literal["bearer", "raw"]
    upstream_static_headers: tuple[tuple[str, str], ...]
    integration_id: str | None
    application_credential_state: Literal["app_vault_bridge"]


@dataclass(frozen=True, slots=True)
class NativeAuthMethodDescriptor:
    """Safe projection of a native OAuth method without retaining native form data."""

    method_id: str
    kind: AuthMethodKind
    label: str
    application_state: ApplicationConnectionState
    application_usable: Literal[False]


@dataclass(frozen=True, slots=True)
class NativeIntegrationDescriptor:
    """Bounded, sanitized view of one installed native integration."""

    integration_id: str
    adapter_id: str | None
    oauth_methods: tuple[NativeAuthMethodDescriptor, ...]
    unsupported_method_count: int


@dataclass(frozen=True, slots=True)
class NativeConfiguredModel:
    """Safe minimal projection of a Console model before endpoint review."""

    config_provider_id: str
    config_model_id: str
    native_model_id: str
    display_name: str
    package_id: str
    adapter: NativeAdapterDescriptor


_CONFIG_PROVIDER_ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_CONFIG_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/-]{0,159}$")
_CANONICAL_PACKAGES = {
    "openai": "@opencode/ai/providers/openai",
    "anthropic": "@opencode/ai/providers/anthropic",
    "google": "@opencode/ai/providers/google",
}


_ADAPTERS: dict[str, NativeAdapterDescriptor] = {
    "openai-responses": NativeAdapterDescriptor(
        adapter_id="openai-responses",
        native_provider_id="openai",
        package_id="@opencode/ai/providers/openai",
        protocol="openai-responses",
        route_suffix="responses",
        fixed_query=(),
        upstream_query=(),
        native_capability_header="Authorization",
        native_capability_scheme="bearer",
        upstream_auth_header="Authorization",
        upstream_auth_scheme="bearer",
        upstream_static_headers=(),
        integration_id="openai",
        application_credential_state="app_vault_bridge",
    ),
    "anthropic-messages": NativeAdapterDescriptor(
        adapter_id="anthropic-messages",
        native_provider_id="anthropic",
        package_id="@opencode/ai/providers/anthropic",
        protocol="anthropic-messages",
        route_suffix="messages",
        fixed_query=(("beta", "true"),),
        upstream_query=(),
        native_capability_header="Authorization",
        native_capability_scheme="bearer",
        upstream_auth_header="x-api-key",
        upstream_auth_scheme="raw",
        upstream_static_headers=(("anthropic-version", "2023-06-01"),),
        integration_id="anthropic",
        application_credential_state="app_vault_bridge",
    ),
    "google-generative-language": NativeAdapterDescriptor(
        adapter_id="google-generative-language",
        native_provider_id="google",
        package_id="@opencode/ai/providers/google",
        protocol="google-generative-language",
        route_suffix="models/{model}:streamGenerateContent",
        fixed_query=(("alt", "sse"),),
        upstream_query=(("alt", "sse"),),
        native_capability_header="Authorization",
        native_capability_scheme="bearer",
        upstream_auth_header="x-goog-api-key",
        upstream_auth_scheme="raw",
        upstream_static_headers=(),
        integration_id="google",
        application_credential_state="app_vault_bridge",
    ),
    "openai-compatible-chat": NativeAdapterDescriptor(
        adapter_id="openai-compatible-chat",
        native_provider_id="assistant-proxy",
        package_id="@opencode/ai/providers/openai-compatible",
        protocol="openai-compatible-chat",
        route_suffix="chat/completions",
        fixed_query=(),
        upstream_query=(),
        native_capability_header="Authorization",
        native_capability_scheme="bearer",
        upstream_auth_header="Authorization",
        upstream_auth_scheme="bearer",
        upstream_static_headers=(),
        integration_id=None,
        application_credential_state="app_vault_bridge",
    ),
}

_ADAPTERS_BY_PACKAGE: dict[str, NativeAdapterDescriptor] = {
    descriptor.package_id: descriptor for descriptor in _ADAPTERS.values()
}

_INTEGRATION_ADAPTERS: dict[str, str | None] = {
    "anthropic": "anthropic-messages",
    "google": "google-generative-language",
    "openai": "openai-responses",
    # OpenCode's device login is a native account flow, not an app model adapter.
    "opencode": None,
}

_OAUTH_METHODS: dict[str, dict[str, str]] = {
    "openai": {
        "chatgpt-browser": "ChatGPT browser sign-in",
        "chatgpt-headless": "ChatGPT headless sign-in",
    },
    "opencode": {"device": "OpenCode device sign-in"},
}


def native_adapter_descriptors() -> tuple[NativeAdapterDescriptor, ...]:
    """Return the fixed native package descriptors in stable adapter-ID order."""

    return tuple(_ADAPTERS[key] for key in sorted(_ADAPTERS))


def resolve_native_adapter(
    adapter_id: str,
    native_provider_id: str,
) -> NativeAdapterDescriptor:
    """Resolve an exact approved adapter/provider pair without importing packages."""

    if (
        not isinstance(adapter_id, str)
        or not isinstance(native_provider_id, str)
        or len(adapter_id) > 64
        or len(native_provider_id) > 64
        or not _NATIVE_ID.fullmatch(adapter_id)
        or not _NATIVE_ID.fullmatch(native_provider_id)
    ):
        raise NativeProviderDescriptorError("native_adapter_unsupported")
    descriptor = _ADAPTERS.get(adapter_id)
    if descriptor is None:
        raise NativeProviderDescriptorError("native_adapter_unsupported")
    if descriptor.native_provider_id != native_provider_id:
        raise NativeProviderDescriptorError("native_provider_mismatch")
    return descriptor


def resolve_native_adapter_package(package_id: str) -> NativeAdapterDescriptor:
    """Resolve only a reviewed built-in package ID from a remote provider config.

    OpenCode Console returns package strings that can otherwise trigger native package
    installation. This resolver is intentionally exact: aliases, NPM specs, and arbitrary
    package names are never accepted as executable adapters.
    """

    if not isinstance(package_id, str) or len(package_id) > 128:
        raise NativeProviderDescriptorError("provider_adapter_unsupported")
    descriptor = _ADAPTERS_BY_PACKAGE.get(package_id)
    if descriptor is None:
        raise NativeProviderDescriptorError("provider_adapter_unsupported")
    return descriptor


def project_opencode_console_models(
    payload: object,
) -> tuple[tuple[NativeConfiguredModel, ...], int]:
    """Project only exact installed adapter/model identities from Console config.

    Provider settings, headers, body overlays, model variants, package URLs, and arbitrary
    JSON are deliberately ignored. Callers must separately validate the public HTTPS endpoint
    and bind each result to owner-specific policy before it can be used.
    """

    if (
        not isinstance(payload, Mapping)
        or set(payload) - {"providers", "websearch"}
        or not isinstance(payload.get("providers"), Mapping)
    ):
        raise NativeProviderDescriptorError("opencode_config_invalid")
    provider_rows = payload["providers"]
    if len(provider_rows) > 128:
        raise NativeProviderDescriptorError("opencode_config_invalid")

    accepted: dict[tuple[str, str], NativeConfiguredModel] = {}
    unsupported = 0
    seen_models = 0
    for raw_provider_id, provider in provider_rows.items():
        if isinstance(raw_provider_id, str) and len(raw_provider_id) > 64:
            raise NativeProviderDescriptorError("opencode_config_invalid")
        if (
            not isinstance(raw_provider_id, str)
            or not _CONFIG_PROVIDER_ID.fullmatch(raw_provider_id)
            or not isinstance(provider, Mapping)
        ):
            unsupported += 1
            continue
        raw_models = provider.get("models", {})
        if not isinstance(raw_models, Mapping):
            unsupported += 1
            continue
        if len(raw_models) > 512 or seen_models + len(raw_models) > 2048:
            raise NativeProviderDescriptorError("opencode_config_invalid")
        seen_models += len(raw_models)
        provider_package = provider.get("package")
        if provider_package is None:
            canonical = provider.get("canonical")
            provider_package = (
                _CANONICAL_PACKAGES.get(canonical) if isinstance(canonical, str) else None
            )
        if isinstance(provider_package, str) and len(provider_package) > 128:
            raise NativeProviderDescriptorError("opencode_config_invalid")
        for raw_model_id, model in raw_models.items():
            if isinstance(raw_model_id, str) and len(raw_model_id) > 160:
                raise NativeProviderDescriptorError("opencode_config_invalid")
            if not isinstance(raw_model_id, str) or not _CONFIG_MODEL_ID.fullmatch(raw_model_id):
                unsupported += 1
                continue
            if not isinstance(model, Mapping):
                unsupported += 1
                continue
            if model.get("disabled") is True:
                continue
            package = model.get("package", provider_package)
            if isinstance(package, str) and len(package) > 128:
                raise NativeProviderDescriptorError("opencode_config_invalid")
            try:
                adapter = resolve_native_adapter_package(package)
            except NativeProviderDescriptorError:
                unsupported += 1
                continue
            native_model_id = model.get("modelID", raw_model_id)
            if isinstance(native_model_id, str) and len(native_model_id) > 160:
                raise NativeProviderDescriptorError("opencode_config_invalid")
            if not isinstance(native_model_id, str) or not _CONFIG_MODEL_ID.fullmatch(
                native_model_id
            ):
                unsupported += 1
                continue
            name = model.get("name", provider.get("name", native_model_id))
            if (
                not isinstance(name, str)
                or not 1 <= len(name) <= 160
                or any(ord(character) < 32 or ord(character) == 127 for character in name)
            ):
                name = native_model_id
            identity = (raw_provider_id, raw_model_id)
            accepted.setdefault(
                identity,
                NativeConfiguredModel(
                    config_provider_id=raw_provider_id,
                    config_model_id=raw_model_id,
                    native_model_id=native_model_id,
                    display_name=name,
                    package_id=adapter.package_id,
                    adapter=adapter,
                ),
            )
    return tuple(accepted[key] for key in sorted(accepted)), unsupported


def native_websearch_schema(protocol: str) -> dict[str, object] | None:
    """Return the captured, closed builtin search declaration for one wire protocol."""

    if protocol == "google-generative-language":
        return project_gemini_tool_schema(_NATIVE_WEBSEARCH_SCHEMA)
    if protocol in {"openai-responses", "anthropic-messages", "openai-compatible-chat"}:
        return dict(_NATIVE_WEBSEARCH_SCHEMA)
    raise NativeProviderDescriptorError("native_tool_protocol_unsupported")


def native_webfetch_schema(protocol: str) -> dict[str, object] | None:
    """Return the pinned builtin fetch declaration for a reviewed wire protocol."""

    if protocol == "google-generative-language":
        return project_gemini_tool_schema(_NATIVE_WEBFETCH_SCHEMA)
    if protocol in {"openai-responses", "anthropic-messages", "openai-compatible-chat"}:
        return dict(_NATIVE_WEBFETCH_SCHEMA)
    raise NativeProviderDescriptorError("native_tool_protocol_unsupported")


def project_gemini_tool_schema(value: object, *, _depth: int = 0) -> dict[str, object] | None:
    """Apply the pinned Gemini tool-schema projection without broad schema relaxation.

    The native converter deliberately drops unsupported JSON Schema keywords. The app applies
    this projection only for declaration comparison; its own MCP argument validator retains the
    full canonical schema and rejects additional or out-of-range arguments.
    """

    if _depth < 0 or _depth > 16:
        raise NativeProviderDescriptorError("native_tool_schema_invalid")

    budget = [2048]

    def sanitize(node: object, depth: int) -> object:
        budget[0] -= 1
        if budget[0] < 0 or depth > 16:
            raise NativeProviderDescriptorError("native_tool_schema_invalid")
        if isinstance(node, Mapping):
            if len(node) > 64:
                raise NativeProviderDescriptorError("native_tool_schema_invalid")
            result: dict[str, object] = {}
            for key, child in node.items():
                if not isinstance(key, str) or len(key) > 128:
                    raise NativeProviderDescriptorError("native_tool_schema_invalid")
                if key == "enum" and isinstance(child, list):
                    if len(child) > 128:
                        raise NativeProviderDescriptorError("native_tool_schema_invalid")
                    result[key] = [_gemini_string(item) for item in child]
                else:
                    result[key] = sanitize(child, depth + 1)

            schema_type = result.get("type")
            if isinstance(result.get("enum"), list) and schema_type in {"integer", "number"}:
                result["type"] = "string"
            properties = result.get("properties")
            required = result.get("required")
            if (
                schema_type == "object"
                and isinstance(properties, Mapping)
                and isinstance(required, list)
            ):
                result["required"] = [
                    field for field in required if isinstance(field, str) and field in properties
                ]
            if schema_type == "array" and not has_combiner(result):
                items = result.get("items")
                if items is None:
                    items = {}
                if isinstance(items, Mapping) and not has_schema_intent(items):
                    items = {**items, "type": "string"}
                result["items"] = items
            if (
                isinstance(schema_type, str)
                and schema_type != "object"
                and not has_combiner(result)
            ):
                result.pop("properties", None)
                result.pop("required", None)
            return result
        if isinstance(node, list):
            if len(node) > 128:
                raise NativeProviderDescriptorError("native_tool_schema_invalid")
            return [sanitize(child, depth + 1) for child in node]
        if node is None or isinstance(node, str | bool | int):
            return node
        if isinstance(node, float) and node == node and abs(node) < float("inf"):
            return node
        raise NativeProviderDescriptorError("native_tool_schema_invalid")

    def has_combiner(schema: Mapping[str, object]) -> bool:
        return any(isinstance(schema.get(key), list) for key in ("anyOf", "oneOf", "allOf"))

    def has_schema_intent(schema: Mapping[str, object]) -> bool:
        return has_combiner(schema) or any(key in schema for key in _GEMINI_SCHEMA_INTENT_FIELDS)

    def project(node: object, depth: int, *, nested: bool) -> dict[str, object] | None:
        budget[0] -= 1
        if budget[0] < 0 or depth > 16:
            raise NativeProviderDescriptorError("native_tool_schema_invalid")
        if not isinstance(node, Mapping):
            return None
        if len(node) > 64:
            raise NativeProviderDescriptorError("native_tool_schema_invalid")

        properties = node.get("properties")
        if (
            not nested
            and node.get("type") == "object"
            and (not isinstance(properties, Mapping) or not properties)
            and not node.get("additionalProperties")
        ):
            return None

        raw_type = node.get("type")
        types = (
            [item for item in raw_type if item != "null"] if isinstance(raw_type, list) else None
        )
        if isinstance(raw_type, list) and (
            len(raw_type) > 16 or any(not isinstance(item, str) for item in raw_type)
        ):
            raise NativeProviderDescriptorError("native_tool_schema_invalid")
        any_of = node.get("anyOf") if isinstance(node.get("anyOf"), list) else None
        has_null_any_of = any(
            isinstance(item, Mapping) and item.get("type") == "null" for item in (any_of or [])
        )
        any_of_types = (
            [
                item
                for item in any_of or []
                if not isinstance(item, Mapping) or item.get("type") != "null"
            ]
            if has_null_any_of
            else any_of
        )
        if any_of is not None and len(any_of) > 64:
            raise NativeProviderDescriptorError("native_tool_schema_invalid")
        flattened_any_of = (
            project(any_of_types[0], depth + 1, nested=True)
            if has_null_any_of and len(any_of_types or []) == 1
            else None
        )

        result: dict[str, object] = {}
        retained: tuple[str, ...] = (
            "description",
            "required",
            "format",
            "enum",
            "minLength",
        )
        for key in retained:
            if key in node and node[key] is not None:
                result[key] = node[key]
        if raw_type is not None:
            if types is None:
                result["type"] = raw_type
            elif len(types) == 0:
                result["type"] = "null"
        if (isinstance(raw_type, list) and "null" in raw_type and types) or has_null_any_of:
            result["nullable"] = True
        elif "nullable" not in result:
            result.pop("nullable", None)

        if "const" in node:
            result["enum"] = [node["const"]]
        elif "enum" in node:
            result["enum"] = node["enum"]

        if isinstance(properties, Mapping):
            if len(properties) > 64:
                raise NativeProviderDescriptorError("native_tool_schema_invalid")
            projected_properties: dict[str, object] = {}
            for name, child in properties.items():
                if not isinstance(name, str) or len(name) > 128:
                    raise NativeProviderDescriptorError("native_tool_schema_invalid")
                child_schema = project(child, depth + 1, nested=True)
                # Native JSON serialization omits undefined object properties.
                if child_schema is not None:
                    projected_properties[name] = child_schema
            result["properties"] = projected_properties

        if "items" in node:
            items = node["items"]
            if isinstance(items, list):
                if len(items) > 64:
                    raise NativeProviderDescriptorError("native_tool_schema_invalid")
                result["items"] = [project(item, depth + 1, nested=True) for item in items]
            elif items is not None:
                result["items"] = project(items, depth + 1, nested=True)

        for key in ("allOf", "anyOf", "oneOf"):
            value_list = any_of_types if key == "anyOf" and has_null_any_of else node.get(key)
            if key == "anyOf" and has_null_any_of and len(any_of_types or []) == 1:
                continue
            if isinstance(value_list, list):
                if len(value_list) > 64:
                    raise NativeProviderDescriptorError("native_tool_schema_invalid")
                result[key] = [project(item, depth + 1, nested=True) for item in value_list]
            elif key == "anyOf" and types:
                result[key] = [{"type": item} for item in types]

        if flattened_any_of:
            result.update(flattened_any_of)
        return result

    sanitized = sanitize(value, _depth)
    return project(sanitized, _depth, nested=False)


def _gemini_string(value: object) -> str:
    """Match JavaScript String() for the JSON scalar enum values used by app schemas."""

    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str | int | float) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        return ",".join(_gemini_string(item) if item is not None else "" for item in value)
    if isinstance(value, Mapping):
        return "[object Object]"
    raise NativeProviderDescriptorError("native_tool_schema_invalid")


def normalize_native_integrations(payload: object) -> tuple[NativeIntegrationDescriptor, ...]:
    """Project native Integration.Info rows to allowlisted method IDs and safe labels.

    The projection intentionally drops connections, names, OAuth forms, environment values,
    and all other native fields. Unknown methods are counted but cannot become usable.
    """

    rows = _integration_rows(payload)
    output: list[NativeIntegrationDescriptor] = []
    seen_integrations: set[str] = set()

    for row in rows:
        if not isinstance(row, Mapping):
            raise NativeProviderDescriptorError("native_integration_invalid")
        integration_id = row.get("id")
        if not isinstance(integration_id, str):
            continue
        if integration_id not in _INTEGRATION_ADAPTERS:
            continue
        if not _NATIVE_ID.fullmatch(integration_id):
            raise NativeProviderDescriptorError("native_integration_invalid")
        if integration_id in seen_integrations:
            raise NativeProviderDescriptorError("native_integration_duplicate")
        seen_integrations.add(integration_id)

        raw_methods = row.get("methods")
        if not isinstance(raw_methods, list) or len(raw_methods) > _MAX_METHOD_ROWS:
            raise NativeProviderDescriptorError("native_integration_invalid")

        known_methods: list[NativeAuthMethodDescriptor] = []
        seen_methods: set[str] = set()
        unsupported_method_count = 0
        permitted_ids = _OAUTH_METHODS.get(integration_id, {})
        for raw_method in raw_methods:
            if not isinstance(raw_method, Mapping):
                unsupported_method_count += 1
                continue
            method_id = raw_method.get("id")
            label = raw_method.get("label")
            method_type = raw_method.get("type")
            if (
                not isinstance(method_id, str)
                or not isinstance(label, str)
                or not isinstance(method_type, str)
                or len(method_id) > _MAX_NATIVE_TEXT
                or len(label) > _MAX_NATIVE_TEXT
                or len(method_type) > _MAX_NATIVE_TEXT
            ):
                unsupported_method_count += 1
                continue
            safe_label = permitted_ids.get(method_id)
            if safe_label is None or method_type != "oauth" or method_id in seen_methods:
                unsupported_method_count += 1
                continue
            seen_methods.add(method_id)
            known_methods.append(
                NativeAuthMethodDescriptor(
                    method_id=method_id,
                    kind="oauth",
                    label=safe_label,
                    application_state="oauth_handoff_pending",
                    application_usable=False,
                )
            )

        output.append(
            NativeIntegrationDescriptor(
                integration_id=integration_id,
                adapter_id=_INTEGRATION_ADAPTERS[integration_id],
                oauth_methods=tuple(sorted(known_methods, key=lambda method: method.method_id)),
                unsupported_method_count=unsupported_method_count,
            )
        )

    return tuple(sorted(output, key=lambda integration: integration.integration_id))


def _integration_rows(payload: object) -> list[object]:
    rows: object
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, Mapping):
        rows = payload.get("data")
    else:
        rows = None
    if not isinstance(rows, list) or len(rows) > _MAX_INTEGRATION_ROWS:
        raise NativeProviderDescriptorError("native_integration_invalid")
    return rows
