"""Exercise the bounded OpenCode worker lifecycle and exact native permission bridge."""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
import socket
import time
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from stock_probs import container_supervisor as supervisor_service
from stock_probs.assistant import net as assistant_net
from stock_probs.assistant import runtime as assistant_runtime
from stock_probs.assistant import supervisor_client as assistant_supervisor_client
from stock_probs.assistant.native_provider_adapters import resolve_native_adapter
from stock_probs.assistant.runtime import (
    OpenCodeV2Runtime,
    _build_prompt,
    _contains_foreign_session_id,
    _native_failure_category,
    _native_search_text_links,
    _native_tool_activity_description,
    _safe_app_exception_code,
    _safe_startup_failure_code,
    _summarize_native_failure_payload,
)
from stock_probs.assistant.schemas import (
    AssistantRuntimeStatus,
    AssistantTurnContext,
    AssistantTurnResult,
    EventEmitter,
)
from stock_probs.assistant.search import NativeSearchPermissionBridge
from stock_probs.assistant.service import AssistantService, AssistantUnavailable
from stock_probs.assistant.supervisor_client import SupervisorClientError
from tests.native_assistant_probe import (
    _attached_acceptance_failures,
    _attached_conversation_detail,
    _attached_interaction_diagnostic,
    _attached_new_interaction_tracker,
    _attached_observe_interaction_snapshot,
    _attached_owner_evidence,
    _attached_record_timeline_phase,
    _attached_require_search_confirmation,
    _attached_reviewed_model_row,
    _attached_totp_code,
    _attached_worker_diagnostic,
    _AttachedProbeFailure,
)

_TEST_MODEL_ID = "fixture-provider/" + secrets.token_hex(8)


def test_attached_probe_totp_matches_rfc6238_six_digit_vector() -> None:
    """The attached-app admin step-up uses a standard current-window TOTP code."""

    assert (
        _attached_totp_code(
            "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ",
            at=datetime.fromtimestamp(59, UTC),
        )
        == "287082"
    )


def test_attached_probe_totp_rejects_invalid_fixture_secret() -> None:
    """Malformed private fixture input fails before the attached app is contacted."""

    with pytest.raises(_AttachedProbeFailure, match="totp_fixture_invalid"):
        _attached_totp_code("not-a-base32-factor")


def test_attached_probe_accepts_exact_reviewed_usable_candidate_row() -> None:
    """The attached probe selects one model only after all reviewed predicates pass."""

    model = {
        "model_id": "fixture-provider/reviewed-free",
        "provider_id": "opencode-zen",
        "available": True,
        "free": True,
        "training_uses_data": False,
        "privacy_policy_version": "privacy-v1",
        "billing_policy_version": "billing-v1",
        "revision": 1,
    }

    assert _attached_reviewed_model_row([model], "fixture-provider/reviewed-free") is model


@pytest.mark.parametrize(
    ("changes", "safe_error_code"),
    [
        ({"provider_id": "other-provider"}, "reviewed_model_provider_mismatch"),
        ({"available": False}, "reviewed_model_not_available"),
        ({"free": False}, "reviewed_model_not_free"),
        ({"training_uses_data": True}, "reviewed_model_training_not_disabled"),
        ({"privacy_policy_version": None}, "reviewed_model_privacy_version_missing"),
        ({"billing_policy_version": None}, "reviewed_model_billing_version_missing"),
        ({"revision": True}, "reviewed_model_revision_invalid"),
    ],
)
def test_attached_probe_fails_closed_on_reviewed_model_mismatch(
    changes: dict[str, object], safe_error_code: str
) -> None:
    """The model picker distinguishes safe catalog mismatches without exposing values."""

    model = {
        "model_id": "fixture-provider/reviewed-free",
        "provider_id": "opencode-zen",
        "available": True,
        "free": True,
        "training_uses_data": False,
        "privacy_policy_version": "privacy-v1",
        "billing_policy_version": "billing-v1",
        "revision": 1,
    }
    model.update(changes)

    with pytest.raises(_AttachedProbeFailure, match=safe_error_code):
        _attached_reviewed_model_row([model], "fixture-provider/reviewed-free")


def test_attached_probe_requires_reviewed_model_in_live_inventory() -> None:
    """An empty native model inventory cannot be mistaken for reviewed availability."""

    with pytest.raises(_AttachedProbeFailure, match="reviewed_model_not_in_inventory"):
        _attached_reviewed_model_row([], "fixture-provider/reviewed-free")


def test_runtime_projects_only_closed_app_error_codes_into_diagnostics() -> None:
    """Native logs may identify a safe rejection without exposing exception detail."""

    safe = AssistantUnavailable("invalid_runtime_event", 502)
    unsafe = AssistantUnavailable("credential=private-value", 502)
    arbitrary = RuntimeError("private exception text")

    assert _safe_app_exception_code(safe) == "invalid_runtime_event"
    assert _safe_app_exception_code(unsafe) is None
    assert _safe_app_exception_code(arbitrary) is None


@pytest.mark.parametrize(
    "code",
    [
        "location_invalid",
        "model_location_mismatch",
        "native_response_encoding_invalid",
        "native_response_invalid",
        "native_response_too_large",
        "worker_unavailable",
    ],
)
def test_runtime_pre_session_projects_only_exact_fixed_runtime_error_codes(code: str) -> None:
    assert assistant_runtime._safe_pre_session_failure_code(RuntimeError(code)) == code

    class RuntimeErrorSubclass(RuntimeError):
        pass

    assert (
        assistant_runtime._safe_pre_session_failure_code(
            RuntimeErrorSubclass("model_location_mismatch")
        )
        == "diagnostic_unknown"
    )
    assert (
        assistant_runtime._safe_pre_session_failure_code(
            RuntimeError("model_location_mismatch token=synthetic")
        )
        == "diagnostic_unknown"
    )


@pytest.mark.parametrize(
    ("native_error", "category"),
    (
        ({"code": "ENOTFOUND", "message": "private host detail"}, "dns"),
        ({"cause": {"code": "ERR_TLS_CERT_ALTNAME_INVALID"}}, "tls"),
        ({"name": "TimeoutError", "message": "private timeout detail"}, "timeout"),
        ({"code": "ECONNRESET"}, "connection"),
        ({"statusCode": 503}, "http"),
        ({"code": "ERR_BODY_TOO_LARGE"}, "body_limit"),
        ({"code": "ERR_INVALID_URL"}, "request_invalid"),
        ({"name": "TypeError", "message": "private runtime detail"}, "native_defect"),
        ({"message": "private unclassified detail"}, "native_error_unknown"),
        ({}, "unknown"),
    ),
)
def test_native_failure_category_uses_closed_transport_classes(
    native_error: dict[str, object], category: str
) -> None:
    """Structured native codes map to fixed classes without retaining their messages."""

    assert _native_failure_category({"error": native_error}) == category


@pytest.mark.parametrize(
    ("message", "category"),
    (
        ("Request timed out for https://user:pass@private.example/?token=secret", "timeout"),
        ("getaddrinfo ENOTFOUND private.example?api_key=secret", "dns"),
        ("TLS handshake failed for https://private.example/path?access_token=secret", "tls"),
        ("connect ECONNREFUSED private.example:443?password=secret", "connection"),
        ("Request failed with status code 403 for https://private.example/?jwt=secret", "http"),
        ("Response too large (exceeds 5242880 byte limit)", "body_limit"),
        ("Invalid URL https://private.example/?credential=secret", "request_invalid"),
        ("Unclassified failure for https://private.example/?secret=secret", "native_error_unknown"),
        ("x" * 512 + " Request timed out", "native_error_unknown"),
    ),
)
def test_native_failure_category_maps_bounded_serialized_error_text(
    message: str, category: str
) -> None:
    """Only reviewed native phrases map; URLs and secret values never become output."""

    assert _native_failure_category({"error": {"type": "unknown", "message": message}}) == category


def test_terminal_failure_summary_omits_private_error_url_and_partial_text() -> None:
    private_url = "https://private.example/path?access_token=never-log-this"
    private_error = "TLS handshake failed for " + private_url
    payload = {
        "data": [
            {
                "info": {"id": "message-private", "role": "assistant", "finish": "error"},
                "parts": [
                    {"type": "text", "text": "partial private answer"},
                    {
                        "type": "tool",
                        "name": "webfetch",
                        "state": {
                            "status": "error",
                            "error": {
                                "type": "unknown",
                                "message": private_error,
                            },
                        },
                    },
                ],
            }
        ]
    }

    summary = _summarize_native_failure_payload(
        payload,
        session_id="sesABCDEFGH",
        approved_fetch_urls={private_url: 1},
    )

    assert summary == {
        "snapshot_status": "read",
        "assistant_finish": "error",
        "assistant_failure_categories": "native_error_unknown",
        "assistant_error_count": 1,
        "webfetch_state": "error",
        "webfetch_failure_categories": "tls",
        "webfetch_timeout_stage": "not_timeout",
        "webfetch_timeout_seconds_max": "none",
        "webfetch_tool_elapsed_ms_max": "none",
        "webfetch_completion_categories": "none",
        "native_failure_categories": "tls",
        "native_tool_error_count": 1,
    }
    assert private_url not in repr(summary)
    assert private_error not in repr(summary)
    assert "partial private answer" not in repr(summary)


@pytest.mark.parametrize(
    (
        "error",
        "timeout",
        "timing",
        "stage",
        "timeout_seconds",
        "elapsed_ms",
        "failure_category",
    ),
    (
        (
            {
                "code": "ETIMEDOUT",
                "syscall": "getaddrinfo",
                "message": "DNS lookup timed out for diagnostic-secret-marker",
            },
            0.25,
            {"ran": 1_000, "completed": 1_091},
            "dns_lookup_timeout",
            "0.25",
            91,
            "timeout",
        ),
        (
            {
                "type": "ToolFailure",
                "message": "Unable to fetch https://private.example/?credential=diagnostic-secret-marker",
                "error": {"name": "Error", "message": "Request timed out"},
            },
            30,
            {"ran": 1_000, "completed": 31_000},
            "request_or_native_tool_timeout",
            "30",
            30_000,
            "timeout",
        ),
        (
            {
                "type": "ToolFailure",
                "message": "Unable to fetch https://private.example/?token=diagnostic-secret-marker",
                "error": "Fetch deadline exceeded",
            },
            30,
            {"ran": 1_000, "completed": 11_000},
            "fetch_deadline",
            "30",
            10_000,
            "native_error_unknown",
        ),
        (
            {
                "name": "TimeoutError",
                "message": "Socket idle timed out for diagnostic-secret-marker",
            },
            120,
            {"ran": 1_000, "completed": 200_001},
            "request_or_native_tool_timeout",
            "120",
            120_000,
            "timeout",
        ),
        (
            {"type": "unknown", "message": "private token=diagnostic-secret-marker"},
            10**400,
            {"ran": 5_000, "completed": 4_000},
            "unknown",
            "none",
            "none",
            "native_error_unknown",
        ),
        (
            {"code": "ERR_TLS_CERT_ALTNAME_INVALID", "message": "tls diagnostic-secret-marker"},
            True,
            {"ran": True, "completed": 5_000},
            "not_timeout",
            "none",
            "none",
            "tls",
        ),
    ),
)
def test_terminal_failure_summary_projects_closed_webfetch_timeout_diagnostics(
    error: dict[str, object],
    timeout: object,
    timing: dict[str, object],
    stage: str,
    timeout_seconds: str,
    elapsed_ms: int | str,
    failure_category: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Failure logs expose fixed timeout stages and bounded native numeric fields only."""

    marker = "diagnostic-secret-marker"
    private_url = f"https://private.example/path?access_token={marker}"
    payload = {
        "data": [
            {
                "info": {"id": "message-private", "role": "assistant", "finish": "error"},
                "parts": [
                    {
                        "id": "part-private",
                        "type": "tool",
                        "name": "webfetch",
                        "state": {
                            "status": "error",
                            "input": {"url": private_url, "timeout": timeout},
                            "error": error,
                        },
                        "time": timing,
                    }
                ],
            }
        ]
    }

    summary = _summarize_native_failure_payload(
        payload,
        session_id="sesABCDEFGH",
        approved_fetch_urls={},
    )
    assistant_runtime._log_native_terminal_failure(summary, session_outcome="failed")

    assert summary["snapshot_status"] == "read"
    assert summary["webfetch_failure_categories"] == failure_category
    assert summary["webfetch_timeout_stage"] == stage
    assert summary["webfetch_timeout_seconds_max"] == timeout_seconds
    assert summary["webfetch_tool_elapsed_ms_max"] == elapsed_ms
    assert f"webfetch_timeout_stage={stage}" in caplog.text
    assert f"webfetch_timeout_seconds_max={timeout_seconds}" in caplog.text
    assert f"webfetch_tool_elapsed_ms_max={elapsed_ms}" in caplog.text
    assert marker not in repr(summary)
    assert marker not in caplog.text
    assert private_url not in repr(summary)
    assert private_url not in caplog.text


def test_terminal_failure_summary_captures_assistant_error_without_tool_error() -> None:
    private_url = "https://private.example/path?token=must-not-log"
    payload = {
        "data": [
            {
                "info": {
                    "id": "message-private",
                    "role": "assistant",
                    "finish": "error",
                    "error": {
                        "type": "unknown",
                        "message": "Request timed out for " + private_url,
                    },
                },
                "parts": [{"type": "text", "text": "partial private answer"}],
            }
        ]
    }

    summary = _summarize_native_failure_payload(
        payload,
        session_id="sesABCDEFGH",
        approved_fetch_urls={},
    )

    assert summary["assistant_finish"] == "error"
    assert summary["assistant_failure_categories"] == "timeout"
    assert summary["assistant_error_count"] == 1
    assert summary["native_tool_error_count"] == 0
    assert private_url not in repr(summary)
    assert "partial private answer" not in repr(summary)


def test_terminal_failure_summary_marks_consumed_fetch_approval_as_present() -> None:
    """A completed source remains explainable after its one-shot approval is consumed."""

    payload = {
        "data": [
            {
                "info": {"id": "message-1", "role": "assistant", "finish": "stop"},
                "parts": [
                    {
                        "id": "part-1",
                        "type": "tool",
                        "name": "webfetch",
                        "state": {
                            "status": "completed",
                            "input": {"url": "https://public.example/article"},
                            "metadata": {"finalUrl": "https://public.example/article"},
                        },
                    }
                ],
            }
        ]
    }

    approved = _summarize_native_failure_payload(
        payload,
        session_id="sesABCDEFGH",
        approved_fetch_urls={},
        validated_fetch_parts={"message-1:part-1"},
    )
    unapproved = _summarize_native_failure_payload(
        payload,
        session_id="sesABCDEFGH",
        approved_fetch_urls={},
    )

    assert approved["webfetch_completion_categories"] == "approved_destination_present"
    assert unapproved["webfetch_completion_categories"] == "approval_missing"


@pytest.mark.parametrize(
    ("payload", "status", "completion"),
    [
        (
            {
                "data": [
                    {
                        "info": {"id": "message-1", "role": "assistant", "finish": "error"},
                        "sessionID": "sesFOREIGN1",
                        "parts": [],
                    }
                ]
            },
            "invalid_scope",
            "none",
        ),
        ({"data": ["malformed native row"]}, "invalid_response", "none"),
        (
            {
                "data": [
                    {
                        "info": {"id": "message-1", "role": "assistant", "finish": "error"},
                        "parts": [
                            {
                                "id": "part-1",
                                "type": "tool",
                                "name": "webfetch",
                                "state": {
                                    "status": "completed",
                                    "input": {"url": "file:///etc/passwd"},
                                    "metadata": {"finalUrl": "file:///etc/passwd"},
                                },
                            }
                        ],
                    }
                ]
            },
            "read",
            "request_invalid",
        ),
    ],
)
def test_terminal_failure_summary_uses_closed_categories_for_untrusted_snapshot_shapes(
    payload: object, status: str, completion: str
) -> None:
    """Foreign scope, malformed rows, and invalid URLs are reduced to fixed labels."""

    summary = _summarize_native_failure_payload(
        payload, session_id="sesABCDEFGH", approved_fetch_urls={}
    )

    assert summary["snapshot_status"] == status
    assert summary["webfetch_completion_categories"] == completion
    assert "file:///etc/passwd" not in repr(summary)


def test_terminal_failure_summary_rejects_unapproved_redirect_destination() -> None:
    """A one-shot approval for the request URL cannot validate a different final URL."""

    requested_url = "https://example.test/start?view=public"
    payload = {
        "data": [
            {
                "info": {"id": "message-1", "role": "assistant", "finish": "stop"},
                "parts": [
                    {
                        "id": "part-1",
                        "type": "tool",
                        "name": "webfetch",
                        "state": {
                            "status": "completed",
                            "input": {"url": requested_url},
                            "metadata": {
                                "finalUrl": "https://redirect.example.test/other?view=public"
                            },
                        },
                    }
                ],
            }
        ]
    }

    summary = _summarize_native_failure_payload(
        payload,
        session_id="sesABCDEFGH",
        approved_fetch_urls={requested_url: 1},
    )

    assert summary["webfetch_completion_categories"] == "destination_mismatch"


def test_startup_failure_code_is_exactly_allowlisted() -> None:
    """Startup diagnostics preserve known fixed codes and discard exception text."""

    assert _safe_startup_failure_code(RuntimeError("native_api_unavailable")) == (
        "native_api_unavailable"
    )
    assert _safe_startup_failure_code(RuntimeError("worker_observation_uncertain")) == (
        "worker_observation_uncertain"
    )
    assert _safe_startup_failure_code(RuntimeError("credential=private-value")) == (
        "diagnostic_unknown"
    )
    assert _safe_startup_failure_code(SupervisorClientError("request_timeout")) == (
        "request_timeout"
    )
    assert _safe_startup_failure_code(SupervisorClientError("credential=private-value")) == (
        "diagnostic_unknown"
    )


@pytest.mark.parametrize(
    ("scenario", "expected_stage", "expected_code"),
    [
        ("ready", None, None),
        ("starting", "supervisor_status", "worker_not_ready"),
        ("unavailable", "supervisor_status", "worker_not_ready"),
        ("native_api_http", "native_api_info", "native_api_unavailable"),
        ("native_api_timeout", "native_api_info", "request_timeout"),
        ("session_timeout", "create_session", "request_timeout"),
    ],
)
def test_concurrent_owner_discovery_and_startup_failure_stages_are_closed(
    scenario: str,
    expected_stage: str | None,
    expected_code: str | None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Attribute a concurrent startup failure before downstream session work."""

    caplog.set_level("WARNING")
    monkeypatch.setattr(assistant_runtime, "_STARTUP_STATUS_DEADLINE_SECONDS", 0.025)
    monkeypatch.setattr(assistant_runtime, "_STARTUP_STATUS_POLL_SECONDS", 0.001)
    discovery_started = asyncio.Event()
    release_discovery = asyncio.Event()
    second_discovery_started = asyncio.Event()
    session_started = asyncio.Event()
    session_executions: set[str] = set()
    info_calls = 0
    verified_executions: set[str] = set()

    class GatedSupervisor(_Supervisor):
        def __init__(self) -> None:
            super().__init__()
            self.status_calls = 0

        async def status(self) -> dict[str, object]:
            self.status_calls += 1
            status = (
                scenario
                if self.status_calls >= 3 and scenario in {"starting", "unavailable"}
                else "ready"
            )
            return {
                "status": status,
                "api_url": "http://127.0.0.1:4097",
                "api_password": "s" * 48,
                "webfetch_guard_ready": self.webfetch_guard_ready,
                "observation_uncertain": False,
            }

    first_context = _context("a" * 32)
    second_context = replace(
        _context("b" * 32),
        user_id=42,
        conversation_id="f" * 36,
        turn_id="e" * 36,
        capability="g" * 48,
    )
    supervisor = GatedSupervisor()
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
    )

    async def native_request(method: str, path: str, **kwargs: object) -> httpx.Response:
        nonlocal info_calls
        del kwargs
        assert method == "GET" and path == "/api/info"
        info_calls += 1
        if info_calls == 3 and scenario == "native_api_http":
            return httpx.Response(503, json={"detail": "private response text"})
        if info_calls == 3 and scenario == "native_api_timeout":
            raise httpx.ReadTimeout("private native API timeout")
        return httpx.Response(200, json={"version": "v2"})

    async def verify_location(
        context: AssistantTurnContext,
        _directory: str,
        _descriptor: object,
        *,
        turn_deadline: float | None,
    ) -> dict[str, str]:
        del turn_deadline
        verified_executions.add(context.execution_id)
        if context.execution_id == first_context.execution_id:
            discovery_started.set()
            await release_discovery.wait()
        else:
            second_discovery_started.set()
        return {"id": "assistant-selected", "providerID": "assistant-proxy"}

    async def create_session(
        context: AssistantTurnContext,
        _directory: str,
        _provider_ref: object,
        *,
        webfetch_enabled: bool | None = None,
    ) -> str:
        del webfetch_enabled
        session_started.set()
        session_executions.add(context.execution_id)
        if scenario == "session_timeout":
            raise httpx.ReadTimeout("private session timeout")
        await asyncio.Event().wait()
        raise AssertionError("a blocked synthetic session should only exit through cancellation")

    runtime._request = native_request
    runtime._verify_location = verify_location
    runtime._create_session = create_session

    async def cancel(task: asyncio.Task[AssistantTurnResult]) -> None:
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def exercise() -> None:
        first_turn: asyncio.Task[AssistantTurnResult] | None = None
        second_turn: asyncio.Task[AssistantTurnResult] | None = None
        try:
            assert (await runtime.start()).status == "ready"
            monitor = runtime._monitor_task
            assert monitor is not None
            monitor.cancel()
            with pytest.raises(asyncio.CancelledError):
                await monitor
            runtime._monitor_task = asyncio.create_task(asyncio.Event().wait())

            first_turn = asyncio.create_task(
                runtime.run_turn(
                    context=first_context,
                    prompt="Synthetic first owner",
                    emit=lambda _event: asyncio.sleep(0),
                )
            )
            await asyncio.wait_for(discovery_started.wait(), timeout=1.0)
            second_turn = asyncio.create_task(
                runtime.run_turn(
                    context=second_context,
                    prompt="Synthetic second owner",
                    emit=lambda _event: asyncio.sleep(0),
                )
            )

            if expected_stage in {"supervisor_status", "native_api_info"}:
                result = await asyncio.wait_for(second_turn, timeout=1.0)
                assert (result.status, result.error_code) == ("failed", "worker_unavailable")
                assert second_context.execution_id not in verified_executions
                assert second_context.execution_id not in session_executions
            elif scenario == "ready":
                await asyncio.wait_for(second_discovery_started.wait(), timeout=1.0)
                await asyncio.wait_for(session_started.wait(), timeout=1.0)
                assert not second_turn.done()
            else:
                await asyncio.wait_for(second_discovery_started.wait(), timeout=1.0)
                release_discovery.set()
                results = await asyncio.wait_for(
                    asyncio.gather(first_turn, second_turn), timeout=2.0
                )
                assert all(
                    (result.status, result.error_code) == ("failed", "worker_unavailable")
                    for result in results
                )
                assert session_executions == {
                    first_context.execution_id,
                    second_context.execution_id,
                }
        finally:
            release_discovery.set()
            if first_turn is not None:
                await cancel(first_turn)
            if second_turn is not None:
                await cancel(second_turn)
            await runtime.close()

    asyncio.run(exercise())

    assert "private response text" not in caplog.text
    assert "private native API timeout" not in caplog.text
    assert "private session timeout" not in caplog.text
    if expected_stage in {"supervisor_status", "native_api_info"}:
        assert (
            "Assistant worker startup failed "
            f"(startup_stage={expected_stage}, failure_code={expected_code})."
        ) in caplog.text
    elif expected_stage == "create_session":
        assert (
            f"Assistant pre-session failure (stage={expected_stage}, failure_code={expected_code})."
        ) in caplog.text
    else:
        assert "Assistant worker startup failed" not in caplog.text


def test_terminal_failure_snapshot_skips_after_the_turn_deadline() -> None:
    """The diagnostic read cannot extend an exhausted original turn budget."""

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
    )
    requests: list[str] = []

    async def unexpected_request(method: str, path: str, **kwargs: object) -> httpx.Response:
        del method, kwargs
        requests.append(path)
        raise AssertionError("deadline-expired diagnostic must not issue a request")

    runtime._request = unexpected_request

    async def exercise() -> dict[str, object]:
        try:
            return await runtime._read_native_terminal_failure_snapshot(
                "sesABCDEFGH",
                started=time.monotonic() - assistant_runtime._MAX_TURN_SECONDS - 0.01,
                approved_fetch_urls={},
            )
        finally:
            await runtime.close()

    summary = asyncio.run(exercise())

    assert summary["snapshot_status"] == "skipped_deadline"
    assert requests == []


def test_terminal_failure_snapshot_propagates_cancellation() -> None:
    """Shutdown cancellation interrupts the read instead of being swallowed as a diagnosis."""

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
    )
    request_started = asyncio.Event()

    async def blocked_request(method: str, path: str, **kwargs: object) -> httpx.Response:
        del method, path, kwargs
        request_started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    runtime._request = blocked_request

    async def exercise() -> None:
        try:
            task = asyncio.create_task(
                runtime._read_native_terminal_failure_snapshot(
                    "sesABCDEFGH", started=time.monotonic(), approved_fetch_urls={}
                )
            )
            await request_started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            await runtime.close()

    asyncio.run(exercise())


