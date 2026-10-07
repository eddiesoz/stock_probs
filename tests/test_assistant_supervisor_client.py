"""Exercise the fixed Unix-socket supervisor client protocol."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from stock_probs.assistant import supervisor_client


def _socket_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "control.sock"
    monkeypatch.setattr(supervisor_client, "CONTROL_SOCKET", path)
    monkeypatch.setattr(supervisor_client, "SOCKET_DIRECTORY", tmp_path)
    monkeypatch.setattr(supervisor_client, "SOCKET_OWNER_UID", os.getuid())
    monkeypatch.setattr(supervisor_client, "SOCKET_GROUP_GID", os.getgid())
    return path


def _serve_one(
    path: Path,
    handler: Callable[[socket.socket], None],
) -> tuple[threading.Thread, list[BaseException]]:
    failures: list[BaseException] = []
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    os.chmod(path, 0o660)
    listener.listen(1)

    def run() -> None:
        try:
            connection, _ = listener.accept()
            with connection:
                handler(connection)
        except BaseException as exc:  # surfaced on the test thread after the client completes
            failures.append(exc)
        finally:
            listener.close()
            path.unlink(missing_ok=True)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, failures


def test_client_status_uses_real_unix_socket_and_transport_peer_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _socket_path(tmp_path, monkeypatch)
    password = "a" * 48

    def respond(connection: socket.socket) -> None:
        request = bytearray()
        while chunk := connection.recv(1024):
            request.extend(chunk)
        assert json.loads(request) == {"version": 1, "op": "status"}
        connection.sendall(
            json.dumps(
                {
                    "ok": True,
                    "status": "ready",
                    "api_url": supervisor_client.WORKER_API_URL,
                    "api_password": password,
                    "webfetch_guard_ready": True,
                    "observation_uncertain": False,
                    "untrusted_extra": "ignored",
                }
            ).encode()
            + b"\n"
        )

    thread, failures = _serve_one(path, respond)
    result = asyncio.run(supervisor_client.SupervisorClient().status())
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert failures == []
    assert result == {
        "ok": True,
        "status": "ready",
        "api_url": supervisor_client.WORKER_API_URL,
        "api_password": password,
        "webfetch_guard_ready": True,
        "observation_uncertain": False,
    }


@pytest.mark.parametrize(("phase", "expected_wait_closed_calls"), (("read", 0), ("close", 1)))
def test_client_status_cancellation_aborts_socket_without_waiting_for_close(
    phase: str,
    expected_wait_closed_calls: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation aborts a stalled read or close without waiting on the I/O deadline."""

    _socket_path(tmp_path, monkeypatch)
    read_started = asyncio.Event()
    close_started = asyncio.Event()
    response = (
        json.dumps(
            {
                "ok": True,
                "status": "ready",
                "api_url": supervisor_client.WORKER_API_URL,
                "api_password": "a" * 48,
                "webfetch_guard_ready": True,
                "observation_uncertain": False,
            }
        ).encode()
        + b"\n"
    )

    class FakeReader:
        async def readuntil(self, _separator: bytes) -> bytes:
            if phase == "read":
                read_started.set()
                await asyncio.Event().wait()
                raise AssertionError("cancelled status read should not return")
            return response

        async def read(self, _size: int) -> bytes:
            return b""

    class FakeTransport:
        aborted = False

        def abort(self) -> None:
            self.aborted = True

    class FakeWriter:
        def __init__(self) -> None:
            self.transport = FakeTransport()
            self.closed = False
            self.wait_closed_calls = 0

        def get_extra_info(self, _name: str) -> object:
            return object()

        def write(self, _data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        def write_eof(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            self.wait_closed_calls += 1
            close_started.set()
            await asyncio.Event().wait()

    writer = FakeWriter()

    async def open_connection(_path: str, *, limit: int) -> tuple[FakeReader, FakeWriter]:
        assert limit == supervisor_client.RESPONSE_LIMIT + 1
        return FakeReader(), writer

    monkeypatch.setattr(supervisor_client, "_validate_socket_path", lambda: None)
    monkeypatch.setattr(supervisor_client, "_peer_uid", lambda _peer: os.getuid())
    monkeypatch.setattr(supervisor_client.asyncio, "open_unix_connection", open_connection)

    async def exercise() -> None:
        task = asyncio.create_task(supervisor_client.SupervisorClient().status())
        started = read_started if phase == "read" else close_started
        await asyncio.wait_for(started.wait(), timeout=1.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())

    assert writer.transport.aborted is True
    assert writer.closed is True
    assert writer.wait_closed_calls == expected_wait_closed_calls


def test_client_disable_returns_the_supervisor_purge_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _socket_path(tmp_path, monkeypatch)
    purge_id = "a" * 32

    def respond(connection: socket.socket) -> None:
        request = bytearray()
        while chunk := connection.recv(1024):
            request.extend(chunk)
        assert json.loads(request) == {
            "version": 1,
            "op": "disable",
            "reason": "operator",
        }
        connection.sendall(json.dumps({"ok": True, "purge_id": purge_id}).encode() + b"\n")

    thread, failures = _serve_one(path, respond)
    result = asyncio.run(supervisor_client.SupervisorClient().disable("operator"))
    thread.join(timeout=1)

    assert result == purge_id
    assert not thread.is_alive()
    assert failures == []


@pytest.mark.parametrize(
    "response",
    (
        {"ok": True},
        {"ok": True, "purge_id": "not-a-purge-id"},
        {"ok": True, "purge_id": 17},
    ),
)
def test_client_disable_rejects_missing_or_malformed_purge_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    response: dict[str, object],
) -> None:
    path = _socket_path(tmp_path, monkeypatch)

    def respond(connection: socket.socket) -> None:
        while connection.recv(1024):
            pass
        connection.sendall(json.dumps(response).encode() + b"\n")

    thread, failures = _serve_one(path, respond)
    with pytest.raises(supervisor_client.SupervisorClientError, match="response_invalid"):
        asyncio.run(supervisor_client.SupervisorClient().disable("operator"))
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert failures == []


@pytest.mark.parametrize("value", (None, False, 1, "true", {"ready": True}))
def test_client_status_does_not_trust_nonliteral_webfetch_guard_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: object
) -> None:
    """A missing or malformed guard projection never enables the native fetch tool."""

    path = _socket_path(tmp_path, monkeypatch)
    response = {
        "ok": True,
        "status": "ready",
        "api_url": supervisor_client.WORKER_API_URL,
        "api_password": "a" * 48,
        "observation_uncertain": False,
    }
    if value is not None:
        response["webfetch_guard_ready"] = value

    def respond(connection: socket.socket) -> None:
        while connection.recv(1024):
            pass
        connection.sendall(json.dumps(response).encode() + b"\n")

    thread, failures = _serve_one(path, respond)
    result = asyncio.run(supervisor_client.SupervisorClient().status())
    thread.join(timeout=1)

    assert result["webfetch_guard_ready"] is False
    assert not thread.is_alive()
    assert failures == []


