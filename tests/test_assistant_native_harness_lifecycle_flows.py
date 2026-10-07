"""Exercise native OpenCode V2 OAuth and failed-turn control flows over bounded HTTP."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from types import SimpleNamespace

import httpx
import pytest

from stock_probs.assistant.native_provider_adapters import (
    NativeAdapterDescriptor,
    resolve_native_adapter,
)
from stock_probs.assistant.runtime import OpenCodeV2Runtime
from stock_probs.assistant.schemas import AssistantTurnContext

_OWNER_ID = 41
_SESSION_ID = "e" * 32
_OTHER_SESSION_ID = "f" * 32
_ATTEMPT_ID = "a" * 32
_CAPABILITY = "b" * 32
_EXECUTION_ID = "c" * 32
_NATIVE_ATTEMPT_ID = "con_fixture_attempt"
_NATIVE_SESSION_ID = "sesFixture1234"
_MODEL_ID = "fixture-provider/native-lifecycle"

_NativeHandler = Callable[[httpx.Request], Awaitable[httpx.Response]]


class _LifecycleSupervisor:
    """Record worker holds and per-turn location cleanup around a fake V2 server."""

    def __init__(self) -> None:
        self.worker_holds: list[str] = []
        self.worker_releases: list[str] = []
        self.prepared: list[str] = []
        self.removed: list[str] = []

    async def status(self) -> dict[str, object]:
        """Report the one fixed, ready loopback worker used by the harness."""

        return {
            "status": "ready",
            "api_url": "http://127.0.0.1:4097",
            "api_password": "s" * 48,
            "webfetch_guard_ready": False,
            "observation_uncertain": False,
        }

    async def hold_worker(self, lease_id: str) -> None:
        """Record the OAuth worker-home lease."""

        self.worker_holds.append(lease_id)

    async def release_worker(self, lease_id: str) -> None:
        """Record lease release after completion, cancellation, or failure."""

        self.worker_releases.append(lease_id)

    async def prepare_location(self, *, execution_id: str, **_kwargs: object) -> dict[str, str]:
        """Return the exact per-turn directory required by the runtime contract."""

        self.prepared.append(execution_id)
        return {"directory": f"/run/assistant/worker-locations/{execution_id}"}

    async def remove_location(self, execution_id: str) -> None:
        """Record location removal after the ephemeral session terminates."""

        self.removed.append(execution_id)


class _LifecycleCatalog:
    """Provide one synthetic model for the public turn API tests."""

    def get_model(self, model_id: str) -> object | None:
        if model_id != _MODEL_ID:
            return None
        return SimpleNamespace(model_id=model_id, available=True, provider_id="opencode-zen")


class _LifecycleProviders:
    """Resolve only the checked-in OpenAI-compatible adapter fixture."""

    def model_policy_state(self, _model_id: str, *, owner_id: int) -> dict[str, bool]:
        assert owner_id == _OWNER_ID
        return {"usable": True}

    def native_execution_descriptor(
        self, _model_id: str, *, owner_id: int
    ) -> NativeAdapterDescriptor:
        assert owner_id == _OWNER_ID
        return resolve_native_adapter("openai-compatible-chat", "assistant-proxy")


class _NativeBody(httpx.AsyncByteStream):
    """Supply one raw response chunk through the runtime's streaming HTTP reader."""

    def __init__(self, content: bytes) -> None:
        self.content = content

    async def __aiter__(self) -> AsyncIterator[bytes]:
        if self.content:
            yield self.content

    async def aclose(self) -> None:
        return None


def _make_runtime(
    native_api: _NativeHandler,
) -> tuple[OpenCodeV2Runtime, _LifecycleSupervisor]:
    """Build a runtime whose only network boundary is an in-memory V2 HTTP handler."""

    supervisor = _LifecycleSupervisor()
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_LifecycleProviders(),
        catalog=_LifecycleCatalog(),
        supervisor=supervisor,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )
    return runtime, supervisor


def _response(status: int, payload: object | None = None) -> httpx.Response:
    headers: dict[str, str] = {}
    content = b""
    if payload is not None:
        headers["content-type"] = "application/json"
        content = json.dumps(payload).encode("utf-8")
    return httpx.Response(status, headers=headers, stream=_NativeBody(content))


def _launch_payload() -> dict[str, object]:
    now = int(time.time() * 1000)
    return {
        "data": {
            "attemptID": _NATIVE_ATTEMPT_ID,
            "url": "https://auth.openai.com/oauth/authorize?fixture=1",
            "instructions": "Complete sign-in in the browser.",
            "mode": "auto",
            "time": {"created": now, "expires": now + 300_000},
        }
    }


