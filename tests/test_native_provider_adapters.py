"""Verify the closed native OpenCode provider and integration descriptor boundary."""

from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError, asdict
from datetime import UTC, datetime

import pytest

from stock_probs.assistant.native_provider_adapters import (
    NATIVE_WEBFETCH_DESCRIPTION_SHA256,
    NativeProviderDescriptorError,
    native_adapter_descriptors,
    native_webfetch_schema,
    native_websearch_description_sha256,
    native_websearch_schema,
    normalize_native_integrations,
    project_gemini_tool_schema,
    project_opencode_console_models,
    resolve_native_adapter,
    resolve_native_adapter_package,
)


def test_adapter_registry_contains_only_reviewed_native_protocol_pairs() -> None:
    """Expose the three executed vendor protocols and the fixed app proxy package."""

    descriptors = native_adapter_descriptors()

    assert [item.adapter_id for item in descriptors] == [
        "anthropic-messages",
        "google-generative-language",
        "openai-compatible-chat",
        "openai-responses",
    ]
    assert {
        item.adapter_id: (
            item.native_provider_id,
            item.package_id,
            item.protocol,
            item.route_suffix,
            item.fixed_query,
            item.upstream_query,
            item.native_capability_header,
            item.native_capability_scheme,
            item.upstream_auth_header,
            item.upstream_auth_scheme,
            item.upstream_static_headers,
        )
        for item in descriptors
    } == {
        "openai-responses": (
            "openai",
            "@opencode/ai/providers/openai",
            "openai-responses",
            "responses",
            (),
            (),
            "Authorization",
            "bearer",
            "Authorization",
            "bearer",
            (),
        ),
        "anthropic-messages": (
            "anthropic",
            "@opencode/ai/providers/anthropic",
            "anthropic-messages",
            "messages",
            (("beta", "true"),),
            (),
            "Authorization",
            "bearer",
            "x-api-key",
            "raw",
            (("anthropic-version", "2023-06-01"),),
        ),
        "google-generative-language": (
            "google",
            "@opencode/ai/providers/google",
            "google-generative-language",
            "models/{model}:streamGenerateContent",
            (("alt", "sse"),),
            (("alt", "sse"),),
            "Authorization",
            "bearer",
            "x-goog-api-key",
            "raw",
            (),
        ),
        "openai-compatible-chat": (
            "assistant-proxy",
            "@opencode/ai/providers/openai-compatible",
            "openai-compatible-chat",
            "chat/completions",
            (),
            (),
            "Authorization",
            "bearer",
            "Authorization",
            "bearer",
            (),
        ),
    }
    assert all(item.application_credential_state == "app_vault_bridge" for item in descriptors)


@pytest.mark.parametrize(
    ("adapter_id", "native_provider_id"),
    [
        ("openai-responses", "openai"),
        ("anthropic-messages", "anthropic"),
        ("google-generative-language", "google"),
        ("openai-compatible-chat", "assistant-proxy"),
    ],
)
def test_resolver_accepts_only_exact_fixed_pairs(adapter_id: str, native_provider_id: str) -> None:
    """Return only statically declared package metadata for an exact identity pair."""

    descriptor = resolve_native_adapter(adapter_id, native_provider_id)

    assert descriptor.adapter_id == adapter_id
    assert descriptor.native_provider_id == native_provider_id


@pytest.mark.parametrize(
    ("package_id", "adapter_id"),
    [
        ("@opencode/ai/providers/openai", "openai-responses"),
        ("@opencode/ai/providers/anthropic", "anthropic-messages"),
        ("@opencode/ai/providers/google", "google-generative-language"),
        ("@opencode/ai/providers/openai-compatible", "openai-compatible-chat"),
    ],
)
def test_package_resolver_accepts_only_exact_builtin_packages(
    package_id: str, adapter_id: str
) -> None:
    descriptor = resolve_native_adapter_package(package_id)

    assert descriptor.adapter_id == adapter_id


@pytest.mark.parametrize(
    "package_id",
    [
        "npm:@attacker/provider",
        "@opencode/ai/providers/openai@latest",
        "@opencode/ai/providers/opencode",
        "openai",
        "",
    ],
)
def test_package_resolver_rejects_dynamic_or_unreviewed_packages(package_id: str) -> None:
    with pytest.raises(NativeProviderDescriptorError) as error:
        resolve_native_adapter_package(package_id)

    assert error.value.code == "provider_adapter_unsupported"