def test_attached_probe_unwraps_create_and_detail_conversation_contracts() -> None:
    """The attached driver follows the app's nested create and direct detail envelopes."""

    conversation_id = "01234567-89ab-cdef-0123-456789abcdef"
    row = {
        "id": conversation_id,
        "revision": 1,
        "delete_confirmation_phrase": "DELETE 89abcdef",
    }
    detail = {
        "conversation": row,
        "messages": {"items": []},
        "events": {"items": []},
        "turns": [],
        "actions": [],
    }

    created_detail, created_row = _attached_conversation_detail(
        {"conversation": detail}, created=True
    )
    fetched_detail, fetched_row = _attached_conversation_detail(detail)

    assert created_detail["conversation"] == row
    assert created_row == row
    assert fetched_detail["conversation"] == row
    assert fetched_row == row


def _attached_acceptance_receipt() -> dict[str, object]:
    owner = {
        "terminal_status": "completed",
        "model_id_matches": True,
        "nonempty_answer": True,
        "workspace_summary_receipt_count": 1,
        "workspace_summary_digest_matches": True,
        "selected_model_id_matches": True,
        "native_search_source_count": 0,
        "native_webfetch_source_count": 0,
        "native_webfetch_source_hosts": [],
        "native_webfetch_source_types": [],
        "webfetch_approved": False,
    }
    return {
        "turn_requests_issued_concurrently": True,
        "owners": [
            owner,
            {
                **owner,
                "native_search_source_count": 1,
                "native_webfetch_source_count": 1,
                "native_webfetch_source_hosts": ["www.iana.org"],
                "native_webfetch_source_types": ["native_webfetch_guarded"],
                "webfetch_approved": True,
            },
        ],
        "search_approved": True,
        "webfetch_approved": True,
        "webfetch_approval_count": 1,
        "active_search_scan_acknowledged": True,
        "conversation_delete_statuses": [200, 200],
        "cross_owner_conversation_status": 404,
        "forged_internal_mcp_status": 404,
        "assistant_worker_status_after_turns": "ready",
        "same_supervised_app_reachable": True,
    }


def test_attached_acceptance_failure_predicates_are_static_and_complete() -> None:
    assert _attached_acceptance_failures(_attached_acceptance_receipt()) == []

    receipt = _attached_acceptance_receipt()
    receipt["owners"] = [
        {**receipt["owners"][0], "webfetch_approved": True},
        receipt["owners"][1],
    ]
    assert _attached_acceptance_failures(receipt) == ["webfetch_approval_not_owner_bound"]

    receipt = _attached_acceptance_receipt()
    receipt["assistant_worker_status_after_turns"] = "starting"
    receipt["owners"] = [
        receipt["owners"][0],
        {**receipt["owners"][1], "workspace_summary_digest_matches": False},
    ]
    assert _attached_acceptance_failures(receipt) == [
        "owner1_workspace_summary_digest_mismatch",
        "worker_not_ready_after_turns",
    ]


def test_attached_owner_failure_evidence_contains_counts_but_no_content() -> None:
    digest = "a" * 64
    detail = {
        "turns": [{"id": "turn-1", "status": "failed", "model_id": "model-a"}],
        "messages": {
            "items": [{"turn_id": "turn-1", "role": "assistant", "text": "private answer"}]
        },
        "events": {
            "items": [
                {
                    "turn_id": "turn-1",
                    "type": "tool",
                    "data": {
                        "name": "workspace.summary",
                        "status": "completed",
                        "result_sha256": digest,
                        "result": "private tool data",
                    },
                },
                {"turn_id": "turn-1", "type": "source", "data": {"url": "private"}},
                {
                    "turn_id": "turn-1",
                    "type": "error",
                    "data": {
                        "code": "worker_unavailable",
                        "message": "safe user message must not be projected",
                    },
                },
                {
                    "turn_id": "other-turn",
                    "type": "error",
                    "data": {"code": "untrusted-private-value"},
                },
            ]
        },
    }
    evidence = _attached_owner_evidence(
        detail,
        owner_index=0,
        turn_id="turn-1",
        expected_model_id="model-a",
        expected_tool_digest=digest,
    )

    assert evidence["terminal_status"] == "failed"
    assert evidence["assistant_text_bytes"] == len("private answer")
    assert evidence["workspace_summary_digest_matches"] is True
    assert evidence["native_search_source_count"] == 1
    assert evidence["turn_error_code"] == "worker_unavailable"
    assert evidence["turn_failure_stage"] == "before_model_session_event"
    assert "private answer" not in repr(evidence)
    assert "private tool data" not in repr(evidence)
    assert "safe user message" not in repr(evidence)
    assert "untrusted-private-value" not in repr(evidence)


def test_attached_owner_evidence_fails_closed_on_unknown_error_code() -> None:
    evidence = _attached_owner_evidence(
        {
            "turns": [{"id": "turn-1", "status": "failed", "model_id": "model-a"}],
            "messages": {"items": []},
            "events": {
                "items": [
                    {
                        "turn_id": "turn-1",
                        "type": "error",
                        "data": {"code": "token=private-value", "message": "do not expose"},
                    }
                ]
            },
        },
        owner_index=0,
        turn_id="turn-1",
        expected_model_id="model-a",
        expected_tool_digest=None,
    )

    assert evidence["turn_error_code"] is None
    assert evidence["turn_failure_stage"] == "unknown_terminal"
    assert "private-value" not in repr(evidence)
    assert "do not expose" not in repr(evidence)


def test_attached_failure_timeline_is_closed_deduplicated_and_chronological() -> None:
    trackers = [_attached_new_interaction_tracker(index) for index in range(2)]
    trackers[0]["turn_started_monotonic"] = 100.0
    trackers[1]["turn_started_monotonic"] = 200.0
    search_preview = {
        "sequence": 1,
        "turn_id": "turn-1",
        "type": "private_context_preview",
        "data": {
            "preview_id": "01234567-89ab-cdef-0123-456789abcdef",
            "query": "secret search terms",
        },
    }
    fetch_preview = {
        "sequence": 2,
        "turn_id": "turn-1",
        "type": "webfetch_preview",
        "data": {
            "preview_id": "a" * 32,
            "url": "https://private.example/target",
        },
    }
    previews = [search_preview, fetch_preview]
    search_only = [search_preview]
    search_and_fetch_preview = [search_preview, fetch_preview]
    sources = [
        {
            "sequence": sequence,
            "turn_id": "turn-1",
            "type": "source",
            "data": {
                "source_type": "native_search_text_unverified",
                "url": "https://private.example/path?secret=value",
            },
        }
        for sequence in range(3, 11)
    ]
    sources.append(
        {
            "sequence": 11,
            "turn_id": "turn-1",
            "type": "source",
            "data": {"source_type": "native_webfetch_guarded", "url": "private"},
        }
    )
    _attached_observe_interaction_snapshot(
        trackers[1],
        turn_id="turn-1",
        event_rows=search_only,
        turn_rows=[{"id": "turn-1", "status": "running"}],
        now=201.0,
    )
    _attached_record_timeline_phase(
        trackers[1],
        "search_approval",
        now=201.25,
        dedupe_key="01234567-89ab-cdef-0123-456789abcdef",
    )
    _attached_observe_interaction_snapshot(
        trackers[1],
        turn_id="turn-1",
        event_rows=search_and_fetch_preview,
        turn_rows=[{"id": "turn-1", "status": "running"}],
        now=201.75,
    )
    _attached_record_timeline_phase(
        trackers[1],
        "search_approval",
        now=201.5,
        dedupe_key="01234567-89ab-cdef-0123-456789abcdef",
    )
    _attached_record_timeline_phase(trackers[1], "fetch_approval", now=202.0, dedupe_key="a" * 32)
    _attached_observe_interaction_snapshot(
        trackers[1],
        turn_id="turn-1",
        event_rows=previews + sources,
        turn_rows=[{"id": "turn-1", "status": "running"}],
        now=202.5,
    )
    _attached_observe_interaction_snapshot(
        trackers[1],
        turn_id="turn-1",
        event_rows=previews + sources,
        turn_rows=[{"id": "turn-1", "status": "timed_out"}],
        now=203.0,
    )
    diagnostic = _attached_interaction_diagnostic(trackers, now=204.0)
    assert diagnostic["status"] == "available"
    phases = diagnostic["owners"][1]["phases"]
    assert [row["phase"] for row in phases] == [
        "search_preview",
        "search_approval",
        "fetch_preview",
        "fetch_approval",
        "search_source",
        "fetch_source",
        "terminal",
    ]
    assert phases[1]["count"] == 1
    assert next(row for row in phases if row["phase"] == "search_source")["count"] == 8
    assert next(row for row in phases if row["phase"] == "fetch_source")["count"] == 1
    assert diagnostic["owners"][0]["turn_elapsed_ms"] == 104_000
    assert diagnostic["owners"][1]["terminal_status"] == "timed_out"
    assert diagnostic["owners"][1]["turn_elapsed_ms"] == 3_000
    assert diagnostic["worker_restart_evidence"] == "unavailable"
    assert "secret search terms" not in repr(diagnostic)
    assert "private.example" not in repr(diagnostic)
    assert "secret=value" not in repr(diagnostic)


@pytest.mark.parametrize(
    ("allow", "status"),
    [(True, "approved"), (False, "denied")],
)
def test_attached_search_confirmation_accepts_exact_preview_decision(
    allow: bool, status: str
) -> None:
    preview_id = "01234567-89ab-cdef-0123-456789abcdef"
    _attached_require_search_confirmation(
        {"preview_id": preview_id, "status": status}, preview_id, allow=allow
    )


@pytest.mark.parametrize(
    ("payload", "allow"),
    [
        (
            {"preview_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "status": "approved"},
            True,
        ),
        (
            {"preview_id": "01234567-89ab-cdef-0123-456789abcdef", "status": "denied"},
            True,
        ),
        (
            {"preview_id": "01234567-89ab-cdef-0123-456789abcdef", "status": "approved"},
            False,
        ),
        ({"status": "approved"}, True),
    ],
)
def test_attached_search_confirmation_rejects_unbound_or_wrong_decision(
    payload: dict[str, object], allow: bool
) -> None:
    preview_id = "01234567-89ab-cdef-0123-456789abcdef"
    with pytest.raises(_AttachedProbeFailure, match="search_confirmation_invalid"):
        _attached_require_search_confirmation(payload, preview_id, allow=allow)


@pytest.mark.parametrize(
    "bad_source,sequence",
    [
        ("unknown_source_type", 1),
        ("native_search_text_unverified", True),
        ("native_webfetch_guarded", 0),
    ],
)
def test_attached_failure_timeline_rejects_unclassified_or_malformed_events(
    bad_source: str, sequence: object
) -> None:
    tracker = _attached_new_interaction_tracker(1)
    tracker["turn_started_monotonic"] = 10.0
    with pytest.raises(_AttachedProbeFailure, match="interaction_timeline_invalid"):
        _attached_observe_interaction_snapshot(
            tracker,
            turn_id="turn-1",
            event_rows=[
                {
                    "sequence": sequence,
                    "turn_id": "turn-1",
                    "type": "source",
                    "data": {"source_type": bad_source},
                }
            ],
            turn_rows=[{"id": "turn-1", "status": "running"}],
            now=11.0,
        )


@pytest.mark.parametrize("now", [float("nan"), float("inf"), 180_011.0])
def test_attached_failure_timeline_rejects_invalid_elapsed_bounds(now: float) -> None:
    tracker = _attached_new_interaction_tracker(0)
    tracker["turn_started_monotonic"] = 0.0
    with pytest.raises(_AttachedProbeFailure, match="interaction_timeline_invalid"):
        _attached_record_timeline_phase(tracker, "search_preview", now=now)


@pytest.mark.parametrize(
    "payload",
    [
        {"conversation": {"id": "01234567-89ab-cdef-0123-456789abcdef"}},
        {
            "conversation": {
                "conversation": {
                    "id": "01234567-89ab-cdef-0123-456789abcdef",
                    "revision": 1,
                    "delete_confirmation_phrase": "DELETE 89abcdef",
                },
                "messages": [],
                "events": {"items": []},
                "turns": [],
                "actions": [],
            }
        },
    ],
)
def test_attached_probe_fails_closed_on_malformed_conversation_envelope(
    payload: dict[str, object],
) -> None:
    with pytest.raises(_AttachedProbeFailure, match="conversation_detail_invalid"):
        _attached_conversation_detail(payload, created=True)


def test_attached_worker_diagnostic_is_passive_and_closed() -> None:
    """Failure receipts retain only the app's fixed readiness projection."""

    paths: list[str] = []

    def request(_owner: int, method: str, path: str):
        assert method == "GET"
        paths.append(path)
        response = httpx.Response(200)
        payload = {
            "status": "ready",
            "schema_version": 13,
            "provider": "must-not-be-retained",
            "assistant": {"enabled": True, "status": "starting", "reason": "secret"},
        }
        return response, payload

    diagnostic = _attached_worker_diagnostic(request)

    assert paths == ["/api/v1/readiness"]
    assert diagnostic == {
        "readiness_http_status": 200,
        "readiness_status": "ready",
        "schema_version": 13,
        "assistant_enabled": True,
        "assistant_readiness": "starting",
    }


def test_public_https_request_allows_dns_inside_absolute_deadline(monkeypatch) -> None:
    """A slow resolver may use the request budget without weakening IP pinning."""

    class Writer:
        def write(self, _data: bytes) -> None:
            return

        async def drain(self) -> None:
            return

        def close(self) -> None:
            return

        async def wait_closed(self) -> None:
            return

    def delayed_resolver(host: str, port: int) -> list[object]:
        assert host == "provider.example"
        assert port == 443
        time.sleep(2.05)
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443))]

    connections: list[tuple[str, int, str | None]] = []

    async def exercise() -> object:
        reader = asyncio.StreamReader()
        reader.feed_data(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
        reader.feed_eof()

        async def open_connection(host: str, port: int, **kwargs: object) -> tuple[object, Writer]:
            connections.append((host, port, kwargs.get("server_hostname")))
            return reader, Writer()

        monkeypatch.setattr(assistant_net.asyncio, "open_connection", open_connection)
        return await assistant_net.request_public_https(
            "https://provider.example/v1/models",
            timeout_seconds=6.0,
            resolver=delayed_resolver,
        )

    response = asyncio.run(exercise())

    assert response.status_code == 200
    assert response.content == b"{}"
    assert connections == [("8.8.8.8", 443, "provider.example")]


def test_public_https_stream_dns_counts_against_absolute_deadline(monkeypatch) -> None:
    """Streaming DNS can exceed two seconds but still shares the request deadline."""

    async def exercise() -> None:
        loop = asyncio.get_running_loop()

        async def delayed_getaddrinfo(host: str, port: int, *, type: int) -> list[object]:
            assert host == "provider.example"
            assert port == 443
            assert type == socket.SOCK_STREAM
            await asyncio.sleep(2.05)
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443))]

        async def slow_connection(*_args: object, **_kwargs: object) -> tuple[object, object]:
            await asyncio.sleep(0.2)
            raise AssertionError("connection should remain inside the same absolute deadline")

        monkeypatch.setattr(loop, "getaddrinfo", delayed_getaddrinfo)
        monkeypatch.setattr(assistant_net.asyncio, "open_connection", slow_connection)
        with pytest.raises(assistant_net.PublicHTTPError, match="provider_deadline_exceeded"):
            async for _chunk in assistant_net.stream_public_https(
                "https://provider.example/v1/chat/completions",
                timeout_seconds=2.2,
            ):
                pass

    asyncio.run(exercise())


class _Catalog:
    def __init__(self, provider_id: str = "opencode-zen") -> None:
        self.provider_id = provider_id

    def get_model(self, model_id: str) -> object | None:
        if model_id != _TEST_MODEL_ID:
            return None
        return SimpleNamespace(
            available=True,
            provider_id=self.provider_id,
            # The catalog's base disclosure version can differ from an admin-approved
            # generation captured in the trusted execution context.
            policy_version="catalog-policy-v0",
        )


class _TestProviders:
    """Return a pinned native adapter descriptor without provider credentials."""

    def __init__(
        self,
        adapter_id: str = "openai-compatible-chat",
        native_provider_id: str = "assistant-proxy",
    ) -> None:
        self.adapter_id = adapter_id
        self.native_provider_id = native_provider_id
        self.descriptor_owners: list[int] = []
        self.policy_owners: list[int] = []

    def model_policy_state(self, _model_id: str, *, owner_id: int) -> dict[str, object]:
        self.policy_owners.append(owner_id)
        return {"usable": True}

    def native_execution_descriptor(self, _model_id: str, *, owner_id: int):
        self.descriptor_owners.append(owner_id)
        return resolve_native_adapter(self.adapter_id, self.native_provider_id)


class _NativeBody(httpx.AsyncByteStream):
    """Supply mock HTTP bytes through the streaming path used by the native API client."""

    def __init__(self, content: bytes) -> None:
        self.content = content

    async def __aiter__(self):
        if self.content:
            yield self.content

    async def aclose(self) -> None:
        return None


def _native_webfetch_redirect_messages(
    redirects: list[tuple[str, str]],
) -> dict[str, list[dict[str, object]]]:
    """Build flat pinned-V2 tool-error messages carrying exact redirect hints."""

    return {
        "data": [
            {
                "type": "assistant",
                "id": f"message-redirect-{index}",
                "finish": "tool-calls",
                "parts": [
                    {
                        "id": f"part-redirect-{index}",
                        "type": "tool",
                        "name": "webfetch",
                        "state": {
                            "status": "error",
                            "input": {"url": source},
                            "error": (
                                "Redirect blocked before contact. "
                                f"REDIRECT_APPROVAL_REQUIRED {target}"
                            ),
                        },
                    }
                ],
            }
            for index, (source, target) in enumerate(redirects)
        ]
    }


def _native_model_payload(
    directory: str,
    rows: list[dict[str, str]],
    *,
    project_directory: str | None = None,
    capability: str = "d" * 48,
    adapter_id: str = "openai-compatible-chat",
    native_provider_id: str = "assistant-proxy",
) -> dict[str, object]:
    """Build the pinned V2 model-list envelope for one requested location."""

    descriptor = resolve_native_adapter(adapter_id, native_provider_id)
    execution_id = directory.rsplit("/", 1)[-1]
    proxy_url = f"http://127.0.0.1:8000/api/v1/assistant/internal/provider/{execution_id}"
    model_rows = [
        {
            **row,
            "modelID": row.get("id", ""),
            "package": descriptor.package_id,
            "settings": {"baseURL": proxy_url, "timeout": 120_000},
            "capabilities": {"tools": True, "input": ["text"], "output": ["text"]},
            "headers": {"Authorization": f"Bearer {capability}"},
        }
        for row in rows
    ]
    return {
        "location": {
            "directory": directory,
            "project": {"directory": project_directory or directory},
        },
        "data": model_rows,
    }


def _native_integration_payload(directory: str) -> dict[str, object]:
    """Build the pinned V2 activation-barrier envelope for one location."""

    return {
        "location": {"directory": directory},
        "data": [],
    }


class _Supervisor:
    def __init__(
        self,
        *,
        purge_id: str | None = None,
        purge_result: object = True,
        webfetch_guard_ready: object = False,
    ) -> None:
        self.removed: list[str] = []
        self.prepared: list[dict[str, object]] = []
        self.purge_id = purge_id
        self.purge_result = purge_result
        self.purge_waits: list[tuple[str, float]] = []
        self.worker_holds: list[str] = []
        self.worker_releases: list[str] = []
        self.webfetch_guard_ready = webfetch_guard_ready
        self.reported_status = "ready"
        self.disabled_reasons: list[str] = []

    async def status(self):
        return {
            "status": self.reported_status,
            "api_url": "http://127.0.0.1:4097",
            "api_password": "s" * 48,
            "webfetch_guard_ready": self.webfetch_guard_ready,
            "observation_uncertain": False,
        }

    async def prepare_location(self, *, execution_id: str, **kwargs: object):
        self.prepared.append({"execution_id": execution_id, **kwargs})
        return {"directory": f"/run/assistant/worker-locations/{execution_id}"}

    async def remove_location(self, execution_id: str) -> str | None:
        self.removed.append(execution_id)
        return self.purge_id

    async def wait_for_home_purge(self, purge_id: str, *, timeout: float) -> object:
        self.purge_waits.append((purge_id, timeout))
        return self.purge_result

    async def request_home_purge(self) -> str:
        if self.purge_id is None:
            raise RuntimeError("test purge ID not configured")
        return self.purge_id

    async def disable(self, reason: str) -> None:
        self.disabled_reasons.append(reason)
        self.reported_status = "disabled"

    async def hold_worker(self, lease_id: str) -> None:
        self.worker_holds.append(lease_id)

    async def release_worker(self, lease_id: str) -> str | None:
        self.worker_releases.append(lease_id)
        return None


class _MutableHealthSupervisor(_Supervisor):
    """Allow startup probes to exercise bounded synthetic worker health changes."""

    def __init__(self) -> None:
        super().__init__()
        self.api_password = "s" * 48
        self.api_url = "http://127.0.0.1:4097"
        self.status_script: list[dict[str, object] | Exception] = []

    async def status(self) -> dict[str, object]:
        if self.status_script:
            next_status = self.status_script.pop(0)
            if isinstance(next_status, Exception):
                raise next_status
            return {
                "status": self.reported_status,
                "api_url": self.api_url,
                "api_password": self.api_password,
                "webfetch_guard_ready": self.webfetch_guard_ready,
                "observation_uncertain": False,
                **next_status,
            }
        return {
            "status": self.reported_status,
            "api_url": self.api_url,
            "api_password": self.api_password,
            "webfetch_guard_ready": self.webfetch_guard_ready,
            "observation_uncertain": False,
        }


def _context(execution_id: str = "a" * 32) -> AssistantTurnContext:
    return AssistantTurnContext(
        user_id=41,
        app_id="signal-ledger",
        conversation_id="b" * 36,
        turn_id="c" * 36,
        execution_id=execution_id,
        capability="d" * 48,
        model_id=_TEST_MODEL_ID,
        policy_version="fixture-policy-v1",
        context_version="e" * 64,
        page_context={"route": "/overview", "instrument": {"symbol": "ACME"}},
        history=({"role": "user", "text": "Earlier question"},),
    )


def test_runtime_latches_supervisor_disabled_without_starting_native_api() -> None:
    """An operator disable survives health polling and cannot restart the worker."""

    supervisor = _Supervisor()
    supervisor.reported_status = "disabled"
    factory_calls: list[object] = []
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
        http_client_factory=lambda **kwargs: factory_calls.append(kwargs),
    )

    async def exercise() -> None:
        status = await runtime.start()
        assert status.status == "disabled"
        assert runtime.operator_disabled is True
        assert runtime.status().status == "disabled"
        assert supervisor.disabled_reasons == ["operator"]
        assert factory_calls == []
        result = await runtime.run_turn(
            context=_context(), prompt="This must not reach the worker.", emit=lambda _event: None
        )
        assert result.status == "failed"
        assert result.error_code == "worker_unavailable"
        await runtime.close()

    asyncio.run(exercise())


def test_unverified_native_api_info_timeout_does_not_enable_transport() -> None:
    """A first health timeout cannot promote a client before its API identity is verified."""

    supervisor = _MutableHealthSupervisor()

    async def native_api(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("synthetic initial API info timeout")

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> None:
        status = await runtime.start()
        assert status.status == "unavailable"
        assert runtime._client is not None
        assert runtime._enabled is False
        assert runtime._transport_verified is False
        await runtime.close()

    asyncio.run(exercise())


def test_password_replacement_api_info_timeout_cannot_retain_old_transport() -> None:
    """A changed supervisor password invalidates the old client before a timed-out probe."""

    supervisor = _MutableHealthSupervisor()
    fail_api_info = False
    client_passwords: list[object] = []

    async def native_api(_request: httpx.Request) -> httpx.Response:
        if fail_api_info:
            raise httpx.ReadTimeout("synthetic replacement API info timeout")
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=_NativeBody(b'{"version":"v2"}'),
        )

    def client_factory(**kwargs: object) -> httpx.AsyncClient:
        client_passwords.append(kwargs.get("auth"))
        return httpx.AsyncClient(transport=httpx.MockTransport(native_api), **kwargs)

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
        http_client_factory=client_factory,
    )

    async def exercise() -> None:
        nonlocal fail_api_info
        assert (await runtime.start()).status == "ready"
        old_client = runtime._client
        assert old_client is not None and runtime._transport_verified is True
        supervisor.api_password = "t" * 48
        supervisor.status_script = [
            TimeoutError("synthetic transient status timeout"),
            {"status": "ready"},
        ]
        fail_api_info = True
        status = await runtime.start(preserve_ready=True)
        assert status.status == "unavailable"
        assert old_client.is_closed is True
        assert runtime._client is not old_client
        assert client_passwords == [("opencode", "s" * 48), ("opencode", "t" * 48)]
        assert runtime._enabled is False
        assert runtime._transport_verified is False
        await runtime.close()

    asyncio.run(exercise())


def test_same_generation_uncertainty_recovers_only_after_positive_observation() -> None:
    """A same-password timeout preserves transport, but readiness needs a later positive probe."""

    supervisor = _MutableHealthSupervisor()

    async def native_api(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=_NativeBody(b'{"version":"v2"}'),
        )

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> None:
        assert (await runtime.start()).status == "ready"
        original_client = runtime._client
        assert runtime._enabled is True and runtime._transport_verified is True
        supervisor.status_script = [
            {"status": "starting", "observation_uncertain": True},
            {"status": "ready", "observation_uncertain": False},
        ]

        status = await runtime.start(preserve_ready=True)

        assert status.status == "ready"
        assert runtime._client is original_client
        assert runtime._enabled is True and runtime._transport_verified is True
        await runtime.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("supervisor_error", ("asyncio_timeout", "client_timeout"))
