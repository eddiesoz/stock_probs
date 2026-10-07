"""Regression cases for bounded assistant HTTPS framing and cleanup boundaries.

Every socket, DNS result, response byte, and timeout in this module is synthetic. The
public transport functions remain the system under test; no external host is contacted.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

import pytest

from stock_probs.assistant import net

_PUBLIC_V4 = "93.184.216.34"
_PUBLIC_V6 = "2606:4700:4700::1111"


def _addrinfo_record(address: str) -> tuple[object, ...]:
    parsed = net.ipaddress.ip_address(address)
    family = net.socket.AF_INET6 if parsed.version == 6 else net.socket.AF_INET
    sockaddr: tuple[object, ...] = (address, 443, 0, 0) if parsed.version == 6 else (address, 443)
    return family, net.socket.SOCK_STREAM, 6, "", sockaddr


def _response(
    status: bytes = b"HTTP/1.1 200 OK\r\n",
    headers: Iterable[bytes] = (),
    body: bytes = b"",
) -> bytes:
    return status + b"".join(header + b"\r\n" for header in headers) + b"\r\n" + body


class _Writer:
    def __init__(self) -> None:
        self.written = bytearray()
        self.closed = False
        self.wait_closed_calls = 0

    def write(self, data: bytes) -> None:
        self.written.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        self.wait_closed_calls += 1


class _Reader:
    """Small in-memory async reader with EOF and timeout behavior but no socket or loop."""

    def __init__(self, wire: bytes, *, eof: bool = True, read_limit: int | None = None) -> None:
        self.buffer = bytearray(wire)
        self.eof = eof
        self.read_limit = read_limit

    async def readline(self) -> bytes:
        newline = self.buffer.find(b"\n")
        if newline >= 0:
            end = newline + 1
            line = bytes(self.buffer[:end])
            del self.buffer[:end]
            return line
        if self.eof and self.buffer:
            line = bytes(self.buffer)
            self.buffer.clear()
            return line
        if self.eof:
            return b""
        raise TimeoutError("synthetic reader has no next line")

    async def read(self, size: int) -> bytes:
        if self.buffer:
            take = min(size, len(self.buffer), self.read_limit or size)
            chunk = bytes(self.buffer[:take])
            del self.buffer[:take]
            return chunk
        if self.eof:
            return b""
        raise TimeoutError("synthetic reader has no body bytes")

    async def readexactly(self, size: int) -> bytes:
        if len(self.buffer) >= size:
            chunk = bytes(self.buffer[:size])
            del self.buffer[:size]
            return chunk
        if self.eof:
            partial = bytes(self.buffer)
            self.buffer.clear()
            raise asyncio.IncompleteReadError(partial, size)
        raise TimeoutError("synthetic reader has no complete chunk")


def _install_request_transport(
    monkeypatch: pytest.MonkeyPatch,
    wire_response: bytes,
    *,
    eof: bool = True,
    read_limit: int | None = None,
) -> tuple[_Writer, list[tuple[object, ...]]]:
    reader = _Reader(wire_response, eof=eof, read_limit=read_limit)
    writer = _Writer()
    connections: list[tuple[object, ...]] = []

    async def in_process_to_thread(function, *args, **kwargs):
        # Resolver callbacks are fixtures; execute them directly without a helper thread.
        return function(*args, **kwargs)

    async def immediate_wait_for(awaitable, timeout: float):
        assert timeout > 0
        return await awaitable

    async def open_connection(host: str, port: int, **kwargs):
        connections.append((host, port, kwargs))
        return reader, writer

    monkeypatch.setattr(net.asyncio, "to_thread", in_process_to_thread)
    monkeypatch.setattr(net.asyncio, "wait_for", immediate_wait_for)
    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)
    return writer, connections


def _install_stream_transport(
    monkeypatch: pytest.MonkeyPatch,
    wire_response: bytes,
    *,
    dns_answers: Iterable[str] = (_PUBLIC_V4,),
    eof: bool = True,
    read_limit: int | None = None,
) -> tuple[_Writer, list[tuple[object, ...]]]:
    reader = _Reader(wire_response, eof=eof, read_limit=read_limit)
    writer = _Writer()
    connections: list[tuple[object, ...]] = []
    records = [_addrinfo_record(answer) for answer in dns_answers]

    async def getaddrinfo(_loop, host: str, port: int, **_kwargs: object):
        assert host == "provider.example"
        assert port == 443
        return records

    async def immediate_wait_for(awaitable, timeout: float):
        assert timeout > 0
        return await awaitable

    async def open_connection(host: str, port: int, **kwargs):
        connections.append((host, port, kwargs))
        return reader, writer

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(net.asyncio, "wait_for", immediate_wait_for)
    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)
    return writer, connections


def _drain_request(**kwargs: object) -> net.PublicHTTPResponse:
    async def exercise() -> net.PublicHTTPResponse:
        return await net.request_public_https(
            "https://provider.example/v1/result?mode=synthetic",
            resolver=lambda _host, _port: [_addrinfo_record(_PUBLIC_V4)],
            **kwargs,
        )

    return asyncio.run(exercise())


def _drain_stream(**kwargs: object) -> bytes:
    async def exercise() -> bytes:
        return b"".join(
            [
                chunk
                async for chunk in net.stream_public_https(
                    "https://provider.example/v1/responses",
                    body=b'{"synthetic":true}',
                    timeout_seconds=1,
                    **kwargs,
                )
            ]
        )

    return asyncio.run(exercise())


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.1.1", "::1"])
def test_request_rejects_mixed_public_and_private_dns_before_socket(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    writer, connections = _install_request_transport(monkeypatch, _response())
    answers = [_addrinfo_record(_PUBLIC_V4), _addrinfo_record(address)]

    async def exercise() -> None:
        with pytest.raises(net.PublicHTTPError) as caught:
            await net.request_public_https(
                "https://provider.example/",
                resolver=lambda _host, _port: answers,
            )
        assert caught.value.code == "private_destination_rejected"

    asyncio.run(exercise())
    assert connections == []
    assert writer.closed is False


@pytest.mark.parametrize(
    "url",
    [
        "http://provider.example/",
        "https://provider.example:444/",
        "https://user:synthetic@provider.example/",
        "https://provider.example/path#fragment",
        "https://provider.example/path\r\nHost: local",
    ],
)
def test_request_rejects_unsafe_url_authority_before_dns_or_socket(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    writer, connections = _install_request_transport(monkeypatch, _response())
    resolutions: list[tuple[str, int]] = []

    def resolver(host: str, port: int) -> list[object]:
        resolutions.append((host, port))
        return [_addrinfo_record(_PUBLIC_V4)]

    async def exercise() -> None:
        with pytest.raises(net.PublicHTTPError) as caught:
            await net.request_public_https(url, resolver=resolver)
        assert caught.value.code == "url_invalid"

    asyncio.run(exercise())
    assert resolutions == []
    assert connections == []
    assert writer.closed is False


def test_request_maps_malformed_dns_answer_to_safe_dns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer, connections = _install_request_transport(monkeypatch, _response())

    async def exercise() -> None:
        with pytest.raises(net.PublicHTTPError) as caught:
            await net.request_public_https(
                "https://provider.example/",
                resolver=lambda _host, _port: [object()],
            )
        assert caught.value.code == "dns_unavailable"

    asyncio.run(exercise())
    assert connections == []
    assert writer.closed is False


def test_request_maps_resolver_failure_without_opening_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer, connections = _install_request_transport(monkeypatch, _response())

    def failed_resolver(_host: str, _port: int) -> list[object]:
        raise OSError("synthetic resolver failure")

    async def exercise() -> None:
        with pytest.raises(net.PublicHTTPError) as caught:
            await net.request_public_https(
                "https://provider.example/",
                resolver=failed_resolver,
            )
        assert caught.value.code == "dns_unavailable"

    asyncio.run(exercise())
    assert connections == []
    assert writer.closed is False


@pytest.mark.parametrize("address", [_PUBLIC_V4, _PUBLIC_V6])
def test_request_connects_to_pinned_ip_and_keeps_url_hostname_for_tls_sni(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    writer, connections = _install_request_transport(
        monkeypatch, _response(headers=[b"Content-Length: 0"])
    )

    async def exercise() -> None:
        await net.request_public_https(
            "https://provider.example/v1/result",
            resolver=lambda _host, _port: [_addrinfo_record(address)],
        )

    asyncio.run(exercise())
    assert connections[0][0:2] == (address, 443)
    assert connections[0][2]["server_hostname"] == "provider.example"
    assert writer.closed
    assert writer.wait_closed_calls == 1


def test_request_maps_socket_connect_failure_without_leaking_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _writer, connections = _install_request_transport(monkeypatch, _response())

    async def failed_connection(host: str, port: int, **kwargs):
        connections.append((host, port, kwargs))
        raise OSError("synthetic connect failure")

    monkeypatch.setattr(net.asyncio, "open_connection", failed_connection)
    with pytest.raises(net.PublicHTTPError) as caught:
        _drain_request()
    assert caught.value.code == "provider_connect_failed"
    assert len(connections) == 1


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_request_rejects_redirect_status_without_following_location(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    writer, connections = _install_request_transport(
        monkeypatch,
        _response(
            f"HTTP/1.1 {status} Synthetic Redirect\r\n".encode("ascii"),
            [b"Location: https://127.0.0.1/private"],
        ),
    )
    with pytest.raises(net.PublicHTTPError) as caught:
        _drain_request()
    assert caught.value.code == "provider_redirect_rejected"
    assert caught.value.status_code == status
    assert len(connections) == 1
    assert writer.closed


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ([b"Content-Length: 1", b"Content-Length: 1"], "provider_response_invalid"),
        (
            [b"Content-Length: 1", b"Transfer-Encoding: chunked"],
            "provider_response_invalid",
        ),
        ([b"Content-Encoding: gzip", b"Content-Length: 0"], "provider_response_invalid"),
        ([b"Content-Length: nope"], "provider_response_invalid"),
        ([b"malformed response field without colon"], "provider_response_invalid"),
        ([b"Transfer-Encoding: gzip"], "provider_response_invalid"),
        ([b"Transfer-Encoding: gzip, chunked"], "provider_response_invalid"),
    ],
)
def test_request_rejects_ambiguous_or_unsupported_response_framing(
    monkeypatch: pytest.MonkeyPatch, headers: list[bytes], expected: str
) -> None:
    writer, _connections = _install_request_transport(monkeypatch, _response(headers=headers))
    with pytest.raises(net.PublicHTTPError) as caught:
        _drain_request()
    assert caught.value.code == expected
    assert writer.closed
    assert writer.wait_closed_calls == 1


@pytest.mark.parametrize(
    "status_line",
    [b"HTTP/2 200 OK\r\n", b"HTTP/1.1 99 Too Early\r\n", b"not-an-http-status\r\n"],
)
def test_request_rejects_malformed_status_lines_and_closes_socket(
    monkeypatch: pytest.MonkeyPatch, status_line: bytes
) -> None:
    writer, _connections = _install_request_transport(monkeypatch, _response(status=status_line))
    with pytest.raises(net.PublicHTTPError) as caught:
        _drain_request()
    assert caught.value.code == "provider_response_invalid"
    assert writer.closed


@pytest.mark.parametrize(
    ("body", "headers", "expected"),
    [
        (b"x", [b"Content-Length: 2"], "provider_response_invalid"),
        (b"12345", [b"Content-Length: 5"], "provider_response_too_large"),
        (
            b"2\r\nxyX\n0\r\n\r\n",
            [b"Transfer-Encoding: chunked"],
            "provider_response_invalid",
        ),
        (b"z\r\n", [b"Transfer-Encoding: chunked"], "provider_response_invalid"),
        (
            b"5\r\n12345\r\n0\r\n\r\n",
            [b"Transfer-Encoding: chunked"],
            "provider_response_too_large",
        ),
    ],
)
def test_request_body_framing_rejects_truncation_bad_chunks_and_over_limit(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
    headers: list[bytes],
    expected: str,
) -> None:
    writer, _connections = _install_request_transport(
        monkeypatch, _response(headers=headers, body=body)
    )
    with pytest.raises(net.PublicHTTPError) as caught:
        _drain_request(max_response_bytes=4)
    assert caught.value.code == expected
    assert writer.closed


def test_request_reads_bounded_chunked_body_and_ignores_valid_trailer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"2;part=one\r\nab\r\n2\r\ncd\r\n0\r\nX-Synthetic: done\r\n\r\n"
    writer, _connections = _install_request_transport(
        monkeypatch,
        _response(headers=[b"Transfer-Encoding: chunked"], body=body),
    )
    response = _drain_request(max_response_bytes=4)
    assert response.content == b"abcd"
    assert writer.closed


def test_request_reads_close_delimited_body_and_enforces_its_size_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer, _connections = _install_request_transport(monkeypatch, _response(body=b"abcd"))
    response = _drain_request(max_response_bytes=4)
    assert response.content == b"abcd"
    assert writer.closed

    writer, _connections = _install_request_transport(monkeypatch, _response(body=b"abcde"))
    with pytest.raises(net.PublicHTTPError) as caught:
        _drain_request(max_response_bytes=4)
    assert caught.value.code == "provider_response_too_large"
    assert writer.closed


def test_request_reads_short_content_length_fragments_until_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer, _connections = _install_request_transport(
        monkeypatch,
        _response(headers=[b"Content-Length: 5"], body=b"abcde"),
        read_limit=2,
    )
    response = _drain_request()
    assert response.content == b"abcde"
    assert writer.closed


def test_request_rejects_embedded_control_line_ending_in_chunk_trailer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"1\r\nx\r\n0\r\nX-Synthetic: safe\rinjected\r\n\r\n"
    writer, _connections = _install_request_transport(
        monkeypatch,
        _response(headers=[b"Transfer-Encoding: chunked"], body=body),
    )
    with pytest.raises(net.PublicHTTPError) as caught:
        _drain_request()
    assert caught.value.code == "provider_response_invalid"
    assert writer.closed


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ([("Host", "127.0.0.1")], "header_invalid"),
        ([("Content-Length", "0")], "header_invalid"),
        ([("X-Synthetic", "safe\r\nHost: 127.0.0.1")], "header_invalid"),
        ([("X-Synthetic", "snowman-\u2603")], "header_invalid"),
    ],
)
def test_request_rejects_host_override_and_hostile_caller_headers(
    monkeypatch: pytest.MonkeyPatch,
    headers: list[tuple[str, str]],
    expected: str,
) -> None:
    writer, _connections = _install_request_transport(monkeypatch, _response())
    with pytest.raises(net.PublicHTTPError) as caught:
        _drain_request(headers=dict(headers))
    assert caught.value.code == expected
    assert writer.closed
    assert bytes(writer.written) == b""


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_stream_rejects_redirect_status_and_never_follows_location(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    writer, connections = _install_stream_transport(
        monkeypatch,
        _response(
            f"HTTP/1.1 {status} Synthetic Redirect\r\n".encode("ascii"),
            [b"Location: https://127.0.0.1/private", b"Content-Type: text/event-stream"],
        ),
    )
    with pytest.raises(net.PublicHTTPError) as caught:
        _drain_stream()
    assert caught.value.code == "provider_redirect_rejected"
    assert len(connections) == 1
    assert writer.closed
    assert writer.wait_closed_calls == 1


@pytest.mark.parametrize("status", [201, 401, 429, 500])
def test_stream_maps_non_success_status_to_upstream_unavailable(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    writer, _connections = _install_stream_transport(
        monkeypatch,
        _response(
            f"HTTP/1.1 {status} Synthetic Status\r\n".encode("ascii"),
            [b"Content-Type: text/event-stream", b"Content-Length: 0"],
        ),
    )
    with pytest.raises(net.PublicHTTPError) as caught:
        _drain_stream()
    assert caught.value.code == "provider_upstream_unavailable"
    assert caught.value.status_code == status
    assert writer.closed


def test_public_http_error_keeps_legacy_code_only_construction() -> None:
    failure = net.PublicHTTPError("provider_connect_failed")

    assert failure.code == "provider_connect_failed"
    assert failure.status_code is None


@pytest.mark.parametrize("status_code", [True, 99, 600, 503.0, "503"])
def test_public_http_error_rejects_unvalidated_status_code(status_code: object) -> None:
    with pytest.raises(ValueError, match="HTTP status code"):
        net.PublicHTTPError("provider_upstream_unavailable", status_code=status_code)


@pytest.mark.parametrize(
    "status_line",
    [b"HTTP/2 200 OK\r\n", b"HTTP/1.1 99 Too Early\r\n", b"malformed status\r\n"],
)
def test_stream_rejects_malformed_status_lines(
    monkeypatch: pytest.MonkeyPatch, status_line: bytes
) -> None:
    writer, _connections = _install_stream_transport(
        monkeypatch,
        _response(
            status_line,
            [b"Content-Type: text/event-stream", b"Content-Length: 0"],
        ),
    )
    with pytest.raises(net.PublicHTTPError) as caught:
        _drain_stream()
    assert caught.value.code == "provider_response_invalid"
    assert writer.closed


@pytest.mark.parametrize("address", ["127.0.0.1", "192.168.1.1", "::1"])
def test_stream_rejects_mixed_public_and_private_dns_before_socket(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    writer, connections = _install_stream_transport(
        monkeypatch, _response(), dns_answers=[_PUBLIC_V4, address]
    )
    with pytest.raises(net.PublicHTTPError) as caught:
        _drain_stream()
    assert caught.value.code == "private_destination_rejected"
    assert connections == []
    assert writer.closed is False


@pytest.mark.parametrize(
    "url",
    [
        "http://provider.example/",
        "https://provider.example:444/",
        "https://user:synthetic@provider.example/",
        "https://provider.example/path#fragment",
        "https://provider.example/path\r\nHost: local",
    ],
)
def test_stream_rejects_unsafe_url_authority_before_dns_or_socket(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    writer, connections = _install_stream_transport(monkeypatch, _response())
    dns_calls: list[tuple[str, int]] = []

    async def record_getaddrinfo(_loop, host: str, port: int, **_kwargs: object):
        dns_calls.append((host, port))
        return [_addrinfo_record(_PUBLIC_V4)]

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", record_getaddrinfo)

    async def exercise() -> None:
        with pytest.raises(net.PublicHTTPError) as caught:
            async for _chunk in net.stream_public_https(url, timeout_seconds=1):
                raise AssertionError("invalid URL produced response bytes")
        assert caught.value.code == "url_invalid"

    asyncio.run(exercise())
    assert dns_calls == []
    assert connections == []
    assert writer.closed is False


def test_stream_maps_dns_failure_without_opening_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer, connections = _install_stream_transport(monkeypatch, _response())

    async def failed_getaddrinfo(_loop, _host: str, _port: int, **_kwargs: object):
        raise OSError("synthetic DNS failure")

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", failed_getaddrinfo)

    async def exercise() -> None:
        with pytest.raises(net.PublicHTTPError) as caught:
            async for _chunk in net.stream_public_https(
                "https://provider.example/v1/responses",
                timeout_seconds=1,
            ):
                raise AssertionError("DNS failure produced response bytes")
        assert caught.value.code == "dns_unavailable"

    asyncio.run(exercise())
    assert connections == []
    assert writer.closed is False


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        (
            [b"Content-Length: 0", b"Content-Length: 0"],
            "provider_response_invalid",
        ),
        (
            [b"Transfer-Encoding: chunked", b"Content-Length: 0"],
            "provider_response_invalid",
        ),
        ([b"Content-Encoding: gzip", b"Content-Length: 0"], "provider_response_invalid"),
        (
            [b"Transfer-Encoding: gzip", b"Content-Type: text/event-stream"],
            "provider_response_invalid",
        ),
        (
            [b"Content-Type: application/json", b"Content-Length: 0"],
            "provider_response_invalid",
        ),
        (
            [b" Bad-Fold: value", b"Content-Type: text/event-stream"],
            "provider_response_invalid",
        ),
        (
            [b"Bad Header: value", b"Content-Type: text/event-stream"],
            "provider_response_invalid",
        ),
    ],
)
def test_stream_rejects_duplicate_framing_and_malformed_response_headers(
    monkeypatch: pytest.MonkeyPatch,
    headers: list[bytes],
    expected: str,
) -> None:
    writer, _connections = _install_stream_transport(monkeypatch, _response(headers=headers))
    with pytest.raises(net.PublicHTTPError) as caught:
        _drain_stream()
    assert caught.value.code == expected
    assert writer.closed


@pytest.mark.parametrize(
    ("body", "headers", "expected"),
    [
        (b"xy", [b"Content-Length: 3"], "provider_response_invalid"),
        (b"12345", [b"Content-Length: 5"], "provider_response_too_large"),
        (b"z\r\n", [b"Transfer-Encoding: chunked"], "provider_response_invalid"),
        (
            b"1\r\nxX\n0\r\n\r\n",
            [b"Transfer-Encoding: chunked"],
            "provider_response_invalid",
        ),
        (
            b"5\r\n12345\r\n0\r\n\r\n",
            [b"Transfer-Encoding: chunked"],
            "provider_response_too_large",
        ),
        (b"abcde", [], "provider_response_too_large"),
    ],
)
def test_stream_rejects_truncated_malformed_and_over_limit_bodies(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
    headers: list[bytes],
    expected: str,
) -> None:
    writer, _connections = _install_stream_transport(
        monkeypatch,
        _response(
            headers=[b"Content-Type: text/event-stream", *headers],
            body=body,
        ),
    )
    with pytest.raises(net.PublicHTTPError) as caught:
        _drain_stream(max_response_bytes=4)
    assert caught.value.code == expected
    assert writer.closed


def test_stream_decodes_chunked_events_and_consumes_trailers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"3;part=one\r\nabc\r\n2\r\nde\r\n0\r\nX-Synthetic: done\r\n\r\n"
    writer, _connections = _install_stream_transport(
        monkeypatch,
        _response(
            headers=[b"Transfer-Encoding: chunked", b"Content-Type: text/event-stream"],
            body=body,
        ),
    )
    assert _drain_stream(max_response_bytes=5) == b"abcde"
    assert writer.closed
    assert writer.wait_closed_calls == 1


def test_stream_reads_short_content_length_fragments_until_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer, _connections = _install_stream_transport(
        monkeypatch,
        _response(
            headers=[b"Content-Type: text/event-stream", b"Content-Length: 5"],
            body=b"abcde",
        ),
        read_limit=2,
    )
    assert _drain_stream() == b"abcde"
    assert writer.closed


def test_stream_rejects_hostile_caller_headers_and_closes_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer, _connections = _install_stream_transport(monkeypatch, _response())

    async def exercise() -> None:
        with pytest.raises(net.PublicHTTPError) as caught:
            async for _chunk in net.stream_public_https(
                "https://provider.example/v1/responses",
                headers={"X-Synthetic": "safe\r\nHost: 127.0.0.1"},
                timeout_seconds=1,
            ):
                raise AssertionError("invalid request header emitted a response chunk")
        assert caught.value.code == "header_invalid"

    asyncio.run(exercise())
    assert writer.closed
    assert bytes(writer.written) == b""


def test_request_deadline_is_controlled_and_socket_is_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer, _connections = _install_request_transport(
        monkeypatch,
        _response(headers=[b"Content-Length: 1"]),
        eof=False,
    )
    clock = {"now": net.time.monotonic()}

    def remaining(deadline: float) -> float:
        value = deadline - clock["now"]
        if value <= 0:
            raise TimeoutError("synthetic deadline expired")
        return value

    async def deterministic_wait_for(awaitable, timeout: float):
        code = getattr(awaitable, "cr_code", None)
        if code is not None and code.co_qualname.endswith("StreamReader.read"):
            awaitable.close()
            clock["now"] += timeout
            raise TimeoutError("synthetic transport deadline")
        return await awaitable

    monkeypatch.setattr(net, "_remaining", remaining)
    monkeypatch.setattr(net.asyncio, "wait_for", deterministic_wait_for)
    with pytest.raises(net.PublicHTTPError) as caught:
        _drain_request(timeout_seconds=1)
    assert caught.value.code == "provider_deadline_exceeded"
    assert writer.closed
    assert writer.wait_closed_calls == 1


def test_stream_deadline_is_controlled_and_socket_is_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer, _connections = _install_stream_transport(
        monkeypatch,
        _response(headers=[b"Content-Type: text/event-stream", b"Content-Length: 1"]),
        eof=False,
    )
    clock = {"now": net.time.monotonic()}

    def remaining(deadline: float) -> float:
        value = deadline - clock["now"]
        if value <= 0:
            raise TimeoutError("synthetic deadline expired")
        return value

    async def deterministic_wait_for(awaitable, timeout: float):
        code = getattr(awaitable, "cr_code", None)
        if code is not None and code.co_qualname.endswith("StreamReader.read"):
            awaitable.close()
            clock["now"] += timeout
            raise TimeoutError("synthetic transport deadline")
        return await awaitable

    monkeypatch.setattr(net, "_remaining", remaining)
    monkeypatch.setattr(net.asyncio, "wait_for", deterministic_wait_for)

    async def exercise() -> None:
        with pytest.raises(net.PublicHTTPError) as caught:
            async for _chunk in net.stream_public_https(
                "https://provider.example/v1/responses",
                timeout_seconds=1,
            ):
                raise AssertionError("a timed-out body emitted data")
        assert caught.value.code == "provider_deadline_exceeded"

    asyncio.run(exercise())
    assert writer.closed
    assert writer.wait_closed_calls == 1


def test_stream_cancellation_after_first_event_closes_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _Reader(
        _response(
            headers=[b"Content-Type: text/event-stream", b"Content-Length: 4"],
            body=b"ab",
        ),
        eof=False,
    )
    writer = _Writer()

    async def getaddrinfo(_loop, _host: str, _port: int, **_kwargs: object):
        return [_addrinfo_record(_PUBLIC_V4)]

    async def immediate_wait_for(awaitable, timeout: float):
        assert timeout > 0
        return await awaitable

    async def open_connection(_host: str, _port: int, **_kwargs: object):
        return reader, writer

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(net.asyncio, "wait_for", immediate_wait_for)
    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def exercise() -> None:
        first_chunk = asyncio.Event()
        hold_consumer = asyncio.Event()

        async def consume() -> None:
            async for chunk in net.stream_public_https(
                "https://provider.example/v1/responses",
                timeout_seconds=1,
            ):
                assert chunk == b"ab"
                first_chunk.set()
                await hold_consumer.wait()

        task = asyncio.create_task(consume())
        await first_chunk.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert writer.closed
    assert writer.wait_closed_calls == 1