def _turn_context() -> AssistantTurnContext:
    return AssistantTurnContext(
        user_id=_OWNER_ID,
        app_id="signal-ledger",
        conversation_id="d" * 36,
        turn_id="e" * 36,
        execution_id=_EXECUTION_ID,
        capability="g" * 48,
        model_id=_MODEL_ID,
        policy_version="fixture-policy",
        context_version="h" * 64,
        page_context={"route": "/overview"},
        history=(),
    )


def test_native_integration_listing_projects_only_allowlisted_oauth_methods() -> None:
    """The V2 integration response exposes only the pinned OAuth method projection."""

    requests: list[tuple[str, str]] = []

    async def native_api(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/api/info":
            return _response(200, {"version": "v2"})
        if request.url.path == "/api/integration":
            return _response(
                200,
                {
                    "data": [
                        {
                            "id": "openai",
                            "name": "Native provider display name",
                            "methods": [
                                {
                                    "id": "chatgpt-browser",
                                    "type": "oauth",
                                    "label": "Untrusted native label",
                                    "form": {"fields": ["discarded"]},
                                },
                                {"id": "chatgpt-browser", "type": "oauth", "label": "Duplicate"},
                                {"id": "native-shell", "type": "terminal", "label": "Unsupported"},
                            ],
                        },
                        {
                            "id": "opencode",
                            "methods": [
                                {"id": "device", "type": "oauth", "label": "Device sign-in"}
                            ],
                        },
                        {"id": "unreviewed-provider", "methods": []},
                    ],
                },
            )
        raise AssertionError(f"unexpected native V2 request: {request.method} {request.url.path}")

    runtime, _supervisor = _make_runtime(native_api)

    async def exercise() -> list[dict[str, object]]:
        try:
            return await runtime.list_native_integrations()
        finally:
            await runtime.close()

    integrations = asyncio.run(exercise())

    assert [row["integration_id"] for row in integrations] == ["openai", "opencode"]
    openai_methods = integrations[0]["methods"]
    assert isinstance(openai_methods, list)
    assert openai_methods == [
        {
            "method_id": "chatgpt-browser",
            "kind": "oauth",
            "label": "ChatGPT browser sign-in",
            "application_state": "oauth_handoff_pending",
            "application_usable": False,
        }
    ]
    assert integrations[0]["unsupported_method_count"] == 2
    assert integrations[1]["methods"] == [
        {
            "method_id": "device",
            "kind": "oauth",
            "label": "OpenCode device sign-in",
            "application_state": "oauth_handoff_pending",
            "application_usable": False,
        }
    ]
    assert "form" not in json.dumps(integrations)
    assert "Untrusted native label" not in json.dumps(integrations)
    assert requests == [("GET", "/api/info"), ("GET", "/api/integration")]


def test_native_oauth_attempt_is_actor_bound_and_stale_broker_attempt_releases_hold() -> None:
    """Wrong owners cannot poll or cancel; a stale V2 attempt cannot be handed off."""

    requests: list[tuple[str, str]] = []

    async def native_api(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/api/info":
            return _response(200, {"version": "v2"})
        if request.url.path == "/api/integration/openai/connect/oauth":
            assert request.method == "POST"
            body = json.loads(request.content)
            assert body["methodID"] == "chatgpt-browser"
            assert body["assistantOAuth"] == {"attemptID": _ATTEMPT_ID, "capability": _CAPABILITY}
            return _response(200, _launch_payload())
        if request.url.path == f"/api/integration/openai/connect/oauth/{_NATIVE_ATTEMPT_ID}":
            assert request.method == "GET"
            return _response(404, {"error": {"name": "NotFoundError"}})
        raise AssertionError(f"unexpected native V2 request: {request.method} {request.url.path}")

    runtime, supervisor = _make_runtime(native_api)

    async def exercise() -> None:
        try:
            launch = await runtime.begin_native_oauth(
                "openai",
                "chatgpt-browser",
                attempt_id=_ATTEMPT_ID,
                capability=_CAPABILITY,
                owner_id=_OWNER_ID,
                session_id=_SESSION_ID,
            )
            assert launch["native_attempt_id"] == _NATIVE_ATTEMPT_ID
            assert supervisor.worker_holds == [_ATTEMPT_ID]

            before_rejected_calls = list(requests)
            with pytest.raises(RuntimeError, match="native_oauth_attempt_unavailable"):
                await runtime.native_oauth_status(
                    "openai", _ATTEMPT_ID, owner_id=_OWNER_ID + 1, session_id=_SESSION_ID
                )
            with pytest.raises(RuntimeError, match="native_oauth_attempt_unavailable"):
                await runtime.native_oauth_status(
                    "openai", _ATTEMPT_ID, owner_id=_OWNER_ID, session_id=_OTHER_SESSION_ID
                )
            with pytest.raises(RuntimeError, match="native_oauth_attempt_unavailable"):
                await runtime.cancel_native_oauth(
                    "openai", _ATTEMPT_ID, owner_id=_OWNER_ID, session_id=_OTHER_SESSION_ID
                )
            assert requests == before_rejected_calls
            assert supervisor.worker_releases == []

            assert (
                await runtime.native_oauth_status(
                    "openai", _ATTEMPT_ID, owner_id=_OWNER_ID, session_id=_SESSION_ID
                )
                == "cancelled"
            )
            assert (
                await runtime.native_oauth_status(
                    "openai", _ATTEMPT_ID, owner_id=_OWNER_ID, session_id=_SESSION_ID
                )
                == "cancelled"
            )
            with pytest.raises(RuntimeError, match="native_oauth_attempt_unavailable"):
                await runtime.take_native_oauth_handoff(
                    "openai", _ATTEMPT_ID, owner_id=_OWNER_ID, session_id=_SESSION_ID
                )
            assert supervisor.worker_releases == [_ATTEMPT_ID]
            assert runtime.status().status == "ready"
        finally:
            await runtime.close()

    asyncio.run(exercise())
    assert (
        requests.count(("GET", f"/api/integration/openai/connect/oauth/{_NATIVE_ATTEMPT_ID}")) == 1
    )
    assert not any(path.endswith("/handoff") for _method, path in requests)


def test_native_oauth_cancel_releases_hold_after_failed_native_delete() -> None:
    """A failed best-effort V2 delete still clears the app attempt and its worker lease."""

    requests: list[tuple[str, str]] = []

    async def native_api(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/api/info":
            return _response(200, {"version": "v2"})
        if request.url.path == "/api/integration/openai/connect/oauth":
            return _response(200, _launch_payload())
        if request.url.path == f"/api/integration/openai/connect/oauth/{_NATIVE_ATTEMPT_ID}":
            assert request.method == "DELETE"
            return _response(503, {"error": {"name": "TemporaryFailure"}})
        raise AssertionError(f"unexpected native V2 request: {request.method} {request.url.path}")

    runtime, supervisor = _make_runtime(native_api)

    async def exercise() -> None:
        try:
            await runtime.begin_native_oauth(
                "openai",
                "chatgpt-browser",
                attempt_id=_ATTEMPT_ID,
                capability=_CAPABILITY,
                owner_id=_OWNER_ID,
                session_id=_SESSION_ID,
            )
            before_rejected_cancel = list(requests)
            with pytest.raises(RuntimeError, match="native_oauth_attempt_unavailable"):
                await runtime.cancel_native_oauth(
                    "openai", _ATTEMPT_ID, owner_id=_OWNER_ID, session_id=_OTHER_SESSION_ID
                )
            assert requests == before_rejected_cancel
            assert supervisor.worker_releases == []

            await runtime.cancel_native_oauth(
                "openai", _ATTEMPT_ID, owner_id=_OWNER_ID, session_id=_SESSION_ID
            )
            assert supervisor.worker_releases == [_ATTEMPT_ID]
            assert (
                await runtime.native_oauth_status(
                    "openai", _ATTEMPT_ID, owner_id=_OWNER_ID, session_id=_SESSION_ID
                )
                == "cancelled"
            )
            with pytest.raises(RuntimeError, match="native_oauth_attempt_unavailable"):
                await runtime.take_native_oauth_handoff(
                    "openai", _ATTEMPT_ID, owner_id=_OWNER_ID, session_id=_SESSION_ID
                )
            assert runtime.status().status == "ready"
        finally:
            await runtime.close()

    asyncio.run(exercise())
    assert ("DELETE", f"/api/integration/openai/connect/oauth/{_NATIVE_ATTEMPT_ID}") in requests
    assert not any(path.endswith("/handoff") for _method, path in requests)


@pytest.mark.parametrize(
    ("native_result", "error_code"),
    (
        ("http_failure", "native_oauth_begin_failed"),
        ("invalid_launch", "native_oauth_launch_expiry_invalid"),
    ),
)
def test_failed_native_oauth_begin_releases_hold_and_keeps_worker_ready(
    native_result: str, error_code: str
) -> None:
    """Every rejected V2 launch response releases its temporary worker-home lease."""

    requests: list[tuple[str, str]] = []

    async def native_api(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/api/info":
            return _response(200, {"version": "v2"})
        if request.url.path == "/api/integration/openai/connect/oauth":
            if native_result == "http_failure":
                return _response(502, {"error": {"name": "TemporaryFailure"}})
            launch = _launch_payload()
            data = launch["data"]
            assert isinstance(data, dict)
            data["time"] = {"created": 1, "expires": 1}
            return _response(200, launch)
        raise AssertionError(f"unexpected native V2 request: {request.method} {request.url.path}")

    runtime, supervisor = _make_runtime(native_api)

    async def exercise() -> None:
        try:
            with pytest.raises(RuntimeError, match=error_code):
                await runtime.begin_native_oauth(
                    "openai",
                    "chatgpt-browser",
                    attempt_id=_ATTEMPT_ID,
                    capability=_CAPABILITY,
                    owner_id=_OWNER_ID,
                    session_id=_SESSION_ID,
                )
            assert supervisor.worker_holds == [_ATTEMPT_ID]
            assert supervisor.worker_releases == [_ATTEMPT_ID]
            assert (
                await runtime.native_oauth_status(
                    "openai", _ATTEMPT_ID, owner_id=_OWNER_ID, session_id=_SESSION_ID
                )
                == "cancelled"
            )
            assert (await runtime.start(preserve_ready=True)).status == "ready"
            assert runtime.status().status == "ready"
        finally:
            await runtime.close()

    asyncio.run(exercise())
    assert requests.count(("POST", "/api/integration/openai/connect/oauth")) == 1


def _native_turn_api(
    *,
    failure_mode: str,
    permission_reply: asyncio.Event,
    message_read: asyncio.Event,
    requests: list[tuple[str, str]],
    session_payloads: list[dict[str, object]],
    replies: list[dict[str, object]],
) -> _NativeHandler:
    """Build the pinned location/session/permission HTTP routes for one fake turn."""

    async def native_api(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        requests.append((request.method, path))
        if path == "/api/info":
            return _response(200, {"version": "v2"})
        if path == "/api/location":
            directory = request.url.params.get("location[directory]")
            return _response(200, {"directory": directory, "project": {"directory": directory}})
        if path == "/api/model":
            directory = request.url.params.get("location[directory]")
            execution_id = directory.rsplit("/", 1)[-1] if isinstance(directory, str) else ""
            context = _turn_context()
            adapter = resolve_native_adapter("openai-compatible-chat", "assistant-proxy")
            return _response(
                200,
                {
                    "location": {"directory": directory, "project": {"directory": directory}},
                    "data": [
                        {
                            "id": "assistant-selected",
                            "modelID": "assistant-selected",
                            "providerID": adapter.native_provider_id,
                            "package": adapter.package_id,
                            "settings": {
                                "baseURL": (
                                    "http://127.0.0.1:8000/api/v1/assistant/internal/provider/"
                                    f"{execution_id}"
                                ),
                                "timeout": 120_000,
                            },
                            "capabilities": {"tools": True, "input": ["text"], "output": ["text"]},
                            "headers": {"Authorization": f"Bearer {context.capability}"},
                        }
                    ],
                },
            )
        if path == "/api/mcp":
            return _response(
                200,
                {"data": [{"name": "signal-ledger", "status": {"status": "connected"}}]},
            )
        if path == "/api/websearch/provider":
            return _response(200, {"data": []})
        if path == "/api/session":
            session_payloads.append(json.loads(request.content))
            return _response(200, {"data": {"id": _NATIVE_SESSION_ID}})
        if path == f"/api/session/{_NATIVE_SESSION_ID}/prompt":
            return _response(204)
        if path == f"/api/session/{_NATIVE_SESSION_ID}/permission":
            if failure_mode == "permission_denied":
                return _response(
                    200,
                    {
                        "data": [
                            {
                                "id": "perFixture1234",
                                "sessionID": _NATIVE_SESSION_ID,
                                "action": "execute",
                                "resources": ["synthetic-command"],
                            }
                        ]
                    },
                )
            return _response(200, {"data": []})
        if path == f"/api/session/{_NATIVE_SESSION_ID}/permission/perFixture1234/reply":
            replies.append(json.loads(request.content))
            permission_reply.set()
            return _response(204)
        if path == f"/api/experimental/session/{_NATIVE_SESSION_ID}/wait":
            if failure_mode == "permission_denied":
                await asyncio.wait_for(permission_reply.wait(), timeout=1.0)
                return _response(200, {"data": {"status": "failed", "outcome": "interrupted"}})
            await asyncio.wait_for(message_read.wait(), timeout=1.0)
            return _response(204)
        if path == f"/api/session/{_NATIVE_SESSION_ID}/message":
            message_read.set()
            if failure_mode == "malformed_message":
                return _response(200, {"data": [None]})
            if failure_mode == "native_http_error":
                return _response(503, {"error": {"name": "TemporaryFailure"}})
            return _response(200, {"data": []})
        if path == f"/api/session/{_NATIVE_SESSION_ID}":
            if request.method == "DELETE":
                return _response(204)
            return _response(200, {"data": {"outcome": "succeeded"}})
        if path == f"/api/session/{_NATIVE_SESSION_ID}/interrupt":
            return _response(204)
        raise AssertionError(f"unexpected native V2 request: {request.method} {path}")

    return native_api


@pytest.mark.parametrize("failure_mode", ("malformed_message", "native_http_error"))
def test_failed_native_message_response_fails_turn_without_downgrading_worker(
    failure_mode: str,
) -> None:
    """Malformed or failed V2 message reads end one turn and preserve app worker readiness."""

    permission_reply = asyncio.Event()
    message_read = asyncio.Event()
    requests: list[tuple[str, str]] = []
    session_payloads: list[dict[str, object]] = []
    replies: list[dict[str, object]] = []
    native_api = _native_turn_api(
        failure_mode=failure_mode,
        permission_reply=permission_reply,
        message_read=message_read,
        requests=requests,
        session_payloads=session_payloads,
        replies=replies,
    )
    runtime, supervisor = _make_runtime(native_api)
    events: list[Mapping[str, object]] = []

    async def emit(event: Mapping[str, object]) -> None:
        events.append(event)

    async def exercise() -> tuple[object, str]:
        try:
            result = await runtime.run_turn(
                context=_turn_context(), prompt="Return a bounded fixture result.", emit=emit
            )
            return result, runtime.status().status
        finally:
            await runtime.close()

    result, status_before_close = asyncio.run(exercise())

    assert (result.status, result.error_code) == ("failed", "provider_unavailable")
    assert status_before_close == "ready"
    assert supervisor.prepared == [_EXECUTION_ID]
    assert supervisor.removed == [_EXECUTION_ID]
    assert len(session_payloads) == 1
    interrupt = ("POST", f"/api/session/{_NATIVE_SESSION_ID}/interrupt")
    delete = ("DELETE", f"/api/session/{_NATIVE_SESSION_ID}")
    assert requests.index(interrupt) < requests.index(delete)
    assert not replies
    assert all(event.get("type") != "tool" for event in events)


def test_native_execute_permission_is_rejected_before_tool_activity_and_keeps_readiness() -> None:
    """An unexpected native execute permission is rejected without starting its tool."""

    permission_reply = asyncio.Event()
    message_read = asyncio.Event()
    requests: list[tuple[str, str]] = []
    session_payloads: list[dict[str, object]] = []
    replies: list[dict[str, object]] = []
    native_api = _native_turn_api(
        failure_mode="permission_denied",
        permission_reply=permission_reply,
        message_read=message_read,
        requests=requests,
        session_payloads=session_payloads,
        replies=replies,
    )
    runtime, supervisor = _make_runtime(native_api)
    events: list[Mapping[str, object]] = []

    async def emit(event: Mapping[str, object]) -> None:
        events.append(event)

    async def exercise() -> tuple[object, str]:
        try:
            result = await runtime.run_turn(
                context=_turn_context(), prompt="Do not execute commands.", emit=emit
            )
            return result, runtime.status().status
        finally:
            await runtime.close()

    result, status_before_close = asyncio.run(exercise())

    assert (result.status, result.error_code) == ("failed", "provider_unavailable")
    assert status_before_close == "ready"
    assert len(session_payloads) == 1
    permissions = session_payloads[0]["permissions"]
    assert isinstance(permissions, list)
    execute_rules = [
        row for row in permissions if isinstance(row, dict) and row.get("action") == "execute"
    ]
    assert execute_rules == [{"action": "execute", "resource": "*", "effect": "deny"}]
    assert replies == [{"decision": "reject"}]
    assert all(event.get("type") != "tool" for event in events)
    assert not any(path.endswith("/execute") for _method, path in requests)
    assert supervisor.prepared == [_EXECUTION_ID]
    assert supervisor.removed == [_EXECUTION_ID]