def test_transient_supervisor_status_timeout_retries_before_reopening_admission(
    supervisor_error: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A status timeout closes admission but retains a verified transport for active work."""

    monkeypatch.setattr(assistant_runtime, "_STARTUP_STATUS_POLL_SECONDS", 0.001)
    supervisor = _MutableHealthSupervisor()

    async def native_api(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=_NativeBody(b'{"version":"v2"}'),
        )

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> None:
        assert (await runtime.start()).status == "ready"
        original_client = runtime._client
        assert original_client is not None
        assert runtime._transport_verified is True

        retry_started = asyncio.Event()
        release_retry = asyncio.Event()
        status_calls = 0
        timeout = (
            TimeoutError("synthetic supervisor status timeout")
            if supervisor_error == "asyncio_timeout"
            else SupervisorClientError("request_timeout")
        )
        original_status = supervisor.status

        async def timeout_then_gate_ready() -> dict[str, object]:
            nonlocal status_calls
            status_calls += 1
            if status_calls == 1:
                raise timeout
            retry_started.set()
            await release_retry.wait()
            return await original_status()

        supervisor.status = timeout_then_gate_ready
        start_task = asyncio.create_task(runtime.start(preserve_ready=True))
        await asyncio.wait_for(retry_started.wait(), timeout=1.0)

        assert runtime.status().status == "starting"
        assert runtime._client is original_client
        assert runtime._enabled is True
        assert runtime._transport_verified is True
        with pytest.raises(RuntimeError, match="worker_unavailable"):
            runtime._require_ready_worker()

        release_retry.set()
        status = await start_task
        assert status.status == "ready"
        assert status_calls == 2
        assert runtime._client is original_client
        assert runtime._enabled is True
        assert runtime._transport_verified is True
        await runtime.close()

    asyncio.run(exercise())


def test_repeated_status_timeouts_exhaust_one_clamped_startup_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Status attempts and retry sleeps stop at the existing absolute deadline."""

    class FakeClock:
        def __init__(self) -> None:
            self.now = 10.0

        def time(self) -> float:
            return self.now

    class AlwaysTimeoutSupervisor(_MutableHealthSupervisor):
        def __init__(self) -> None:
            super().__init__()
            self.status_calls = 0

        async def status(self) -> dict[str, object]:
            self.status_calls += 1
            raise TimeoutError("synthetic repeated status timeout")

    clock = FakeClock()
    supervisor = AlwaysTimeoutSupervisor()
    factory_calls: list[object] = []
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
        http_client_factory=lambda **kwargs: factory_calls.append(kwargs),
    )
    monkeypatch.setattr(assistant_runtime, "_STARTUP_STATUS_DEADLINE_SECONDS", 0.6875)
    monkeypatch.setattr(assistant_runtime, "_STARTUP_STATUS_REQUEST_TIMEOUT_SECONDS", 0.375)
    monkeypatch.setattr(assistant_runtime, "_STARTUP_STATUS_POLL_SECONDS", 0.375)

    real_get_running_loop = asyncio.get_running_loop
    real_sleep = asyncio.sleep
    real_wait_for = asyncio.wait_for
    request_timeouts: list[float] = []
    retry_sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        retry_sleeps.append(delay)
        clock.now += delay

    async def fake_wait_for(awaitable, *, timeout: float):
        request_timeouts.append(timeout)
        try:
            await awaitable
        except TimeoutError:
            clock.now += min(0.125, timeout)
            raise
        raise AssertionError("the synthetic supervisor should always time out")

    async def exercise() -> None:
        monkeypatch.setattr(assistant_runtime.asyncio, "get_running_loop", lambda: clock)
        monkeypatch.setattr(assistant_runtime.asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(assistant_runtime.asyncio, "wait_for", fake_wait_for)

        status = await runtime.start()
        assert status.status == "unavailable"
        assert supervisor.status_calls == 2
        assert request_timeouts == pytest.approx([0.375, 0.1875])
        assert retry_sleeps == pytest.approx([0.375, 0.0625])
        assert clock.now == pytest.approx(10.6875)
        assert runtime._client is None
        assert factory_calls == []

        monitor, runtime._monitor_task = runtime._monitor_task, None
        assert monitor is not None
        monitor.cancel()
        with pytest.raises(asyncio.CancelledError):
            await monitor
        monkeypatch.setattr(assistant_runtime.asyncio, "get_running_loop", real_get_running_loop)
        monkeypatch.setattr(assistant_runtime.asyncio, "sleep", real_sleep)
        monkeypatch.setattr(assistant_runtime.asyncio, "wait_for", real_wait_for)
        await runtime.close()

    asyncio.run(exercise())


def test_status_timeout_retry_does_not_retry_confirmed_disabled_worker() -> None:
    """A timeout may retry, but an explicit disabled status latches immediately."""

    supervisor = _MutableHealthSupervisor()
    supervisor.status_script = [TimeoutError("synthetic timeout"), {"status": "disabled"}]
    factory_calls: list[object] = []
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
        http_client_factory=lambda **kwargs: factory_calls.append(kwargs),
    )

    async def exercise() -> None:
        status = await runtime.start()
        assert status.status == "disabled"
        assert runtime.operator_disabled is True
        assert supervisor.status_script == []
        assert supervisor.disabled_reasons == ["operator"]
        assert factory_calls == []
        await runtime.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("failure", "expected_status"),
    (
        ("nonready", "unavailable"),
        ("disabled", "disabled"),
        ("bad_identity", "unavailable"),
        ("native_info_503", "unavailable"),
    ),
)
def test_confirmed_startup_failure_invalidates_verified_transport(
    failure: str,
    expected_status: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirmed lifecycle, identity, and native API failures revoke the prior transport latch."""

    supervisor = _MutableHealthSupervisor()
    native_info_503 = False

    async def native_api(_request: httpx.Request) -> httpx.Response:
        if native_info_503:
            return httpx.Response(
                503,
                headers={"content-type": "application/json"},
                stream=_NativeBody(b'{"error":"unavailable"}'),
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=_NativeBody(b'{"version":"v2"}'),
        )

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> None:
        nonlocal native_info_503
        monkeypatch.setattr(assistant_runtime, "_STARTUP_STATUS_DEADLINE_SECONDS", 0.025)
        monkeypatch.setattr(assistant_runtime, "_STARTUP_STATUS_POLL_SECONDS", 0.001)
        assert (await runtime.start()).status == "ready"
        assert runtime._enabled is True
        assert runtime._transport_verified is True
        if failure == "nonready":
            supervisor.reported_status = "starting"
            supervisor.status_script = [
                {"status": "starting"},
                TimeoutError("synthetic supervisor observation timeout"),
            ]
        elif failure == "disabled":
            supervisor.reported_status = "disabled"
        elif failure == "bad_identity":
            supervisor.api_url = "http://127.0.0.1:4098"
        else:
            native_info_503 = True
        status = await runtime.start(preserve_ready=True)
        assert status.status == expected_status
        assert runtime._enabled is False
        assert runtime._transport_verified is False
        await runtime.close()

    asyncio.run(exercise())


def test_runtime_kill_switch_cancels_active_turn_and_blocks_new_turns() -> None:
    """The fixed kill path interrupts in-flight work without stopping the app runtime."""

    supervisor = _Supervisor()
    runtime = _oauth_test_runtime(supervisor)
    context = _context()
    started = asyncio.Event()
    interrupted: list[str | None] = []
    impl_calls: list[str] = []

    async def blocked_impl(*, context, prompt, emit):
        del prompt, emit
        impl_calls.append(context.execution_id)
        started.set()
        await asyncio.Event().wait()

    async def interrupt(session_id: str | None) -> None:
        interrupted.append(session_id)

    runtime._run_turn_impl = blocked_impl
    runtime._interrupt = interrupt
    native_session = "ses_0123456789abABCDEFGHIJKLMN"
    runtime._active[context.execution_id] = native_session
    runtime._native_project_ids[context.execution_id] = "global"
    runtime._enabled = True
    runtime._status = AssistantRuntimeStatus("ready", None)

    async def exercise() -> None:
        async def emit(_event):
            return None

        task = asyncio.create_task(
            runtime.run_turn(context=context, prompt="wait for permission", emit=emit)
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        await runtime.kill_switch("operator")
        with pytest.raises(asyncio.CancelledError):
            await task
        assert runtime.operator_disabled is True
        assert runtime.status().status == "disabled"
        assert runtime._enabled is False
        assert runtime._turn_tasks == {}
        assert supervisor.disabled_reasons == ["operator"]
        assert interrupted == [native_session]
        assert context.execution_id not in runtime._active
        assert context.execution_id not in runtime._native_project_ids
        assert runtime.native_provider_metadata(context.execution_id) is None
        result = await runtime.run_turn(context=context, prompt="a later turn", emit=emit)
        assert result.status == "failed"
        assert result.error_code == "worker_unavailable"
        assert impl_calls == [context.execution_id]
        await runtime.close()

    asyncio.run(exercise())


def test_cancel_execution_clears_native_correlation_before_interrupt() -> None:
    """A cancellation immediately closes the metadata gate before native cleanup awaits."""

    runtime = _oauth_test_runtime(_Supervisor())
    context = _context()
    native_session = "ses_0123456789abABCDEFGHIJKLMN"
    runtime._active[context.execution_id] = native_session
    runtime._native_project_ids[context.execution_id] = "global"
    interrupted: list[str | None] = []

    async def interrupt(session_id: str | None) -> None:
        assert runtime.native_provider_metadata(context.execution_id) is None
        assert context.execution_id not in runtime._active
        assert context.execution_id not in runtime._native_project_ids
        interrupted.append(session_id)

    runtime._interrupt = interrupt

    async def exercise() -> None:
        await runtime.cancel_execution(context.execution_id)

    asyncio.run(exercise())
    assert interrupted == [native_session]


def test_cancelled_native_session_creation_does_not_retain_project_metadata() -> None:
    """Cancellation while native creation is pending cannot leave an identity mapping."""

    runtime = _oauth_test_runtime(_Supervisor())
    context = _context()
    request_started = asyncio.Event()

    async def blocked_request(*_args: object, **_kwargs: object) -> httpx.Response:
        request_started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    runtime._request = blocked_request

    async def exercise() -> None:
        task = asyncio.create_task(
            runtime._create_session(
                context,
                "/run/assistant/worker-locations/" + context.execution_id,
                {"providerID": "assistant-proxy", "modelID": "assistant-selected"},
            )
        )
        await asyncio.wait_for(request_started.wait(), timeout=1.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert runtime.native_provider_metadata(context.execution_id) is None
        assert context.execution_id not in runtime._active
        assert context.execution_id not in runtime._native_project_ids

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("guard_projection", "callback_available", "expected_effect"),
    (
        (True, True, "ask"),
        (True, False, "deny"),
        (False, True, "deny"),
        (1, True, "deny"),
    ),
)
def test_runtime_enables_native_webfetch_only_with_verified_guard_and_preview_callback(
    guard_projection: object, callback_available: bool, expected_effect: str
) -> None:
    """A guarded worker and exact browser preview callback are both required for fetch."""

    session_permissions: list[object] = []

    async def approve(_context: AssistantTurnContext, url: str, _emit: EventEmitter) -> str:
        return url

    async def native_api(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/info":
            payload = {"data": {"version": "2.0.7"}}
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_NativeBody(json.dumps(payload).encode("utf-8")),
            )
        if request.url.path == "/api/session":
            body = json.loads(await request.aread())
            session_permissions.append(body["permissions"])
            payload = {
                "data": {
                    "id": "ses_0123456789abABCDEFGHIJKLMN",
                    "projectID": "global",
                }
            }
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_NativeBody(json.dumps(payload).encode("utf-8")),
            )
        raise AssertionError("unexpected native API path")

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(webfetch_guard_ready=guard_projection),
        webfetch_approval=approve if callback_available else None,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> None:
        status = await runtime.start()
        assert status.status == "ready"
        context = _context()
        session_id = await runtime._create_session(
            context,
            "/run/assistant/worker-locations/" + "a" * 32,
            {"providerID": "assistant-proxy", "modelID": "assistant-selected"},
        )
        runtime._active[context.execution_id] = session_id
        assert runtime.native_provider_metadata(context.execution_id) == (
            "ses_0123456789abABCDEFGHIJKLMN",
            "global",
        )
        runtime._clear_native_provider_metadata(context.execution_id)
        assert runtime.native_provider_metadata(context.execution_id) is None
        assert context.execution_id not in runtime._native_project_ids
        await runtime.close()

    asyncio.run(exercise())
    permissions = session_permissions[0]
    fetch_rules = [rule for rule in permissions if rule["action"] == "webfetch"]
    assert fetch_rules == [{"action": "webfetch", "resource": "*", "effect": expected_effect}]


def _oauth_test_runtime(
    supervisor: _Supervisor,
) -> OpenCodeV2Runtime:
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
    )

    async def ready(*, preserve_ready: bool = False) -> AssistantRuntimeStatus:
        del preserve_ready
        runtime._status = AssistantRuntimeStatus("ready", None)
        runtime._enabled = True
        runtime._transport_verified = True
        return runtime._status

    runtime.start = ready
    runtime._status = AssistantRuntimeStatus("ready", None)
    runtime._enabled = True
    runtime._transport_verified = True
    return runtime


@pytest.mark.parametrize("operation", ("begin", "status", "complete", "callback", "handoff"))
def test_native_oauth_work_is_denied_when_runtime_readiness_is_uncertain(
    operation: str,
) -> None:
    """New OAuth work cannot reach the worker while shared readiness is uncertain."""

    if operation == "begin":

        class UncertainSupervisor(_Supervisor):
            async def status(self):
                raise TimeoutError("synthetic supervisor observation timeout")

        supervisor = UncertainSupervisor()
    else:
        supervisor = _Supervisor()
    runtime = _oauth_test_runtime(supervisor)
    attempt_id = "f" * 32
    handoff_ready = operation == "handoff"
    if operation != "begin":
        runtime._oauth_attempts[attempt_id] = assistant_runtime._NativeOAuthAttempt(
            attempt_id=attempt_id,
            native_attempt_id="con_fixture_attempt",
            integration_id="openai",
            method_id="chatgpt-browser",
            owner_id=41,
            session_id="e" * 32,
            expires_at=time.time() + 300,
            url="https://auth.openai.com/oauth/authorize?fixture=1",
            instructions="Complete sign-in in your browser.",
            mode="code" if operation == "complete" else "auto",
            status="handoff_ready" if handoff_ready else "pending",
        )
    runtime._status = AssistantRuntimeStatus("unavailable", "The assistant worker is unavailable.")
    if operation == "begin":
        runtime.start = OpenCodeV2Runtime.start.__get__(runtime, OpenCodeV2Runtime)
    requests: list[str] = []

    async def unexpected_request(method: str, path: str, **kwargs: object) -> httpx.Response:
        del method, kwargs
        requests.append(path)
        raise AssertionError("uncertain readiness must deny native OAuth work before transport")

    runtime._request = unexpected_request

    async def exercise() -> None:
        with pytest.raises(RuntimeError, match="worker_unavailable"):
            if operation == "begin":
                await runtime.begin_native_oauth(
                    "openai",
                    "chatgpt-browser",
                    attempt_id=attempt_id,
                    capability="b" * 32,
                    owner_id=41,
                    session_id="e" * 32,
                )
            elif operation == "status":
                await runtime.native_oauth_status(
                    "openai", attempt_id, owner_id=41, session_id="e" * 32
                )
            elif operation == "complete":
                await runtime.complete_native_oauth(
                    "openai",
                    attempt_id,
                    owner_id=41,
                    session_id="e" * 32,
                    code="fixture-code",
                )
            elif operation == "callback":
                await runtime.submit_native_oauth_callback(
                    "openai",
                    attempt_id,
                    owner_id=41,
                    session_id="e" * 32,
                    callback_url="http://localhost:1455/auth/callback?code=fixture&state=fixture",
                )
            else:
                await runtime.take_native_oauth_handoff(
                    "openai", attempt_id, owner_id=41, session_id="e" * 32
                )
        assert requests == []
        if operation == "begin":
            assert supervisor.worker_holds == []
            assert runtime._oauth_attempts == {}
        await runtime.close()

    asyncio.run(exercise())


def test_native_oauth_begin_and_one_time_handoff_are_bound_and_bounded() -> None:
    """Native OAuth secrets cross only the private in-process handoff boundary."""

    supervisor = _Supervisor()
    runtime = _oauth_test_runtime(supervisor)
    attempt_id = "f" * 32
    owner_id = 41
    session_id = "e" * 32
    native_attempt_id = "con_fixture_attempt"
    expires_at = int((time.time() + 300) * 1000)
    handoff_expiry = int((time.time() + 3600) * 1000)
    requests: list[tuple[str, str, object]] = []
    handoff_started = asyncio.Event()
    finish_handoff = asyncio.Event()

    async def native_request(method: str, path: str, **kwargs: object) -> httpx.Response:
        requests.append((method, path, kwargs.get("json")))
        if path == "/api/integration/openai/connect/oauth":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "attemptID": native_attempt_id,
                        "url": "https://auth.openai.com/oauth/authorize?fixture=1",
                        "instructions": "Complete sign-in in your browser.",
                        "mode": "auto",
                        "time": {"created": expires_at - 300_000, "expires": expires_at},
                    }
                },
            )
        if path.endswith("/complete-status"):
            return httpx.Response(200, json={"data": {"status": "complete"}})
        if path.endswith("/handoff"):
            handoff_started.set()
            await finish_handoff.wait()
            return httpx.Response(
                200,
                json={
                    "data": {
                        "type": "oauth",
                        "methodID": "chatgpt-browser",
                        "access": "fixture-access-value",
                        "refresh": "fixture-refresh-value",
                        "expires": handoff_expiry,
                        "metadata": {"accountID": "fixture-account"},
                    }
                },
            )
        raise AssertionError(f"unexpected private native request path {path}")

    runtime._request = native_request

    async def exercise() -> None:
        launch = await runtime.begin_native_oauth(
            "openai",
            "chatgpt-browser",
            attempt_id=attempt_id,
            capability="b" * 32,
            owner_id=owner_id,
            session_id=session_id,
        )
        assert launch == {
            "native_attempt_id": native_attempt_id,
            "url": "https://auth.openai.com/oauth/authorize?fixture=1",
            "instructions": "Complete sign-in in your browser.",
            "mode": "auto",
            "expires_at": pytest.approx(expires_at / 1000, abs=0.01),
        }
        assert "capability" not in launch
        assert supervisor.worker_holds == [attempt_id]
        assert requests[0] == (
            "POST",
            "/api/integration/openai/connect/oauth",
            {
                "methodID": "chatgpt-browser",
                "assistantOAuth": {"attemptID": attempt_id, "capability": "b" * 32},
            },
        )
        with pytest.raises(RuntimeError, match="native_oauth_attempt_unavailable"):
            await runtime.native_oauth_status(
                "openai", attempt_id, owner_id=owner_id, session_id="d" * 32
            )

        attempt = runtime._oauth_attempts[attempt_id]
        attempt.status = "handoff_ready"
        task = asyncio.create_task(
            runtime.take_native_oauth_handoff(
                "openai", attempt_id, owner_id=owner_id, session_id=session_id
            )
        )
        await handoff_started.wait()
        with pytest.raises(RuntimeError, match="native_oauth_handoff_not_ready"):
            await runtime.take_native_oauth_handoff(
                "openai", attempt_id, owner_id=owner_id, session_id=session_id
            )
        finish_handoff.set()
        credential = await task
        assert credential == {
            "type": "oauth",
            "methodID": "chatgpt-browser",
            "access": "fixture-access-value",
            "refresh": "fixture-refresh-value",
            "expires": handoff_expiry,
            "metadata": {"accountID": "fixture-account"},
        }
        assert attempt_id not in runtime._oauth_attempts
        assert supervisor.worker_releases == [attempt_id]
        await runtime.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("capability", (None, "", "g" * 32, "b" * 31, []))
def test_native_oauth_rejects_invalid_broker_capability_before_worker_hold(
    capability: object,
) -> None:
    """Only a manager-issued fixed-size opaque capability reaches native connect."""

    supervisor = _Supervisor()
    runtime = _oauth_test_runtime(supervisor)

    async def exercise() -> None:
        with pytest.raises(RuntimeError, match="native_oauth_capability_invalid"):
            await runtime.begin_native_oauth(
                "openai",
                "chatgpt-browser",
                attempt_id="f" * 32,
                capability=capability,  # type: ignore[arg-type]
                owner_id=41,
                session_id="e" * 32,
            )
        assert supervisor.worker_holds == []
        assert runtime._oauth_attempts == {}
        await runtime.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("attempt_id", "owner_id", "session_id"),
    (
        ([], 41, "e" * 32),
        ("f" * 32, True, "e" * 32),
        ("f" * 32, 41, "bad-session"),
    ),
)
def test_native_oauth_rejects_malformed_actor_before_lookup(
    attempt_id: object, owner_id: object, session_id: object
) -> None:
    """Malformed identities cannot trigger lookup, path formatting, or a supervisor hold."""

    supervisor = _Supervisor()
    runtime = _oauth_test_runtime(supervisor)

    async def exercise() -> None:
        with pytest.raises(RuntimeError, match="native_oauth_actor_invalid"):
            await runtime.native_oauth_status(
                "openai",
                attempt_id,  # type: ignore[arg-type]
                owner_id=owner_id,  # type: ignore[arg-type]
                session_id=session_id,  # type: ignore[arg-type]
            )
        assert supervisor.worker_holds == []
        await runtime.close()

    asyncio.run(exercise())


def test_native_oauth_browser_callback_is_relayed_only_to_fixed_native_route() -> None:
    """The app relays pasted callback data to native validation and never fetches its URL."""

    supervisor = _Supervisor()
    runtime = _oauth_test_runtime(supervisor)
    attempt_id = "f" * 32
    runtime._oauth_attempts[attempt_id] = assistant_runtime._NativeOAuthAttempt(
        attempt_id=attempt_id,
        native_attempt_id="con_fixture_attempt",
        integration_id="openai",
        method_id="chatgpt-browser",
        owner_id=41,
        session_id="e" * 32,
        expires_at=time.time() + 300,
        url="https://auth.openai.com/oauth/authorize?fixture=1",
        instructions="Complete sign-in in your browser.",
        mode="auto",
    )
    requests: list[tuple[str, str, object]] = []

    async def native_request(method: str, path: str, **kwargs: object) -> httpx.Response:
        requests.append((method, path, kwargs.get("json")))
        return httpx.Response(204)

    runtime._request = native_request

    async def exercise() -> None:
        callback_url = "http://localhost:1455/auth/callback?code=fixture&state=fixture"
        await runtime.submit_native_oauth_callback(
            "openai",
            attempt_id,
            owner_id=41,
            session_id="e" * 32,
            callback_url=callback_url,
        )
        assert requests == [
            (
                "POST",
                "/api/integration/openai/connect/oauth/con_fixture_attempt/callback",
                {"callbackURL": callback_url},
            )
        ]
        await runtime.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("provider_id", "adapter_id", "native_provider_id"),
    (
        ("opencode-zen", "openai-compatible-chat", "assistant-proxy"),
        ("openai-chatgpt", "openai-responses", "openai"),
    ),
)
def test_runtime_completes_native_terminal_turn_without_text_delta(
    provider_id: str, adapter_id: str, native_provider_id: str
) -> None:
    """Allow a terminal action-only result; durable usefulness is decided by the backend."""

    supervisor = _Supervisor()
    prompt_payloads: list[object] = []
    session_payloads: list[object] = []
    requests: list[tuple[str, str]] = []
    location = "/run/assistant/worker-locations/" + "a" * 32

    def response(
        status_code: int,
        *,
        payload: object | None = None,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        response_headers = dict(headers or {})
        if payload is not None:
            content = json.dumps(payload).encode("utf-8")
            response_headers.setdefault("content-type", "application/json")
        return httpx.Response(
            status_code,
            headers=response_headers,
            stream=_NativeBody(content),
        )

    async def native_api(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        requests.append((request.method, path))
        if path == "/api/info":
            return response(200, payload={"version": "v2"})
        if path == "/api/location":
            assert request.url.params.get("location[directory]") == location
            return response(
                200, payload={"directory": location, "project": {"directory": location}}
            )
        if path == "/api/model":
            assert request.url.params.get("location[directory]") == location
            return response(
                200,
                payload=_native_model_payload(
                    location,
                    [{"id": "assistant-selected", "providerID": native_provider_id}],
                    adapter_id=adapter_id,
                    native_provider_id=native_provider_id,
                ),
            )
        if path == "/api/mcp":
            return response(
                200,
                payload={
                    "data": [
                        {
                            "name": "signal-ledger",
                            "status": {"status": "connected"},
                        }
                    ]
                },
            )
        if path == "/api/websearch/provider":
            return response(200, payload={"data": []})
        if path == "/api/session":
            session_payloads.append(json.loads(request.content))
            return response(200, payload={"data": {"id": "sesABCDEFGH"}})
        if path == "/api/session/sesABCDEFGH/prompt":
            prompt_payloads.append(request.content)
            return response(204)
        if path == "/api/experimental/session/sesABCDEFGH/wait":
            return response(204)
        if path == "/api/session/sesABCDEFGH/message":
            return response(
                200,
                payload={
                    "data": [
                        {
                            "info": {
                                "id": "msg-1",
                                "type": "assistant",
                                "finish": "stop",
                                "content": [
                                    {
                                        "id": "part-1",
                                        "type": "tool",
                                        "name": "signal-ledger_workspace_summary",
                                        "state": {"status": "completed"},
                                    }
                                ],
                            },
                        }
                    ]
                },
            )
        if path == "/api/session/sesABCDEFGH/permission":
            return response(200, payload={"data": []})
        if path == "/api/session/sesABCDEFGH":
            if request.method == "DELETE":
                return response(204)
            return response(200, payload={"data": {"outcome": "succeeded"}})
        raise AssertionError(f"unexpected native API route {path}")

    def client_factory(**kwargs: object) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(native_api), **kwargs)

    providers = _TestProviders(adapter_id, native_provider_id)
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=providers,
        catalog=_Catalog(provider_id),
        supervisor=supervisor,
        http_client_factory=client_factory,
    )
    preparation_errors: list[str] = []
    original_prepare = runtime._prepare_location

    async def capture_prepare_error(context: AssistantTurnContext, descriptor=None) -> str:
        try:
            return await original_prepare(context, descriptor)
        except Exception as exc:
            preparation_errors.append(type(exc).__name__)
            raise

    runtime._prepare_location = capture_prepare_error
    events: list[object] = []

    async def emit(event):
        events.append(event)

    async def exercise():
        initial_status = await runtime.start()
        assert initial_status.status == "ready", (initial_status, requests)
        result = await runtime.run_turn(
            context=_context(), prompt="Show my workspace summary", emit=emit
        )
        await runtime.close()
        return result

    result = asyncio.run(exercise())

    assert result.status == "completed", (requests, preparation_errors)
    assert result.error_code is None
    assert providers.policy_owners == [41]
    assert providers.descriptor_owners == [41]
    assert supervisor.removed == ["a" * 32]
    assert supervisor.prepared[0]["provider_id"] == provider_id
    assert supervisor.prepared[0]["adapter_id"] == adapter_id
    assert supervisor.prepared[0]["native_provider_id"] == native_provider_id
    assistant_supervisor_client._validate_prepare_request(**supervisor.prepared[0])
    assert len(prompt_payloads) == 1
    assert len(session_payloads) == 1
    permissions = session_payloads[0]["permissions"]
    assert [row["action"] for row in permissions] == [
        "*",
        "signal-ledger_workspace_summary",
        "signal-ledger_workspace_instrument_lists",
        "signal-ledger_history_search",
        "signal-ledger_history_saved_forecast",
        "signal-ledger_history_outcomes",
        "signal-ledger_market_instrument_search",
        "signal-ledger_market_quote",
        "signal-ledger_market_bars",
        "signal-ledger_market_compare",
        "signal-ledger_market_news",
        "signal-ledger_assistant_propose_action",
        "websearch",
        "webfetch",
        "execute",
        "browser",
        "subagent",
        "question",
        "skill",
        "plugins",
    ]
    assert all(row["effect"] == "allow" for row in permissions[1:12])
    assert all(row["effect"] != "allow" for row in permissions[12:])
    assert b"Earlier question" in prompt_payloads[0]
    assert b"Show my workspace summary" in prompt_payloads[0]
    assert b"d" * 48 not in prompt_payloads[0]
    assert [event["type"] for event in events] == ["meta", "tool"]
    assert events[0]["data"]["policy_version"] == "fixture-policy-v1"
    assert events[1]["data"]["name"] == "signal-ledger_workspace_summary"
    assert events[1]["data"]["status"] == "completed"


@pytest.mark.parametrize(
    "identity",
    (
        {"info": {"id": "msg-1", "role": "assistant", "finish": "stop"}},
        {
            "info": {"id": "msg-1", "role": "assistant", "finish": "stop"},
            "parts": [{"id": "part-1", "state": {"sessionID": "sesFOREIGN"}}],
        },
        {
            "type": "assistant",
            "id": "msg-1",
            "finish": "stop",
            "content": [
                {
                    "type": "tool",
                    "name": "signal-ledger_workspace_summary",
                    "state": {"sessionID": "sesFOREIGN"},
                }
            ],
        },
    ),
)
def test_native_message_scope_accepts_absent_identity_but_rejects_nested_foreign_id(
    identity: object,
) -> None:
    """The session-specific route scopes absent IDs; every supplied nested ID must match."""

    assert _contains_foreign_session_id(identity, "sesABCDEFGH") is (
        "sessionID" in json.dumps(identity)
    )


def test_native_flat_content_text_snapshot_deduplicates_repeated_polling() -> None:
    """The pinned V2 flat `content` format emits each text delta only once across polls."""

    async def native_api(_request: httpx.Request) -> httpx.Response:
        payload = {
            "data": [
                {
                    "type": "assistant",
                    "id": "msg-1",
                    "finish": "stop",
                    "content": [{"type": "text", "id": "part-1", "text": "Hello native."}],
                }
            ]
        }
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=_NativeBody(json.dumps(payload).encode()),
        )

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )
    events: list[object] = []

    async def exercise() -> None:
        runtime._client = runtime._http_client_factory(
            base_url="http://127.0.0.1:4097",
            auth=("opencode", "s" * 48),
            timeout=httpx.Timeout(5.0),
            trust_env=False,
        )
        runtime._enabled = True

        async def emit(event):
            events.append(event)

        outcome: dict[str, object] = {"status": "completed", "tokens": 0}
        for _ in range(2):
            await runtime._consume_message_snapshot("sesABCDEFGH", _context(), emit, outcome)
        assert outcome["terminal_finish"] == "stop"
        await runtime.close()

    asyncio.run(exercise())
    assert events == [{"type": "token", "data": {"text": "Hello native."}}]


def test_completed_native_exa_result_emits_bounded_public_sources_once() -> None:
    """Only exact native Exa H2 records persist, never links embedded in result snippets."""

    native_content = "\n".join(
        [
            "## [Untrusted title is not retained](https://www.nasa.gov/mission/artemis-ii/?id=mission#timeline)",
            "Untrusted result summary includes [an embedded link](https://bad.example/snippet).",
            "",
            "## [Duplicate record](https://www.nasa.gov/mission/artemis-ii/?id=mission#timeline)",
            "Duplicate result snippet.",
            "",
            "## [Query-dependent document](https://ssd.jpl.nasa.gov/api/horizons.api?query=synthetic&target=earth)",
            "The query is part of the destination.",
            "",
            "## [Different query](https://ssd.jpl.nasa.gov/api/horizons.api?query=synthetic&target=mars)",
            "The second query must not collapse onto the first document.",
            "",
            "## [Balanced parentheses](https://www.nasa.gov/mission/flight/segment_(phase-2)?view=full#timeline)",
            "Destination parentheses must remain intact.",
            "",
            "## [Trailing punctuation](https://www.nasa.gov/a-destination-ending-in-period.)",
            "The final dot is part of this exact URL.",
            "",
            "## [Secret query](https://www.nasa.gov/search?access_token=synthetic)",
            "",
            "## [Overlong path](https://www.nasa.gov/" + ("x" * 2050) + ")",
            "",
            "## [Private address](https://127.0.0.1/internal)",
            "",
            "## [User information](https://user:password@private.example/path)",
            "",
            "## [Non-HTTPS](http://plain.example/not-https)",
            "",
            "## [Unbalanced destination](https://www.nasa.gov/path_(unclosed)",
            "",
            "Prefix ## [Ambiguous source](https://bad.example/prefixed)",
            "## [Ambiguous suffix](https://bad.example/suffixed) trailing text",
            "A snippet can mention https://www.nasa.gov/untrusted-snippet-link directly.",
            "A snippet can also contain a heading without a record boundary:",
            "## [Snippet heading](https://bad.example/snippet-heading)",
            "```markdown",
            "",
            "## [Fenced snippet heading](https://bad.example/fenced-heading)",
            "```",
            "",
            "## [Bounded source 0](https://source0.example/article)",
            *[
                line
                for index in range(1, 12)
                for line in (
                    "",
                    f"## [Bounded source {index}](https://source{index}.example/article)",
                )
            ],
        ]
    )
    payload = {
        "data": [
            {
                "type": "assistant",
                "id": "msg-search",
                "finish": "tool-calls",
                "content": [
                    {
                        "type": "tool",
                        "id": "part-search",
                        "name": "websearch",
                        "state": {
                            "status": "completed",
                            "input": {"query": "synthetic public schedule"},
                            "content": [{"type": "text", "text": native_content}],
                        },
                    }
                ],
            }
        ]
    }

    async def native_api(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=_NativeBody(json.dumps(payload).encode("utf-8")),
        )

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )
    events: list[object] = []

    async def exercise() -> None:
        runtime._client = runtime._http_client_factory(
            base_url="http://127.0.0.1:4097",
            auth=("opencode", "s" * 48),
            timeout=httpx.Timeout(5.0),
            trust_env=False,
        )
        runtime._enabled = True

        async def emit(event):
            events.append(event)

        outcome: dict[str, object] = {"status": "completed", "tokens": 0}
        for _ in range(2):
            await runtime._consume_message_snapshot("sesABCDEFGH", _context(), emit, outcome)
        await runtime.close()

    asyncio.run(exercise())

    sources = [event["data"] for event in events if event["type"] == "source"]
    assert len(sources) == 8
    assert sources[0] == {
        "title": "Unverified link from native Exa search text at www.nasa.gov",
        "url": "https://www.nasa.gov/mission/artemis-ii/?id=mission#timeline",
        "source_type": "native_search_text_unverified",
    }
    assert sources[1]["url"] == (
        "https://ssd.jpl.nasa.gov/api/horizons.api?query=synthetic&target=earth"
    )
    assert sources[2]["url"] == (
        "https://ssd.jpl.nasa.gov/api/horizons.api?query=synthetic&target=mars"
    )
    assert sources[3]["url"] == (
        "https://www.nasa.gov/mission/flight/segment_(phase-2)?view=full#timeline"
    )
    assert sources[4]["url"] == "https://www.nasa.gov/a-destination-ending-in-period."
    assert all(source["source_type"] == "native_search_text_unverified" for source in sources)
    assert all(
        source["title"]
        == "Unverified link from native Exa search text at " + source["url"].split("/")[2]
        for source in sources
    )
    assert all("untrusted-snippet-link" not in source["url"] for source in sources)
    assert len({source["url"] for source in sources}) == 8
    assert [event["type"] for event in events].count("tool") == 1
    tool_event = next(event for event in events if event["type"] == "tool")
    assert tool_event["data"]["description"] == "Searching public sources."
    assert (
        _native_search_text_links(
            [{"type": "text", "text": "x" * 65_537 + " https://www.nasa.gov/"}]
        )
        == ()
    )
    punctuated = _native_search_text_links(
        [
            {
                "type": "text",
                "text": "## [Exact punctuation](https://www.nasa.gov/a-destination-ending-in-period.)",
            }
        ]
    )
    assert punctuated[0]["url"] == "https://www.nasa.gov/a-destination-ending-in-period."
    assert (
        _native_search_text_links(
            [{"type": "text", "text": "## [Snippet](https://bad.example/embedded) trailing"}]
        )
        == ()
    )
    assert (
        _native_search_text_links(
            [
                {
                    "type": "text",
                    "text": "Body text:\n## [Snippet heading](https://bad.example/body-heading)",
                }
            ]
        )
        == ()
    )
    assert (
        _native_search_text_links(
            [
                {
                    "type": "text",
                    "text": "```markdown\n\n## [Fenced](https://bad.example/fenced)\n```",
                }
            ]
        )
        == ()
    )


@pytest.mark.parametrize(
    ("final_url", "expected_status", "expected_source_count"),
    (
        (
            "https://example.test/start?view=public",
            "completed",
            1,
        ),
        (None, "failed", 0),
        ("https://127.0.0.1/private", "failed", 0),
        ("https://example.test/other?view=public", "failed", 0),
        ("https://example.test/start?view=other", "failed", 0),
        ("https://redirect.example.test/start?view=public", "failed", 0),
    ),
)
def test_native_webfetch_citation_uses_only_approved_guarded_result_metadata(
    final_url: str | None, expected_status: str, expected_source_count: int
) -> None:
    """Cite only an exact approved request URL and consume its approval once on completion."""

    requested_url = "https://example.test/start?view=public"
    page_marker = "synthetic-private-page-content-marker"
    state: dict[str, object] = {
        "status": "completed",
        "input": {"url": requested_url, "format": "markdown"},
        "content": [{"type": "text", "text": page_marker}],
        "metadata": {"contentType": "text/markdown"},
    }
    if final_url is not None:
        state["metadata"] = {"contentType": "text/markdown", "finalUrl": final_url}
    payload = {
        "data": [
            {
                "type": "assistant",
                "id": "msg-fetch",
                "finish": "stop",
                "content": [
                    {
                        "type": "tool",
                        "id": "part-fetch",
                        "name": "webfetch",
                        "state": state,
                    }
                ],
            }
        ]
    }

    async def native_api(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=_NativeBody(json.dumps(payload).encode("utf-8")),
        )

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )
    events: list[object] = []

    async def exercise() -> dict[str, object]:
        runtime._client = runtime._http_client_factory(
            base_url="http://127.0.0.1:4097",
            auth=("opencode", "s" * 48),
            timeout=httpx.Timeout(5.0),
            trust_env=False,
        )
        runtime._enabled = True

        async def emit(event):
            events.append(event)

        outcome: dict[str, object] = {
            "status": "completed",
            "tokens": 0,
            "approved_fetch_urls": {requested_url: 1},
        }
        await runtime._consume_message_snapshot("sesABCDEFGH", _context(), emit, outcome)
        await runtime._consume_message_snapshot("sesABCDEFGH", _context(), emit, outcome)
        await runtime.close()
        return outcome

    outcome = asyncio.run(exercise())

    assert outcome["status"] == expected_status
    sources = [event["data"] for event in events if event["type"] == "source"]
    assert len(sources) == expected_source_count
    assert page_marker not in repr(events)
    tool_event = next(event for event in events if event["type"] == "tool")
    assert tool_event["data"]["description"] == "Fetching an approved public URL."
    assert outcome["approved_fetch_urls"] == {}
    if expected_source_count:
        assert sources == [
            {
                "title": "Fetched public page at example.test",
                "url": final_url,
                "source_type": "native_webfetch_guarded",
            }
        ]


def test_native_webfetch_redirect_error_can_retry_only_after_fresh_exact_preview() -> None:
    """A redirect error consumes its source approval; the hinted URL needs its own preview."""

    source_url = "https://example.test/start?view=public"
    target_url = "https://redirect.example.test/article?view=public"
    stopped = asyncio.Event()
    permission_replied: list[dict[str, object]] = []
    approved_destinations: list[str] = []
    emitted: list[dict[str, object]] = []
    current_payload: dict[str, object] = {
        "data": [
            {
                "type": "assistant",
                "id": "message-redirect-error",
                "finish": "tool-calls",
                "parts": [
                    {
                        "id": "part-redirect-error",
                        "type": "tool",
                        "name": "webfetch",
                        "state": {
                            "status": "error",
                            "input": {"url": source_url},
                            "error": (
                                "Redirect blocked before contact. REDIRECT_APPROVAL_REQUIRED "
                                f"{target_url}"
                            ),
                        },
                    }
                ],
            }
        ]
    }

    async def native_api(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/session/sesABCDEFGH/message":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_NativeBody(json.dumps(current_payload).encode("utf-8")),
            )
        if request.url.path == "/api/session/sesABCDEFGH/permission":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_NativeBody(
                    json.dumps(
                        {
                            "data": [
                                {
                                    "id": "per12345",
                                    "sessionID": "sesABCDEFGH",
                                    "action": "webfetch",
                                    "resources": [target_url],
                                }
                            ]
                        }
                    ).encode("utf-8")
                ),
            )
        if request.url.path == "/api/session/sesABCDEFGH/permission/per12345/reply":
            permission_replied.append(json.loads(request.content))
            stopped.set()
            return httpx.Response(204, stream=_NativeBody(b""))
        raise AssertionError(f"unexpected native API route {request.url.path}")

    async def approve_exact_target(
        _context: AssistantTurnContext, destination: str, _emit: EventEmitter
    ) -> str | None:
        approved_destinations.append(destination)
        return destination

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
        webfetch_approval=approve_exact_target,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> dict[str, object]:
        nonlocal current_payload
        runtime._client = runtime._http_client_factory(
            base_url="http://127.0.0.1:4097",
            auth=("opencode", "s" * 48),
            timeout=httpx.Timeout(5.0),
            trust_env=False,
        )
        runtime._enabled = True

        async def emit(event):
            emitted.append(event)

        outcome: dict[str, object] = {
            "status": "completed",
            "tokens": 0,
            "approved_fetch_urls": {source_url: 1},
            "processed_fetch_parts": set(),
        }
        await runtime._consume_message_snapshot("sesABCDEFGH", _context(), emit, outcome)
        assert outcome["approved_fetch_urls"] == {}
        assert outcome["status"] == "completed"

        await runtime._poll_permissions(
            "sesABCDEFGH",
            _context(),
            emit,
            stopped,
            outcome,
            time.monotonic(),
        )
        assert approved_destinations == [target_url]
        assert permission_replied == [{"decision": "once"}]
        assert outcome["approved_fetch_urls"] == {target_url: 1}

        current_payload = {
            "data": [
                {
                    "type": "assistant",
                    "id": "message-redirect-retry",
                    "finish": "stop",
                    "parts": [
                        {
                            "id": "part-redirect-retry",
                            "type": "tool",
                            "name": "webfetch",
                            "state": {
                                "status": "completed",
                                "input": {"url": target_url},
                                "content": [
                                    {"type": "text", "text": "approved redirected document"}
                                ],
                                "metadata": {
                                    "contentType": "text/markdown",
                                    "finalUrl": target_url,
                                },
                            },
                        }
                    ],
                }
            ]
        }
        await runtime._consume_message_snapshot("sesABCDEFGH", _context(), emit, outcome)
        await runtime.close()
        return outcome

    outcome = asyncio.run(exercise())
    sources = [event["data"] for event in emitted if event["type"] == "source"]
    assert sources == [
        {
            "title": "Fetched public page at redirect.example.test",
            "url": target_url,
            "source_type": "native_webfetch_guarded",
        }
    ]
    assert outcome["approved_fetch_urls"] == {}
    assert outcome["status"] == "completed"


def test_native_webfetch_error_consumes_approval_and_blocks_same_part_replay() -> None:
    """An errored approved call cannot later reuse its approval under the same part identity."""

    url = "https://example.test/report?view=public"
    payload: dict[str, object] = {
        "data": [
            {
                "type": "assistant",
                "id": "message-replayed-fetch",
                "finish": "tool-calls",
                "parts": [
                    {
                        "id": "part-replayed-fetch",
                        "type": "tool",
                        "name": "webfetch",
                        "state": {
                            "status": "error",
                            "input": {"url": url},
                            "error": "synthetic safe redirect hint",
                        },
                    }
                ],
            }
        ]
    }

    async def native_api(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=_NativeBody(json.dumps(payload).encode("utf-8")),
        )

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )
    emitted: list[object] = []

    async def exercise() -> dict[str, object]:
        nonlocal payload
        runtime._client = runtime._http_client_factory(
            base_url="http://127.0.0.1:4097",
            auth=("opencode", "s" * 48),
            timeout=httpx.Timeout(5.0),
            trust_env=False,
        )
        runtime._enabled = True

        async def emit(event):
            emitted.append(event)

        outcome: dict[str, object] = {
            "status": "completed",
            "tokens": 0,
            "approved_fetch_urls": {url: 1},
            "processed_fetch_parts": set(),
        }
        await runtime._consume_message_snapshot("sesABCDEFGH", _context(), emit, outcome)
        assert outcome["approved_fetch_urls"] == {}

        payload = {
            "data": [
                {
                    "type": "assistant",
                    "id": "message-replayed-fetch",
                    "finish": "stop",
                    "parts": [
                        {
                            "id": "part-replayed-fetch",
                            "type": "tool",
                            "name": "webfetch",
                            "state": {
                                "status": "completed",
                                "input": {"url": url},
                                "metadata": {"finalUrl": url},
                            },
                        }
                    ],
                }
            ]
        }
        await runtime._consume_message_snapshot("sesABCDEFGH", _context(), emit, outcome)
        await runtime.close()
        return outcome

    outcome = asyncio.run(exercise())
    assert not [event for event in emitted if event["type"] == "source"]
    assert outcome["approved_fetch_urls"] == {}
    assert outcome["fetch_source_parts"] == set()


def test_native_webfetch_fresh_redirect_retries_keep_the_five_hop_cap() -> None:
    """Fresh exact previews cannot reset the original five-hop redirect bound."""

    stopped = asyncio.Event()
    approvals: list[str] = []
    replies: list[dict[str, object]] = []
    current_payload: dict[str, object] = {"data": []}

    async def approve_destination(
        _context: AssistantTurnContext, destination: str, _emit: EventEmitter
    ) -> str | None:
        approvals.append(destination)
        return destination

    async def native_api(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/session/sesABCDEFGH/message":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_NativeBody(json.dumps(current_payload).encode("utf-8")),
            )
        if request.url.path == "/api/session/sesABCDEFGH/permission":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_NativeBody(
                    json.dumps(
                        {
                            "data": [
                                {
                                    "id": "per12345",
                                    "sessionID": "sesABCDEFGH",
                                    "action": "webfetch",
                                    "resources": ["https://chain.example/hop6"],
                                }
                            ]
                        }
                    ).encode("utf-8")
                ),
            )
        if request.url.path == "/api/session/sesABCDEFGH/permission/per12345/reply":
            replies.append(json.loads(request.content))
            stopped.set()
            return httpx.Response(204, stream=_NativeBody(b""))
        raise AssertionError(f"unexpected native API route {request.url.path}")

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
        webfetch_approval=approve_destination,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> dict[str, object]:
        nonlocal current_payload
        runtime._client = runtime._http_client_factory(
            base_url="http://127.0.0.1:4097",
            auth=("opencode", "s" * 48),
            timeout=httpx.Timeout(5.0),
            trust_env=False,
        )
        runtime._enabled = True
        outcome: dict[str, object] = {
            "status": "completed",
            "tokens": 0,
            "approved_fetch_urls": {},
            "processed_fetch_parts": set(),
        }

        async def emit(_event):
            return None

        requested_url = "https://chain.example/hop0"
        for index in range(6):
            target_url = f"https://chain.example/hop{index + 1}"
            outcome["approved_fetch_urls"] = {requested_url: 1}
            current_payload = {
                "data": [
                    {
                        "type": "assistant",
                        "id": f"message-hop-{index}",
                        "finish": "tool-calls",
                        "parts": [
                            {
                                "id": f"part-hop-{index}",
                                "type": "tool",
                                "name": "webfetch",
                                "state": {
                                    "status": "error",
                                    "input": {"url": requested_url},
                                    "error": (
                                        "Redirect blocked before contact. "
                                        "REDIRECT_APPROVAL_REQUIRED "
                                        f"{target_url}"
                                    ),
                                },
                            }
                        ],
                    }
                ]
            }
            await runtime._consume_message_snapshot("sesABCDEFGH", _context(), emit, outcome)
            requested_url = target_url

        assert outcome["webfetch_redirect_targets"] == {
            f"https://chain.example/hop{index}" for index in range(1, 6)
        }
        assert outcome["webfetch_blocked_redirect_urls"] == {"https://chain.example/hop6"}
        await runtime._poll_permissions(
            "sesABCDEFGH",
            _context(),
            emit,
            stopped,
            outcome,
            time.monotonic(),
        )
        await runtime.close()
        return outcome

    outcome = asyncio.run(exercise())
    assert approvals == []
    assert replies == [{"decision": "reject"}]
    assert outcome["approved_fetch_urls"] == {}


def test_native_webfetch_loop_across_fresh_calls_is_rejected_before_preview() -> None:
    """A later hop back to any requested URL is rejected without another browser preview."""

    source_url = "https://loop.example/start"
    target_url = "https://loop.example/next"
    current_payload: dict[str, object] = {"data": []}
    stopped = asyncio.Event()
    approvals: list[str] = []
    replies: list[dict[str, object]] = []

    async def approve_destination(
        _context: AssistantTurnContext, destination: str, _emit: EventEmitter
    ) -> str | None:
        approvals.append(destination)
        return destination

    async def native_api(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/session/sesABCDEFGH/message":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_NativeBody(json.dumps(current_payload).encode("utf-8")),
            )
        if request.url.path == "/api/session/sesABCDEFGH/permission":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_NativeBody(
                    json.dumps(
                        {
                            "data": [
                                {
                                    "id": "per12345",
                                    "sessionID": "sesABCDEFGH",
                                    "action": "webfetch",
                                    "resources": [source_url],
                                }
                            ]
                        }
                    ).encode("utf-8")
                ),
            )
        if request.url.path == "/api/session/sesABCDEFGH/permission/per12345/reply":
            replies.append(json.loads(request.content))
            stopped.set()
            return httpx.Response(204, stream=_NativeBody(b""))
        raise AssertionError(f"unexpected native API route {request.url.path}")

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
        webfetch_approval=approve_destination,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> dict[str, object]:
        nonlocal current_payload
        runtime._client = runtime._http_client_factory(
            base_url="http://127.0.0.1:4097",
            auth=("opencode", "s" * 48),
            timeout=httpx.Timeout(5.0),
            trust_env=False,
        )
        runtime._enabled = True
        outcome: dict[str, object] = {
            "status": "completed",
            "tokens": 0,
            "approved_fetch_urls": {source_url: 1},
            "processed_fetch_parts": set(),
        }

        async def emit(_event):
            return None

        for index, (requested, redirected) in enumerate(
            ((source_url, target_url), (target_url, source_url))
        ):
            if index:
                outcome["approved_fetch_urls"] = {requested: 1}
            current_payload = {
                "data": [
                    {
                        "type": "assistant",
                        "id": f"message-loop-{index}",
                        "finish": "tool-calls",
                        "parts": [
                            {
                                "id": f"part-loop-{index}",
                                "type": "tool",
                                "name": "webfetch",
                                "state": {
                                    "status": "error",
                                    "input": {"url": requested},
                                    "error": (
                                        "Redirect blocked before contact. "
                                        "REDIRECT_APPROVAL_REQUIRED "
                                        f"{redirected}"
                                    ),
                                },
                            }
                        ],
                    }
                ]
            }
            await runtime._consume_message_snapshot("sesABCDEFGH", _context(), emit, outcome)

        assert outcome["webfetch_blocked_redirect_urls"] == {source_url}
        await runtime._poll_permissions(
            "sesABCDEFGH",
            _context(),
            emit,
            stopped,
            outcome,
            time.monotonic(),
        )
        await runtime.close()
        return outcome

    outcome = asyncio.run(exercise())
    assert approvals == []
    assert replies == [{"decision": "reject"}]
    assert outcome["approved_fetch_urls"] == {}


def test_native_webfetch_waits_for_yielding_snapshot_before_redirect_approval() -> None:
    """A permission cannot outrun a message snapshot paused inside event delivery."""

    requested_urls = [f"https://chain.example/hop{index}" for index in range(7)]
    current_payload = _native_webfetch_redirect_messages(
        list(zip(requested_urls, requested_urls[1:], strict=False))
    )
    stopped = asyncio.Event()
    emit_started = asyncio.Event()
    release_emit = asyncio.Event()
    permission_read = asyncio.Event()
    approval_started = asyncio.Event()
    replies: list[dict[str, object]] = []

    class _ObservedLock(asyncio.Lock):
        def __init__(self) -> None:
            super().__init__()
            self.second_acquire_waiting = asyncio.Event()
            self.acquire_count = 0

        async def acquire(self) -> bool:
            self.acquire_count += 1
            if self.acquire_count == 2:
                self.second_acquire_waiting.set()
            return await super().acquire()

    state_lock = _ObservedLock()

    async def native_api(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/session/sesABCDEFGH/message":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_NativeBody(json.dumps(current_payload).encode("utf-8")),
            )
        if request.url.path == "/api/session/sesABCDEFGH/permission":
            permission_read.set()
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_NativeBody(
                    json.dumps(
                        {
                            "data": [
                                {
                                    "id": "per12345",
                                    "sessionID": "sesABCDEFGH",
                                    "action": "webfetch",
                                    "resources": [requested_urls[-1]],
                                }
                            ]
                        }
                    ).encode("utf-8")
                ),
            )
        if request.url.path == "/api/session/sesABCDEFGH/permission/per12345/reply":
            replies.append(json.loads(request.content))
            stopped.set()
            return httpx.Response(204, stream=_NativeBody(b""))
        raise AssertionError(f"unexpected native API route {request.url.path}")

    async def approve_destination(
        _context: AssistantTurnContext, _destination: str, _emit: EventEmitter
    ) -> str:
        approval_started.set()
        return requested_urls[-1]

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
        webfetch_approval=approve_destination,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> dict[str, object]:
        runtime._client = runtime._http_client_factory(
            base_url="http://127.0.0.1:4097",
            auth=("opencode", "s" * 48),
            timeout=httpx.Timeout(5.0),
            trust_env=False,
        )
        runtime._enabled = True
        outcome: dict[str, object] = {
            "approved_fetch_urls": {},
            "webfetch_state_lock": state_lock,
        }

        async def emit(event: dict[str, object]) -> None:
            if event.get("type") == "tool" and not emit_started.is_set():
                emit_started.set()
                await release_emit.wait()

        snapshot_task = asyncio.create_task(
            runtime._consume_message_snapshot("sesABCDEFGH", _context(), emit, outcome)
        )
        permission_task: asyncio.Task[None] | None = None
        try:
            await asyncio.wait_for(emit_started.wait(), timeout=1.0)
            permission_task = asyncio.create_task(
                runtime._poll_permissions(
                    "sesABCDEFGH",
                    _context(),
                    emit,
                    stopped,
                    outcome,
                    time.monotonic(),
                )
            )
            await asyncio.wait_for(permission_read.wait(), timeout=1.0)
            await asyncio.wait_for(state_lock.second_acquire_waiting.wait(), timeout=1.0)
            assert not approval_started.is_set()
            release_emit.set()
            await snapshot_task
            await permission_task
        finally:
            release_emit.set()
            for task in (snapshot_task, permission_task):
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            await runtime.close()
        return outcome

    outcome = asyncio.run(exercise())
    assert outcome["webfetch_blocked_redirect_urls"] == {requested_urls[-1]}
    assert not approval_started.is_set()
    assert replies == [{"decision": "reject"}]
    assert outcome["approved_fetch_urls"] == {}


@pytest.mark.parametrize(
    ("initial_redirects", "completed_redirects", "candidate"),
    (
        (
            [
                (f"https://chain.example/hop{index}", f"https://chain.example/hop{index + 1}")
                for index in range(5)
            ],
            [
                (f"https://chain.example/hop{index}", f"https://chain.example/hop{index + 1}")
                for index in range(6)
            ],
            "https://chain.example/hop6",
        ),
        (
            [("https://loop.example/start", "https://loop.example/next")],
            [
                ("https://loop.example/start", "https://loop.example/next"),
                ("https://loop.example/next", "https://loop.example/start"),
            ],
            "https://loop.example/start",
        ),
    ),
)
def test_native_webfetch_rechecks_redirect_policy_after_approval_yields(
    initial_redirects: list[tuple[str, str]],
    completed_redirects: list[tuple[str, str]],
    candidate: str,
) -> None:
    """A fresh redirect result during user review overrides an in-flight once choice."""

    current_payload = _native_webfetch_redirect_messages(initial_redirects)
    stopped = asyncio.Event()
    approval_started = asyncio.Event()
    release_approval = asyncio.Event()
    replies: list[dict[str, object]] = []
    approvals: list[str] = []

    async def native_api(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/session/sesABCDEFGH/message":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_NativeBody(json.dumps(current_payload).encode("utf-8")),
            )
        if request.url.path == "/api/session/sesABCDEFGH/permission":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_NativeBody(
                    json.dumps(
                        {
                            "data": [
                                {
                                    "id": "per12345",
                                    "sessionID": "sesABCDEFGH",
                                    "action": "webfetch",
                                    "resources": [candidate],
                                }
                            ]
                        }
                    ).encode("utf-8")
                ),
            )
        if request.url.path == "/api/session/sesABCDEFGH/permission/per12345/reply":
            replies.append(json.loads(request.content))
            stopped.set()
            return httpx.Response(204, stream=_NativeBody(b""))
        raise AssertionError(f"unexpected native API route {request.url.path}")

    async def approve_destination(
        _context: AssistantTurnContext, destination: str, _emit: EventEmitter
    ) -> str:
        approvals.append(destination)
        approval_started.set()
        await release_approval.wait()
        return destination

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
        webfetch_approval=approve_destination,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> dict[str, object]:
        nonlocal current_payload
        runtime._client = runtime._http_client_factory(
            base_url="http://127.0.0.1:4097",
            auth=("opencode", "s" * 48),
            timeout=httpx.Timeout(5.0),
            trust_env=False,
        )
        runtime._enabled = True
        outcome: dict[str, object] = {"approved_fetch_urls": {}}

        async def emit(_event: dict[str, object]) -> None:
            return None

        permission_task = asyncio.create_task(
            runtime._poll_permissions(
                "sesABCDEFGH",
                _context(),
                emit,
                stopped,
                outcome,
                time.monotonic(),
            )
        )
        try:
            await asyncio.wait_for(approval_started.wait(), timeout=1.0)
            current_payload = _native_webfetch_redirect_messages(completed_redirects)
            await runtime._consume_message_snapshot("sesABCDEFGH", _context(), emit, outcome)
            release_approval.set()
            await permission_task
        finally:
            release_approval.set()
            if not permission_task.done():
                permission_task.cancel()
                await asyncio.gather(permission_task, return_exceptions=True)
            await runtime.close()
        return outcome

    outcome = asyncio.run(exercise())
    assert approvals == [candidate]
    assert outcome["webfetch_blocked_redirect_urls"] == {candidate}
    assert replies == [{"decision": "reject"}]
    assert outcome["approved_fetch_urls"] == {}


@pytest.mark.parametrize(
    ("approval_result", "reply", "approved_count"),
    (
        ("https://example.test/report", "once", 1),
        (None, "reject", 0),
    ),
)
def test_native_webfetch_permission_records_only_exact_once_reply(
    approval_result: str | None, reply: str, approved_count: int
) -> None:
    """Only a successfully replied exact fetch approval can authorize its later citation."""

    url = "https://example.test/report"
    stopped = asyncio.Event()
    replies: list[dict[str, object]] = []

    async def native_api(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/session/sesABCDEFGH/message":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_NativeBody(b'{"data":[]}'),
            )
        if request.url.path == "/api/session/sesABCDEFGH/permission":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_NativeBody(
                    json.dumps(
                        {
                            "data": [
                                {
                                    "id": "per12345",
                                    "sessionID": "sesABCDEFGH",
                                    "action": "webfetch",
                                    "resources": [url],
                                }
                            ]
                        }
                    ).encode("utf-8")
                ),
            )
        if request.url.path == "/api/session/sesABCDEFGH/permission/per12345/reply":
            replies.append(json.loads(request.content))
            stopped.set()
            return httpx.Response(204, stream=_NativeBody(b""))
        raise AssertionError(f"unexpected native API route {request.url.path}")

    async def approve(
        _context: AssistantTurnContext, destination: str, _emit: EventEmitter
    ) -> str | None:
        assert destination == url
        return approval_result

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
        webfetch_approval=approve,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> dict[str, object]:
        runtime._client = runtime._http_client_factory(
            base_url="http://127.0.0.1:4097",
            auth=("opencode", "s" * 48),
            timeout=httpx.Timeout(5.0),
            trust_env=False,
        )
        runtime._enabled = True
        outcome: dict[str, object] = {"approved_fetch_urls": {}}

        async def emit(_event):
            return None

        await runtime._poll_permissions(
            "sesABCDEFGH", _context(), emit, stopped, outcome, time.monotonic()
        )
        await runtime.close()
        return outcome

    outcome = asyncio.run(exercise())
    assert replies == [{"decision": reply}]
    assert outcome["approved_fetch_urls"] == ({url: 1} if approved_count else {})


def test_native_webfetch_permission_reply_failure_rolls_back_approval() -> None:
    """A failed native permission reply cannot leave a citation authorization behind."""

    url = "https://example.test/report"
    stopped = asyncio.Event()
    outcome: dict[str, object] = {"approved_fetch_urls": {}}

    async def native_api(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/session/sesABCDEFGH/message":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_NativeBody(b'{"data":[]}'),
            )
        if request.url.path == "/api/session/sesABCDEFGH/permission":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_NativeBody(
                    json.dumps(
                        {
                            "data": [
                                {
                                    "id": "per12345",
                                    "sessionID": "sesABCDEFGH",
                                    "action": "webfetch",
                                    "resources": [url],
                                }
                            ]
                        }
                    ).encode("utf-8")
                ),
            )
        if request.url.path == "/api/session/sesABCDEFGH/permission/per12345/reply":
            stopped.set()
            return httpx.Response(503, stream=_NativeBody(b""))
        raise AssertionError(f"unexpected native API route {request.url.path}")

    async def approve(
        _context: AssistantTurnContext, destination: str, _emit: EventEmitter
    ) -> str | None:
        assert destination == url
        return url

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
        webfetch_approval=approve,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> None:
        runtime._client = runtime._http_client_factory(
            base_url="http://127.0.0.1:4097",
            auth=("opencode", "s" * 48),
            timeout=httpx.Timeout(5.0),
            trust_env=False,
        )
        runtime._enabled = True

        async def emit(_event):
            return None

        try:
            await runtime._poll_permissions(
                "sesABCDEFGH", _context(), emit, stopped, outcome, time.monotonic()
            )
        finally:
            await runtime.close()

    with pytest.raises(RuntimeError, match="permission_reply_failed"):
        asyncio.run(exercise())
    assert outcome["approved_fetch_urls"] == {}


@pytest.mark.parametrize(
    ("name", "description"),
    (
        ("websearch", "Searching public sources."),
        ("webfetch", "Fetching an approved public URL."),
        ("signal-ledger_workspace_summary", "Using an approved local tool."),
    ),
)
def test_native_tool_activity_describes_builtin_network_tools(name: str, description: str) -> None:
    assert _native_tool_activity_description(name) == description


def test_native_long_multibyte_text_is_split_at_backend_event_limit() -> None:
    """Preserve long native text while keeping each persisted event within 8 KiB."""

    text = "🧭" * 3_000

    async def native_api(_request: httpx.Request) -> httpx.Response:
        payload = {
            "data": [
                {
                    "type": "assistant",
                    "id": "msg-long",
                    "finish": "stop",
                    "content": [{"type": "text", "id": "part-long", "text": text}],
                }
            ]
        }
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=_NativeBody(json.dumps(payload, ensure_ascii=False).encode()),
        )

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )
    events: list[object] = []

    async def exercise() -> None:
        runtime._client = runtime._http_client_factory(
            base_url="http://127.0.0.1:4097",
            auth=("opencode", "s" * 48),
            timeout=httpx.Timeout(5.0),
            trust_env=False,
        )
        runtime._enabled = True

        async def emit(event):
            events.append(event)

        outcome: dict[str, object] = {"status": "completed", "tokens": 0}
        await runtime._consume_message_snapshot("sesABCDEFGH", _context(), emit, outcome)
        await runtime.close()

    asyncio.run(exercise())
    chunks = [event["data"]["text"] for event in events]
    assert "".join(chunks) == text
    assert all(len(chunk.encode("utf-8")) <= 8_192 for chunk in chunks)
    assert sum(len(chunk.encode("utf-8")) for chunk in chunks) == 12_000


def test_native_request_can_wait_longer_than_default_idle_read_timeout() -> None:
    """A bounded native wait endpoint may remain idle longer than httpx's 5s default."""

    async def exercise() -> None:
        async def delayed_response(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            try:
                await reader.readuntil(b"\r\n\r\n")
                await asyncio.sleep(5.2)
                writer.write(
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Content-Length: 2\r\n"
                    b"Connection: close\r\n\r\n{}"
                )
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(delayed_response, "127.0.0.1", 0)
        port = int(server.sockets[0].getsockname()[1])
        runtime = OpenCodeV2Runtime(
            SimpleNamespace(assistant_enabled=True),
            providers=_TestProviders(),
            catalog=_Catalog(),
            supervisor=_Supervisor(),
        )
        runtime._client = httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}",
            timeout=httpx.Timeout(5.0, connect=1.0),
            trust_env=False,
        )
        runtime._enabled = True
        started = asyncio.get_running_loop().time()
        try:
            response = await runtime._request("GET", "/delayed", timeout=8.0)
            elapsed = asyncio.get_running_loop().time() - started
            assert response.status_code == 200
            assert response.json() == {}
            assert elapsed >= 5.0
        finally:
            await runtime.close()
            server.close()
            await server.wait_closed()

    asyncio.run(exercise())


