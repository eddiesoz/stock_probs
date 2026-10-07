"""Focused worker lifecycle and native-envelope recovery regressions."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from stock_probs import container_supervisor as supervisor_service
from stock_probs.assistant.runtime import OpenCodeV2Runtime


class _LiveChild:
    """Represent the app process independently from assistant worker state."""

    def poll(self) -> None:
        return None


class _ExitedChild:
    """Represent a worker wrapper that has already exited."""

    def poll(self) -> int:
        return 1


class _ReadyChild:
    """Represent a replacement worker that remains alive while readiness is probed."""

    def poll(self) -> None:
        return None


class _JsonBody(httpx.AsyncByteStream):
    """Keep MockTransport responses unread so the runtime owns the streaming read."""

    def __init__(self, payload: object) -> None:
        self.content = json.dumps(payload).encode("utf-8")

    async def __aiter__(self):
        yield self.content

    async def aclose(self) -> None:
        return None


def test_worker_restart_budget_keeps_application_alive_after_spawn_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated worker spawn errors exhaust assistant retries without stopping the app."""

    instance = supervisor_service.ContainerSupervisor(worker_enabled=True, environment={})
    app = _LiveChild()
    instance._app = app  # type: ignore[assignment]
    instance._worker = _ExitedChild()  # type: ignore[assignment]
    instance._worker_started_once = True
    spawn_attempts: list[str] = []

    monkeypatch.setattr(supervisor_service.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(
        supervisor_service.ContainerSupervisor,
        "_stop_child",
        staticmethod(lambda _child, *, uid, gid: None),
    )

    def fail_worker_spawn() -> object:
        spawn_attempts.append("worker")
        raise OSError("synthetic worker spawn failure")

    monkeypatch.setattr(instance, "_spawn_worker", fail_worker_spawn)

    for _ in range(supervisor_service.RESTART_LIMIT + 1):
        instance._poll_worker()
        assert app.poll() is None

    status = instance._dispatch({"version": 1, "op": "status"})
    assert len(spawn_attempts) == supervisor_service.RESTART_LIMIT
    assert len(instance._restart_times) == supervisor_service.RESTART_LIMIT
    assert instance._worker is None
    assert status["status"] == "unavailable"
    assert app.poll() is None


def test_worker_recycle_timeout_fails_closed_without_stopping_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A purge whose replacement worker never readies fails while the app stays live."""

    now = [0.0]
    instance = supervisor_service.ContainerSupervisor(worker_enabled=True, environment={})
    app = _LiveChild()
    old_worker = _ExitedChild()
    replacement_worker = _ReadyChild()
    instance._app = app  # type: ignore[assignment]
    instance._worker = old_worker  # type: ignore[assignment]
    purge_id = "a" * 32
    instance._purge_pending_id = purge_id
    instance._purge_jobs[purge_id] = "pending"
    stopped: list[object] = []
    spawned: list[str] = []

    monkeypatch.setattr(supervisor_service, "HOME_PURGE_WAIT_SECONDS", 0.2)
    monkeypatch.setattr(supervisor_service.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(supervisor_service, "_reset_worker_home", lambda: None)
    monkeypatch.setattr(
        instance,
        "_spawn_worker",
        lambda: spawned.append("worker") or replacement_worker,
    )
    monkeypatch.setattr(instance, "_worker_ready", lambda: False)
    monkeypatch.setattr(
        supervisor_service.ContainerSupervisor,
        "_stop_child",
        staticmethod(lambda child, *, uid, gid: stopped.append(child)),
    )

    instance._perform_pending_purge()
    assert spawned == ["worker"]
    assert stopped == [old_worker]
    assert instance._worker is replacement_worker
    assert instance._purge_pending_id == purge_id
    assert app.poll() is None

    # The supervisor advances purges across serve-loop ticks instead of blocking here.
    now[0] += supervisor_service.HOME_PURGE_WAIT_SECONDS
    instance._perform_pending_purge()

    assert spawned == ["worker"]
    assert stopped == [old_worker, replacement_worker]
    assert instance._worker is None
    assert instance._purge_response(purge_id)["status"] == "failed"
    assert instance._worker_status() == "unavailable"
    assert not instance._restart_times
    assert app.poll() is None


def test_kill_switch_clears_worker_without_stopping_application_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fixed disable operation purges worker state while leaving the app running."""

    instance = supervisor_service.ContainerSupervisor(worker_enabled=True, environment={})
    app = _LiveChild()
    worker = _ReadyChild()
    instance._app = app  # type: ignore[assignment]
    instance._worker = worker  # type: ignore[assignment]
    stopped: list[object] = []
    monkeypatch.setattr(supervisor_service, "_reset_worker_home", lambda: None)
    monkeypatch.setattr(
        supervisor_service.ContainerSupervisor,
        "_stop_child",
        staticmethod(
            lambda child, *, uid, gid: stopped.append(child) if child is not None else None
        ),
    )

    disabled = instance._dispatch({"version": 1, "op": "disable", "reason": "kill_switch"})
    purge_id = disabled["purge_id"]
    instance._perform_pending_purge()

    assert stopped == [worker]
    assert instance._dispatch({"version": 1, "op": "status"})["status"] == "disabled"
    assert instance._purge_response(str(purge_id))["status"] == "cleared"
    assert app.poll() is None


def test_home_purge_reconnects_only_to_the_rotated_worker_password() -> None:
    """Verified HOME erasure rebinds to the new worker generation before readiness returns."""

    class RotatingSupervisor:
        """Provide only the fixed local status and purge operations used by this flow."""

        def __init__(self) -> None:
            self.api_password = "a" * 48
            self.purge_id = "b" * 32

        async def status(self) -> dict[str, object]:
            return {
                "status": "ready",
                "api_url": "http://127.0.0.1:4097",
                "api_password": self.api_password,
                "webfetch_guard_ready": False,
                "observation_uncertain": False,
            }

        async def request_home_purge(self) -> str:
            self.api_password = "c" * 48
            return self.purge_id

        async def wait_for_home_purge(self, purge_id: str, *, timeout: float) -> bool:
            assert purge_id == self.purge_id
            assert timeout == 20.0
            return True

    supervisor = RotatingSupervisor()
    clients: list[httpx.AsyncClient] = []
    authentications: list[object] = []

    async def native_api(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/info"
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=_JsonBody({"version": "v2"}),
        )

    def client_factory(**kwargs: object) -> httpx.AsyncClient:
        authentications.append(kwargs.get("auth"))
        client = httpx.AsyncClient(transport=httpx.MockTransport(native_api), **kwargs)
        clients.append(client)
        return client

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=object(),
        catalog=object(),
        supervisor=supervisor,
        http_client_factory=client_factory,
    )

    async def exercise() -> None:
        assert (await runtime.start()).status == "ready"
        first_client = runtime._client
        assert first_client is not None

        assert await runtime.clear_conversation_cache("conversation-fixture") is True

        assert first_client.is_closed is True
        assert runtime._client is not first_client
        assert runtime._api_password == "c" * 48
        assert runtime.status().status == "ready"
        assert runtime._enabled is True
        assert len(clients) == 2 and clients[1].is_closed is False
        assert authentications == [("opencode", "a" * 48), ("opencode", "c" * 48)]
        await runtime.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("messages", "expected_error"),
    (
        ([None], "session_message_invalid"),
        (
            [{"info": {"role": "assistant", "finish": "stop"}, "parts": [None]}],
            "session_part_invalid",
        ),
    ),
)
def test_native_message_route_rejects_invalid_envelope_rows_and_parts(
    messages: list[object], expected_error: str
) -> None:
    """Malformed fixed native HTTP message envelopes fail closed at the parser boundary."""

    async def native_api(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/session/sesFixture1234/message"
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=_JsonBody({"data": messages}),
        )

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=object(),
        catalog=object(),
        supervisor=object(),
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(native_api), **kwargs
        ),
    )

    async def exercise() -> None:
        runtime._client = runtime._http_client_factory(
            base_url="http://127.0.0.1:4097",
            auth=("opencode", "d" * 48),
            timeout=httpx.Timeout(5.0),
            trust_env=False,
            follow_redirects=False,
        )
        runtime._enabled = True
        try:
            # This scoped case exercises a fixed local HTTP response through the message parser.
            # It does not establish native OpenCode/model/runtime acceptance.
            with pytest.raises(RuntimeError, match=expected_error):
                await runtime._consume_message_snapshot(
                    "sesFixture1234",
                    context=SimpleNamespace(),
                    emit=lambda _event: asyncio.sleep(0),
                    outcome={"status": "completed"},
                )
        finally:
            client, runtime._client = runtime._client, None
            if client is not None:
                await client.aclose()

    asyncio.run(exercise())