@pytest.mark.parametrize(
    ("include_marker", "value"),
    (
        (False, None),
        (True, None),
        (True, 0),
        (True, 1),
        (True, "true"),
        (True, {"uncertain": True}),
    ),
)
def test_client_status_rejects_missing_or_malformed_observation_uncertainty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    include_marker: bool,
    value: object,
) -> None:
    path = _socket_path(tmp_path, monkeypatch)
    response: dict[str, object] = {
        "ok": True,
        "status": "starting",
        "api_url": supervisor_client.WORKER_API_URL,
        "api_password": "a" * 48,
    }
    if include_marker:
        response["observation_uncertain"] = value

    def respond(connection: socket.socket) -> None:
        while connection.recv(1024):
            pass
        connection.sendall(json.dumps(response).encode() + b"\n")

    thread, failures = _serve_one(path, respond)
    with pytest.raises(supervisor_client.SupervisorClientError, match="status_invalid"):
        asyncio.run(supervisor_client.SupervisorClient().status())
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert failures == []


def test_client_status_projects_explicit_observation_uncertainty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _socket_path(tmp_path, monkeypatch)
    response = {
        "ok": True,
        "status": "starting",
        "api_url": supervisor_client.WORKER_API_URL,
        "api_password": "a" * 48,
        "observation_uncertain": True,
    }

    def respond(connection: socket.socket) -> None:
        while connection.recv(1024):
            pass
        connection.sendall(json.dumps(response).encode() + b"\n")

    thread, failures = _serve_one(path, respond)
    result = asyncio.run(supervisor_client.SupervisorClient().status())
    thread.join(timeout=1)

    assert result["observation_uncertain"] is True
    assert not thread.is_alive()
    assert failures == []