def test_console_projection_discards_overlays_and_pins_package_and_model_identity() -> None:
    payload = {
        "providers": {
            "my-openai": {
                "canonical": "openai",
                "name": "Reviewed provider",
                "settings": {
                    "baseURL": "https://api.example.test/v1",
                    "apiKey": "must-not-project",
                },
                "headers": {"x-attacker": "must-not-project"},
                "body": {"model": "must-not-project"},
                "models": {
                    "model-a": {
                        "modelID": "vendor/model-a",
                        "name": "Model A",
                        "settings": {"baseURL": "https://other.example.test/v1"},
                        "headers": {"x-attacker": "must-not-project"},
                        "body": {"model": "must-not-project"},
                        "variants": [{"id": "unsafe"}],
                    },
                    "disabled-model": {"disabled": True},
                },
            },
            "arbitrary": {
                "package": "npm:attacker/provider",
                "models": {"x": {"modelID": "x"}},
            },
        },
        "websearch": {"providerID": "console-search"},
    }

    rows, unsupported_count = project_opencode_console_models(payload)

    assert len(rows) == 1
    assert unsupported_count == 1
    assert rows[0].config_provider_id == "my-openai"
    assert rows[0].native_model_id == "vendor/model-a"
    assert rows[0].package_id == "@opencode/ai/providers/openai"
    assert rows[0].adapter.adapter_id == "openai-responses"
    assert "must-not-project" not in repr(rows[0])


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"providers": []},
        {"providers": {}, "unexpected": "field"},
        {"providers": {"a" * 65: {"models": {}}}},
        {"providers": {"p": {"models": {"m": {"package": "x" * 129}}}}},
    ],
)
def test_console_projection_rejects_malformed_top_level_or_bounds(payload: object) -> None:
    with pytest.raises(NativeProviderDescriptorError) as error:
        project_opencode_console_models(payload)

    assert error.value.code == "opencode_config_invalid"


def test_console_projection_keeps_in_bounds_unknown_package_as_unsupported() -> None:
    payload = {"providers": {"provider": {"models": {"model": {"package": "x" * 128}}}}}
    rows, unsupported_count = project_opencode_console_models(payload)
    assert rows == ()
    assert unsupported_count == 1


def test_resolver_rejects_unknown_ids_and_mismatched_providers_without_echoing_input() -> None:
    """Reject dynamic package/provider values with stable, non-reflective error codes."""

    with pytest.raises(NativeProviderDescriptorError) as unknown:
        resolve_native_adapter("@attacker/package", "openai")
    assert unknown.value.code == "native_adapter_unsupported"
    assert str(unknown.value) == "native_adapter_unsupported"

    with pytest.raises(NativeProviderDescriptorError) as mismatch:
        resolve_native_adapter("openai-responses", "assistant-proxy")
    assert mismatch.value.code == "native_provider_mismatch"
    assert str(mismatch.value) == "native_provider_mismatch"


def test_gemini_projection_matches_the_pinned_converter_allowlist() -> None:
    """Project only the pinned Gemini-lowered constraints and preserve retained fields."""

    projected = project_gemini_tool_schema(
        {
            "type": "object",
            "description": "Safe schema text",
            "required": ["count", "label"],
            "additionalProperties": False,
            "minimum": 0,
            "properties": {
                "count": {"type": "integer", "enum": [1, 2], "maximum": 3},
                "label": {"type": "string", "const": "approved", "maxLength": 12},
                "items": {"type": "array", "pattern": "ignored-by-native-converter"},
            },
        }
    )

    assert projected == {
        "type": "object",
        "description": "Safe schema text",
        "required": ["count", "label"],
        "properties": {
            "count": {"type": "string", "enum": ["1", "2"]},
            "label": {"type": "string", "enum": ["approved"]},
            "items": {"type": "array", "items": {"type": "string"}},
        },
    }
    assert project_gemini_tool_schema({"type": "object", "properties": {}}) is None


