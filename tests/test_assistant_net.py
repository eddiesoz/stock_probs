"""Focused provider transport checks for fixed OAuth and JSON content types."""

from __future__ import annotations

import asyncio
import json

import pytest

from stock_probs.assistant import net


def _addrinfo_record(address: str) -> tuple[object, ...]:
    parsed = net.ipaddress.ip_address(address)
    family = net.socket.AF_INET6 if parsed.version == 6 else net.socket.AF_INET
    sockaddr: tuple[object, ...] = (address, 443, 0, 0) if parsed.version == 6 else (address, 443)
    return family, net.socket.SOCK_STREAM, 6, "", sockaddr


@pytest.mark.parametrize(
    ("status", "headers", "expected_content_type", "expected_cf_mitigated"),
    [
        (403, [b"Content-Type: application/json"], "json", "absent"),
        (
            403,
            [b"Content-Type: text/html", b"cf-mitigated: challenge"],
            "html",
            "challenge",
        ),
        (
            403,
            [b"Content-Type: text/event-stream", b"cf-mitigated: managed"],
            "event_stream",
            "other",
        ),
        (403, [b"Content-Type: application/octet-stream"], "other", "absent"),
        (403, [], "missing", "absent"),
        (403, [b"Content-Type: text/html\xff"], "invalid", "absent"),
        (403, [b"Content-Type: text / html"], "invalid", "absent"),
        (
            403,
            [b"Content-Type: application/json", b"Content-Type: text/html"],
            "invalid",
            "absent",
        ),
        (
            403,
            [b"Content-Type: application/json", b"cf-mitigated: challenge", b"cf-mitigated: x"],
            "json",
            "other",
        ),
        (403, [b"Content-Type: application/json", b"cf-mitigated: cha\x01llenge"], "json", "other"),
        (401, [b"Content-Type: text/html", b"cf-mitigated: challenge"], None, None),
        (429, [b"Content-Type: application/json"], None, None),
        (500, [b"Content-Type: text/html"], None, None),
    ],
)
def test_public_https_stream_projects_only_closed_403_header_classes_without_reading_body(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    headers: list[bytes],
    expected_content_type: str | None,
    expected_cf_mitigated: str | None,
) -> None:
    class TrackingReader(asyncio.StreamReader):
        def __init__(self) -> None:
            super().__init__()
            self.body_read_calls = 0

        async def read(self, n: int = -1) -> bytes:
            self.body_read_calls += 1
            return await super().read(n)

        async def readexactly(self, n: int) -> bytes:
            self.body_read_calls += 1
            return await super().readexactly(n)

    class Writer:
        def write(self, _data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    readers: list[TrackingReader] = []

    async def resolve(_loop, host: str, port: int, **_kwargs: object):
        return [_addrinfo_record("93.184.216.34")]

    async def open_connection(*_args: object, **_kwargs: object):
        reader = TrackingReader()
        reader.feed_data(
            f"HTTP/1.1 {status} Synthetic\r\n".encode("ascii")
            + b"".join(header + b"\r\n" for header in headers)
            + b"\r\nPRIVATE BODY MUST NOT BE READ"
        )
        reader.feed_eof()
        readers.append(reader)
        return reader, Writer()

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", resolve)
    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def exercise() -> None:
        with pytest.raises(net.PublicHTTPError) as caught:
            async for _chunk in net.stream_public_https(
                "https://provider.example/v1/responses",
                body=b"{}",
                timeout_seconds=1,
            ):
                raise AssertionError("an error response yielded a body chunk")
        assert caught.value.code == "provider_upstream_unavailable"
        assert caught.value.status_code == status
        assert caught.value.content_type_class == expected_content_type
        assert caught.value.cf_mitigated_class == expected_cf_mitigated
        assert caught.value.provider_error_type_class == ("unknown" if status == 403 else None)
        assert str(caught.value) == "provider_upstream_unavailable"
        assert len(readers) == 1
        assert readers[0].body_read_calls == 0

    asyncio.run(exercise())


def test_public_http_error_keeps_code_only_compatibility_and_validates_403_classes() -> None:
    legacy = net.PublicHTTPError("provider_upstream_unavailable")
    assert legacy.code == "provider_upstream_unavailable"
    assert legacy.status_code is None
    assert legacy.content_type_class is None
    assert legacy.cf_mitigated_class is None
    assert legacy.provider_error_type_class is None
    assert str(legacy) == "provider_upstream_unavailable"

    classified = net.PublicHTTPError(
        "provider_upstream_unavailable",
        status_code=403,
        content_type_class="json",
        cf_mitigated_class="challenge",
    )
    assert classified.content_type_class == "json"
    assert classified.cf_mitigated_class == "challenge"
    classified_type = net.PublicHTTPError(
        "provider_upstream_unavailable",
        status_code=403,
        content_type_class="json",
        cf_mitigated_class="absent",
        provider_error_type_class="region_error",
    )
    assert classified_type.provider_error_type_class == "region_error"

    for values in (
        {
            "status_code": 403,
            "content_type_class": "application/json",
            "cf_mitigated_class": "absent",
        },
        {"status_code": 403, "content_type_class": "json", "cf_mitigated_class": "private"},
        {"status_code": 403, "content_type_class": "json"},
        {
            "status_code": 403,
            "content_type_class": "json",
            "cf_mitigated_class": "absent",
            "provider_error_type_class": "raw-provider-class",
        },
        {
            "status_code": 503,
            "content_type_class": "json",
            "cf_mitigated_class": "absent",
            "provider_error_type_class": "region_error",
        },
        {
            "status_code": 503,
            "content_type_class": "json",
            "cf_mitigated_class": "absent",
        },
    ):
        with pytest.raises(ValueError):
            net.PublicHTTPError("provider_upstream_unavailable", **values)
    with pytest.raises(ValueError):
        net.PublicHTTPError(
            "provider_response_invalid",
            status_code=403,
            provider_error_type_class="region_error",
        )


@pytest.mark.parametrize(
    ("error_type", "expected_class"),
    [
        ("RegionError", "region_error"),
        ("DataPolicyError", "data_policy_error"),
        ("FreeUsageLimitError", "free_usage_limit_error"),
        ("UNTRUSTED_PROVIDER_TYPE_SECRET", "other"),
    ],
)
def test_public_https_stream_projects_only_closed_provider_error_type_classes(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error_type: str,
    expected_class: str,
) -> None:
    body = json.dumps(
        {
            "error": {
                "type": error_type,
                "message": "SYNTHETIC_PROVIDER_BODY_SECRET_7b9a",
            }
        },
        separators=(",", ":"),
    ).encode("utf-8")

    class TrackingReader(asyncio.StreamReader):
        def __init__(self) -> None:
            super().__init__()
            self.body_read_calls = 0
            self.body_read_bytes = 0

        async def readexactly(self, n: int) -> bytes:
            self.body_read_calls += 1
            value = await super().readexactly(n)
            self.body_read_bytes += len(value)
            return value

    class Writer:
        def __init__(self) -> None:
            self.closed = False

        def write(self, _data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            return None

    readers: list[TrackingReader] = []
    writers: list[Writer] = []

    async def resolve(_loop, host: str, port: int, **_kwargs: object):
        return [_addrinfo_record("93.184.216.34")]

    async def open_connection(*_args: object, **_kwargs: object):
        reader = TrackingReader()
        reader.feed_data(
            b"HTTP/1.1 403 Forbidden\r\n"
            b"Content-Type: application/json; charset=utf-8\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
            + body
        )
        reader.feed_eof()
        writer = Writer()
        readers.append(reader)
        writers.append(writer)
        return reader, writer

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", resolve)
    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def exercise() -> net.PublicHTTPError:
        with pytest.raises(net.PublicHTTPError) as caught:
            async for _chunk in net.stream_public_https(
                "https://provider.example/v1/responses",
                body=b"{}",
                timeout_seconds=1,
            ):
                raise AssertionError("an error response yielded a body chunk")
        return caught.value

    error = asyncio.run(exercise())
    assert error.code == "provider_upstream_unavailable"
    assert error.status_code == 403
    assert error.provider_error_type_class == expected_class
    assert error.args == ("provider_upstream_unavailable",)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert "SYNTHETIC_PROVIDER_BODY_SECRET_7b9a" not in repr(error)
    assert "SYNTHETIC_PROVIDER_BODY_SECRET_7b9a" not in caplog.text
    assert "UNTRUSTED_PROVIDER_TYPE_SECRET" not in repr(error)
    assert "UNTRUSTED_PROVIDER_TYPE_SECRET" not in caplog.text
    assert "UNTRUSTED_PROVIDER_TYPE_SECRET" not in repr(vars(error))
    assert readers[0].body_read_calls == 1
    assert readers[0].body_read_bytes == len(body)
    assert writers[0].closed


@pytest.mark.parametrize(
    ("body", "expected_class"),
    [
        (b"not-json", "malformed"),
        (b"\xff", "malformed"),
        (b"[]", "malformed"),
        (b'{"error":null}', "malformed"),
        (b'{"error":{"message":"missing type"}}', "malformed"),
        (b'{"error":{"type":12}}', "malformed"),
        (b'{"error":{"type":""}}', "malformed"),
        (b'{"error":{"type":"RegionError","type":"DataPolicyError"}}', "malformed"),
        (b'{"error":{"type":"RegionError"},"error":{"type":"DataPolicyError"}}', "malformed"),
        (b'{"other":NaN,"error":{"type":"RegionError"}}', "malformed"),
        (b'{"other":Infinity,"error":{"type":"RegionError"}}', "malformed"),
        (b'{"other":-Infinity,"error":{"type":"RegionError"}}', "malformed"),
        (b'{"error":{"type":"' + b"x" * 129 + b'"}}', "malformed"),
    ],
)
def test_public_https_stream_marks_malformed_provider_error_json_without_retaining_body(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
    expected_class: str,
) -> None:
    class TrackingReader(asyncio.StreamReader):
        def __init__(self) -> None:
            super().__init__()
            self.body_read_calls = 0

        async def readexactly(self, n: int) -> bytes:
            self.body_read_calls += 1
            return await super().readexactly(n)

    class Writer:
        def __init__(self) -> None:
            self.closed = False

        def write(self, _data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            return None

    readers: list[TrackingReader] = []
    writers: list[Writer] = []

    async def resolve(_loop, host: str, port: int, **_kwargs: object):
        return [_addrinfo_record("93.184.216.34")]

    async def open_connection(*_args: object, **_kwargs: object):
        reader = TrackingReader()
        reader.feed_data(
            b"HTTP/1.1 403 Forbidden\r\n"
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
            + body
        )
        reader.feed_eof()
        writer = Writer()
        readers.append(reader)
        writers.append(writer)
        return reader, writer

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", resolve)
    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def exercise() -> net.PublicHTTPError:
        with pytest.raises(net.PublicHTTPError) as caught:
            async for _chunk in net.stream_public_https(
                "https://provider.example/v1/responses",
                body=b"{}",
                timeout_seconds=1,
            ):
                raise AssertionError("an error response yielded a body chunk")
        return caught.value

    error = asyncio.run(exercise())
    assert error.provider_error_type_class == expected_class
    assert error.__cause__ is None
    assert error.__context__ is None
    decoded_body = body.decode("utf-8", errors="ignore")
    if decoded_body:
        assert decoded_body not in repr(vars(error))
    assert readers[0].body_read_calls == (0 if not body else 1)
    assert writers[0].closed


@pytest.mark.parametrize(
    ("status", "headers", "expected_error_code", "expected_type_class"),
    [
        (
            403,
            [b"Content-Type: text/html", b"Content-Length: 2"],
            "provider_upstream_unavailable",
            "unknown",
        ),
        (
            403,
            [
                b"Content-Type: application/json",
                b"cf-mitigated: challenge",
                b"Content-Length: 2",
            ],
            "provider_upstream_unavailable",
            "unknown",
        ),
        (
            403,
            [b"Content-Type: application/json"],
            "provider_upstream_unavailable",
            "unknown",
        ),
        (
            403,
            [b"Content-Type: application/json", b"Transfer-Encoding: chunked"],
            "provider_upstream_unavailable",
            "unknown",
        ),
        (
            403,
            [
                b"Content-Type: application/json",
                b"Content-Length: 2",
                b"Content-Encoding: gzip",
            ],
            "provider_upstream_unavailable",
            "unknown",
        ),
        (
            403,
            [b"Content-Type: application/json", b"Content-Length: 4097"],
            "provider_upstream_unavailable",
            "unknown",
        ),
        (
            403,
            [b"Content-Type: application/json", b"Content-Length: +2"],
            "provider_upstream_unavailable",
            "unknown",
        ),
        (
            403,
            [b"Content-Type: application/json", b"Content-Length: 0"],
            "provider_upstream_unavailable",
            "malformed",
        ),
        (
            403,
            [b"Content-Type: application/json", b"Content-Length: 0000000000000000000000002"],
            "provider_upstream_unavailable",
            "unknown",
        ),
        (
            403,
            [
                b"Content-Type: application/json",
                b"Content-Length: 2",
                b"Transfer-Encoding: chunked",
            ],
            "provider_upstream_unavailable",
            "unknown",
        ),
        (
            403,
            [b"Content-Type: application/problem+json", b"Content-Length: 2"],
            "provider_upstream_unavailable",
            "unknown",
        ),
        (
            401,
            [b"Content-Type: application/json", b"Content-Length: 2"],
            "provider_upstream_unavailable",
            None,
        ),
        (
            403,
            [
                b"Content-Type: application/json",
                b"Content-Length: 2",
                b"Content-Length: 2",
            ],
            "provider_response_invalid",
            None,
        ),
    ],
)
def test_public_https_stream_does_not_read_unsupported_403_diagnostic_framing(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    headers: list[bytes],
    expected_error_code: str,
    expected_type_class: str | None,
) -> None:
    class TrackingReader(asyncio.StreamReader):
        def __init__(self) -> None:
            super().__init__()
            self.body_read_calls = 0

        async def read(self, n: int = -1) -> bytes:
            self.body_read_calls += 1
            return await super().read(n)

        async def readexactly(self, n: int) -> bytes:
            self.body_read_calls += 1
            return await super().readexactly(n)

    class Writer:
        def __init__(self) -> None:
            self.closed = False

        def write(self, _data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            return None

    readers: list[TrackingReader] = []
    writers: list[Writer] = []

    async def resolve(_loop, host: str, port: int, **_kwargs: object):
        return [_addrinfo_record("93.184.216.34")]

    async def open_connection(*_args: object, **_kwargs: object):
        reader = TrackingReader()
        reader.feed_data(
            f"HTTP/1.1 {status} Synthetic\r\n".encode("ascii")
            + b"".join(header + b"\r\n" for header in headers)
            + b"\r\nSYNTHETIC_BODY_SECRET"
        )
        reader.feed_eof()
        writer = Writer()
        readers.append(reader)
        writers.append(writer)
        return reader, writer

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", resolve)
    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def exercise() -> net.PublicHTTPError:
        with pytest.raises(net.PublicHTTPError) as caught:
            async for _chunk in net.stream_public_https(
                "https://provider.example/v1/responses",
                body=b"{}",
                timeout_seconds=1,
            ):
                raise AssertionError("an error response yielded a body chunk")
        return caught.value

    error = asyncio.run(exercise())
    assert error.code == expected_error_code
    assert error.provider_error_type_class == expected_type_class
    assert readers[0].body_read_calls == 0
    assert writers[0].closed


def test_public_https_stream_bounds_403_diagnostic_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(net, "_PROVIDER_403_DIAGNOSTIC_TIMEOUT_SECONDS", 0.01)
    readers: list[asyncio.StreamReader] = []

    class Writer:
        def __init__(self) -> None:
            self.closed = False

        def write(self, _data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            return None

    writers: list[Writer] = []

    async def resolve(_loop, host: str, port: int, **_kwargs: object):
        return [_addrinfo_record("93.184.216.34")]

    async def open_connection(*_args: object, **_kwargs: object):
        reader = asyncio.StreamReader()
        reader.feed_data(
            b"HTTP/1.1 403 Forbidden\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: 64\r\n\r\nSYNTHETIC_PARTIAL_SECRET"
        )
        writer = Writer()
        readers.append(reader)
        writers.append(writer)
        return reader, writer

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", resolve)
    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def exercise() -> net.PublicHTTPError:
        with pytest.raises(net.PublicHTTPError) as caught:
            async for _chunk in net.stream_public_https(
                "https://provider.example/v1/responses",
                body=b"{}",
                timeout_seconds=1,
            ):
                raise AssertionError("an error response yielded a body chunk")
        return caught.value

    error = asyncio.run(exercise())
    assert error.provider_error_type_class == "unknown"
    assert error.__cause__ is None
    assert error.__context__ is None
    assert "SYNTHETIC_PARTIAL_SECRET" not in repr(error)
    assert readers[0].at_eof() is False
    assert writers[0].closed


def test_public_https_stream_suppresses_truncated_403_body_exception_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partial = b'{"error":{"type":"RegionError","message":"SYNTHETIC_PARTIAL_SECRET"}}'

    class TrackingReader(asyncio.StreamReader):
        def __init__(self) -> None:
            super().__init__()
            self.body_read_calls = 0

        async def readexactly(self, n: int) -> bytes:
            self.body_read_calls += 1
            return await super().readexactly(n)

    class Writer:
        def __init__(self) -> None:
            self.closed = False

        def write(self, _data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            return None

    readers: list[TrackingReader] = []
    writers: list[Writer] = []

    async def resolve(_loop, host: str, port: int, **_kwargs: object):
        return [_addrinfo_record("93.184.216.34")]

    async def open_connection(*_args: object, **_kwargs: object):
        reader = TrackingReader()
        reader.feed_data(
            b"HTTP/1.1 403 Forbidden\r\n"
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(partial) + 3}\r\n\r\n".encode("ascii")
            + partial
        )
        reader.feed_eof()
        writer = Writer()
        readers.append(reader)
        writers.append(writer)
        return reader, writer

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", resolve)
    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def exercise() -> net.PublicHTTPError:
        with pytest.raises(net.PublicHTTPError) as caught:
            async for _chunk in net.stream_public_https(
                "https://provider.example/v1/responses",
                body=b"{}",
                timeout_seconds=1,
            ):
                raise AssertionError("an error response yielded a body chunk")
        return caught.value

    error = asyncio.run(exercise())
    assert error.provider_error_type_class == "unknown"
    assert error.__cause__ is None
    assert error.__context__ is None
    assert "SYNTHETIC_PARTIAL_SECRET" not in repr(error)
    assert readers[0].body_read_calls == 1
    assert writers[0].closed


def test_public_https_stream_treats_truncated_403_diagnostic_as_unknown_without_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partial = b'{"error":{"type":"RegionError","message":"SYNTHETIC_PARTIAL_SECRET"}}'

    class Writer:
        def __init__(self) -> None:
            self.closed = False

        def write(self, _data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            return None

    class Reader(asyncio.StreamReader):
        def __init__(self) -> None:
            super().__init__()
            self.body_read_calls = 0

        async def readexactly(self, n: int) -> bytes:
            self.body_read_calls += 1
            return await super().readexactly(n)

    readers: list[Reader] = []
    writers: list[Writer] = []

    async def resolve(_loop, host: str, port: int, **_kwargs: object):
        return [_addrinfo_record("93.184.216.34")]

    async def open_connection(*_args: object, **_kwargs: object):
        reader = Reader()
        reader.feed_data(
            b"HTTP/1.1 403 Forbidden\r\n"
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(partial) + 10}\r\n\r\n".encode("ascii")
            + partial
        )
        reader.feed_eof()
        writer = Writer()
        readers.append(reader)
        writers.append(writer)
        return reader, writer

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", resolve)
    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def exercise() -> net.PublicHTTPError:
        with pytest.raises(net.PublicHTTPError) as caught:
            async for _chunk in net.stream_public_https(
                "https://provider.example/v1/responses",
                body=b"{}",
                timeout_seconds=1,
            ):
                raise AssertionError("an error response yielded a body chunk")
        return caught.value

    error = asyncio.run(exercise())
    assert error.provider_error_type_class == "unknown"
    assert error.__cause__ is None
    assert error.__context__ is None
    assert "SYNTHETIC_PARTIAL_SECRET" not in repr(error)
    assert readers[0].body_read_calls == 1
    assert writers[0].closed


def test_public_https_stream_rejects_short_403_read_result_without_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partial = b'{"error":{"type":"RegionError","message":"SYNTHETIC_SHORT_READ_SECRET"}}'

    class Reader(asyncio.StreamReader):
        def __init__(self) -> None:
            super().__init__()
            self.body_read_calls = 0

        async def readexactly(self, n: int) -> bytes:
            self.body_read_calls += 1
            assert n == len(partial) + 7
            return partial

    class Writer:
        def __init__(self) -> None:
            self.closed = False

        def write(self, _data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            return None

    readers: list[Reader] = []
    writers: list[Writer] = []

    async def resolve(_loop, host: str, port: int, **_kwargs: object):
        return [_addrinfo_record("93.184.216.34")]

    async def open_connection(*_args: object, **_kwargs: object):
        reader = Reader()
        reader.feed_data(
            b"HTTP/1.1 403 Forbidden\r\n"
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(partial) + 7}\r\n\r\n".encode("ascii")
        )
        writer = Writer()
        readers.append(reader)
        writers.append(writer)
        return reader, writer

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", resolve)
    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def exercise() -> net.PublicHTTPError:
        with pytest.raises(net.PublicHTTPError) as caught:
            async for _chunk in net.stream_public_https(
                "https://provider.example/v1/responses",
                body=b"{}",
                timeout_seconds=1,
            ):
                raise AssertionError("an error response yielded a body chunk")
        return caught.value

    error = asyncio.run(exercise())
    assert error.provider_error_type_class == "unknown"
    assert error.__cause__ is None
    assert error.__context__ is None
    assert "SYNTHETIC_SHORT_READ_SECRET" not in repr(error)
    assert readers[0].body_read_calls == 1
    assert writers[0].closed


def test_public_https_stream_propagates_revocation_around_403_diagnostic_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b'{"error":{"type":"RegionError","message":"SYNTHETIC_REVOKED_SECRET"}}'

    class TrackingReader(asyncio.StreamReader):
        def __init__(self) -> None:
            super().__init__()
            self.body_read_calls = 0

        async def readexactly(self, n: int) -> bytes:
            self.body_read_calls += 1
            return await super().readexactly(n)

    class Writer:
        def __init__(self) -> None:
            self.closed = False

        def write(self, _data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            return None

    readers: list[TrackingReader] = []
    writers: list[Writer] = []

    async def resolve(_loop, host: str, port: int, **_kwargs: object):
        return [_addrinfo_record("93.184.216.34")]

    async def open_connection(*_args: object, **_kwargs: object):
        reader = TrackingReader()
        reader.feed_data(
            b"HTTP/1.1 403 Forbidden\r\n"
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
            + body
        )
        reader.feed_eof()
        writer = Writer()
        readers.append(reader)
        writers.append(writer)
        return reader, writer

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", resolve)
    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def exercise(revoked_at_call: int) -> net.PublicHTTPError:
        calls = 0

        async def authorize() -> bool:
            nonlocal calls
            calls += 1
            return calls != revoked_at_call

        with pytest.raises(net.PublicHTTPError) as caught:
            async for _chunk in net.stream_public_https(
                "https://provider.example/v1/responses",
                body=b"{}",
                timeout_seconds=1,
                authorization_check=authorize,
            ):
                raise AssertionError("an error response yielded a body chunk")
        return caught.value

    before_read_error = asyncio.run(exercise(revoked_at_call=3))
    assert before_read_error.code == "provider_authorization_required"
    assert before_read_error.provider_error_type_class is None
    assert readers[0].body_read_calls == 0
    assert writers[0].closed

    after_read_error = asyncio.run(exercise(revoked_at_call=4))
    assert after_read_error.code == "provider_authorization_required"
    assert after_read_error.provider_error_type_class is None
    assert after_read_error.__context__ is None
    assert "SYNTHETIC_REVOKED_SECRET" not in repr(after_read_error)
    assert readers[1].body_read_calls == 1
    assert writers[1].closed


def test_public_https_stream_cancellation_during_403_diagnostic_closes_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class WaitingReader(asyncio.StreamReader):
        def __init__(self) -> None:
            super().__init__()
            self.body_read_started = asyncio.Event()

        async def readexactly(self, n: int) -> bytes:
            self.body_read_started.set()
            return await super().readexactly(n)

    class Writer:
        def __init__(self) -> None:
            self.closed = False

        def write(self, _data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            return None

    readers: list[WaitingReader] = []
    writers: list[Writer] = []

    async def resolve(_loop, host: str, port: int, **_kwargs: object):
        return [_addrinfo_record("93.184.216.34")]

    async def open_connection(*_args: object, **_kwargs: object):
        reader = WaitingReader()
        reader.feed_data(
            b"HTTP/1.1 403 Forbidden\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: 32\r\n\r\n"
        )
        writer = Writer()
        readers.append(reader)
        writers.append(writer)
        return reader, writer

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", resolve)
    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def exercise() -> None:
        async def consume() -> None:
            async for _chunk in net.stream_public_https(
                "https://provider.example/v1/responses",
                body=b"{}",
                timeout_seconds=10,
            ):
                raise AssertionError("an error response yielded a body chunk")

        task = asyncio.create_task(consume())
        await asyncio.wait_for(readers_waiting(), timeout=0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async def readers_waiting() -> None:
        while not readers:
            await asyncio.sleep(0)
        await readers[0].body_read_started.wait()

    asyncio.run(exercise())
    assert writers[0].closed


def test_public_https_request_uses_validated_form_content_type(monkeypatch) -> None:
    """OAuth refresh sends form bytes with the declared type, not JSON or a caller override."""

    captured: bytearray = bytearray()

    class Writer:
        def write(self, data: bytes) -> None:
            captured.extend(data)

        async def drain(self) -> None:
            return

        def close(self) -> None:
            return

        async def wait_closed(self) -> None:
            return

    async def exercise() -> net.PublicHTTPResponse:
        reader = asyncio.StreamReader()
        reader.feed_data(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
        reader.feed_eof()

        async def open_connection(*_args: object, **_kwargs: object) -> tuple[object, Writer]:
            return reader, Writer()

        monkeypatch.setattr(net.asyncio, "open_connection", open_connection)
        return await net.request_public_https(
            "https://auth.example/oauth/token",
            method="POST",
            body=b"grant_type=refresh_token&refresh_token=synthetic",
            content_type="application/x-www-form-urlencoded",
            resolver=lambda _host, _port: [
                (2, 1, 6, "", ("8.8.8.8", 443)),
            ],
        )

    response = asyncio.run(exercise())

    request = bytes(captured).lower()
    assert response.status_code == 200
    assert response.content == b"{}"
    assert b"post /oauth/token http/1.1\r\n" in request
    assert b"content-type: application/x-www-form-urlencoded\r\n" in request
    assert request.endswith(b"grant_type=refresh_token&refresh_token=synthetic")


@pytest.mark.parametrize("held_phase", ("dns", "tls"))
def test_public_https_request_rechecks_authorization_before_provider_bytes(
    monkeypatch: pytest.MonkeyPatch, held_phase: str
) -> None:
    """A revocation during DNS or TLS stops the request before credential bytes are written."""

    phase_started = asyncio.Event()
    release_phase = asyncio.Event()
    writer_state: dict[str, object] = {"writes": 0, "closed": False}
    authorization = {"allowed": True}

    class Writer:
        def write(self, _data: bytes) -> None:
            writer_state["writes"] = int(writer_state["writes"]) + 1

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            writer_state["closed"] = True

        async def wait_closed(self) -> None:
            return None

    async def resolver(_host: str, _port: int) -> list[object]:
        if held_phase == "dns":
            phase_started.set()
            await release_phase.wait()
        return [_addrinfo_record("93.184.216.34")]

    async def open_connection(*_args: object, **_kwargs: object):
        if held_phase == "tls":
            phase_started.set()
            await release_phase.wait()
        return asyncio.StreamReader(), Writer()

    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def authorize() -> bool:
        return authorization["allowed"] is True

    async def exercise() -> net.PublicHTTPError:
        pending = asyncio.create_task(
            net.request_public_https(
                "https://provider.example/v1/models",
                headers={"authorization": "Bearer synthetic-provider-secret"},
                timeout_seconds=2,
                resolver=resolver,
                authorization_check=authorize,
            )
        )
        await asyncio.wait_for(phase_started.wait(), timeout=1)
        authorization["allowed"] = False
        release_phase.set()
        with pytest.raises(net.PublicHTTPError) as caught:
            await pending
        return caught.value

    error = asyncio.run(exercise())
    assert error.code == "provider_authorization_required"
    assert writer_state["writes"] == 0
    assert writer_state["closed"] is (held_phase == "tls")


def test_public_https_request_rejects_unreviewed_content_type() -> None:
    async def exercise() -> None:
        await net.request_public_https(
            "https://auth.example/oauth/token",
            method="POST",
            body=b"synthetic",
            content_type="text/plain",
            resolver=lambda _host, _port: [],
        )

    try:
        asyncio.run(exercise())
    except net.PublicHTTPError as exc:
        assert exc.code == "request_invalid"
    else:
        raise AssertionError("unreviewed request content type was accepted")


@pytest.mark.parametrize("address", ["224.0.0.1", "ff02::1"])
def test_public_https_request_rejects_multicast_dns_answers_before_connect(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    connection_attempts: list[str] = []

    async def open_connection(host: str, *_args: object, **_kwargs: object):
        connection_attempts.append(host)
        raise AssertionError("non-unicast destination reached the socket layer")

    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def exercise() -> None:
        with pytest.raises(net.PublicHTTPError) as caught:
            await net.request_public_https(
                "https://provider.example/v1/models",
                resolver=lambda _host, _port: [_addrinfo_record(address)],
            )
        assert caught.value.code == "private_destination_rejected"

    asyncio.run(exercise())
    assert connection_attempts == []


@pytest.mark.parametrize("address", ["224.0.0.1", "ff02::1"])
def test_public_https_stream_rejects_multicast_dns_answers_before_connect(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    connection_attempts: list[str] = []

    async def resolve(_loop, host: str, port: int, **_kwargs: object):
        return [_addrinfo_record(address)]

    async def open_connection(host: str, *_args: object, **_kwargs: object):
        connection_attempts.append(host)
        raise AssertionError("non-unicast destination reached the socket layer")

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", resolve)
    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def exercise() -> None:
        with pytest.raises(net.PublicHTTPError) as caught:
            async for _chunk in net.stream_public_https(
                "https://provider.example/v1/responses",
                body=b"{}",
                timeout_seconds=1,
            ):
                raise AssertionError("a rejected destination emitted response bytes")
        assert caught.value.code == "private_destination_rejected"

    asyncio.run(exercise())
    assert connection_attempts == []


def test_public_https_stream_accepts_public_unicast_dns_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_body = b"data: [DONE]\n\n"
    connection_attempts: list[str] = []

    class Writer:
        def write(self, _data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    async def resolve(_loop, host: str, port: int, **_kwargs: object):
        return [_addrinfo_record("93.184.216.34")]

    async def open_connection(host: str, *_args: object, **_kwargs: object):
        connection_attempts.append(host)
        reader = asyncio.StreamReader()
        reader.feed_data(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/event-stream\r\n"
            + f"Content-Length: {len(response_body)}\r\n\r\n".encode("ascii")
            + response_body
        )
        reader.feed_eof()
        return reader, Writer()

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", resolve)
    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def exercise() -> bytes:
        return b"".join(
            [
                chunk
                async for chunk in net.stream_public_https(
                    "https://provider.example/v1/responses",
                    body=b"{}",
                    timeout_seconds=1,
                )
            ]
        )

    assert asyncio.run(exercise()) == response_body
    assert connection_attempts == ["93.184.216.34"]


@pytest.mark.parametrize(
    ("response_bytes", "expected_phase", "expected_status"),
    [
        (b"not-http\r\n", "status_line", None),
        (b"HTTP/1.1 200 OK\r\nbad header\r\n\r\n", "headers", 200),
        (
            b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Type: text/event-stream\r\n\r\n",
            "content_encoding",
            200,
        ),
        (
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 0\r\n\r\n",
            "content_type",
            200,
        ),
        (
            b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
            b"Content-Length: 0\r\nTransfer-Encoding: chunked\r\n\r\n",
            "transfer_framing",
            200,
        ),
        (
            b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: 1\r\n\r\n",
            "body_eof",
            200,
        ),
    ],
)
def test_public_https_stream_classifies_closed_response_failure_phases(
    monkeypatch: pytest.MonkeyPatch,
    response_bytes: bytes,
    expected_phase: str,
    expected_status: int | None,
) -> None:
    class Writer:
        def write(self, _data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    async def resolve(_loop, _host: str, _port: int, **_kwargs: object):
        return [_addrinfo_record("93.184.216.34")]

    async def open_connection(_host: str, *_args: object, **_kwargs: object):
        reader = asyncio.StreamReader()
        reader.feed_data(response_bytes)
        reader.feed_eof()
        return reader, Writer()

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", resolve)
    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def exercise() -> None:
        with pytest.raises(net.PublicHTTPError) as caught:
            async for _chunk in net.stream_public_https(
                "https://provider.example/v1/responses",
                body=b"{}",
                timeout_seconds=1,
            ):
                raise AssertionError("invalid response emitted data")
        assert caught.value.code == "provider_response_invalid"
        assert caught.value.response_failure_phase == expected_phase
        assert caught.value.status_code == expected_status
        assert str(caught.value) == "provider_response_invalid"

    asyncio.run(exercise())


def test_public_https_stream_yields_available_data_before_chunk_remainder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed SSE event is yielded before the rest of its HTTP chunk arrives."""

    first_event = b"data: first\n\n"
    later_event = b"data: " + b"x" * 20_000 + b"\n\n"
    payload = first_event + later_event
    response_head = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: text/event-stream\r\n"
        b"Transfer-Encoding: chunked\r\n\r\n"
        + f"{len(payload):X};synthetic=yes\r\n".encode("ascii")
        + first_event
    )

    class Writer:
        def __init__(self) -> None:
            self.closed = False
            self.waited_closed = False

        def write(self, _data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            self.waited_closed = True

    writer = Writer()

    async def resolve(_loop, host: str, port: int, **_kwargs: object):
        return [_addrinfo_record("93.184.216.34")]

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", resolve)

    async def exercise() -> bytes:
        reader = asyncio.StreamReader()
        reader.feed_data(response_head)
        release_remainder = asyncio.Event()

        async def open_connection(host: str, *_args: object, **_kwargs: object):
            assert host == "93.184.216.34"
            return reader, writer

        async def feed_remainder_after_first_yield() -> None:
            await release_remainder.wait()
            reader.feed_data(later_event + b"\r\n0\r\n\r\n")
            reader.feed_eof()

        monkeypatch.setattr(net.asyncio, "open_connection", open_connection)
        stream = net.stream_public_https(
            "https://provider.example/v1/responses",
            body=b"{}",
            timeout_seconds=1,
        )
        feeder = asyncio.create_task(feed_remainder_after_first_yield())
        try:
            try:
                first = await anext(stream)
            except net.PublicHTTPError as exc:
                raise AssertionError(
                    f"first available SSE bytes were buffered until {exc.code}"
                ) from exc
            assert first == first_event
            assert not release_remainder.is_set()
            release_remainder.set()
            chunks = [first]
            async for chunk in stream:
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            release_remainder.set()
            await feeder
            await stream.aclose()
            assert writer.closed

    assert asyncio.run(exercise()) == payload
    assert writer.waited_closed


@pytest.mark.parametrize(
    "size_token",
    [b"-1", b"+1", b"1 ", b" 1", b"0x1", b"1g", b"\xff", b"\xb9"],
)
def test_public_https_stream_rejects_non_hex_chunk_sizes_before_body_io(
    monkeypatch: pytest.MonkeyPatch,
    size_token: bytes,
) -> None:
    """Malformed chunk sizes fail before body bytes are read or yielded."""

    class Writer:
        def __init__(self) -> None:
            self.closed = False

        def write(self, _data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            return None

    class ObservedStreamReader(asyncio.StreamReader):
        def __init__(self) -> None:
            super().__init__()
            self.body_read_sizes: list[int] = []

        async def read(self, n: int = -1) -> bytes:
            self.body_read_sizes.append(n)
            return await super().read(n)

    writer = Writer()
    readers: list[ObservedStreamReader] = []

    async def resolve(_loop, host: str, port: int, **_kwargs: object):
        return [_addrinfo_record("93.184.216.34")]

    async def open_connection(
        host: str, *_args: object, **_kwargs: object
    ) -> tuple[ObservedStreamReader, Writer]:
        reader = ObservedStreamReader()
        reader.feed_data(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/event-stream\r\n"
            b"Transfer-Encoding: chunked\r\n\r\n" + size_token + b"\r\npayload\r\n0\r\n\r\n"
        )
        reader.feed_eof()
        readers.append(reader)
        return reader, writer

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", resolve)
    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def exercise() -> list[bytes]:
        chunks: list[bytes] = []
        with pytest.raises(net.PublicHTTPError) as caught:
            async for chunk in net.stream_public_https(
                "https://provider.example/v1/responses",
                body=b"{}",
                timeout_seconds=1,
            ):
                chunks.append(chunk)
        assert caught.value.code == "provider_response_invalid"
        assert caught.value.response_failure_phase == "transfer_framing"
        return chunks

    chunks = asyncio.run(exercise())
    assert chunks == []
    assert readers[0].body_read_sizes == []
    assert writer.closed


@pytest.mark.parametrize(
    ("chunked_body", "max_response_bytes", "expected_code", "expected_prefix"),
    [
        (b"4\r\nab", 16, "provider_response_invalid", b"ab"),
        (b"3\r\nabcXX", 16, "provider_response_invalid", b"abc"),
        (b"4\r\nabcd\r\n0\r\n\r\n", 3, "provider_response_too_large", b""),
        (b"2\r\nab\r\n2\r\ncd\r\n0\r\n\r\n", 3, "provider_response_too_large", b"ab"),
    ],
)
def test_public_https_stream_rejects_invalid_chunked_framing_and_bounds(
    monkeypatch: pytest.MonkeyPatch,
    chunked_body: bytes,
    max_response_bytes: int,
    expected_code: str,
    expected_prefix: bytes,
) -> None:
    """Framing errors fail after only the bounded chunk prefix has been yielded."""

    class Writer:
        def __init__(self) -> None:
            self.closed = False

        def write(self, _data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            return None

    writer = Writer()

    async def resolve(_loop, host: str, port: int, **_kwargs: object):
        return [_addrinfo_record("93.184.216.34")]

    async def open_connection(host: str, *_args: object, **_kwargs: object):
        reader = asyncio.StreamReader()
        reader.feed_data(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/event-stream\r\n"
            b"Transfer-Encoding: chunked\r\n\r\n" + chunked_body
        )
        reader.feed_eof()
        return reader, writer

    monkeypatch.setattr(net.asyncio.BaseEventLoop, "getaddrinfo", resolve)
    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def exercise() -> bytes:
        chunks: list[bytes] = []
        with pytest.raises(net.PublicHTTPError) as caught:
            async for chunk in net.stream_public_https(
                "https://provider.example/v1/responses",
                body=b"{}",
                timeout_seconds=1,
                max_response_bytes=max_response_bytes,
            ):
                chunks.append(chunk)
        assert caught.value.code == expected_code
        if expected_code == "provider_response_invalid":
            assert caught.value.response_failure_phase == (
                "body_eof" if chunked_body == b"4\r\nab" else "transfer_framing"
            )
        return b"".join(chunks)

    assert asyncio.run(exercise()) == expected_prefix
    assert writer.closed


@pytest.mark.parametrize("address", ["224.0.0.1", "ff02::1", "::ffff:93.184.216.34"])
def test_public_unicast_classifier_rejects_special_or_ambiguous_addresses(address: str) -> None:
    assert not net.is_public_unicast(net.ipaddress.ip_address(address))


@pytest.mark.parametrize("address", ["8.8.8.8", "2606:4700:4700::1111"])
def test_public_unicast_classifier_accepts_public_v4_and_v6(address: str) -> None:
    assert net.is_public_unicast(net.ipaddress.ip_address(address))


def test_public_https_request_denies_before_dns_when_authorization_is_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver_calls: list[str] = []
    connection_attempts: list[str] = []

    async def resolver(host: str, _port: int) -> list[object]:
        resolver_calls.append(host)
        return [_addrinfo_record("93.184.216.34")]

    async def open_connection(host: str, *_args: object, **_kwargs: object):
        connection_attempts.append(host)
        raise AssertionError("denied request reached the socket layer")

    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def authorize() -> bool:
        return False

    async def exercise() -> net.PublicHTTPError:
        with pytest.raises(net.PublicHTTPError) as caught:
            await net.request_public_https(
                "https://provider.example/oauth/token",
                method="POST",
                body=b"code=synthetic-authorization-code",
                resolver=resolver,
                authorization_check=authorize,
            )
        return caught.value

    error = asyncio.run(exercise())
    assert error.code == "provider_authorization_required"
    assert resolver_calls == []
    assert connection_attempts == []


def test_public_https_request_withholds_response_body_after_mid_read_revocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body_read_started = asyncio.Event()
    release_body = asyncio.Event()
    authorization = {"allowed": True}
    callback_calls = 0
    reader: asyncio.StreamReader | None = None
    writer_state = {"closed": False, "wait_closed": False}
    captured_response: list[net.PublicHTTPResponse] = []

    class HeldBodyReader(asyncio.StreamReader):
        async def read(self, n: int = -1) -> bytes:
            body_read_started.set()
            await release_body.wait()
            return await super().read(n)

    class Writer:
        def write(self, _data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            writer_state["closed"] = True

        async def wait_closed(self) -> None:
            writer_state["wait_closed"] = True

    async def open_connection(*_args: object, **_kwargs: object):
        nonlocal reader
        reader = HeldBodyReader()
        reader.feed_data(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 25\r\n\r\n"
        )
        return reader, Writer()

    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def authorize() -> bool:
        nonlocal callback_calls
        callback_calls += 1
        return authorization["allowed"] is True

    async def exercise() -> net.PublicHTTPError:
        pending = asyncio.create_task(
            net.request_public_https(
                "https://provider.example/oauth/token",
                method="POST",
                body=b"code=synthetic-authorization-code",
                timeout_seconds=2,
                resolver=lambda _host, _port: [_addrinfo_record("93.184.216.34")],
                authorization_check=authorize,
            )
        )
        await asyncio.wait_for(body_read_started.wait(), timeout=1)
        authorization["allowed"] = False
        assert reader is not None
        reader.feed_data(b'{"access_token":"secret"}')
        reader.feed_eof()
        release_body.set()
        with pytest.raises(net.PublicHTTPError) as caught:
            response = await pending
            captured_response.append(response)
        return caught.value

    error = asyncio.run(exercise())
    assert error.code == "provider_authorization_required"
    assert "secret" not in repr(error)
    assert captured_response == []
    assert callback_calls == 4
    assert writer_state == {"closed": True, "wait_closed": True}


def test_public_https_request_cancellation_during_body_read_closes_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body_read_started = asyncio.Event()
    release_body = asyncio.Event()
    writer_state = {"closed": False, "wait_closed": False}

    class HeldBodyReader(asyncio.StreamReader):
        async def read(self, n: int = -1) -> bytes:
            body_read_started.set()
            await release_body.wait()
            return await super().read(n)

    class Writer:
        def write(self, _data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            writer_state["closed"] = True

        async def wait_closed(self) -> None:
            writer_state["wait_closed"] = True

    async def open_connection(*_args: object, **_kwargs: object):
        reader = HeldBodyReader()
        reader.feed_data(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n"
        )
        return reader, Writer()

    monkeypatch.setattr(net.asyncio, "open_connection", open_connection)

    async def exercise() -> None:
        pending = asyncio.create_task(
            net.request_public_https(
                "https://provider.example/oauth/token",
                timeout_seconds=2,
                resolver=lambda _host, _port: [_addrinfo_record("93.184.216.34")],
                authorization_check=lambda: True,
            )
        )
        await asyncio.wait_for(body_read_started.wait(), timeout=1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending

    asyncio.run(exercise())
    assert writer_state == {"closed": True, "wait_closed": True}