def test_client_rejects_wrong_peer_and_closes_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _socket_path(tmp_path, monkeypatch)
    thread, failures = _serve_one(path, lambda connection: connection.recv(1024))
    monkeypatch.setattr(supervisor_client, "_peer_uid", lambda _: os.getuid() + 1)

    with pytest.raises(supervisor_client.SupervisorClientError, match="peer_identity_invalid"):
        asyncio.run(supervisor_client.SupervisorClient().status())
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert failures == []


@pytest.mark.parametrize(
    "frame",
    (
        b"x" * (supervisor_client.RESPONSE_LIMIT + 1) + b"\n",
        b'{"ok":true}',
        b'{"ok":true}\n{"ok":true}\n',
    ),
)
def test_client_rejects_oversized_or_ambiguous_response_frames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, frame: bytes
) -> None:
    path = _socket_path(tmp_path, monkeypatch)

    def respond(connection: socket.socket) -> None:
        while connection.recv(1024):
            pass
        connection.sendall(frame)

    thread, failures = _serve_one(path, respond)
    with pytest.raises(supervisor_client.SupervisorClientError):
        asyncio.run(supervisor_client.SupervisorClient().status())
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert failures == []


def test_client_deadline_bounds_read_and_close_and_does_not_echo_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _socket_path(tmp_path, monkeypatch)
    monkeypatch.setattr(supervisor_client, "IO_TIMEOUT_SECONDS", 0.08)
    sentinel_value = "capability-that-must-not-appear"

    def stall(connection: socket.socket) -> None:
        connection.recv(1024)
        time.sleep(0.25)

    thread, failures = _serve_one(path, stall)
    started = time.monotonic()
    with pytest.raises(supervisor_client.SupervisorClientError) as captured:
        asyncio.run(supervisor_client.SupervisorClient()._request({"secret": sentinel_value}))
    elapsed = time.monotonic() - started
    thread.join(timeout=1)

    assert elapsed < 0.5
    assert sentinel_value not in str(captured.value)
    assert captured.value.code == "request_timeout"
    assert not thread.is_alive()
    assert failures == []


@pytest.mark.parametrize("provider_id", ("openai", "openai-chatgpt"))
def test_prepare_request_accepts_registered_openai_provider_ids(provider_id: str) -> None:
    execution_id = "a" * 32
    request = {
        "version": 1,
        "op": "prepare_location",
        "execution_id": execution_id,
        "provider_id": provider_id,
        "adapter_id": "openai-responses",
        "native_provider_id": "openai",
        "model_id": "openai/gpt-test+preview",
        "model_alias": "assistant-selected",
        "proxy_base_url": f"http://127.0.0.1:8000/api/v1/assistant/internal/provider/{execution_id}",
        "proxy_capability": "b" * 48,
        "mcp_url": f"http://127.0.0.1:8000/api/v1/assistant/internal/mcp/{execution_id}",
        "mcp_capability": "c" * 48,
    }
    supervisor_client._validate_prepare_request(
        **{key: request[key] for key in request if key not in {"version", "op"}}
    )

    invalid = dict(request)
    invalid["mcp_url"] = f"https://example.com/{execution_id}"
    with pytest.raises(supervisor_client.SupervisorClientError, match="endpoint_invalid"):
        supervisor_client._validate_prepare_request(
            execution_id=execution_id,
            provider_id=provider_id,
            adapter_id="openai-responses",
            native_provider_id="openai",
            model_id="openai/gpt-test+preview",
            model_alias="assistant-selected",
            proxy_base_url=request["proxy_base_url"],
            proxy_capability=request["proxy_capability"],
            mcp_url=invalid["mcp_url"],
            mcp_capability=request["mcp_capability"],
        )


