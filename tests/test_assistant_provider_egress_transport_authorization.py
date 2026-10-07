"""Exercise live provider authorization at synthetic DNS/TLS transport boundaries."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from stock_probs.assistant import net
from stock_probs.assistant.native_provider_adapters import native_adapter_descriptors
from stock_probs.assistant.providers import AssistantProviderManager, _stream_with_authorization


def _addrinfo_record() -> tuple[object, ...]:
    return net.socket.AF_INET, net.socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)


class _Catalog:
    def __init__(self, model_id: str) -> None:
        self.model = SimpleNamespace(provider_id="openai", model_id=model_id, available=True)

    def get_model(self, model_id: str) -> Any | None:
        return self.model if model_id == self.model.model_id else None


def _manager(tmp_path: Path) -> tuple[AssistantProviderManager, str, dict[str, object]]:
    model_id = "openai/synthetic-egress-transport-model"
    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="e" * 64),
        catalog=_Catalog(model_id),
        vault_dir=tmp_path / "assistant-vault",
    )
    manager.set_credential("openai", "synthetic-key-not-for-output")
    body: dict[str, object] = {
        "model": "assistant-selected",
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "synthetic private prompt"}],
            }
        ],
        "instructions": "Use only approved local functions.",
        "stream": True,
        "store": False,
    }
    return manager, model_id, body


class _Writer:
    def __init__(self) -> None:
        self.write_calls = 0
        self.closed = False

    def write(self, _data: bytes) -> None:
        self.write_calls += 1

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


def _reader(response: bytes = b"data: [DONE]\n\n") -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(
        b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
        + f"Content-Length: {len(response)}\r\n\r\n".encode("ascii")
        + response
    )
    reader.feed_eof()
    return reader


@pytest.mark.parametrize("revoke_at", ("dns", "tls"))
def test_real_manager_transport_rechecks_revocation_after_dns_and_tls_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    revoke_at: str,
) -> None:
    """A real provider manager cannot write its prepared request after either revocation."""

    manager, model_id, body = _manager(tmp_path)
    current = {"value": True}
    dns_calls = 0
    connection_calls = 0
    writer = _Writer()

    async def getaddrinfo(_loop, _host: str, _port: int, **_kwargs: object):
        nonlocal dns_calls
        dns_calls += 1
        if revoke_at == "dns":
            current["value"] = False
        return [_addrinfo_record()]

    async def open_connection(_host: str, _port: int, **_kwargs: object):
        nonlocal connection_calls
        connection_calls += 1
        if revoke_at == "tls":
            current["value"] = False
        return _reader(), writer

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def authorize() -> bool:
        return current["value"] is True

    descriptor = next(
        item for item in native_adapter_descriptors() if item.integration_id == "openai"
    )
    stream = manager.proxy_native_stream(
        "openai",
        model_id,
        body,
        path_model_id=None,
        query=descriptor.fixed_query,
        app_tools=[
            {
                "name": "workspace.summary",
                "description": "Synthetic local summary.",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            }
        ],
        owner_id=501,
        app_session_id="synthetic-r120-session",
        authorization_check=authorize,
    )

    async def collect() -> None:
        async for _chunk in stream:
            pass

    with pytest.raises(net.PublicHTTPError) as caught:
        asyncio.run(collect())

    assert caught.value.code == "provider_authorization_required"
    assert dns_calls == 1
    assert connection_calls == (0 if revoke_at == "dns" else 1)
    assert current["value"] is False
    assert writer.write_calls == 0
    if revoke_at == "dns":
        assert connection_calls == 0
        assert writer.closed is False
    else:
        assert connection_calls == 1
        assert writer.closed is True


def test_stream_rejects_authenticated_request_without_authorization_before_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dns_calls = 0

    async def getaddrinfo(_loop, _host: str, _port: int, **_kwargs: object):
        nonlocal dns_calls
        dns_calls += 1
        return [_addrinfo_record()]

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", getaddrinfo)

    async def exercise() -> None:
        with pytest.raises(net.PublicHTTPError) as caught:
            async for _chunk in net.stream_public_https(
                "https://provider.example/v1/responses",
                headers={"Authorization": "Bearer synthetic"},
                body=b"{}",
                timeout_seconds=1,
            ):
                pass
        assert caught.value.code == "provider_authorization_required"

    asyncio.run(exercise())
    assert dns_calls == 0


def test_provider_stream_adapter_rejects_async_false_before_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dns_calls = 0
    connection_calls = 0

    async def getaddrinfo(_loop, _host: str, _port: int, **_kwargs: object):
        nonlocal dns_calls
        dns_calls += 1
        return [_addrinfo_record()]

    async def open_connection(_host: str, _port: int, **_kwargs: object):
        nonlocal connection_calls
        connection_calls += 1
        return _reader(), _Writer()

    async def deny() -> bool:
        return False

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def exercise() -> None:
        with pytest.raises(net.PublicHTTPError) as caught:
            async for _chunk in _stream_with_authorization(
                "https://provider.example/v1/responses",
                authorization_check=deny,
                headers={"Authorization": "Bearer synthetic"},
                body=b"{}",
                timeout_seconds=1,
            ):
                pass
        assert caught.value.code == "provider_authorization_required"

    asyncio.run(exercise())
    assert dns_calls == 1
    assert connection_calls == 0


def test_authorized_stream_completes_with_bounded_synthetic_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = _Writer()
    authorization_calls = 0

    async def getaddrinfo(_loop, _host: str, _port: int, **_kwargs: object):
        return [_addrinfo_record()]

    async def open_connection(_host: str, _port: int, **_kwargs: object):
        return _reader(), writer

    async def authorize() -> bool:
        nonlocal authorization_calls
        authorization_calls += 1
        return True

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def exercise() -> bytes:
        return b"".join(
            [
                chunk
                async for chunk in net.stream_public_https(
                    "https://provider.example/v1/responses",
                    headers={"Authorization": "Bearer synthetic"},
                    body=b"{}",
                    timeout_seconds=1,
                    authorization_check=authorize,
                )
            ]
        )

    assert asyncio.run(exercise()) == b"data: [DONE]\n\n"
    assert authorization_calls >= 2
    assert writer.write_calls == 1
    assert writer.closed is True


@pytest.mark.parametrize("failure", ("denied", "error", "timeout"))
def test_authorization_failure_after_tls_never_writes_and_closes_writer(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    writer = _Writer()
    authorization_calls = 0

    async def getaddrinfo(_loop, _host: str, _port: int, **_kwargs: object):
        return [_addrinfo_record()]

    async def open_connection(_host: str, _port: int, **_kwargs: object):
        return _reader(), writer

    async def authorize() -> bool:
        nonlocal authorization_calls
        authorization_calls += 1
        if authorization_calls == 1:
            return True
        if failure == "denied":
            return False
        if failure == "error":
            raise RuntimeError("synthetic authorization failure")
        await asyncio.Event().wait()
        return True

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def exercise() -> None:
        with pytest.raises(net.PublicHTTPError) as caught:
            async for _chunk in net.stream_public_https(
                "https://provider.example/v1/responses",
                headers={"x-api-key": "synthetic"},
                body=b"{}",
                timeout_seconds=0.05 if failure == "timeout" else 1,
                authorization_check=authorize,
            ):
                pass
        expected = (
            "provider_authorization_timeout"
            if failure == "timeout"
            else "provider_authorization_required"
        )
        assert caught.value.code == expected

    asyncio.run(exercise())
    assert authorization_calls >= 2
    assert writer.write_calls == 0
    assert writer.closed is True


def test_cancellation_during_post_tls_authorization_closes_without_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = _Writer()
    auth_waiting = asyncio.Event()
    authorization_calls = 0

    async def getaddrinfo(_loop, _host: str, _port: int, **_kwargs: object):
        return [_addrinfo_record()]

    async def open_connection(_host: str, _port: int, **_kwargs: object):
        return _reader(), writer

    async def authorize() -> bool:
        nonlocal authorization_calls
        authorization_calls += 1
        if authorization_calls == 1:
            return True
        auth_waiting.set()
        await asyncio.Event().wait()
        return True

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def exercise() -> None:
        stream = net.stream_public_https(
            "https://provider.example/v1/responses",
            headers={"Authorization": "Bearer synthetic"},
            body=b"{}",
            timeout_seconds=1,
            authorization_check=authorize,
        )
        task = asyncio.create_task(anext(stream))
        await asyncio.wait_for(auth_waiting.wait(), timeout=0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await stream.aclose()

    asyncio.run(exercise())
    assert authorization_calls == 2
    assert writer.write_calls == 0
    assert writer.closed is True