def test_gemini_projection_matches_pinned_nullable_and_const_lowering() -> None:
    """Match V2.0.7 type-array, nullable-anyOf, and const lowering exactly."""

    assert project_gemini_tool_schema({"type": ["number", "null"], "minimum": 0}) == {
        "nullable": True,
        "anyOf": [{"type": "number"}],
    }
    assert project_gemini_tool_schema(
        {
            "type": "object",
            "properties": {
                "quantity": {
                    "anyOf": [{"type": "number"}, {"type": "null"}],
                    "minimum": 0,
                },
                "fixed": {"type": "string", "const": "exact"},
            },
            "required": ["quantity", "missing"],
            "additionalProperties": False,
        }
    ) == {
        "type": "object",
        "required": ["quantity"],
        "properties": {
            "quantity": {"nullable": True, "type": "number"},
            "fixed": {"type": "string", "enum": ["exact"]},
        },
    }
    assert project_gemini_tool_schema({"type": ["null"]}) == {"type": "null"}
    assert project_gemini_tool_schema({"type": ["string", "integer"]}) == {
        "anyOf": [{"type": "string"}, {"type": "integer"}]
    }


def test_gemini_projection_keeps_native_bounds_and_drops_only_unmodeled_keywords() -> None:
    """Keep retained fields while omitting exact pinned unsupported constraints."""

    projected = project_gemini_tool_schema(
        {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "minLength": 2,
                    "maxLength": 40,
                    "pattern": "secret-free-pattern",
                    "format": "date-time",
                },
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "enum": [1, 2],
                },
            },
            "required": ["text", "not-present"],
            "additionalProperties": False,
        }
    )

    assert projected == {
        "type": "object",
        "properties": {
            "text": {"type": "string", "format": "date-time", "minLength": 2},
            "count": {"type": "string", "enum": ["1", "2"]},
        },
        "required": ["text"],
    }


def test_builtin_search_schema_is_closed_for_all_reviewed_wire_protocols() -> None:
    """Expose only the captured query-string builtin on the four reviewed adapters."""

    for protocol in (
        "openai-responses",
        "anthropic-messages",
        "google-generative-language",
        "openai-compatible-chat",
    ):
        schema = native_websearch_schema(protocol)
        assert isinstance(schema, dict)
        assert schema["type"] == "object"
        assert schema["required"] == ["query"]
        assert schema["properties"] == {
            "query": {"type": "string", "description": "Websearch query"}
        }
        if protocol == "google-generative-language":
            assert "additionalProperties" not in schema
        else:
            assert schema["additionalProperties"] is False


def test_builtin_search_pins_function_description_separately_from_parameter_description() -> None:
    """Pin the full description template while supporting native year rollover."""

    current_year = native_websearch_description_sha256()
    assert hashlib.sha256(b"Websearch query").hexdigest() != current_year
    expected_2026 = (
        "Search the web using the user's selected search integration. Use this for current "
        "information beyond knowledge cutoff.\n\nThe current year is 2026. Use this year "
        "when searching for recent information or current events."
    )
    assert (
        native_websearch_description_sha256(2026)
        == hashlib.sha256(expected_2026.encode("utf-8")).hexdigest()
    )
    assert native_websearch_description_sha256(2026) == (
        "a99cebc6723d8d1fdf45be61d0f99e35cf31e769412059ff35293c8010de5c5f"
    )
    assert native_websearch_description_sha256(2027) != native_websearch_description_sha256(2026)
    assert current_year == native_websearch_description_sha256(datetime.now(UTC).year)
    with pytest.raises(ValueError):
        native_websearch_description_sha256(True)


def test_builtin_webfetch_schema_is_closed_for_reviewed_wire_protocols() -> None:
    """Pin the source-derived native URL/format/timeout contract per protocol."""

    expected_properties = {
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
    }
    expected_schema = {
        "type": "object",
        "properties": expected_properties,
        "required": ["url"],
        "additionalProperties": False,
    }
    for protocol in (
        "openai-responses",
        "anthropic-messages",
        "google-generative-language",
        "openai-compatible-chat",
    ):
        schema = native_webfetch_schema(protocol)
        assert isinstance(schema, dict)
        if protocol == "google-generative-language":
            assert schema == project_gemini_tool_schema(expected_schema)
            assert "additionalProperties" not in schema
        else:
            assert schema == expected_schema


def test_builtin_webfetch_function_description_hash_is_pinned_separately() -> None:
    assert NATIVE_WEBFETCH_DESCRIPTION_SHA256 == (
        "b958b70f4a4edd3ce9add115a5d127f6a7948e65f95c0793f11c871456d59d8c"
    )