def test_prepare_request_accepts_owner_scoped_console_model_provider() -> None:
    execution_id = "a" * 32
    supervisor_client._validate_prepare_request(
        execution_id=execution_id,
        provider_id="opencode-console",
        adapter_id="openai-compatible-chat",
        native_provider_id="assistant-proxy",
        model_id="opencode-console/" + "b" * 64,
        model_alias="assistant-selected",
        proxy_base_url=("http://127.0.0.1:8000/api/v1/assistant/internal/provider/" + execution_id),
        proxy_capability="b" * 48,
        mcp_url="http://127.0.0.1:8000/api/v1/assistant/internal/mcp/" + execution_id,
        mcp_capability="c" * 48,
    )


def test_prepare_request_rejects_unregistered_provider_id() -> None:
    execution_id = "a" * 32
    with pytest.raises(supervisor_client.SupervisorClientError, match="provider_invalid"):
        supervisor_client._validate_prepare_request(
            execution_id=execution_id,
            provider_id="opencode",
            adapter_id="openai-responses",
            native_provider_id="openai",
            model_id="openai/gpt-test+preview",
            model_alias="assistant-selected",
            proxy_base_url=(
                "http://127.0.0.1:8000/api/v1/assistant/internal/provider/" + execution_id
            ),
            proxy_capability="b" * 48,
            mcp_url="http://127.0.0.1:8000/api/v1/assistant/internal/mcp/" + execution_id,
            mcp_capability="c" * 48,
        )


def test_prepare_request_rejects_non_loopback_endpoint() -> None:
    execution_id = "a" * 32
    request = {
        "provider_id": "openai",
        "adapter_id": "openai-responses",
        "native_provider_id": "openai",
        "model_id": "openai/gpt-test+preview",
        "model_alias": "assistant-selected",
        "proxy_base_url": f"http://127.0.0.1:8000/api/v1/assistant/internal/provider/{execution_id}",
        "proxy_capability": "b" * 48,
        "mcp_url": f"http://127.0.0.1:8000/api/v1/assistant/internal/mcp/{execution_id}",
        "mcp_capability": "c" * 48,
    }
    invalid = dict(request)
    invalid["mcp_url"] = f"https://example.com/{execution_id}"
    with pytest.raises(supervisor_client.SupervisorClientError, match="endpoint_invalid"):
        supervisor_client._validate_prepare_request(
            execution_id=execution_id,
            provider_id="openai",
            adapter_id="openai-responses",
            native_provider_id="openai",
            model_id="openai/gpt-test+preview",
            model_alias="assistant-selected",
            proxy_base_url=request["proxy_base_url"],
            proxy_capability=request["proxy_capability"],
            mcp_url=invalid["mcp_url"],
            mcp_capability=request["mcp_capability"],
        )