def test_model_discovery_retries_cold_start_timeout_within_original_budget() -> None:
    """A slow initial catalog read may time out while later location reads settle."""

    location = "/run/assistant/worker-locations/" + "a" * 32
    model_calls = 0
    model_timeouts: list[float] = []

    def response(status_code: int, payload: object) -> httpx.Response:
        return httpx.Response(
            status_code,
            headers={"content-type": "application/json"},
            stream=_NativeBody(json.dumps(payload).encode("utf-8")),
        )

    async def native_api(request: httpx.Request) -> httpx.Response:
        nonlocal model_calls
        path = request.url.path
        if path == "/api/location":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_NativeBody(
                    json.dumps({"directory": location, "project": {"directory": location}}).encode(
                        "utf-8"
                    )
                ),
            )
        if path == "/api/integration":
            assert request.url.params.get("location[directory]") == location
            return response(200, _native_integration_payload(location))
        if path == "/api/model":
            model_calls += 1
            if model_calls == 1:
                try:
                    await asyncio.sleep(2.1)
                except asyncio.CancelledError:
                    raise
                return response(200, {"data": []})
            return response(
                200,
                _native_model_payload(
                    location,
                    [{"id": "assistant-selected", "providerID": "assistant-proxy"}],
                    project_directory="/repo/worktree",
                ),
            )
        if path == "/api/mcp":
            return response(
                200, {"data": [{"name": "signal-ledger", "status": {"status": "connected"}}]}
            )
        if path == "/api/websearch/provider":
            return response(200, {"data": []})
        raise AssertionError(f"unexpected native API route {path}")

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )
    original_request = runtime._request

    async def capture_model_timeout(method: str, path: str, **kwargs: object) -> httpx.Response:
        if path == "/api/model":
            model_timeouts.append(float(kwargs["timeout"]))
        return await original_request(method, path, **kwargs)

    runtime._request = capture_model_timeout

    async def exercise() -> tuple[dict[str, str], float]:
        runtime._client = runtime._http_client_factory(
            base_url="http://127.0.0.1:4097",
            auth=("opencode", "s" * 48),
            timeout=httpx.Timeout(5.0, connect=1.0),
            trust_env=False,
        )
        runtime._enabled = True
        started = asyncio.get_running_loop().time()
        try:
            provider = await runtime._verify_location(_context(), location)
            return dict(provider), asyncio.get_running_loop().time() - started
        finally:
            await runtime.close()

    provider, elapsed = asyncio.run(exercise())

    assert provider == {"id": "assistant-selected", "providerID": "assistant-proxy"}
    assert model_calls == 2
    assert model_timeouts == [2.0, 2.0]
    assert 2.0 <= elapsed < 4.0