def test_integration_projection_keeps_only_known_oauth_ids_and_fixed_labels() -> None:
    """Discard native labels, forms, connections, and metadata from Integration.Info."""

    payload: object = {
        "data": [
            {
                "id": "openai",
                "name": "Untrusted display value",
                "methods": [
                    {"id": "chatgpt-browser", "label": "Changed label", "type": "oauth"},
                    {"id": "chatgpt-headless", "label": "Changed label", "type": "oauth"},
                ],
                "connections": [{"id": "private-connection-marker", "type": "oauth"}],
                "metadata": {"token": "private-metadata-marker"},
            },
            {
                "id": "opencode",
                "name": "OpenCode",
                "methods": [
                    {
                        "id": "device",
                        "label": "Changed label",
                        "type": "oauth",
                        "form": {"secret": "private-form-marker"},
                    }
                ],
                "connections": [],
            },
            {"id": "google", "name": "Google", "methods": [], "connections": []},
            {"id": "anthropic", "name": "Anthropic", "methods": [], "connections": []},
            {"id": "unreviewed-provider", "name": "Ignored", "methods": [{"secret": "x"}]},
        ]
    }

    integrations = normalize_native_integrations(payload)

    assert [item.integration_id for item in integrations] == [
        "anthropic",
        "google",
        "openai",
        "opencode",
    ]
    by_id = {item.integration_id: item for item in integrations}
    assert by_id["openai"].adapter_id == "openai-responses"
    assert [method.method_id for method in by_id["openai"].oauth_methods] == [
        "chatgpt-browser",
        "chatgpt-headless",
    ]
    assert [method.label for method in by_id["openai"].oauth_methods] == [
        "ChatGPT browser sign-in",
        "ChatGPT headless sign-in",
    ]
    assert by_id["opencode"].adapter_id is None
    assert by_id["opencode"].oauth_methods[0].label == "OpenCode device sign-in"
    assert all(
        method.application_usable is False and method.application_state == "oauth_handoff_pending"
        for item in integrations
        for method in item.oauth_methods
    )

    serialized = repr(tuple(asdict(item) for item in integrations))
    assert "private-connection-marker" not in serialized
    assert "private-metadata-marker" not in serialized
    assert "private-form-marker" not in serialized
    assert "Changed label" not in serialized
    assert "Untrusted display value" not in serialized


def test_unknown_or_malformed_methods_are_counted_but_never_promoted() -> None:
    """Keep unknown native auth methods unavailable without copying their contents."""

    integrations = normalize_native_integrations(
        [
            {
                "id": "openai",
                "methods": [
                    {"id": "chatgpt-browser", "label": "Browser", "type": "oauth"},
                    {"id": "future-auth-secret-name", "label": "Private", "type": "unknown"},
                    {"id": "chatgpt-headless", "label": "Wrong kind", "type": "key"},
                    {"id": "chatgpt-browser", "label": "Duplicate", "type": "oauth"},
                    {"id": 17, "label": "Malformed", "type": "oauth"},
                ],
            }
        ]
    )

    assert len(integrations) == 1
    assert [method.method_id for method in integrations[0].oauth_methods] == ["chatgpt-browser"]
    assert integrations[0].unsupported_method_count == 4
    assert "future-auth-secret-name" not in repr(integrations)
    assert "Private" not in repr(integrations)
    assert "Wrong kind" not in repr(integrations)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"items": []},
        {"data": "not-a-list"},
        {"data": [{"id": "openai", "methods": "not-a-list"}]},
        {"data": [{"id": "openai", "methods": [None] * 33}]},
        {"data": [{"id": "openai", "methods": []}, {"id": "openai", "methods": []}]},
    ],
)
def test_integration_projection_rejects_invalid_or_unbounded_envelopes(payload: object) -> None:
    """Fail closed on malformed, duplicate, or over-bound known native rows."""

    with pytest.raises(NativeProviderDescriptorError):
        normalize_native_integrations(payload)


def test_adapter_descriptors_are_immutable() -> None:
    """Prevent callers from rewriting process-wide fixed package metadata."""

    descriptor = resolve_native_adapter("openai-responses", "openai")

    with pytest.raises(FrozenInstanceError):
        descriptor.package_id = "@attacker/package"  # type: ignore[misc]