@pytest.mark.parametrize(
    ("adapter_id", "native_provider_id", "error_code"),
    (
        ("unknown-adapter", "openai", "native_adapter_unsupported"),
        ("openai-responses", "anthropic", "native_provider_mismatch"),
    ),
)
def test_prepare_request_rejects_unreviewed_native_adapter_pair(
    adapter_id: str, native_provider_id: str, error_code: str
) -> None:
    with pytest.raises(supervisor_client.SupervisorClientError) as caught:
        supervisor_client._validate_prepare_request(
            execution_id="a" * 32,
            provider_id="openai",
            adapter_id=adapter_id,
            native_provider_id=native_provider_id,
            model_id="openai/gpt-test+preview",
            model_alias="assistant-selected",
            proxy_base_url="http://127.0.0.1:8000/api/v1/assistant/internal/provider/" + "a" * 32,
            proxy_capability="b" * 48,
            mcp_url="http://127.0.0.1:8000/api/v1/assistant/internal/mcp/" + "a" * 32,
            mcp_capability="c" * 48,
        )
    assert caught.value.code == error_code


def test_prepare_location_transmits_only_the_validated_native_adapter_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _socket_path(tmp_path, monkeypatch)
    execution_id = "a" * 32
    request = {
        "version": 1,
        "op": "prepare_location",
        "execution_id": execution_id,
        "provider_id": "anthropic",
        "adapter_id": "anthropic-messages",
        "native_provider_id": "anthropic",
        "model_id": "anthropic/model-test",
        "model_alias": "assistant-selected",
        "proxy_base_url": (
            "http://127.0.0.1:8000/api/v1/assistant/internal/provider/" + execution_id
        ),
        "proxy_capability": "b" * 48,
        "mcp_url": "http://127.0.0.1:8000/api/v1/assistant/internal/mcp/" + execution_id,
        "mcp_capability": "c" * 48,
    }

    def respond(connection: socket.socket) -> None:
        received = bytearray()
        while chunk := connection.recv(1024):
            received.extend(chunk)
        assert json.loads(received) == request
        connection.sendall(
            json.dumps(
                {
                    "ok": True,
                    "directory": f"/run/assistant/worker-locations/{execution_id}",
                }
            ).encode()
            + b"\n"
        )

    thread, failures = _serve_one(path, respond)
    result = asyncio.run(
        supervisor_client.SupervisorClient().prepare_location(
            **{key: value for key, value in request.items() if key not in {"version", "op"}}
        )
    )
    thread.join(timeout=1)

    assert result == {"ok": True, "directory": f"/run/assistant/worker-locations/{execution_id}"}
    assert not thread.is_alive()
    assert failures == []


def test_oauth_worker_hold_and_release_use_only_fixed_lease_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _socket_path(tmp_path, monkeypatch)
    lease_id = "f" * 32
    requests: list[dict[str, object]] = []

    def hold(connection: socket.socket) -> None:
        payload = bytearray()
        while chunk := connection.recv(1024):
            payload.extend(chunk)
        requests.append(json.loads(payload))
        connection.sendall(b'{"ok":true}\n')

    thread, failures = _serve_one(path, hold)
    asyncio.run(supervisor_client.SupervisorClient().hold_worker(lease_id))
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert failures == []

    purge_id = "a" * 32

    def release(connection: socket.socket) -> None:
        payload = bytearray()
        while chunk := connection.recv(1024):
            payload.extend(chunk)
        requests.append(json.loads(payload))
        connection.sendall(json.dumps({"ok": True, "purge_id": purge_id}).encode() + b"\n")

    thread, failures = _serve_one(path, release)
    result = asyncio.run(supervisor_client.SupervisorClient().release_worker(lease_id))
    thread.join(timeout=1)

    assert result == purge_id
    assert requests == [
        {"version": 1, "op": "hold_worker", "lease_id": lease_id},
        {"version": 1, "op": "release_worker", "lease_id": lease_id},
    ]
    assert not thread.is_alive()
    assert failures == []


def test_oauth_worker_hold_rejects_malformed_or_unbounded_lease_ids() -> None:
    client = supervisor_client.SupervisorClient()
    for lease_id in ("../etc/passwd", "g" * 32, "f" * 129):
        with pytest.raises(supervisor_client.SupervisorClientError) as captured:
            asyncio.run(client.hold_worker(lease_id))
        assert captured.value.code == "worker_hold_id_invalid"