def test_concurrent_fresh_locations_wait_for_their_own_activation_before_model_retry() -> None:
    """A partial cold catalog triggers a location-scoped plugin readiness barrier."""

    first_context = _context("a" * 32)
    second_context = replace(_context("b" * 32), capability="g" * 48)
    contexts = {
        first_context.execution_id: first_context,
        second_context.execution_id: second_context,
    }
    locations = {
        execution_id: f"/run/assistant/worker-locations/{execution_id}" for execution_id in contexts
    }
    model_calls = {execution_id: 0 for execution_id in contexts}
    routes: dict[str, list[str]] = {execution_id: [] for execution_id in contexts}
    entered_location_reads: set[str] = set()
    both_location_reads = asyncio.Event()
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
    )

    async def native_request(method: str, path: str, **kwargs: object) -> httpx.Response:
        assert method == "GET"
        params = kwargs.get("params")
        directory = params.get("location[directory]") if isinstance(params, dict) else None
        execution_id = next((key for key, value in locations.items() if value == directory), None)
        assert execution_id is not None
        routes[execution_id].append(path)
        if path == "/api/location":
            entered_location_reads.add(execution_id)
            if len(entered_location_reads) == len(contexts):
                both_location_reads.set()
            await both_location_reads.wait()
            return httpx.Response(
                200, json={"directory": directory, "project": {"directory": directory}}
            )
        if path == "/api/model":
            model_calls[execution_id] += 1
            if execution_id == first_context.execution_id and model_calls[execution_id] == 1:
                return httpx.Response(200, json=_native_model_payload(locations[execution_id], []))
            return httpx.Response(
                200,
                json=_native_model_payload(
                    locations[execution_id],
                    [{"id": "assistant-selected", "providerID": "assistant-proxy"}],
                    capability=contexts[execution_id].capability,
                ),
            )
        if path == "/api/integration":
            assert execution_id == first_context.execution_id
            assert params == {"location[directory]": locations[execution_id]}
            await asyncio.sleep(0.02)
            return httpx.Response(200, json=_native_integration_payload(locations[execution_id]))
        if path == "/api/mcp":
            return httpx.Response(
                200, json={"data": [{"name": "signal-ledger", "status": {"status": "connected"}}]}
            )
        if path == "/api/websearch/provider":
            return httpx.Response(200, json={"data": []})
        raise AssertionError(f"unexpected native API route {path}")

    runtime._request = native_request

    async def exercise() -> list[dict[str, str]]:
        try:
            first, second = await asyncio.gather(
                runtime._verify_location(first_context, locations[first_context.execution_id]),
                runtime._verify_location(second_context, locations[second_context.execution_id]),
            )
            return [dict(first), dict(second)]
        finally:
            await runtime.close()

    provider_refs = asyncio.run(exercise())

    assert provider_refs == [
        {"id": "assistant-selected", "providerID": "assistant-proxy"},
        {"id": "assistant-selected", "providerID": "assistant-proxy"},
    ]
    assert model_calls == {first_context.execution_id: 2, second_context.execution_id: 1}
    assert routes[first_context.execution_id] == [
        "/api/location",
        "/api/model",
        "/api/integration",
        "/api/model",
        "/api/mcp",
        "/api/websearch/provider",
    ]
    assert routes[second_context.execution_id] == [
        "/api/location",
        "/api/model",
        "/api/mcp",
        "/api/websearch/provider",
    ]


@pytest.mark.parametrize("readiness_fault", ("malformed", "foreign_location"))
def test_model_activation_barrier_rejects_malformed_or_foreign_location(
    readiness_fault: str,
) -> None:
    """A readiness response must be well-formed and belong to the exact location."""

    location = "/run/assistant/worker-locations/" + "a" * 32
    routes: list[str] = []
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
    )

    async def native_request(method: str, path: str, **kwargs: object) -> httpx.Response:
        assert method == "GET"
        routes.append(path)
        if path == "/api/location":
            return httpx.Response(
                200, json={"directory": location, "project": {"directory": location}}
            )
        if path == "/api/model":
            return httpx.Response(200, json=_native_model_payload(location, []))
        if path == "/api/integration":
            if readiness_fault == "malformed":
                payload: object = {"location": {"directory": location}, "data": {}}
            else:
                foreign = "/run/assistant/worker-locations/" + "b" * 32
                payload = _native_integration_payload(foreign)
            return httpx.Response(200, json=payload)
        raise AssertionError("an invalid activation barrier must stop native discovery")

    runtime._request = native_request

    async def exercise() -> None:
        with pytest.raises(assistant_runtime._AssistantRuntimeFailure) as caught:
            await runtime._verify_location(_context(), location)
        assert caught.value.code == "model_discovery_invalid"
        assert caught.value.phase == "model_discovery"
        await runtime.close()

    asyncio.run(exercise())
    assert routes == ["/api/location", "/api/model", "/api/integration"]


@pytest.mark.parametrize("outer_deadline", (False, True))
def test_model_activation_barrier_timeout_respects_discovery_and_turn_deadlines(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    outer_deadline: bool,
) -> None:
    """The readiness waiter cannot extend the fixed catalog or whole-turn budget."""

    caplog.set_level("WARNING")
    monkeypatch.setattr(assistant_runtime, "_MODEL_DISCOVERY_SECONDS", 0.5)
    monkeypatch.setattr(assistant_runtime, "_MODEL_DISCOVERY_REQUEST_SECONDS", 0.02)
    monkeypatch.setattr(assistant_runtime, "_MODEL_DISCOVERY_RETRY_SECONDS", 0.005)
    location = "/run/assistant/worker-locations/" + "a" * 32
    readiness_calls = 0
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
    )

    async def native_request(method: str, path: str, **kwargs: object) -> httpx.Response:
        nonlocal readiness_calls
        if path == "/api/location":
            return httpx.Response(
                200, json={"directory": location, "project": {"directory": location}}
            )
        if path == "/api/model":
            return httpx.Response(200, json=_native_model_payload(location, []))
        if path == "/api/integration":
            readiness_calls += 1
            await asyncio.sleep(float(kwargs["timeout"]))
            raise httpx.ReadTimeout("private timeout detail")
        raise AssertionError("timed-out readiness must not reach tools or session creation")

    runtime._request = native_request

    async def exercise() -> float:
        started = asyncio.get_running_loop().time()
        deadline = started + 0.055 if outer_deadline else None
        if outer_deadline:
            with pytest.raises(TimeoutError):
                await runtime._verify_location(_context(), location, turn_deadline=deadline)
        else:
            with pytest.raises(assistant_runtime._AssistantRuntimeFailure) as caught:
                await runtime._verify_location(_context(), location)
            assert caught.value.code == "native_request_timeout"
            assert caught.value.phase == "model_discovery"
        elapsed = asyncio.get_running_loop().time() - started
        await runtime.close()
        return elapsed

    elapsed = asyncio.run(exercise())

    assert readiness_calls >= 1
    assert elapsed < (0.07 if outer_deadline else 0.53)
    assert "outcome=readiness_timeout" in caplog.text
    assert "readiness_attempts=" in caplog.text
    assert "readiness_timeouts=" in caplog.text
    assert "private timeout detail" not in caplog.text
    assert location not in caplog.text


