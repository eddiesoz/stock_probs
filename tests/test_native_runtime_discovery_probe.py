"""Focused tests for the standalone attached-runtime diagnostic."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from native_runtime_discovery_probe import (
    _diagnostic_accepted,
    _exception_code,
    _failure_projection,
    _response_hook,
)


def test_async_httpx_response_hook_projects_only_closed_header_metadata() -> None:
    """HTTPX awaits the hook, whose projection excludes raw headers and content."""

    responses: list[dict[str, object]] = []
    hook = _response_hook(responses)

    async def exercise() -> None:
        async def transport(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={
                    "content-encoding": "br",
                    "content-length": "11",
                    "content-type": "application/json",
                },
                content=b'{"data":[]}',
                request=request,
            )

        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:4097",
            headers={"accept-encoding": "identity"},
            event_hooks={"response": [hook]},
            transport=httpx.MockTransport(transport),
        ) as client:
            await client.get("/api/session")
            await client.get("/api/model")
            await client.post("/api/session/synthetic/prompt")

    asyncio.run(exercise())

    assert responses == [
        {
            "route": "session_api",
            "status": 200,
            "request_accept_encoding_identity": True,
            "response_encoding": "encoded_or_unrecognized",
            "content_length_state": "within_limit",
            "content_length_within_cap": True,
            "content_type_json": True,
        },
        {
            "route": "model",
            "status": 200,
            "request_accept_encoding_identity": True,
            "response_encoding": "encoded_or_unrecognized",
            "content_length_state": "within_limit",
            "content_length_within_cap": True,
            "content_type_json": True,
        },
        {
            "route": "session_prompt",
            "status": 200,
            "request_accept_encoding_identity": True,
            "response_encoding": "encoded_or_unrecognized",
            "content_length_state": "within_limit",
            "content_length_within_cap": True,
            "content_type_json": True,
        },
    ]


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("model_location_mismatch", "model_location_mismatch"),
        ("native_response_encoding_invalid", "native_response_encoding_invalid"),
        ("secret=must-not-echo", "diagnostic_unknown"),
        ("model_location_mismatch secret=must-not-echo", "diagnostic_unknown"),
    ],
)
def test_probe_projects_only_fixed_runtime_error_codes(message: str, expected: str) -> None:
    """Untrusted RuntimeError arguments never enter a diagnostic receipt."""

    assert _exception_code(RuntimeError(message)) == expected


def test_cleanup_success_does_not_pass_failed_location_verification() -> None:
    """The diagnostic passes only when both locations verified before purge."""

    result: dict[str, object] = {
        "outcome": "metadata_only_complete",
        "runtime_start_status": "ready",
        "locations": [{"prepared": True}, {"prepared": True}],
        "verify_outcomes": [
            {"status": "verified", "phase": "complete", "code": "none"},
            {"status": "failed", "phase": "model_discovery", "code": "model_alias_unavailable"},
        ],
        "native_session_requests": 0,
        "native_prompt_requests": 0,
        "runtime_close": "complete",
        "cleanup": {
            "locations_removed": 2,
            "location_removal_failures": 0,
            "purge_requested": True,
            "purge_completed": True,
        },
    }

    assert _diagnostic_accepted(result) is False


def test_diagnostic_pass_requires_two_verified_locations_and_cleanup() -> None:
    """A complete metadata read and successful purge satisfy the diagnostic."""

    result: dict[str, object] = {
        "outcome": "metadata_only_complete",
        "runtime_start_status": "ready",
        "locations": [{"prepared": True}, {"prepared": True}],
        "verify_outcomes": [
            {"status": "verified", "phase": "complete", "code": "none"},
            {"status": "verified", "phase": "complete", "code": "none"},
        ],
        "native_session_requests": 0,
        "native_prompt_requests": 0,
        "runtime_close": "complete",
        "cleanup": {
            "locations_removed": 2,
            "location_removal_failures": 0,
            "purge_requested": True,
            "purge_completed": True,
        },
    }

    assert _diagnostic_accepted(result) is True


def test_failure_projection_separates_native_model_and_mcp_phases() -> None:
    """Only fixed native phases and error codes reach the probe projection."""

    assert _failure_projection(RuntimeError("model_location_mismatch"), "unknown") == {
        "status": "failed",
        "phase": "model_discovery",
        "code": "model_location_mismatch",
    }
    assert _failure_projection(RuntimeError("secret=private"), "verify_location") == {
        "status": "failed",
        "phase": "verify_location",
        "code": "diagnostic_unknown",
    }