def test_home_purge_protocol_uses_only_fixed_ids_and_waits_for_cleared_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    purge_id = "a" * 32
    requests = []
    responses = iter(
        (
            {"ok": True, "purge_id": purge_id, "status": "pending"},
            {"ok": True, "purge_id": purge_id, "status": "cleared"},
        )
    )

    async def request(payload):
        requests.append(dict(payload))
        return next(responses)

    client = supervisor_client.SupervisorClient()
    monkeypatch.setattr(client, "_request", request)
    assert asyncio.run(client.request_home_purge()) == purge_id
    assert asyncio.run(client.wait_for_home_purge(purge_id, timeout=1.0)) is True
    assert requests == [
        {"version": 1, "op": "purge_worker_home"},
        {"version": 1, "op": "purge_status", "purge_id": purge_id},
    ]


def test_home_purge_wait_retries_a_status_read_that_times_out_during_recycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _socket_path(tmp_path, monkeypatch)
    purge_id = "e" * 32
    failures: list[BaseException] = []
    received: list[dict[str, object]] = []
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    os.chmod(path, 0o660)
    listener.listen(2)

    def read_frame(connection: socket.socket) -> dict[str, object]:
        data = bytearray()
        while chunk := connection.recv(1024):
            data.extend(chunk)
        return json.loads(data)

    def serve() -> None:
        try:
            first, _ = listener.accept()
            with first:
                received.append(read_frame(first))
                time.sleep(supervisor_client.IO_TIMEOUT_SECONDS + 0.1)

            second, _ = listener.accept()
            with second:
                received.append(read_frame(second))
                second.sendall(
                    json.dumps({"ok": True, "purge_id": purge_id, "status": "cleared"}).encode()
                    + b"\n"
                )
        except BaseException as exc:  # surfaced on the test thread after the client completes
            failures.append(exc)
        finally:
            listener.close()
            path.unlink(missing_ok=True)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    started = time.monotonic()
    cleared = asyncio.run(
        supervisor_client.SupervisorClient().wait_for_home_purge(purge_id, timeout=8.0)
    )
    elapsed = time.monotonic() - started
    thread.join(timeout=1)

    assert cleared is True
    assert elapsed > supervisor_client.IO_TIMEOUT_SECONDS
    assert received == [
        {"version": 1, "op": "purge_status", "purge_id": purge_id},
        {"version": 1, "op": "purge_status", "purge_id": purge_id},
    ]
    assert not thread.is_alive()
    assert failures == []


@pytest.mark.parametrize("status,expected", (("failed", False), ("pending", False)))
def test_home_purge_wait_fails_closed_for_failure_or_deadline(
    monkeypatch: pytest.MonkeyPatch, status: str, expected: bool
) -> None:
    purge_id = "b" * 32

    async def request(payload):
        assert payload == {"version": 1, "op": "purge_status", "purge_id": purge_id}
        return {"ok": True, "purge_id": purge_id, "status": status}

    client = supervisor_client.SupervisorClient()
    monkeypatch.setattr(client, "_request", request)
    started = time.monotonic()
    result = asyncio.run(client.wait_for_home_purge(purge_id, timeout=0.02))

    assert result is expected
    assert time.monotonic() - started < 0.2


def test_home_purge_client_rejects_unknown_status_or_mismatched_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    purge_id = "c" * 32

    async def unknown_status(payload):
        return {"ok": True, "purge_id": purge_id, "status": "almost-cleared"}

    client = supervisor_client.SupervisorClient()
    monkeypatch.setattr(client, "_request", unknown_status)
    with pytest.raises(supervisor_client.SupervisorClientError, match="purge_response_invalid"):
        asyncio.run(client.home_purge_status(purge_id))

    async def wrong_id(payload):
        return {"ok": True, "purge_id": "d" * 32, "status": "cleared"}

    monkeypatch.setattr(client, "_request", wrong_id)
    with pytest.raises(supervisor_client.SupervisorClientError, match="purge_response_invalid"):
        asyncio.run(client.home_purge_status(purge_id))