def test_model_catalog_timeout_after_activation_is_not_reported_as_alias_absent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A readiness barrier cannot turn an unanswered catalog request into alias absence."""

    caplog.set_level("WARNING")
    monkeypatch.setattr(assistant_runtime, "_MODEL_DISCOVERY_SECONDS", 0.05)
    monkeypatch.setattr(assistant_runtime, "_MODEL_DISCOVERY_REQUEST_SECONDS", 0.02)
    monkeypatch.setattr(assistant_runtime, "_MODEL_DISCOVERY_RETRY_SECONDS", 0.002)
    location = "/run/assistant/worker-locations/" + "a" * 32
    model_calls = 0
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
    )

    async def native_request(method: str, path: str, **kwargs: object) -> httpx.Response:
        nonlocal model_calls
        if method != "GET":
            raise AssertionError("discovery must use read-only routes")
        if path == "/api/location":
            return httpx.Response(
                200, json={"directory": location, "project": {"directory": location}}
            )
        if path == "/api/model":
            model_calls += 1
            if model_calls == 1:
                return httpx.Response(200, json=_native_model_payload(location, []))
            await asyncio.sleep(float(kwargs["timeout"]))
            raise httpx.ReadTimeout("catalog response unavailable")
        if path == "/api/integration":
            return httpx.Response(200, json=_native_integration_payload(location))
        raise AssertionError("model discovery timeout must stop before other native routes")

    runtime._request = native_request

    async def exercise() -> None:
        with pytest.raises(assistant_runtime._AssistantRuntimeFailure) as caught:
            await runtime._verify_location(_context(), location)
        assert caught.value.code == "model_alias_unavailable"
        assert caught.value.phase == "model_discovery"
        await runtime.close()

    asyncio.run(exercise())

    assert model_calls >= 2
    assert "outcome=catalog_timeout_after_readiness" in caplog.text
    assert "post_readiness_catalog_responses=0" in caplog.text
    assert "post_readiness_missing_alias_responses=0" in caplog.text
    assert "catalog response unavailable" not in caplog.text
    assert location not in caplog.text


def test_model_activation_barrier_cancellation_propagates_without_retry_or_model_work() -> None:
    """Cancellation interrupts only the waiter and never proceeds to a model session."""

    location = "/run/assistant/worker-locations/" + "a" * 32
    routes: list[str] = []
    barrier_started = asyncio.Event()
    never = asyncio.Event()
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
    )

    async def native_request(method: str, path: str, **kwargs: object) -> httpx.Response:
        assert method == "GET"
        routes.append(path)
        if path == "/api/location":
            return httpx.Response(
                200, json={"directory": location, "project": {"directory": location}}
            )
        if path == "/api/model":
            return httpx.Response(200, json=_native_model_payload(location, []))
        if path == "/api/integration":
            barrier_started.set()
            await never.wait()
        raise AssertionError("cancelled activation waiter must not continue discovery")

    runtime._request = native_request

    async def exercise() -> None:
        verification = asyncio.create_task(runtime._verify_location(_context(), location))
        await barrier_started.wait()
        verification.cancel()
        with pytest.raises(asyncio.CancelledError):
            await verification
        await runtime.close()

    asyncio.run(exercise())
    assert routes == ["/api/location", "/api/model", "/api/integration"]


@pytest.mark.parametrize(
    ("status_code", "payload", "failure_code"),
    [
        (
            403,
            {"data": [{"id": "assistant-selected", "providerID": "assistant-proxy"}]},
            "model_discovery_unavailable",
        ),
        (200, {"data": {}}, "model_discovery_invalid"),
        (
            200,
            {"data": [{"id": "assistant-selected", "providerID": "other-provider"}]},
            "model_provider_invalid",
        ),
    ],
)
def test_model_discovery_does_not_retry_denied_or_malformed_responses(
    status_code: int, payload: dict[str, object], failure_code: str
) -> None:
    """Only request-local timeout signals are retryable during catalog discovery."""

    location = "/run/assistant/worker-locations/" + "a" * 32
    model_calls = 0

    def response(status: int, payload: object) -> httpx.Response:
        return httpx.Response(
            status,
            headers={"content-type": "application/json"},
            stream=_NativeBody(json.dumps(payload).encode("utf-8")),
        )

    async def native_api(request: httpx.Request) -> httpx.Response:
        nonlocal model_calls
        if request.url.path == "/api/location":
            return response(200, {"directory": location, "project": {"directory": location}})
        if request.url.path == "/api/model":
            model_calls += 1
            model_payload = {
                **payload,
                "location": {
                    "directory": location,
                    "project": {"directory": "/repo/worktree"},
                },
            }
            return response(status_code, model_payload)
        raise AssertionError("non-model discovery must not continue after a bad response")

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> None:
        runtime._client = runtime._http_client_factory(
            base_url="http://127.0.0.1:4097",
            auth=("opencode", "s" * 48),
            timeout=httpx.Timeout(5.0, connect=1.0),
            trust_env=False,
        )
        runtime._enabled = True
        try:
            with pytest.raises(RuntimeError, match=failure_code):
                await runtime._verify_location(_context(), location)
        finally:
            await runtime.close()

    asyncio.run(exercise())
    assert model_calls == 1


def test_model_discovery_rejects_a_different_response_location_directory() -> None:
    """Model rows must belong to the queried directory, regardless of project metadata."""

    location = "/run/assistant/worker-locations/" + "a" * 32
    routes: list[str] = []

    def response(status: int, payload: object) -> httpx.Response:
        return httpx.Response(
            status,
            headers={"content-type": "application/json"},
            stream=_NativeBody(json.dumps(payload).encode("utf-8")),
        )

    async def native_api(request: httpx.Request) -> httpx.Response:
        routes.append(request.url.path)
        if request.url.path == "/api/location":
            return response(200, {"directory": location, "project": {"directory": location}})
        if request.url.path == "/api/model":
            return response(
                200,
                _native_model_payload(
                    "/run/assistant/worker-locations/" + "b" * 32,
                    [{"id": "assistant-selected", "providerID": "assistant-proxy"}],
                    project_directory=location,
                ),
            )
        raise AssertionError("a model response from another location must stop discovery")

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> None:
        runtime._client = runtime._http_client_factory(
            base_url="http://127.0.0.1:4097",
            auth=("opencode", "s" * 48),
            timeout=httpx.Timeout(5.0, connect=1.0),
            trust_env=False,
        )
        runtime._enabled = True
        try:
            with pytest.raises(RuntimeError, match="model_location_mismatch"):
                await runtime._verify_location(_context(), location)
        finally:
            await runtime.close()

    asyncio.run(exercise())

    assert routes == ["/api/location", "/api/model"]


@pytest.mark.parametrize(
    ("mismatch", "expected_code"),
    [
        ("package", "model_proxy_config_invalid"),
        ("model_id", "model_proxy_config_invalid"),
        ("proxy_url", "model_proxy_config_invalid"),
        ("capability", "model_proxy_config_invalid"),
        ("capabilities", "model_capabilities_invalid"),
    ],
)
def test_model_alias_is_bound_to_exact_per_execution_proxy_configuration(
    mismatch: str, expected_code: str
) -> None:
    """An alias is unusable if its native package, URL, model, or capability drifts."""

    location = "/run/assistant/worker-locations/" + "a" * 32
    routes: list[str] = []

    def response(status: int, payload: object) -> httpx.Response:
        return httpx.Response(
            status,
            headers={"content-type": "application/json"},
            stream=_NativeBody(json.dumps(payload).encode("utf-8")),
        )

    async def native_api(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        routes.append(path)
        if path == "/api/location":
            return response(200, {"directory": location, "project": {"directory": location}})
        if path == "/api/model":
            payload = _native_model_payload(
                location,
                [{"id": "assistant-selected", "providerID": "assistant-proxy"}],
            )
            row = payload["data"][0]
            if mismatch == "package":
                row["package"] = "unexpected-package"
            elif mismatch == "model_id":
                row["modelID"] = "unexpected-model"
            elif mismatch == "proxy_url":
                row["settings"]["baseURL"] = (
                    "http://127.0.0.1:8000/api/v1/assistant/internal/provider/" + "b" * 32
                )
            elif mismatch == "capabilities":
                row["capabilities"]["tools"] = False
            else:
                row["headers"]["Authorization"] = "Bearer " + "e" * 48
            return response(200, payload)
        raise AssertionError("a mismatched per-execution proxy must fail before MCP discovery")

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> None:
        runtime._client = runtime._http_client_factory(
            base_url="http://127.0.0.1:4097",
            auth=("opencode", "s" * 48),
            timeout=httpx.Timeout(5.0, connect=1.0),
            trust_env=False,
        )
        runtime._enabled = True
        try:
            with pytest.raises(assistant_runtime._AssistantRuntimeFailure) as caught:
                await runtime._verify_location(_context(), location)
            assert caught.value.code == expected_code
            assert str(caught.value) == expected_code
        finally:
            await runtime.close()

    asyncio.run(exercise())

    assert routes == ["/api/location", "/api/model"]


def test_model_alias_configuration_is_isolated_between_execution_locations() -> None:
    """The same native alias binds separately to each execution URL and capability."""

    first_context = _context("a" * 32)
    second_context = replace(_context("b" * 32), capability="g" * 48)
    locations = {
        context.execution_id: f"/run/assistant/worker-locations/{context.execution_id}"
        for context in (first_context, second_context)
    }
    capabilities = {
        first_context.execution_id: first_context.capability,
        second_context.execution_id: second_context.capability,
    }
    checked: dict[str, tuple[bool, bool]] = {}

    def response(status: int, payload: object) -> httpx.Response:
        return httpx.Response(
            status,
            headers={"content-type": "application/json"},
            stream=_NativeBody(json.dumps(payload).encode("utf-8")),
        )

    async def native_api(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        directory = request.url.params.get("location[directory]", "")
        execution_id = directory.rsplit("/", 1)[-1]
        if path == "/api/location":
            return response(200, {"directory": directory, "project": {"directory": directory}})
        if path == "/api/model":
            payload = _native_model_payload(
                directory,
                [{"id": "assistant-selected", "providerID": "assistant-proxy"}],
                capability=capabilities[execution_id],
            )
            row = payload["data"][0]
            checked[execution_id] = (
                row["settings"]["baseURL"]
                == "http://127.0.0.1:8000/api/v1/assistant/internal/provider/" + execution_id,
                row["headers"]["Authorization"] == "Bearer " + capabilities[execution_id],
            )
            return response(200, payload)
        if path == "/api/mcp":
            return response(
                200, {"data": [{"name": "signal-ledger", "status": {"status": "connected"}}]}
            )
        if path == "/api/websearch/provider":
            return response(200, {"data": []})
        raise AssertionError(f"unexpected native API route {path}")

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> list[dict[str, str]]:
        runtime._client = runtime._http_client_factory(
            base_url="http://127.0.0.1:4097",
            auth=("opencode", "s" * 48),
            timeout=httpx.Timeout(5.0, connect=1.0),
            trust_env=False,
        )
        runtime._enabled = True
        try:
            first, second = await asyncio.gather(
                runtime._verify_location(first_context, locations[first_context.execution_id]),
                runtime._verify_location(second_context, locations[second_context.execution_id]),
            )
            return [dict(first), dict(second)]
        finally:
            await runtime.close()

    providers = asyncio.run(exercise())

    assert providers == [
        {"id": "assistant-selected", "providerID": "assistant-proxy"},
        {"id": "assistant-selected", "providerID": "assistant-proxy"},
    ]
    assert checked == {"a" * 32: (True, True), "b" * 32: (True, True)}


def test_concurrent_cold_location_discovery_retries_only_one_timed_out_get(caplog) -> None:
    """Cold locations stay parallel while model activation is serialized per runtime."""

    caplog.set_level("INFO")
    first_context = _context("a" * 32)
    second_context = replace(_context("b" * 32), capability="g" * 48)
    contexts = {
        first_context.execution_id: first_context,
        second_context.execution_id: second_context,
    }
    locations = {
        execution_id: f"/run/assistant/worker-locations/{execution_id}" for execution_id in contexts
    }
    location_calls: dict[str, int] = {execution_id: 0 for execution_id in contexts}
    model_calls: dict[str, int] = {execution_id: 0 for execution_id in contexts}
    request_timeouts: list[float] = []
    entered_first_reads: set[str] = set()
    both_first_reads_started = asyncio.Event()
    first_integration_started = asyncio.Event()
    release_first_integration = asyncio.Event()
    active_discoveries: set[str] = set()
    integration_calls: list[str] = []
    alias_capabilities: dict[str, str] = {}
    mcp_locations: set[str] = set()
    both_mcp_started = asyncio.Event()
    descriptor = resolve_native_adapter("openai-compatible-chat", "assistant-proxy")
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders("openai-compatible-chat", "assistant-proxy"),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
    )

    async def native_request(method: str, path: str, **kwargs: object) -> httpx.Response:
        assert method == "GET"
        params = kwargs.get("params")
        directory = params.get("location[directory]") if isinstance(params, dict) else None
        execution_id = next((key for key, value in locations.items() if value == directory), None)
        assert execution_id is not None
        if path == "/api/location":
            location_calls[execution_id] += 1
            request_timeouts.append(float(kwargs["timeout"]))
            if location_calls[execution_id] == 1:
                entered_first_reads.add(execution_id)
                if len(entered_first_reads) == len(contexts):
                    both_first_reads_started.set()
                await both_first_reads_started.wait()
                if execution_id == first_context.execution_id:
                    raise httpx.ReadTimeout("synthetic cold-location timeout")
            directory = locations[execution_id]
            return httpx.Response(
                200, json={"directory": directory, "project": {"directory": directory}}
            )
        if path == "/api/model":
            model_calls[execution_id] += 1
            if model_calls[execution_id] == 1:
                active_discoveries.add(execution_id)
                assert len(active_discoveries) == 1
                return httpx.Response(
                    200,
                    json=_native_model_payload(locations[execution_id], []),
                )
            assert execution_id in active_discoveries
            assert len(active_discoveries) == 1
            alias_capabilities[execution_id] = contexts[execution_id].capability
            active_discoveries.remove(execution_id)
            return httpx.Response(
                200,
                json=_native_model_payload(
                    locations[execution_id],
                    [{"id": "assistant-selected", "providerID": "assistant-proxy"}],
                    capability=contexts[execution_id].capability,
                ),
            )
        if path == "/api/integration":
            assert execution_id in active_discoveries
            assert len(active_discoveries) == 1
            integration_calls.append(execution_id)
            if not first_integration_started.is_set():
                first_integration_started.set()
                await release_first_integration.wait()
            return httpx.Response(200, json=_native_integration_payload(locations[execution_id]))
        if path == "/api/mcp":
            mcp_locations.add(execution_id)
            if len(mcp_locations) == len(contexts):
                both_mcp_started.set()
            await asyncio.wait_for(both_mcp_started.wait(), timeout=1.0)
            return httpx.Response(
                200, json={"data": [{"name": "signal-ledger", "status": {"status": "connected"}}]}
            )
        if path == "/api/websearch/provider":
            return httpx.Response(200, json={"data": []})
        raise AssertionError("unexpected native discovery route")

    runtime._request = native_request

    async def exercise() -> list[dict[str, str]]:
        try:
            tasks = [
                asyncio.create_task(
                    runtime._verify_location(
                        first_context, locations[first_context.execution_id], descriptor
                    )
                ),
                asyncio.create_task(
                    runtime._verify_location(
                        second_context, locations[second_context.execution_id], descriptor
                    )
                ),
            ]
            await asyncio.wait_for(first_integration_started.wait(), timeout=1.0)
            await asyncio.sleep(0)
            assert sum(model_calls.values()) == 1
            assert len(active_discoveries) == 1
            release_first_integration.set()
            first, second = await asyncio.wait_for(asyncio.gather(*tasks), timeout=2.0)
            return [dict(first), dict(second)]
        finally:
            release_first_integration.set()
            await runtime.close()

    provider_refs = asyncio.run(exercise())

    assert provider_refs == [
        {"id": "assistant-selected", "providerID": "assistant-proxy"},
        {"id": "assistant-selected", "providerID": "assistant-proxy"},
    ]
    assert location_calls == {first_context.execution_id: 2, second_context.execution_id: 1}
    assert request_timeouts and all(0 < timeout <= 5.0 for timeout in request_timeouts)
    assert sorted(model_calls.values()) == [2, 2]
    assert len(integration_calls) == 2
    assert alias_capabilities == {
        execution_id: context.capability for execution_id, context in contexts.items()
    }
    assert mcp_locations == set(contexts)
    assert not active_discoveries
    assert (
        "Assistant location discovery recovered "
        "(phase=location_discovery, attempts=2, transient_timeouts=1, elapsed_ms="
    ) in caplog.text


def test_model_discovery_lock_wait_respects_deadline_and_cancellation() -> None:
    """An expired or cancelled lock waiter cannot issue model requests or strand the lock."""

    contexts = [_context(letter * 32) for letter in ("a", "b", "c")]
    locations = {
        context.execution_id: f"/run/assistant/worker-locations/{context.execution_id}"
        for context in contexts
    }
    location_started = {context.execution_id: asyncio.Event() for context in contexts}
    model_calls: list[str] = []
    descriptor = resolve_native_adapter("openai-compatible-chat", "assistant-proxy")
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
    )

    async def native_request(method: str, path: str, **kwargs: object) -> httpx.Response:
        assert method == "GET"
        params = kwargs.get("params")
        directory = params.get("location[directory]") if isinstance(params, dict) else None
        execution_id = next((key for key, value in locations.items() if value == directory), None)
        assert execution_id is not None
        if path == "/api/location":
            location_started[execution_id].set()
            return httpx.Response(
                200,
                json={"directory": directory, "project": {"directory": directory}},
            )
        if path == "/api/model":
            model_calls.append(execution_id)
            context = next(item for item in contexts if item.execution_id == execution_id)
            return httpx.Response(
                200,
                json=_native_model_payload(
                    str(directory),
                    [{"id": "assistant-selected", "providerID": "assistant-proxy"}],
                    capability=context.capability,
                ),
            )
        if path == "/api/mcp":
            return httpx.Response(
                200, json={"data": [{"name": "signal-ledger", "status": {"status": "connected"}}]}
            )
        if path == "/api/websearch/provider":
            return httpx.Response(200, json={"data": []})
        raise AssertionError("unexpected native discovery route")

    runtime._request = native_request

    async def exercise() -> None:
        try:
            await runtime._model_discovery_lock.acquire()
            loop = asyncio.get_running_loop()
            deadline_started = loop.time()
            with pytest.raises(TimeoutError):
                await runtime._verify_location(
                    contexts[0],
                    locations[contexts[0].execution_id],
                    descriptor,
                    turn_deadline=deadline_started + 0.05,
                )
            assert loop.time() < deadline_started + 0.15
            assert location_started[contexts[0].execution_id].is_set()
            assert not model_calls
            assert runtime._model_discovery_lock.locked()

            waiter = asyncio.create_task(
                runtime._verify_location(
                    contexts[1],
                    locations[contexts[1].execution_id],
                    descriptor,
                    turn_deadline=loop.time() + 2.0,
                )
            )
            await asyncio.wait_for(location_started[contexts[1].execution_id].wait(), timeout=1.0)
            await asyncio.sleep(0)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert not model_calls
            assert runtime._model_discovery_lock.locked()

            runtime._model_discovery_lock.release()
            provider_ref = await asyncio.wait_for(
                runtime._verify_location(
                    contexts[2], locations[contexts[2].execution_id], descriptor
                ),
                timeout=1.0,
            )
            assert provider_ref == {
                "id": "assistant-selected",
                "providerID": "assistant-proxy",
            }
            assert model_calls == [contexts[2].execution_id]
            assert not runtime._model_discovery_lock.locked()
        finally:
            if runtime._model_discovery_lock.locked():
                runtime._model_discovery_lock.release()
            await runtime.close()

    asyncio.run(exercise())


def test_location_discovery_exhaustion_respects_turn_deadline(monkeypatch, caplog) -> None:
    """Location retries stop at the earlier stage or existing turn deadline."""

    context = _context()
    location = f"/run/assistant/worker-locations/{context.execution_id}"
    request_timeouts: list[float] = []
    descriptor = resolve_native_adapter("openai-compatible-chat", "assistant-proxy")
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders("openai-compatible-chat", "assistant-proxy"),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
    )
    monkeypatch.setattr(assistant_runtime, "_LOCATION_DISCOVERY_SECONDS", 0.5)
    monkeypatch.setattr(assistant_runtime, "_LOCATION_DISCOVERY_REQUEST_SECONDS", 0.02)
    monkeypatch.setattr(assistant_runtime, "_LOCATION_DISCOVERY_RETRY_SECONDS", 0.01)

    async def native_request(method: str, path: str, **kwargs: object) -> httpx.Response:
        assert (method, path) == ("GET", "/api/location")
        timeout = float(kwargs["timeout"])
        request_timeouts.append(timeout)
        await asyncio.sleep(timeout)
        raise httpx.ReadTimeout("synthetic cold-location timeout")

    runtime._request = native_request

    async def exercise() -> float:
        started = asyncio.get_running_loop().time()
        deadline = started + 0.055
        with pytest.raises(TimeoutError):
            await runtime._verify_location(context, location, descriptor, turn_deadline=deadline)
        elapsed = asyncio.get_running_loop().time() - started
        assert asyncio.get_running_loop().time() <= deadline + 0.01
        return elapsed

    elapsed = asyncio.run(exercise())
    asyncio.run(runtime.close())

    assert 1 <= len(request_timeouts) <= 4
    assert all(0 < timeout <= 0.02 for timeout in request_timeouts)
    assert elapsed < 0.07
    assert "Assistant location discovery exhausted " in caplog.text
    assert "transient_timeouts=" in caplog.text


@pytest.mark.parametrize(
    "response",
    (
        httpx.Response(503, json={"directory": "/wrong", "project": {"directory": "/wrong"}}),
        httpx.Response(200, json={"directory": "/wrong", "project": {"directory": "/wrong"}}),
    ),
)
def test_location_discovery_does_not_retry_denied_or_mismatched_responses(response) -> None:
    """Only a request-local timeout is retried; invalid or denied data fails immediately."""

    context = _context()
    location = f"/run/assistant/worker-locations/{context.execution_id}"
    calls = 0
    descriptor = resolve_native_adapter("openai-compatible-chat", "assistant-proxy")
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders("openai-compatible-chat", "assistant-proxy"),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
    )

    async def native_request(method: str, path: str, **_kwargs: object) -> httpx.Response:
        nonlocal calls
        assert (method, path) == ("GET", "/api/location")
        calls += 1
        return response

    runtime._request = native_request

    async def exercise() -> None:
        with pytest.raises(assistant_runtime._AssistantRuntimeFailure) as caught:
            await runtime._verify_location(context, location, descriptor)
        assert caught.value.code == "location_discovery_mismatch"
        assert caught.value.phase == "location_discovery"

    try:
        asyncio.run(exercise())
    finally:
        asyncio.run(runtime.close())
    assert calls == 1


def test_kill_switch_cancels_a_turn_during_location_retry_backoff(monkeypatch) -> None:
    """The operator kill cancels a retry wait before another native location request."""

    context = _context()
    location = f"/run/assistant/worker-locations/{context.execution_id}"
    retry_started = asyncio.Event()
    location_calls = 0
    descriptor = resolve_native_adapter("openai-compatible-chat", "assistant-proxy")
    supervisor = _Supervisor()
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders("openai-compatible-chat", "assistant-proxy"),
        catalog=_Catalog(),
        supervisor=supervisor,
    )
    monkeypatch.setattr(assistant_runtime, "_LOCATION_DISCOVERY_RETRY_SECONDS", 10.0)

    async def native_request(method: str, path: str, **_kwargs: object) -> httpx.Response:
        nonlocal location_calls
        assert (method, path) == ("GET", "/api/location")
        location_calls += 1
        retry_started.set()
        raise httpx.ReadTimeout("synthetic cold-location timeout")

    runtime._request = native_request

    async def blocked_turn(*, context, prompt: str, emit) -> None:
        del prompt, emit
        await runtime._verify_location(context, location, descriptor)

    runtime._run_turn_impl = blocked_turn

    async def exercise() -> None:
        task = asyncio.create_task(
            runtime.run_turn(
                context=context,
                prompt="wait in bounded location retry",
                emit=lambda _event: asyncio.sleep(0),
            )
        )
        await asyncio.wait_for(retry_started.wait(), timeout=1.0)
        await runtime.kill_switch("operator")
        with pytest.raises(asyncio.CancelledError):
            await task
        assert location_calls == 1
        assert runtime.operator_disabled is True
        assert runtime._turn_tasks == {}
        assert supervisor.disabled_reasons == ["operator"]
        await runtime.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("adapter_id", "native_provider_id"),
    (
        ("openai-responses", "openai"),
        ("anthropic-messages", "anthropic"),
        ("google-generative-language", "google"),
        ("openai-compatible-chat", "assistant-proxy"),
    ),
)
def test_runtime_verifies_native_package_from_the_exact_model_adapter(
    adapter_id: str, native_provider_id: str
) -> None:
    """The same alias is accepted only under its selected pinned native adapter."""

    context = _context()
    location = f"/run/assistant/worker-locations/{context.execution_id}"
    requests: list[str] = []
    descriptor = resolve_native_adapter(adapter_id, native_provider_id)

    def response(payload: object) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=_NativeBody(json.dumps(payload).encode("utf-8")),
        )

    async def native_api(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/api/location":
            return response({"directory": location, "project": {"directory": location}})
        if request.url.path == "/api/model":
            return response(
                _native_model_payload(
                    location,
                    [{"id": "assistant-selected", "providerID": native_provider_id}],
                    adapter_id=adapter_id,
                    native_provider_id=native_provider_id,
                    capability=context.capability,
                )
            )
        if request.url.path == "/api/mcp":
            return response(
                {"data": [{"name": "signal-ledger", "status": {"status": "connected"}}]}
            )
        if request.url.path == "/api/websearch/provider":
            return response({"data": []})
        raise AssertionError(f"unexpected native API route {request.url.path}")

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(adapter_id, native_provider_id),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> dict[str, str]:
        runtime._client = runtime._http_client_factory(
            base_url="http://127.0.0.1:4097",
            auth=("opencode", "s" * 48),
            timeout=httpx.Timeout(5.0, connect=1.0),
            trust_env=False,
        )
        runtime._enabled = True
        try:
            return dict(await runtime._verify_location(context, location, descriptor))
        finally:
            await runtime.close()

    provider_ref = asyncio.run(exercise())

    assert provider_ref == {"id": "assistant-selected", "providerID": native_provider_id}
    assert requests == ["/api/location", "/api/model", "/api/mcp", "/api/websearch/provider"]


def test_runtime_rejects_a_forged_descriptor_before_preparing_a_location() -> None:
    """An approved adapter ID cannot carry modified package or route metadata."""

    approved = resolve_native_adapter("openai-responses", "openai")

    class ForgedProviders:
        def native_execution_descriptor(self, _model_id: str, *, owner_id: int):
            assert owner_id == 41
            return replace(approved, package_id="unreviewed/package")

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=ForgedProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
    )

    with pytest.raises(assistant_runtime._AssistantRuntimeFailure) as caught:
        runtime._native_adapter_for_model(_TEST_MODEL_ID, owner_id=41)

    assert caught.value.code == "native_adapter_invalid"
    assert caught.value.phase == "prepare_location"
    assert "unreviewed/package" not in str(caught.value)


def test_runtime_resolves_console_models_from_the_exact_owner_snapshot() -> None:
    """Owner-only Console models do not depend on the shared global model catalog."""

    model_id = "opencode-console/" + "a" * 64
    owner_lookups: list[tuple[str, int]] = []

    class GlobalCatalog:
        def get_model(self, _model_id: str) -> object | None:
            raise AssertionError("owner-scoped model lookup must not query the shared catalog")

        async def ensure_fresh(self, *, minimum_validity_seconds: float) -> tuple[object, ...]:
            del minimum_validity_seconds
            raise AssertionError("owner-scoped model lookup must not refresh the shared catalog")

    class OwnerProviders(_TestProviders):
        def get_opencode_model(self, requested_id: str, *, owner_id: int) -> object:
            owner_lookups.append((requested_id, owner_id))
            return SimpleNamespace(
                model_id=requested_id,
                provider_id="opencode-console",
                available=True,
            )

    supervisor = _Supervisor()
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=OwnerProviders(),
        catalog=GlobalCatalog(),
        supervisor=supervisor,
    )
    descriptor = resolve_native_adapter("openai-compatible-chat", "assistant-proxy")
    context = replace(_context(), model_id=model_id)

    location = asyncio.run(runtime._prepare_location(context, descriptor))

    assert location == f"/run/assistant/worker-locations/{context.execution_id}"
    assert owner_lookups == [(model_id, context.user_id)]
    assert supervisor.prepared[0]["provider_id"] == "opencode-console"
    assert supervisor.prepared[0]["model_id"] == model_id


def test_runtime_rejects_owner_model_resolution_if_provider_returns_another_owner_id() -> None:
    """A Console cache miss or mismatched returned ID fails before native location setup."""

    class OwnerProviders(_TestProviders):
        def get_opencode_model(self, _model_id: str, *, owner_id: int) -> object:
            del owner_id
            return SimpleNamespace(
                model_id="opencode-console/" + "b" * 64,
                provider_id="opencode-console",
                available=True,
            )

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=OwnerProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
    )
    context = replace(_context(), model_id="opencode-console/" + "a" * 64)

    assert runtime._model_for_turn(context) is None


def test_model_discovery_deadline_fails_closed_without_starting_a_model_session(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An exhausted catalog budget stays a setup failure and never prompts a model."""

    monkeypatch.setattr(assistant_runtime, "_MODEL_DISCOVERY_SECONDS", 0.06)
    monkeypatch.setattr(assistant_runtime, "_MODEL_DISCOVERY_REQUEST_SECONDS", 0.02)
    monkeypatch.setattr(assistant_runtime, "_MODEL_DISCOVERY_RETRY_SECONDS", 0.01)
    location = "/run/assistant/worker-locations/" + "a" * 32
    model_calls = 0
    forbidden_calls: list[str] = []

    def response(status: int, payload: object) -> httpx.Response:
        return httpx.Response(
            status,
            headers={"content-type": "application/json"},
            stream=_NativeBody(json.dumps(payload).encode("utf-8")),
        )

    async def native_api(request: httpx.Request) -> httpx.Response:
        nonlocal model_calls
        path = request.url.path
        if path == "/api/info":
            return response(200, {"version": "v2"})
        if path == "/api/location":
            return response(200, {"directory": location, "project": {"directory": location}})
        if path == "/api/integration":
            return response(200, _native_integration_payload(location))
        if path == "/api/model":
            model_calls += 1
            await asyncio.sleep(0.05)
            return response(200, _native_model_payload(location, []))
        forbidden_calls.append(path)
        raise AssertionError("catalog failure must not start MCP/session/model work")

    supervisor = _Supervisor()
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> tuple[object, float]:
        started = asyncio.get_running_loop().time()
        result = await runtime.run_turn(
            context=_context(),
            prompt="Synthetic bounded fixture",
            emit=lambda _event: asyncio.sleep(0),
        )
        elapsed = asyncio.get_running_loop().time() - started
        await runtime.close()
        return result, elapsed

    result, elapsed = asyncio.run(exercise())

    assert (result.status, result.error_code) == ("failed", "worker_unavailable")
    assert model_calls >= 1
    assert forbidden_calls == []
    assert supervisor.removed == ["a" * 32]
    assert elapsed < 0.2
    assert "phase=model_discovery, failure_code=model_alias_unavailable" in caplog.text
    assert "phase=model_discovery, outcome=catalog_timeout" in caplog.text
    assert "readiness_attempts=0" in caplog.text
    assert "missing_alias_responses=" in caplog.text
    assert "Synthetic bounded fixture" not in caplog.text
    assert _TEST_MODEL_ID not in caplog.text


@pytest.mark.parametrize(
    ("timeout_stage", "expected_phase", "expected_error", "diagnostic"),
    [
        ("location", "location_discovery", "worker_unavailable", "failure_code"),
        ("mcp", "mcp_discovery", "worker_unavailable", "failure_code"),
        ("session", "create_session", "worker_unavailable", "request_timeout"),
        ("prompt", "prompt", "provider_unavailable", "request_timeout"),
    ],
)
def test_request_local_timeouts_fail_closed_without_becoming_turn_deadlines(
    timeout_stage: str,
    expected_phase: str,
    expected_error: str,
    diagnostic: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Location, MCP, session, and prompt timeouts are local failures before 120s."""

    timeout_paths = {
        "location": "/api/location",
        "mcp": "/api/mcp",
        "session": "/api/session",
        "prompt": "/api/session/sesABCDEFGH/prompt",
    }
    request_paths: list[str] = []

    def response(status: int, payload: object | None = None) -> httpx.Response:
        body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        headers = {"content-type": "application/json"} if payload is not None else {}
        return httpx.Response(status, headers=headers, stream=_NativeBody(body))

    async def native_api(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        request_paths.append(path)
        if path == timeout_paths[timeout_stage]:
            raise httpx.ReadTimeout("synthetic private timeout detail")
        if path == "/api/info":
            return response(200, {"version": "v2"})
        if path == "/api/location":
            requested = request.url.params.get("location[directory]", "")
            return response(200, {"directory": requested, "project": {"directory": requested}})
        if path == "/api/model":
            requested = request.url.params.get("location[directory]", "")
            return response(
                200,
                _native_model_payload(
                    requested,
                    [{"id": "assistant-selected", "providerID": "assistant-proxy"}],
                ),
            )
        if path == "/api/mcp":
            return response(
                200, {"data": [{"name": "signal-ledger", "status": {"status": "connected"}}]}
            )
        if path == "/api/websearch/provider":
            return response(200, {"data": []})
        if path == "/api/session":
            return response(200, {"data": {"id": "sesABCDEFGH"}})
        if path == "/api/session/sesABCDEFGH/permission":
            return response(200, {"data": []})
        if path == "/api/session/sesABCDEFGH/interrupt":
            return response(204)
        if path == "/api/session/sesABCDEFGH":
            return response(204)
        raise AssertionError(f"unexpected native API route {path}")

    supervisor = _Supervisor()
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> object:
        try:
            return await runtime.run_turn(
                context=_context(),
                prompt="Synthetic private timeout fixture",
                emit=lambda _event: asyncio.sleep(0),
            )
        finally:
            await runtime.close()

    result = asyncio.run(exercise())

    assert (result.status, result.error_code) == ("failed", expected_error)
    assert f"phase={expected_phase}" in caplog.text
    assert diagnostic in caplog.text
    if timeout_stage == "session":
        assert (
            "Assistant pre-session failure (stage=create_session, failure_code=request_timeout)."
        ) in caplog.text
    assert "turn deadline expired" not in caplog.text
    assert "synthetic private timeout detail" not in caplog.text
    assert "Synthetic private timeout fixture" not in caplog.text
    assert "Assistant worker startup failed" not in caplog.text
    assert supervisor.removed == ["a" * 32]
    assert timeout_paths[timeout_stage] in request_paths


def test_only_full_turn_budget_expiry_returns_turn_timeout(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An exhausted absolute turn budget remains distinct from request-local failures."""

    monkeypatch.setattr(assistant_runtime, "_MAX_TURN_SECONDS", 0.05)
    location = "/run/assistant/worker-locations/" + "a" * 32

    def response(status: int, payload: object | None = None) -> httpx.Response:
        body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        headers = {"content-type": "application/json"} if payload is not None else {}
        return httpx.Response(status, headers=headers, stream=_NativeBody(body))

    async def native_api(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/info":
            return response(200, {"version": "v2"})
        if path == "/api/location":
            return response(200, {"directory": location, "project": {"directory": location}})
        if path == "/api/model":
            directory = request.url.params.get("location[directory]", "")
            execution_id = directory.rsplit("/", 1)[-1]
            capability = {"a" * 32: "d" * 48, "b" * 32: "g" * 48}[execution_id]
            return response(
                200,
                _native_model_payload(
                    directory,
                    [{"id": "assistant-selected", "providerID": "assistant-proxy"}],
                    capability=capability,
                ),
            )
        if path == "/api/mcp":
            return response(
                200, {"data": [{"name": "signal-ledger", "status": {"status": "connected"}}]}
            )
        if path == "/api/websearch/provider":
            return response(200, {"data": []})
        if path == "/api/session":
            return response(200, {"data": {"id": "sesABCDEFGH"}})
        if path == "/api/session/sesABCDEFGH/prompt":
            await asyncio.sleep(0.06)
            return response(204)
        if path == "/api/session/sesABCDEFGH/interrupt":
            return response(204)
        if path == "/api/session/sesABCDEFGH":
            return response(204)
        if path == "/api/session/sesABCDEFGH/permission":
            return response(200, {"data": []})
        raise AssertionError(f"unexpected native API route {path}")

    supervisor = _Supervisor()
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> object:
        try:
            return await runtime.run_turn(
                context=_context(),
                prompt="Synthetic full deadline fixture",
                emit=lambda _event: asyncio.sleep(0),
            )
        finally:
            await runtime.close()

    result = asyncio.run(exercise())

    assert (result.status, result.error_code) == ("timed_out", "turn_timeout")
    assert "Assistant turn deadline expired (phase=prompt" in caplog.text
    assert "request_timeout" not in caplog.text
    assert "Synthetic full deadline fixture" not in caplog.text
    assert supervisor.removed == ["a" * 32]


@pytest.mark.parametrize(
    "terminal_case",
    ("wait_failed", "idle_failed", "missing_finish", "invalid_fetch", "success"),
)
def test_native_terminal_diagnostics_cover_failures_without_logging_success(
    terminal_case: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Failed terminal paths get safe diagnostics, while a successful stop stays quiet."""

    supervisor = _Supervisor()
    message_poll_started = asyncio.Event()
    message_calls = 0

    def response(status_code: int, payload: object | None = None) -> httpx.Response:
        content = json.dumps(payload).encode() if payload is not None else b""
        headers = {"content-type": "application/json"} if payload is not None else {}
        return httpx.Response(status_code, headers=headers, stream=_NativeBody(content))

    async def native_api(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/info":
            return response(200, {"version": "v2"})
        if path == "/api/location":
            directory = request.url.params.get("location[directory]")
            return response(200, {"directory": directory, "project": {"directory": directory}})
        if path == "/api/model":
            directory = request.url.params.get("location[directory]")
            return response(
                200,
                _native_model_payload(
                    directory,
                    [{"id": "assistant-selected", "providerID": "assistant-proxy"}],
                ),
            )
        if path == "/api/mcp":
            return response(
                200,
                {"data": [{"name": "signal-ledger", "status": {"status": "connected"}}]},
            )
        if path == "/api/websearch/provider":
            return response(200, {"data": []})
        if path == "/api/session":
            return response(200, {"data": {"id": "sesABCDEFGH"}})
        if path == "/api/session/sesABCDEFGH/prompt":
            return response(204)
        if path == "/api/experimental/session/sesABCDEFGH/wait":
            if terminal_case in {"wait_failed", "idle_failed"}:
                await asyncio.wait_for(message_poll_started.wait(), timeout=1.0)
            if terminal_case == "wait_failed":
                return response(200, {"data": {"status": "failed", "outcome": "failed"}})
            return response(204)
        if path == "/api/session/sesABCDEFGH/message":
            nonlocal message_calls
            if terminal_case in {"wait_failed", "idle_failed"}:
                message_calls += 1
                if message_calls == 1:
                    message_poll_started.set()
                    return response(200, {"data": []})
                private_url = "https://private.example/path?token=must-not-log"
                return response(
                    200,
                    {
                        "data": [
                            {
                                "info": {
                                    "id": "msg-terminal",
                                    "role": "assistant",
                                    "finish": "error",
                                },
                                "parts": [
                                    {"type": "text", "text": "partial private answer"},
                                    {
                                        "type": "tool",
                                        "name": "webfetch",
                                        "state": {
                                            "status": "error",
                                            "error": {
                                                "type": "unknown",
                                                "message": "Request timed out for " + private_url,
                                            },
                                        },
                                    },
                                ],
                            }
                        ]
                    },
                )
            if terminal_case == "invalid_fetch":
                return response(
                    200,
                    {
                        "data": [
                            {
                                "info": {
                                    "id": "msg-invalid-fetch",
                                    "role": "assistant",
                                    "finish": "stop",
                                },
                                "parts": [
                                    {
                                        "id": "part-invalid-fetch",
                                        "type": "tool",
                                        "name": "webfetch",
                                        "state": {
                                            "status": "completed",
                                            "input": {"url": "file:///etc/passwd"},
                                            "metadata": {"finalUrl": "file:///etc/passwd"},
                                        },
                                    }
                                ],
                            }
                        ]
                    },
                )
            finish = "tool-calls" if terminal_case == "missing_finish" else "stop"
            return response(
                200,
                {
                    "data": [
                        {
                            "info": {"id": "msg-1", "role": "assistant", "finish": finish},
                            "parts": [],
                        }
                    ]
                },
            )
        if path == "/api/session/sesABCDEFGH/permission":
            return response(200, {"data": []})
        if path == "/api/session/sesABCDEFGH":
            if request.method == "DELETE":
                return response(204)
            outcome = "failed" if terminal_case == "idle_failed" else "succeeded"
            return response(200, {"data": {"outcome": outcome}})
        raise AssertionError(f"unexpected native API route {path}")

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    events: list[dict[str, object]] = []

    async def emit(event: dict[str, object]) -> None:
        events.append(event)

    async def exercise():
        assert (await runtime.start()).status == "ready"
        result = await runtime.run_turn(context=_context(), prompt="Continue", emit=emit)
        await runtime.close()
        return result

    result = asyncio.run(exercise())
    assert supervisor.removed == ["a" * 32]
    if terminal_case == "success":
        assert (result.status, result.error_code) == ("completed", None)
        assert "Assistant native terminal turn failed" not in caplog.text
    else:
        assert (result.status, result.error_code) == ("failed", "provider_unavailable")
        assert "snapshot=read" in caplog.text
        assert "Assistant native terminal turn failed" in caplog.text
    if terminal_case == "wait_failed":
        assert "session_outcome=wait_failed" in caplog.text
    elif terminal_case == "idle_failed":
        assert "session_outcome=failed" in caplog.text
    elif terminal_case in {"missing_finish", "invalid_fetch"}:
        assert "session_outcome=succeeded" in caplog.text
    if terminal_case in {"wait_failed", "idle_failed"}:
        assert "assistant_finish=error" in caplog.text
        assert "webfetch_state=error" in caplog.text
        assert "webfetch_failure=timeout" in caplog.text
        assert "webfetch_timeout_stage=request_or_native_tool_timeout" in caplog.text
        assert "webfetch_timeout_seconds_max=none" in caplog.text
        assert "webfetch_tool_elapsed_ms_max=none" in caplog.text
        assert "native_failure=timeout" in caplog.text
        assert "native_tool_error_count=1" in caplog.text
        assert "https://private.example/path?token=must-not-log" not in caplog.text
        assert "partial private answer" not in caplog.text
    elif terminal_case == "missing_finish":
        assert "assistant_finish=tool-calls" in caplog.text
        assert "native_failure=none" in caplog.text
    elif terminal_case == "invalid_fetch":
        assert "assistant_finish=stop" in caplog.text
        assert "webfetch_completion=request_invalid" in caplog.text
        assert "file:///etc/passwd" not in caplog.text
    if terminal_case == "wait_failed":
        assert [event["type"] for event in events] == ["meta"]


def test_runtime_monitor_recovers_from_bounded_cold_start_unavailability() -> None:
    """A delayed worker becomes ready for passive probes without requiring a user turn."""

    class DelayedSupervisor(_Supervisor):
        def __init__(self) -> None:
            super().__init__()
            self.status_calls = 0

        async def status(self):
            self.status_calls += 1
            if self.status_calls <= 3:
                await asyncio.sleep(1.2)
                return {"status": "starting"}
            return await super().status()

    supervisor = DelayedSupervisor()

    async def native_api(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/info"
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=_NativeBody(b'{"version":"v2"}'),
        )

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> None:
        initial = await runtime.start()
        assert initial.status == "unavailable"
        deadline = asyncio.get_running_loop().time() + 3.0
        while runtime.status().status != "ready":
            if asyncio.get_running_loop().time() >= deadline:
                raise AssertionError("passive health monitor did not recover worker readiness")
            await asyncio.sleep(0.02)
        assert supervisor.status_calls >= 2
        await runtime.close()

    asyncio.run(exercise())


def test_runtime_monitor_recheck_does_not_demote_readiness_during_turn_start() -> None:
    """A normal in-progress monitor check retains ready until it fails or succeeds."""

    class GatedRecheckSupervisor(_Supervisor):
        def __init__(self) -> None:
            super().__init__()
            self.status_calls = 0
            self.recheck_started = asyncio.Event()
            self.release_recheck = asyncio.Event()
            self.failure_recheck_started = asyncio.Event()
            self.release_failure_recheck = asyncio.Event()

        async def status(self):
            self.status_calls += 1
            if self.status_calls in {2, 4}:
                started, release = (
                    (self.recheck_started, self.release_recheck)
                    if self.status_calls == 2
                    else (self.failure_recheck_started, self.release_failure_recheck)
                )
                started.set()
                await release.wait()
            return await super().status()

    supervisor = GatedRecheckSupervisor()
    location = "/run/assistant/worker-locations/" + "a" * 32
    fail_health_check = False

    def response(status_code: int, payload: object | None = None) -> httpx.Response:
        content = json.dumps(payload).encode("utf-8") if payload is not None else b""
        headers = {"content-type": "application/json"} if payload is not None else {}
        return httpx.Response(status_code, headers=headers, stream=_NativeBody(content))

    async def native_api(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/info":
            if fail_health_check:
                return response(503)
            return response(200, {"version": "v2"})
        if path == "/api/location":
            return response(200, {"directory": location, "project": {"directory": location}})
        if path == "/api/model":
            return response(
                200,
                _native_model_payload(
                    location,
                    [{"id": "assistant-selected", "providerID": "assistant-proxy"}],
                ),
            )
        if path == "/api/mcp":
            return response(
                200,
                {"data": [{"name": "signal-ledger", "status": {"status": "connected"}}]},
            )
        if path == "/api/websearch/provider":
            return response(200, {"data": []})
        if path == "/api/session":
            return response(200, {"data": {"id": "sesABCDEFGH"}})
        if path == "/api/session/sesABCDEFGH/prompt":
            return response(204)
        if path == "/api/experimental/session/sesABCDEFGH/wait":
            return response(204)
        if path == "/api/session/sesABCDEFGH/message":
            return response(
                200,
                {
                    "data": [
                        {
                            "info": {"id": "msg-1", "role": "assistant", "finish": "stop"},
                            "parts": [],
                        }
                    ]
                },
            )
        if path == "/api/session/sesABCDEFGH/permission":
            return response(200, {"data": []})
        if path == "/api/session/sesABCDEFGH":
            if request.method == "DELETE":
                return response(204)
            return response(200, {"data": {"outcome": "succeeded"}})
        raise AssertionError(f"unexpected native API route {path}")

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> None:
        nonlocal fail_health_check
        assert (await runtime.start()).status == "ready"
        await asyncio.wait_for(supervisor.recheck_started.wait(), timeout=2.0)
        assert runtime.status().status == "ready"
        turn = asyncio.create_task(
            runtime.run_turn(
                context=_context(),
                prompt="Show my workspace summary",
                emit=lambda _event: asyncio.sleep(0),
            )
        )
        await asyncio.sleep(0)
        assert not turn.done()
        assert runtime.status().status == "ready"
        supervisor.release_recheck.set()
        result = await asyncio.wait_for(turn, timeout=3.0)
        assert result.status == "completed"
        assert runtime.status().status == "ready"

        # A later confirmed failure must still revoke readiness. A turn queued behind that
        # check cannot consume the last successful status as proof that the native worker lives.
        await asyncio.wait_for(supervisor.failure_recheck_started.wait(), timeout=2.0)
        assert runtime.status().status == "ready"
        fail_health_check = True
        failed_turn = asyncio.create_task(
            runtime.run_turn(
                context=_context("f" * 32),
                prompt="Check the worker before starting",
                emit=lambda _event: asyncio.sleep(0),
            )
        )
        await asyncio.sleep(0)
        assert not failed_turn.done()
        supervisor.release_failure_recheck.set()
        failed_result = await asyncio.wait_for(failed_turn, timeout=3.0)
        assert (failed_result.status, failed_result.error_code) == ("failed", "worker_unavailable")
        assert runtime.status().status == "unavailable"
        await runtime.close()

    asyncio.run(exercise())


def test_supervisor_observation_timeout_preserves_admitted_turn_preparations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real supervisor status uncertainty blocks admission but preserves two admitted turns."""

    class ObservationTimeoutSupervisor(_Supervisor):
        def __init__(self) -> None:
            super().__init__()
            self.uncertainty_probes: int | None = 0
            self.observe_timeout = False
            self.monitor_checks = 0
            self.monitor_started = [asyncio.Event(), asyncio.Event()]
            self.release_monitor = [asyncio.Event(), asyncio.Event()]
            self.prepare_started: set[str] = set()
            self.both_preparations_started = asyncio.Event()
            self.release_preparations = asyncio.Event()
            self.container = supervisor_service.ContainerSupervisor(
                worker_enabled=True, environment={}
            )

            class LiveWorker:
                def poll(self) -> None:
                    return None

            self.container._worker = LiveWorker()  # type: ignore[assignment]
            self.container._worker_holds["z" * 32] = time.monotonic() + 60.0

            def worker_ready() -> bool | None:
                if self.uncertainty_probes is None:
                    return None
                if self.uncertainty_probes > 0:
                    self.uncertainty_probes -= 1
                    return None
                return True

            self.container._worker_ready = worker_ready
            self.client = assistant_supervisor_client.SupervisorClient()

            async def dispatch(request: dict[str, object]) -> dict[str, object]:
                try:
                    return self.container._dispatch(request)
                except supervisor_service.SupervisorError as exc:
                    raise SupervisorClientError(exc.code) from None

            self.client._request = dispatch

        async def status(self):
            if self.observe_timeout:
                self.observe_timeout = False
                index = self.monitor_checks
                self.monitor_checks += 1
                if index < len(self.monitor_started):
                    self.monitor_started[index].set()
                    await self.release_monitor[index].wait()
            return await self.client.status()

        async def prepare_location(self, *, execution_id: str, **kwargs: object):
            self.prepare_started.add(execution_id)
            if len(self.prepare_started) == 2:
                self.both_preparations_started.set()
            await self.release_preparations.wait()
            return await self.client.prepare_location(execution_id=execution_id, **kwargs)

        async def remove_location(self, execution_id: str) -> str | None:
            self.removed.append(execution_id)
            return await self.client.remove_location(execution_id)

    monkeypatch.setattr(
        supervisor_service,
        "_write_location",
        lambda root, execution_id, _document, **_kwargs: root / execution_id,
    )
    monkeypatch.setattr(supervisor_service, "_remove_location", lambda _root, _execution_id: None)
    supervisor = ObservationTimeoutSupervisor()
    first_context = _context("a" * 32)
    second_context = replace(
        _context("b" * 32),
        user_id=42,
        conversation_id="f" * 36,
        turn_id="e" * 36,
        capability="g" * 48,
    )
    third_context = replace(
        _context("c" * 32),
        user_id=43,
        conversation_id="h" * 36,
        turn_id="i" * 36,
        capability="j" * 48,
    )
    contexts = {
        context.execution_id: context for context in (first_context, second_context, third_context)
    }
    location_calls = {first_context.execution_id: 0, second_context.execution_id: 0}
    entered_first_reads: set[str] = set()
    both_first_reads_started = asyncio.Event()
    release_location_failures = asyncio.Event()
    session_ids = ("sesSESSION01", "sesSESSION02")
    session_count = 0

    def response(status_code: int, payload: object | None = None) -> httpx.Response:
        headers: dict[str, str] = {}
        content = b""
        if payload is not None:
            headers["content-type"] = "application/json"
            content = json.dumps(payload).encode("utf-8")
        return httpx.Response(status_code, headers=headers, stream=_NativeBody(content))

    async def native_api(request: httpx.Request) -> httpx.Response:
        nonlocal session_count
        path = request.url.path
        if path == "/api/info":
            return response(200, {"version": "v2"})
        if path == "/api/location":
            params = dict(request.url.params)
            directory = params.get("location[directory]")
            assert isinstance(directory, str)
            execution_id = directory.rsplit("/", 1)[-1]
            assert execution_id in location_calls
            location_calls[execution_id] += 1
            if location_calls[execution_id] == 1:
                entered_first_reads.add(execution_id)
                if len(entered_first_reads) == 2:
                    both_first_reads_started.set()
                await both_first_reads_started.wait()
                await release_location_failures.wait()
                raise httpx.ReadTimeout("synthetic cold location read timeout")
            return response(200, {"directory": directory, "project": {"directory": directory}})
        if path == "/api/model":
            params = dict(request.url.params)
            directory = params.get("location[directory]")
            assert isinstance(directory, str)
            execution_id = directory.rsplit("/", 1)[-1]
            context = contexts[execution_id]
            return response(
                200,
                _native_model_payload(
                    directory,
                    [{"id": "assistant-selected", "providerID": "assistant-proxy"}],
                    capability=context.capability,
                ),
            )
        if path == "/api/mcp":
            return response(
                200, {"data": [{"name": "signal-ledger", "status": {"status": "connected"}}]}
            )
        if path == "/api/websearch/provider":
            return response(200, {"data": []})
        if path == "/api/session" and request.method == "POST":
            session_id = session_ids[session_count]
            session_count += 1
            return response(200, {"data": {"id": session_id}})
        for session_id in session_ids:
            if path == f"/api/session/{session_id}/prompt":
                return response(204)
            if path == f"/api/experimental/session/{session_id}/wait":
                return response(204)
            if path == f"/api/session/{session_id}/permission":
                return response(200, {"data": []})
            if path == f"/api/session/{session_id}/message":
                return response(
                    200,
                    {
                        "data": [
                            {
                                "info": {
                                    "id": f"message-{session_id}",
                                    "role": "assistant",
                                    "finish": "stop",
                                },
                                "parts": [],
                            }
                        ]
                    },
                )
            if path == f"/api/session/{session_id}":
                if request.method == "DELETE":
                    return response(204)
                return response(200, {"data": {"outcome": "succeeded"}})
        raise AssertionError(f"unexpected native API route {request.method} {path}")

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> tuple[list[AssistantTurnResult], AssistantTurnResult]:
        try:
            assert (await runtime.start()).status == "ready"
            original_client = runtime._client
            monitor = runtime._monitor_task
            assert monitor is not None
            monitor.cancel()
            with pytest.raises(asyncio.CancelledError):
                await monitor
            # Keep startup from creating a background poller; this test drives exact
            # observation windows itself through the same public start() check.
            runtime._monitor_task = asyncio.create_task(asyncio.Event().wait())
            turns = [
                asyncio.create_task(
                    runtime.run_turn(
                        context=context,
                        prompt="Read the workspace summary",
                        emit=lambda _event: asyncio.sleep(0),
                    )
                )
                for context in (first_context, second_context)
            ]
            await asyncio.wait_for(supervisor.both_preparations_started.wait(), timeout=2.0)
            assert runtime._locations == {}
            assert supervisor.container._locations == {}
            supervisor.uncertainty_probes = 1
            supervisor.observe_timeout = True
            first_health_check = asyncio.create_task(runtime.start(preserve_ready=True))
            await asyncio.wait_for(supervisor.monitor_started[0].wait(), timeout=2.5)
            supervisor.release_monitor[0].set()
            first_health = await asyncio.wait_for(first_health_check, timeout=4.0)
            assert first_health.status == "ready"
            assert runtime._client is original_client
            runtime._require_ready_worker()

            supervisor.uncertainty_probes = None
            supervisor.observe_timeout = True
            second_health_check = asyncio.create_task(runtime.start(preserve_ready=True))
            await asyncio.wait_for(supervisor.monitor_started[1].wait(), timeout=2.5)
            supervisor.release_monitor[1].set()
            second_health = await asyncio.wait_for(second_health_check, timeout=4.0)
            assert second_health.status == "unavailable"
            assert runtime._enabled is True
            assert runtime._transport_verified is True
            assert runtime._client is original_client

            rejected_turn = await runtime.run_turn(
                context=third_context,
                prompt="This call must wait for a fresh successful health check",
                emit=lambda _event: asyncio.sleep(0),
            )
            assert (rejected_turn.status, rejected_turn.error_code) == (
                "failed",
                "worker_unavailable",
            )
            assert third_context.execution_id not in supervisor.prepare_started

            supervisor.release_preparations.set()
            await asyncio.wait_for(both_first_reads_started.wait(), timeout=1.0)
            release_location_failures.set()
            results = await asyncio.wait_for(asyncio.gather(*turns), timeout=3.0)
            return results, rejected_turn
        finally:
            supervisor.release_preparations.set()
            release_location_failures.set()
            for release in supervisor.release_monitor:
                release.set()
            await runtime.close()

    results, rejected_turn = asyncio.run(exercise())

    assert all(result.status == "completed" for result in results), [
        (result.status, result.error_code) for result in results
    ]
    assert all(location_calls[execution_id] == 2 for execution_id in location_calls)
    assert rejected_turn.error_code == "worker_unavailable"
    assert session_count == 2


def test_foreground_health_recheck_keeps_readiness_for_concurrent_owner_turn() -> None:
    """Ordinary positive rechecks keep ready visible while startup is serialized."""

    class GatedSupervisor(_Supervisor):
        def __init__(self) -> None:
            super().__init__()
            self.status_calls = 0
            self.foreground_check_started = asyncio.Event()
            self.release_foreground_check = asyncio.Event()

        async def status(self):
            self.status_calls += 1
            if self.status_calls == 2:
                self.foreground_check_started.set()
                await self.release_foreground_check.wait()
            return await super().status()

    class EmptyCatalog:
        def get_model(self, model_id: str) -> None:
            del model_id
            return None

    supervisor = GatedSupervisor()

    async def native_api(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/info"
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=_NativeBody(b'{"version":"v2"}'),
        )

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=EmptyCatalog(),
        supervisor=supervisor,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )
    service = AssistantService(
        settings=SimpleNamespace(assistant_enabled=True),
        repository=object(),
        forecast_service=object(),
        auth_manager=object(),
        runtime=runtime,
        catalog=EmptyCatalog(),
        providers=_TestProviders(),
    )

    async def exercise() -> None:
        assert (await runtime.start()).status == "ready"
        monitor, runtime._monitor_task = runtime._monitor_task, None
        assert monitor is not None
        monitor.cancel()
        with pytest.raises(asyncio.CancelledError):
            await monitor

        loop = asyncio.get_running_loop()
        service._runtime_last_start_attempt = loop.time()
        first_context = replace(_context(), user_id=41)
        second_context = replace(
            _context("b" * 32),
            user_id=42,
            conversation_id="f" * 36,
            turn_id="e" * 36,
            capability="g" * 48,
        )
        first_turn = asyncio.create_task(
            runtime.run_turn(
                context=first_context,
                prompt="First synthetic owner",
                emit=lambda _event: asyncio.sleep(0),
            )
        )
        await asyncio.wait_for(supervisor.foreground_check_started.wait(), timeout=1.0)

        # This is the same app preflight used by the second owner's create-turn request.
        service._runtime_last_start_attempt = loop.time()
        await service._ensure_runtime_ready()
        assert runtime.status().status == "ready"

        second_turn = asyncio.create_task(
            runtime.run_turn(
                context=second_context,
                prompt="Second synthetic owner",
                emit=lambda _event: asyncio.sleep(0),
            )
        )
        await asyncio.sleep(0)
        assert not second_turn.done()

        supervisor.release_foreground_check.set()
        first_result, second_result = await asyncio.wait_for(
            asyncio.gather(first_turn, second_turn), timeout=2.0
        )
        assert (first_result.status, first_result.error_code) == (
            "failed",
            "provider_unavailable",
        )
        assert (second_result.status, second_result.error_code) == (
            "failed",
            "provider_unavailable",
        )
        assert supervisor.status_calls == 3
        await runtime.close()

    asyncio.run(exercise())


def test_runtime_close_serializes_with_start_and_prevents_client_resurrection() -> None:
    """A close queued during native readiness closes the client after startup leaves its lock."""

    class GatedSupervisor(_Supervisor):
        def __init__(self) -> None:
            super().__init__()
            self.api_started = asyncio.Event()
            self.release_api = asyncio.Event()

    supervisor = GatedSupervisor()
    calls: list[str] = []
    client_closed = False

    async def native_api(request: httpx.Request) -> httpx.Response:
        nonlocal client_closed
        if client_closed:
            calls.append("request_after_close")
            raise AssertionError("runtime called a closed native client")
        calls.append(request.url.path)
        supervisor.api_started.set()
        await supervisor.release_api.wait()
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=_NativeBody(b'{"version":"v2"}'),
        )

    class TrackingClient(httpx.AsyncClient):
        async def aclose(self) -> None:
            nonlocal client_closed
            client_closed = True
            await super().aclose()

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
        http_client_factory=lambda **kwargs: TrackingClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> None:
        start_task = asyncio.create_task(runtime.start())
        await asyncio.wait_for(supervisor.api_started.wait(), timeout=1.0)
        close_task = asyncio.create_task(runtime.close())
        await asyncio.sleep(0)
        assert runtime._killed is True
        supervisor.release_api.set()
        await asyncio.wait_for(asyncio.gather(start_task, close_task), timeout=2.0)
        assert runtime._client is None
        assert runtime.status().status == "stopped"
        assert client_closed is True
        call_count = len(calls)
        await runtime.start()
        assert len(calls) == call_count
        assert "request_after_close" not in calls
        assert runtime._monitor_task is None

    asyncio.run(exercise())


def test_runtime_classifies_native_location_setup_failure_as_worker_unavailable() -> None:
    """A local worker/config preparation error is not reported as bad provider credentials."""

    class FailedLocationSupervisor(_Supervisor):
        async def prepare_location(self, **_values: object) -> dict[str, str]:
            raise RuntimeError("native location configuration was rejected")

    async def native_api(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/info"
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=_NativeBody(b'{"version":"v2"}'),
        )

    supervisor = FailedLocationSupervisor()
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise():
        assert (await runtime.start()).status == "ready"
        result = await runtime.run_turn(
            context=_context(), prompt="Continue", emit=lambda _event: asyncio.sleep(0)
        )
        await runtime.close()
        return result

    result = asyncio.run(exercise())
    assert (result.status, result.error_code) == ("failed", "worker_unavailable")
    assert supervisor.removed == ["a" * 32]


def test_runtime_timing_records_closed_early_startup_failure(capsys: pytest.CaptureFixture) -> None:
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=False),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=_Supervisor(),
    )
    context = _context()

    async def exercise() -> AssistantTurnResult:
        result = await runtime.run_turn(
            context=context,
            prompt="Synthetic startup classification",
            emit=lambda _event: asyncio.sleep(0),
        )
        runtime._finish_turn_timing_diagnostic(context.execution_id, context.user_id, "failed")
        return result

    result = asyncio.run(exercise())

    assert (result.status, result.error_code) == ("failed", "worker_unavailable")
    stderr = capsys.readouterr().err
    assert stderr.startswith(assistant_runtime._TURN_TIMING_LOG_MARKER)
    receipt = json.loads(stderr.removeprefix(assistant_runtime._TURN_TIMING_LOG_MARKER))
    assert (receipt["pre_session_phase"], receipt["pre_session_failure_code"]) == (
        "startup",
        "worker_unavailable",
    )
    assert context.execution_id not in stderr
    assert "Synthetic startup classification" not in stderr


@pytest.mark.parametrize(
    ("supervisor_code", "diagnostic_code"),
    [
        ("location_unavailable", "location_unavailable"),
        ("credential=synthetic-private-marker", "diagnostic_unknown"),
    ],
)
def test_runtime_logs_only_fixed_phase_and_allowlisted_supervisor_code(
    caplog: pytest.LogCaptureFixture,
    supervisor_code: str,
    diagnostic_code: str,
) -> None:
    """Setup diagnostics keep typed supervisor codes closed and never log exception text."""

    class FailedLocationSupervisor(_Supervisor):
        async def prepare_location(self, **_values: object) -> dict[str, str]:
            raise SupervisorClientError(supervisor_code)

    async def native_api(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/info"
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=_NativeBody(b'{"version":"v2"}'),
        )

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=FailedLocationSupervisor(),
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise():
        assert (await runtime.start()).status == "ready"
        result = await runtime.run_turn(
            context=_context(), prompt="Synthetic setup probe", emit=lambda _event: asyncio.sleep(0)
        )
        await runtime.close()
        return result

    result = asyncio.run(exercise())
    assert (result.status, result.error_code) == ("failed", "worker_unavailable")
    assert f"phase=prepare_location, supervisor_code={diagnostic_code}" in caplog.text
    if diagnostic_code == "diagnostic_unknown":
        assert supervisor_code not in caplog.text


def test_failed_native_session_is_interrupted_before_delete_while_other_turn_finishes() -> None:
    """Stop the failed session explicitly without interrupting an unrelated native turn."""

    supervisor = _Supervisor()
    bad_session = "sesFAILEDSESSION"
    good_session = "sesGOODSESSION"
    bad_interrupted = False
    session_counter = 0
    request_paths: list[str] = []
    bad_activity_after_interrupt: list[str] = []
    bad_session_calls: list[str] = []

    def response(status_code: int, payload: object | None = None) -> httpx.Response:
        content = json.dumps(payload).encode() if payload is not None else b""
        headers = {"content-type": "application/json"} if payload is not None else {}
        return httpx.Response(status_code, headers=headers, stream=_NativeBody(content))

    async def native_api(request: httpx.Request) -> httpx.Response:
        nonlocal bad_interrupted, session_counter
        path = request.url.path
        request_paths.append(f"{request.method} {path}")
        if path == "/api/info":
            return response(200, {"version": "v2"})
        if path == "/api/location":
            directory = request.url.params.get("location[directory]", "")
            return response(200, {"directory": directory, "project": {"directory": directory}})
        if path == "/api/model":
            directory = request.url.params.get("location[directory]", "")
            execution_id = directory.rsplit("/", 1)[-1]
            capability = {"a" * 32: "d" * 48, "f" * 32: "d" * 48}[execution_id]
            return response(
                200,
                _native_model_payload(
                    directory,
                    [{"id": "assistant-selected", "providerID": "assistant-proxy"}],
                    capability=capability,
                ),
            )
        if path == "/api/mcp":
            return response(
                200, {"data": [{"name": "signal-ledger", "status": {"status": "connected"}}]}
            )
        if path == "/api/websearch/provider":
            return response(200, {"data": []})
        if path == "/api/session":
            session_counter += 1
            session_id = bad_session if session_counter == 1 else good_session
            return response(200, {"data": {"id": session_id}})
        if path.endswith("/permission") and request.method == "GET":
            session_id = path.split("/")[3]
            if session_id == bad_session:
                bad_session_calls.append("permission")
            return response(200, {"data": []})
        if path.endswith("/prompt"):
            session_id = path.split("/")[3]
            if session_id == bad_session:
                bad_session_calls.append("prompt")
            return response(204)
        if path == f"/api/experimental/session/{bad_session}/wait":
            return response(200, {"data": {"status": "failed", "outcome": "failed"}})
        if path == f"/api/experimental/session/{good_session}/wait":
            return response(204)
        if path.endswith("/message") and request.method == "GET":
            session_id = path.split("/")[3]
            if session_id == bad_session:
                bad_session_calls.append("messages")
                if bad_interrupted:
                    bad_activity_after_interrupt.append("messages")
                return response(200, {"data": []})
            return response(
                200,
                {
                    "data": [
                        {
                            "type": "assistant",
                            "id": "msg-good",
                            "finish": "stop",
                            "content": [
                                {
                                    "type": "text",
                                    "id": "part-good",
                                    "text": "Other owner completed.",
                                }
                            ],
                        }
                    ]
                },
            )
        if path == f"/api/session/{good_session}":
            return response(200, {"data": {"outcome": "succeeded"}})
        if path == f"/api/session/{bad_session}/interrupt" and request.method == "POST":
            bad_interrupted = True
            bad_session_calls.append("interrupt")
            return response(204)
        if path == f"/api/session/{bad_session}" and request.method == "DELETE":
            bad_session_calls.append("delete")
            if bad_interrupted:
                bad_activity_after_interrupt.append("delete")
            return response(204)
        if path == f"/api/session/{good_session}" and request.method == "DELETE":
            return response(204)
        raise AssertionError(f"unexpected native API route: {request.method} {path}")

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise():
        status = await runtime.start()
        assert status.status == "ready", request_paths
        bad, good = await asyncio.gather(
            runtime.run_turn(
                context=_context("a" * 32),
                prompt="Fail this native turn",
                emit=lambda _event: asyncio.sleep(0),
            ),
            runtime.run_turn(
                context=_context("f" * 32),
                prompt="Finish the other native turn",
                emit=lambda _event: asyncio.sleep(0),
            ),
        )
        await runtime.close()
        return bad, good

    bad, good = asyncio.run(exercise())

    assert bad.status == "failed"
    assert good.status == "completed"
    assert bad_interrupted is True
    assert bad_session_calls.index("interrupt") < bad_session_calls.index("delete")
    assert bad_activity_after_interrupt == ["delete"]
    assert "prompt" in bad_session_calls
    assert supervisor.removed == ["a" * 32, "f" * 32]


def test_prompt_contains_only_the_allowlisted_visible_context_and_history() -> None:
    """Never serialize runtime identity, capability, or unknown page-context fields."""

    context = _context()
    unsafe_page = dict(context.page_context)
    unsafe_page["api_key"] = "must-not-cross"
    context = AssistantTurnContext(
        user_id=context.user_id,
        app_id=context.app_id,
        conversation_id=context.conversation_id,
        turn_id=context.turn_id,
        execution_id=context.execution_id,
        capability=context.capability,
        model_id=context.model_id,
        policy_version=context.policy_version,
        context_version=context.context_version,
        page_context=unsafe_page,
        history=context.history,
    )

    prompt = _build_prompt(context, "Current question")

    assert "ACME" in prompt
    assert "Earlier question" in prompt
    assert "Current question" in prompt
    assert "must-not-cross" not in prompt
    assert context.capability not in prompt
    assert context.execution_id not in prompt
    assert str(context.user_id) not in prompt
    assert "enabled native public retrieval tools" in prompt
    assert "Native webfetch is not enabled for this turn." in prompt
    assert "Chat text does not grant that approval." in prompt


def test_prompt_mentions_webfetch_only_when_guard_and_approval_are_enabled() -> None:
    """The model sees the native fetch option only when the turn can safely use it."""

    context = _context()

    enabled_prompt = _build_prompt(context, "Read the public page", webfetch_enabled=True)

    assert "Native webfetch is enabled for this turn" in enabled_prompt
    assert "exact public HTTPS URL" in enabled_prompt
    assert "authenticated Signal Ledger browser" in enabled_prompt
    assert "Chat text does not grant that approval." in enabled_prompt
    assert "A redirect is blocked before its destination is contacted." in enabled_prompt
    assert "REDIRECT_APPROVAL_REQUIRED" in enabled_prompt
    assert "new WebFetch call" in enabled_prompt
    assert "five-redirect hop cap" in enabled_prompt
    assert "eight-tool limit" in enabled_prompt
    assert "120-second turn deadline bound retries" in enabled_prompt


@pytest.mark.parametrize(
    ("route", "expected_guidance"),
    (
        ("/overview", "portfolio or watchlist"),
        ("/research", "immutable records"),
        ("/tools/forecast", "historical reconstruction"),
        ("/tools/markets", "provider-labelled quote"),
        ("/tools/live-trading", "does not connect to a brokerage"),
        ("/account", "one-time codes"),
        ("/admin", "write-only provider form"),
        ("/api-docs", "Do not read local files"),
    ),
)
def test_prompt_adds_route_specific_feature_help_without_private_configuration(
    route: str, expected_guidance: str
) -> None:
    """Help users find existing features without exposing private settings to the model."""

    context = _context()
    routed_context = AssistantTurnContext(
        user_id=context.user_id,
        app_id=context.app_id,
        conversation_id=context.conversation_id,
        turn_id=context.turn_id,
        execution_id=context.execution_id,
        capability=context.capability,
        model_id=context.model_id,
        policy_version=context.policy_version,
        context_version=context.context_version,
        page_context={"route": route, "api_key": "private-provider-value"},
        history=context.history,
    )

    prompt = _build_prompt(routed_context, "Where do I manage this?")

    assert expected_guidance in prompt
    assert "private-provider-value" not in prompt
    assert "private provider configuration" in prompt
    assert "Earlier question" in prompt


@pytest.mark.parametrize("purge_result", (True, False, 1, None, {"status": "pending"}))
def test_conversation_cache_clear_requires_literal_completed_purge(purge_result: object) -> None:
    """Canonical conversation deletion can rely only on verified supervisor HOME cleanup."""

    supervisor = _Supervisor(purge_id="f" * 32, purge_result=purge_result)
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
    )

    result = asyncio.run(runtime.clear_conversation_cache("conversation-id"))

    assert result is (purge_result is True)
    assert supervisor.purge_waits == [("f" * 32, 20.0)]


@pytest.mark.parametrize("reconnect_raises", (False, True))
def test_conversation_cache_clear_confirms_purge_when_reconnect_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, reconnect_raises: bool
) -> None:
    """A verified HOME wipe remains confirmed when the worker API is still reconnecting."""

    supervisor = _Supervisor(purge_id="f" * 32, purge_result=True)
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
    )
    reconnect_calls: list[bool] = []

    async def reconnect() -> bool:
        reconnect_calls.append(True)
        runtime._enabled = False
        runtime._transport_verified = False
        runtime._webfetch_guard_ready = False
        runtime._status = AssistantRuntimeStatus(
            "unavailable", "The assistant worker is unavailable."
        )
        if reconnect_raises:
            raise RuntimeError("synthetic reconnect detail")
        return False

    monkeypatch.setattr(runtime, "_refresh_after_home_purge", reconnect)

    result = asyncio.run(runtime.clear_conversation_cache("conversation-id"))

    assert result is True
    assert runtime.status().status == "unavailable"
    assert runtime._enabled is False
    assert runtime._transport_verified is False
    assert reconnect_calls == [True]
    assert supervisor.purge_waits == [("f" * 32, 20.0)]


def test_conversation_cache_clear_rejects_malformed_purge_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supervisor = _Supervisor(purge_id="not-a-purge-id", purge_result=True)
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
    )
    reconnect_calls: list[bool] = []

    async def reconnect() -> bool:
        reconnect_calls.append(True)
        return True

    monkeypatch.setattr(runtime, "_refresh_after_home_purge", reconnect)

    assert asyncio.run(runtime.clear_conversation_cache("conversation-id")) is False
    assert supervisor.purge_waits == []
    assert reconnect_calls == []


def test_conversation_cache_clear_fails_closed_on_purge_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supervisor = _Supervisor(purge_id="f" * 32, purge_result=True)
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_TestProviders(),
        catalog=_Catalog(),
        supervisor=supervisor,
    )
    reconnect_calls: list[bool] = []

    async def fail_wait(_purge_id: str, *, timeout: float) -> object:
        assert timeout == 20.0
        raise RuntimeError("synthetic purge failure")

    async def reconnect() -> bool:
        reconnect_calls.append(True)
        return True

    monkeypatch.setattr(supervisor, "wait_for_home_purge", fail_wait)
    monkeypatch.setattr(runtime, "_refresh_after_home_purge", reconnect)

    assert asyncio.run(runtime.clear_conversation_cache("conversation-id")) is False
    assert supervisor.purge_waits == []
    assert reconnect_calls == []


@pytest.mark.parametrize(
    ("permission", "resources", "approval_result", "expected"),
    (
        ("websearch", {"patterns": ["public market hours"]}, "public market hours", "once"),
        ("websearch", {"patterns": ["public market hours"]}, "a different query", "reject"),
        ("webfetch", {"patterns": ["https://example.test"]}, "https://example.test", "reject"),
        ("websearch", {"patterns": ["query one", "query two"]}, "query one", "reject"),
    ),
)
def test_native_search_permission_requires_exact_backend_approval(
    permission: str, resources: object, approval_result: str, expected: str
) -> None:
    """Only one exact native websearch resource can receive a one-time approval."""

    async def approval(_context, query: str, _emit) -> str | None:
        assert query == "public market hours"
        return approval_result

    bridge = NativeSearchPermissionBridge(approval)
    context = _context()

    async def exercise():
        return await bridge.decide(
            context=context,
            permission=permission,
            resources=resources,
            emit=lambda _event: asyncio.sleep(0),
        )

    result = asyncio.run(exercise())
    assert result.decision == expected


@pytest.mark.parametrize(
    ("resources", "approval_result", "expected"),
    (
        (
            ["https://example.test/reports/2026?q=public%2Fdata#section"],
            "https://example.test/reports/2026?q=public%2Fdata#section",
            "once",
        ),
        (["https://example.test/report"], "https://example.test/other", "reject"),
        (["http://example.test/report"], "http://example.test/report", "reject"),
        (
            ["https://user:pass@example.test/report"],
            "https://user:pass@example.test/report",
            "reject",
        ),
        (["https://127.0.0.1/report"], "https://127.0.0.1/report", "reject"),
        (["https://example.test:8443/report"], "https://example.test:8443/report", "reject"),
        (["https://example.test/report?access_token=private"], "", "reject"),
        (["https://example.test/report?%74oken=synthetic"], "", "reject"),
        (["https://example.test/report?access%5Ftoken=synthetic"], "", "reject"),
        (["https://example.test/report?api%5fkey=synthetic"], "", "reject"),
        (["https://example.test/report?%2574oken=synthetic"], "", "reject"),
        (["https://example.test/report?password%ZZ=synthetic"], "", "reject"),
        (["https://example.test/report", "https://example.test/other"], "", "reject"),
        ({"patterns": ["https://example.test/report"]}, "", "reject"),
    ),
)
def test_native_webfetch_permission_requires_exact_public_destination_approval(
    resources: object, approval_result: str, expected: str
) -> None:
    """Native webfetch is approved only for one exact public HTTPS destination."""

    observed: list[str] = []

    async def approve_exact_destination(
        _context: AssistantTurnContext, destination: str, _emit: EventEmitter
    ) -> str | None:
        observed.append(destination)
        return approval_result

    bridge = NativeSearchPermissionBridge(None, approve_exact_destination)

    async def exercise():
        return await bridge.decide(
            context=_context(),
            permission="webfetch",
            resources=resources,
            emit=lambda _event: asyncio.sleep(0),
        )

    decision = asyncio.run(exercise())
    assert decision.decision == expected
    if expected == "once":
        assert observed == [approval_result]
        assert decision.reason == "exact_fetch_approved"
    elif (
        isinstance(resources, list)
        and len(resources) == 1
        and resources[0] == "https://example.test/report"
    ):
        assert observed == [resources[0]]
