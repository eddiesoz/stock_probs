"""Small bounded HTTPS client that pins the validated public DNS answer per request."""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import ipaddress
import json
import socket
import ssl
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from urllib.parse import urlsplit

MAX_HEADER_BYTES = 65_536
_DNS_TIMEOUT_SECONDS = 5.5
_HEADER_NAME_CHARS = frozenset(
    "!#$%&'*+-.^_`|~0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
)
_HEADER_VALUE_TOKEN_BYTES = frozenset(
    b"!#$%&'*+-.^_`|~0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
)
_PROVIDER_403_CONTENT_TYPE_CLASSES = frozenset(
    {"json", "html", "event_stream", "other", "missing", "invalid"}
)
_PROVIDER_403_CF_MITIGATED_CLASSES = frozenset({"challenge", "absent", "other"})
_PROVIDER_403_ERROR_TYPE_CLASSES = frozenset(
    {"region_error", "data_policy_error", "free_usage_limit_error", "other", "malformed", "unknown"}
)
_PROVIDER_RESPONSE_FAILURE_PHASES = frozenset(
    {
        "body_eof",
        "content_encoding",
        "content_type",
        "headers",
        "status_line",
        "transfer_framing",
        "transport_io",
    }
)
_PROVIDER_403_ERROR_TYPE_MAP = {
    "RegionError": "region_error",
    "DataPolicyError": "data_policy_error",
    "FreeUsageLimitError": "free_usage_limit_error",
}
_PROVIDER_403_JSON_BODY_MAX_BYTES = 4096
_PROVIDER_403_DIAGNOSTIC_TIMEOUT_SECONDS = 1.0
_PROVIDER_403_ERROR_TYPE_MAX_CHARS = 128
Resolver = Callable[[str, int], Awaitable[list[object]] | list[object]]
StreamAuthorizationCheck = Callable[[], Awaitable[object] | object]
RequestAuthorizationCheck = Callable[[], Awaitable[object] | object]
_STREAM_AUTHORIZATION_CHECK: contextvars.ContextVar[StreamAuthorizationCheck | None] = (
    contextvars.ContextVar("assistant_stream_authorization_check", default=None)
)
_AUTHENTICATION_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "x-api-key", "x-goog-api-key", "api-key"}
)


@contextmanager
def bind_stream_authorization(check: StreamAuthorizationCheck):
    """Bind one provider authorization callback to a single async stream iteration."""

    if not callable(check):
        raise PublicHTTPError("provider_authorization_required")
    token = _STREAM_AUTHORIZATION_CHECK.set(check)
    try:
        yield
    finally:
        _STREAM_AUTHORIZATION_CHECK.reset(token)


async def _require_stream_authorization(
    check: StreamAuthorizationCheck | None, deadline: float
) -> None:
    """Run a live provider authorization check within the transport's remaining deadline."""

    if check is None:
        return
    if not callable(check):
        raise PublicHTTPError("provider_authorization_required")
    try:
        result = check()
        if not inspect.isawaitable(result):
            raise TypeError("authorization check must be awaitable")
        authorized = await asyncio.wait_for(result, timeout=_remaining(deadline))
    except asyncio.CancelledError:
        raise
    except TimeoutError as exc:
        raise PublicHTTPError("provider_authorization_timeout") from exc
    except Exception as exc:
        raise PublicHTTPError("provider_authorization_required") from exc
    if authorized is not True:
        raise PublicHTTPError("provider_authorization_required")


async def _require_request_authorization(
    check: RequestAuthorizationCheck | None, deadline: float
) -> None:
    """Run a live authorization check inside the bounded request deadline."""

    if check is None:
        return
    if not callable(check):
        raise PublicHTTPError("provider_authorization_required")
    try:
        result = check()
        if inspect.isawaitable(result):
            result = await asyncio.wait_for(result, timeout=_remaining(deadline))
    except asyncio.CancelledError:
        raise
    except TimeoutError as exc:
        raise PublicHTTPError("provider_authorization_timeout") from exc
    except Exception as exc:
        raise PublicHTTPError("provider_authorization_required") from exc
    if result is not True:
        raise PublicHTTPError("provider_authorization_required")


def is_public_unicast(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Accept only globally routable unicast addresses for outbound provider sockets."""

    if address.version == 6 and address.ipv4_mapped is not None:
        # Mapped values have two address-class interpretations; reject instead of guessing.
        return False
    return (
        address.is_global
        and not address.is_multicast
        and not address.is_unspecified
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_private
        and not address.is_reserved
    )


class PublicHTTPError(Exception):
    """Safe provider transport failure without URL, body, or credential contents."""

    def __init__(
        self,
        code: str,
        *,
        status_code: int | None = None,
        content_type_class: str | None = None,
        cf_mitigated_class: str | None = None,
        provider_error_type_class: str | None = None,
        response_failure_phase: str | None = None,
    ):
        if status_code is not None and (
            type(status_code) is not int or not 100 <= status_code <= 599
        ):
            raise ValueError("HTTP status code must be an integer from 100 through 599")
        if (content_type_class is not None or cf_mitigated_class is not None) and (
            type(code) is not str
            or code != "provider_upstream_unavailable"
            or status_code != 403
            or type(content_type_class) is not str
            or content_type_class not in _PROVIDER_403_CONTENT_TYPE_CLASSES
            or type(cf_mitigated_class) is not str
            or cf_mitigated_class not in _PROVIDER_403_CF_MITIGATED_CLASSES
        ):
            raise ValueError("HTTP 403 diagnostic classes are invalid")
        if provider_error_type_class is not None and (
            type(code) is not str
            or code != "provider_upstream_unavailable"
            or status_code != 403
            or type(provider_error_type_class) is not str
            or provider_error_type_class not in _PROVIDER_403_ERROR_TYPE_CLASSES
        ):
            raise ValueError("HTTP 403 provider error type class is invalid")
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.content_type_class = content_type_class
        self.cf_mitigated_class = cf_mitigated_class
        self.provider_error_type_class = provider_error_type_class
        self.response_failure_phase = (
            response_failure_phase
            if code == "provider_response_invalid"
            and type(response_failure_phase) is str
            and response_failure_phase in _PROVIDER_RESPONSE_FAILURE_PHASES
            else None
        )


def _classify_provider_403_content_type(value: bytes | None) -> str:
    if value is None:
        return "missing"
    if any(byte > 126 or (byte < 32 and byte != 9) or byte == 127 for byte in value):
        return "invalid"
    media_type = value.split(b";", 1)[0].strip(b" \t")
    if media_type.count(b"/") != 1:
        return "invalid"
    major, minor = media_type.split(b"/", 1)
    if (
        not major
        or not minor
        or any(byte not in _HEADER_VALUE_TOKEN_BYTES for byte in major)
        or any(byte not in _HEADER_VALUE_TOKEN_BYTES for byte in minor)
    ):
        return "invalid"
    normalized = media_type.lower()
    if normalized == b"text/html":
        return "html"
    if normalized == b"text/event-stream":
        return "event_stream"
    if normalized == b"application/json" or (
        normalized.startswith(b"application/") and normalized.endswith(b"+json")
    ):
        return "json"
    return "other"


def _classify_provider_403_cf_mitigated(value: bytes | None) -> str:
    if value is None:
        return "absent"
    if any(byte > 126 or byte < 32 or byte == 127 for byte in value):
        return "other"
    return "challenge" if value.strip(b" \t").lower() == b"challenge" else "other"


class _DuplicateProviderErrorJSONKey(ValueError):
    """Reject ambiguous provider error objects without retaining their key text."""


class _MalformedProviderErrorJSON(ValueError):
    """Reject non-finite JSON constants without retaining their source text."""


def _reject_duplicate_provider_error_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    """Build one JSON object while rejecting repeated keys."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateProviderErrorJSONKey
        result[key] = value
    return result


def _reject_nonfinite_provider_error_json_constant(_value: str) -> object:
    """Reject NaN and Infinity constants, which are outside strict JSON."""

    raise _MalformedProviderErrorJSON


def _classify_provider_403_json_error_type(body: bytes) -> str:
    """Map a small provider JSON error body to a closed class without retaining its text."""

    try:
        document = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_provider_error_json_keys,
            parse_constant=_reject_nonfinite_provider_error_json_constant,
        )
    except (
        UnicodeError,
        json.JSONDecodeError,
        _DuplicateProviderErrorJSONKey,
        _MalformedProviderErrorJSON,
        RecursionError,
    ):
        return "malformed"
    if not isinstance(document, dict):
        return "malformed"
    error = document.get("error")
    if not isinstance(error, dict):
        return "malformed"
    error_type = error.get("type")
    if (
        not isinstance(error_type, str)
        or not error_type
        or len(error_type) > _PROVIDER_403_ERROR_TYPE_MAX_CHARS
    ):
        return "malformed"
    return _PROVIDER_403_ERROR_TYPE_MAP.get(error_type, "other")


async def _read_provider_403_json_error_type_class(
    reader: asyncio.StreamReader,
    headers: Mapping[str, str],
    *,
    deadline: float,
    authorization_check: StreamAuthorizationCheck | None,
) -> str:
    """Read a small identity-encoded JSON diagnostic within the request deadline."""

    content_type = headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if (
        media_type != "application/json"
        or "transfer-encoding" in headers
        or headers.get("content-encoding", "identity").lower() != "identity"
    ):
        return "unknown"
    length_text = headers.get("content-length")
    if (
        length_text is None
        or not length_text.isascii()
        or not length_text.isdigit()
        or len(length_text) > 20
    ):
        return "unknown"
    length = int(length_text)
    if length > _PROVIDER_403_JSON_BODY_MAX_BYTES:
        return "unknown"
    if length == 0:
        return "malformed"

    await _require_stream_authorization(authorization_check, deadline)
    body: bytes | None = None
    read_failed = False
    try:
        body = await asyncio.wait_for(
            reader.readexactly(length),
            timeout=min(_remaining(deadline), _PROVIDER_403_DIAGNOSTIC_TIMEOUT_SECONDS),
        )
        if not isinstance(body, bytes) or len(body) != length:
            del body
            body = None
            read_failed = True
    except asyncio.CancelledError:
        raise
    except (TimeoutError, OSError, asyncio.IncompleteReadError):
        read_failed = True
    try:
        await _require_stream_authorization(authorization_check, deadline)
    except BaseException:
        if body is not None:
            del body
        raise
    if read_failed or body is None:
        return "unknown"

    try:
        error_type_class = _classify_provider_403_json_error_type(body)
    finally:
        del body
    return error_type_class


@dataclass(frozen=True, slots=True)
class PublicHTTPResponse:
    """A small response record whose body has already passed strict size/deadline bounds."""

    status_code: int
    headers: Mapping[str, str]
    content: bytes


async def request_public_https(
    url: str,
    *,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    body: bytes = b"",
    content_type: str = "application/json",
    timeout_seconds: float = 5.0,
    max_response_bytes: int = 262_144,
    resolver: Resolver | None = None,
    authorization_check: RequestAuthorizationCheck | None = None,
) -> PublicHTTPResponse:
    """Connect only to public resolved addresses and preserve TLS SNI for the URL hostname.

    DNS resolution is rechecked for every call. The chosen public IP is then the actual socket
    destination, avoiding the validation/second-resolution gap in ordinary HTTP clients.
    Redirects are rejected so a public provider cannot redirect a native caller to a private host.
    """

    if (
        not isinstance(url, str)
        or len(url) > 4096
        or method not in {"GET", "POST"}
        or content_type not in {"application/json", "application/x-www-form-urlencoded"}
        or len(body) > 2 * 1024 * 1024
        or not 0 < timeout_seconds <= 30
        or not 0 < max_response_bytes <= 4 * 1024 * 1024
    ):
        raise PublicHTTPError("request_invalid")
    try:
        parsed = urlsplit(url)
        port = parsed.port or 443
        host = parsed.hostname
    except ValueError as exc:
        raise PublicHTTPError("url_invalid") from exc
    if (
        parsed.scheme != "https"
        or not host
        or port != 443
        or parsed.username
        or parsed.password
        or parsed.fragment
        or "\\" in parsed.path
        or any(ord(character) < 32 for character in url)
    ):
        raise PublicHTTPError("url_invalid")
    try:
        tls_host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise PublicHTTPError("url_invalid") from exc
    started = time.monotonic()
    deadline = started + timeout_seconds
    await _require_request_authorization(authorization_check, deadline)
    try:
        loop = asyncio.get_running_loop()
        remaining = _remaining(deadline)
        if resolver is None:
            lookup: Awaitable[list[object]] = loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        else:

            async def resolve_in_thread() -> list[object]:
                result = await asyncio.to_thread(resolver, host, port)
                if asyncio.iscoroutine(result):
                    return await result
                return result

            lookup = resolve_in_thread()
        records = await asyncio.wait_for(lookup, timeout=min(remaining, _DNS_TIMEOUT_SECONDS))
    except PublicHTTPError:
        raise
    except (OSError, TimeoutError) as exc:
        raise PublicHTTPError("dns_unavailable") from exc
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    try:
        for record in records:
            raw = record[4][0]
            if "%" in raw:
                raise ValueError("scoped destination rejected")
            address = ipaddress.ip_address(raw)
            if address not in addresses:
                addresses.append(address)
    except (IndexError, TypeError, ValueError) as exc:
        raise PublicHTTPError("dns_unavailable") from exc
    if not addresses or any(not is_public_unicast(address) for address in addresses):
        raise PublicHTTPError("private_destination_rejected")
    await _require_request_authorization(authorization_check, deadline)

    # A literal address remains pinned while certificate verification and SNI use the hostname.
    context = ssl.create_default_context()
    connect_host = str(addresses[0])
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                connect_host,
                port,
                ssl=context,
                server_hostname=tls_host,
                ssl_handshake_timeout=min(_remaining(deadline), 3.0),
                limit=MAX_HEADER_BYTES,
            ),
            timeout=_remaining(deadline),
        )
    except (OSError, ssl.SSLError, TimeoutError) as exc:
        raise PublicHTTPError("provider_connect_failed") from exc

    try:
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        if any(character in path for character in "\r\n "):
            raise PublicHTTPError("url_invalid")
        request_headers: dict[str, str] = {
            "host": tls_host,
            "connection": "close",
            "accept": "application/json",
            "accept-encoding": "identity",
        }
        for name, value in (headers or {}).items():
            if (
                not isinstance(name, str)
                or not isinstance(value, str)
                or not name
                or any(character not in _HEADER_NAME_CHARS for character in name)
                or any(ord(character) < 32 or ord(character) == 127 for character in value)
                or name.lower()
                in {"host", "connection", "content-length", "transfer-encoding", "content-type"}
            ):
                raise PublicHTTPError("header_invalid")
            request_headers[name.lower()] = value
        if body:
            request_headers["content-length"] = str(len(body))
            request_headers["content-type"] = content_type
        raw_headers = "".join(f"{name}: {value}\r\n" for name, value in request_headers.items())
        try:
            request_head = f"{method} {path} HTTP/1.1\r\n{raw_headers}\r\n".encode("latin-1")
        except UnicodeEncodeError as exc:
            raise PublicHTTPError("header_invalid") from exc
        await _require_request_authorization(authorization_check, deadline)
        writer.write(request_head + body)
        await asyncio.wait_for(writer.drain(), timeout=_remaining(deadline))

        header_bytes = 0
        status_line = await _readline(reader, deadline)
        header_bytes += len(status_line)
        try:
            protocol, status_text, _reason = (
                status_line.decode("latin-1").rstrip("\r\n").split(" ", 2)
            )
            status_code = int(status_text)
        except (ValueError, UnicodeError) as exc:
            raise PublicHTTPError("provider_response_invalid") from exc
        if protocol not in {"HTTP/1.0", "HTTP/1.1"} or not 100 <= status_code <= 599:
            raise PublicHTTPError("provider_response_invalid")
        response_headers: dict[str, str] = {}
        while True:
            line = await _readline(reader, deadline)
            header_bytes += len(line)
            if header_bytes > MAX_HEADER_BYTES:
                raise PublicHTTPError("provider_headers_too_large")
            if line in {b"\r\n", b"\n"}:
                break
            try:
                name, value = line.decode("latin-1").split(":", 1)
            except (ValueError, UnicodeError) as exc:
                raise PublicHTTPError("provider_response_invalid") from exc
            key = name.strip().lower()
            normalized_value = value.strip()
            if key in response_headers and key in {
                "content-length",
                "transfer-encoding",
                "content-encoding",
            }:
                raise PublicHTTPError("provider_response_invalid")
            response_headers[key] = (
                f"{response_headers[key]}, {normalized_value}"
                if key in response_headers
                else normalized_value
            )
        if 300 <= status_code < 400:
            raise PublicHTTPError("provider_redirect_rejected", status_code=status_code)
        if response_headers.get("content-encoding", "identity").lower() != "identity":
            raise PublicHTTPError("provider_response_invalid")
        if "transfer-encoding" in response_headers and "content-length" in response_headers:
            raise PublicHTTPError("provider_response_invalid")
        content = await _read_response_body(
            reader,
            response_headers,
            deadline=deadline,
            max_bytes=max_response_bytes,
        )
        await _require_request_authorization(authorization_check, deadline)
        return PublicHTTPResponse(status_code, response_headers, content)
    except TimeoutError as exc:
        raise PublicHTTPError("provider_deadline_exceeded") from exc
    finally:
        writer.close()
        remaining = deadline - time.monotonic()
        if remaining > 0:
            with suppress(OSError, ssl.SSLError, TimeoutError):
                await asyncio.wait_for(writer.wait_closed(), timeout=min(remaining, 0.1))


async def stream_public_https(
    url: str,
    *,
    method: str = "POST",
    headers: Mapping[str, str] | None = None,
    body: bytes = b"",
    timeout_seconds: float = 120.0,
    max_response_bytes: int = 1_048_576,
    authorization_check: StreamAuthorizationCheck | None = None,
) -> AsyncIterator[bytes]:
    """Stream a pinned public HTTPS response in bounded chunks under one hard deadline.

    This is used for chat SSE so first-token latency is preserved. The destination address is
    the exact public DNS answer connected to (not a preflight-only resolution), redirects and
    compressed transfer are rejected, and each yielded chunk counts against one response cap.
    Authenticated requests require a live async authorization check, run after DNS and directly
    before the request bytes are written; both checks consume the same bounded deadline.
    """

    if (
        not isinstance(url, str)
        or len(url) > 4096
        or method != "POST"
        or not isinstance(body, bytes)
        or len(body) > 262_144
        or not 0 < timeout_seconds <= 120
        or not 0 < max_response_bytes <= 1_048_576
    ):
        raise PublicHTTPError("request_invalid")
    live_authorization = (
        authorization_check
        if authorization_check is not None
        else _STREAM_AUTHORIZATION_CHECK.get()
    )
    if any(
        isinstance(name, str) and name.lower() in _AUTHENTICATION_HEADERS
        for name in (headers or {})
    ) and not callable(live_authorization):
        raise PublicHTTPError("provider_authorization_required")
    deadline = time.monotonic() + timeout_seconds
    try:
        parsed = urlsplit(url)
        port = parsed.port or 443
        host = parsed.hostname
    except ValueError as exc:
        raise PublicHTTPError("url_invalid") from exc
    if (
        parsed.scheme != "https"
        or not host
        or port != 443
        or parsed.username
        or parsed.password
        or parsed.fragment
        or "\\" in parsed.path
        or any(ord(character) < 32 for character in url)
    ):
        raise PublicHTTPError("url_invalid")
    try:
        tls_host = host.encode("idna").decode("ascii")
        records = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM),
            timeout=min(_remaining(deadline), _DNS_TIMEOUT_SECONDS),
        )
        addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
        for record in records:
            raw = record[4][0]
            if "%" in raw:
                raise ValueError("scoped destination")
            address = ipaddress.ip_address(raw)
            if address not in addresses:
                addresses.append(address)
    except (UnicodeError, ValueError) as exc:
        raise PublicHTTPError("url_invalid") from exc
    except (OSError, TimeoutError) as exc:
        raise PublicHTTPError("dns_unavailable") from exc
    if not addresses or any(not is_public_unicast(address) for address in addresses):
        raise PublicHTTPError("private_destination_rejected")
    await _require_stream_authorization(live_authorization, deadline)

    writer: asyncio.StreamWriter | None = None
    status_code: int | None = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                str(addresses[0]),
                port,
                ssl=ssl.create_default_context(),
                server_hostname=tls_host,
                ssl_handshake_timeout=min(_remaining(deadline), 3.0),
                limit=MAX_HEADER_BYTES,
            ),
            timeout=_remaining(deadline),
        )
        request_path = parsed.path or "/"
        if parsed.query:
            request_path += "?" + parsed.query
        if any(character in request_path for character in "\r\n "):
            raise PublicHTTPError("url_invalid")
        request_headers: dict[str, str] = {
            "host": tls_host,
            "connection": "close",
            "accept": "text/event-stream",
            "accept-encoding": "identity",
            "content-type": "application/json",
            "content-length": str(len(body)),
        }
        for name, value in (headers or {}).items():
            if (
                not isinstance(name, str)
                or not isinstance(value, str)
                or not name
                or any(character not in _HEADER_NAME_CHARS for character in name)
                or any(ord(character) < 32 or ord(character) == 127 for character in value)
                or name.lower()
                in {"host", "connection", "content-length", "transfer-encoding", "content-type"}
            ):
                raise PublicHTTPError("header_invalid")
            request_headers[name.lower()] = value
        try:
            head = (
                f"POST {request_path} HTTP/1.1\r\n"
                + "".join(f"{key}: {value}\r\n" for key, value in request_headers.items())
                + "\r\n"
            )
            await _require_stream_authorization(live_authorization, deadline)
            writer.write(head.encode("latin-1") + body)
        except UnicodeEncodeError as exc:
            raise PublicHTTPError("header_invalid") from exc
        await asyncio.wait_for(writer.drain(), timeout=_remaining(deadline))

        status_line = await _readline(reader, deadline, response_failure_phase="status_line")
        try:
            protocol, status_text, _ = status_line.decode("latin-1").rstrip("\r\n").split(" ", 2)
            parsed_status_code = int(status_text)
        except (ValueError, UnicodeError) as exc:
            raise PublicHTTPError(
                "provider_response_invalid", response_failure_phase="status_line"
            ) from exc
        if protocol not in {"HTTP/1.0", "HTTP/1.1"} or not 100 <= parsed_status_code <= 599:
            raise PublicHTTPError("provider_response_invalid", response_failure_phase="status_line")
        status_code = parsed_status_code
        response_headers: dict[str, str] = {}
        provider_403_content_type_class: str | None = None
        provider_403_cf_mitigated_class: str | None = None
        provider_403_content_type_seen = False
        provider_403_cf_mitigated_seen = False
        total_header_bytes = len(status_line)
        while True:
            line = await _readline(
                reader,
                deadline,
                response_failure_phase="headers",
                status_code=status_code,
            )
            total_header_bytes += len(line)
            if total_header_bytes > MAX_HEADER_BYTES:
                raise PublicHTTPError("provider_headers_too_large")
            if line in {b"\r\n", b"\n"}:
                break
            if line[:1] in {b" ", b"\t"} or b":" not in line:
                raise PublicHTTPError(
                    "provider_response_invalid",
                    status_code=status_code,
                    response_failure_phase="headers",
                )
            name_bytes, value_bytes = line.rstrip(b"\r\n").split(b":", 1)
            if not name_bytes or any(byte < 33 or byte > 126 for byte in name_bytes):
                raise PublicHTTPError(
                    "provider_response_invalid",
                    status_code=status_code,
                    response_failure_phase="headers",
                )
            key = name_bytes.decode("ascii").lower()
            value = value_bytes.decode("latin-1").strip()
            if key in response_headers and key in {
                "content-length",
                "transfer-encoding",
                "content-encoding",
            }:
                raise PublicHTTPError(
                    "provider_response_invalid",
                    status_code=status_code,
                    response_failure_phase="headers",
                )
            if status_code == 403 and key == "content-type":
                if provider_403_content_type_seen:
                    provider_403_content_type_class = "invalid"
                else:
                    provider_403_content_type_class = _classify_provider_403_content_type(
                        value_bytes.strip(b" \t")
                    )
                provider_403_content_type_seen = True
            elif status_code == 403 and key == "cf-mitigated":
                if provider_403_cf_mitigated_seen:
                    provider_403_cf_mitigated_class = "other"
                else:
                    provider_403_cf_mitigated_class = _classify_provider_403_cf_mitigated(
                        value_bytes.strip(b" \t")
                    )
                provider_403_cf_mitigated_seen = True
            response_headers[key] = (
                f"{response_headers[key]}, {value}" if key in response_headers else value
            )
        if 300 <= status_code < 400:
            raise PublicHTTPError("provider_redirect_rejected", status_code=status_code)
        if status_code != 200:
            if status_code == 403:
                provider_error_type_class = "unknown"
                if (
                    provider_403_content_type_class == "json"
                    and provider_403_cf_mitigated_class != "challenge"
                ):
                    provider_error_type_class = await _read_provider_403_json_error_type_class(
                        reader,
                        response_headers,
                        deadline=deadline,
                        authorization_check=live_authorization,
                    )
                raise PublicHTTPError(
                    "provider_upstream_unavailable",
                    status_code=status_code,
                    content_type_class=provider_403_content_type_class or "missing",
                    cf_mitigated_class=provider_403_cf_mitigated_class or "absent",
                    provider_error_type_class=provider_error_type_class,
                )
            raise PublicHTTPError("provider_upstream_unavailable", status_code=status_code)
        if response_headers.get("content-encoding", "identity").lower() != "identity":
            raise PublicHTTPError(
                "provider_response_invalid",
                status_code=status_code,
                response_failure_phase="content_encoding",
            )
        if "transfer-encoding" in response_headers and "content-length" in response_headers:
            raise PublicHTTPError(
                "provider_response_invalid",
                status_code=status_code,
                response_failure_phase="transfer_framing",
            )
        content_type = response_headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "text/event-stream":
            raise PublicHTTPError(
                "provider_response_invalid",
                status_code=status_code,
                response_failure_phase="content_type",
            )

        sent = 0
        transfer = response_headers.get("transfer-encoding", "").lower()
        if transfer:
            if transfer != "chunked":
                raise PublicHTTPError(
                    "provider_response_invalid",
                    status_code=status_code,
                    response_failure_phase="transfer_framing",
                )
            while True:
                line = await _readline(
                    reader,
                    deadline,
                    response_failure_phase="transfer_framing",
                    status_code=status_code,
                )
                try:
                    size_field = line.split(b";", 1)[0]
                    if size_field.endswith(b"\r\n"):
                        size_token = size_field[:-2]
                    elif size_field.endswith(b"\n"):
                        size_token = size_field[:-1]
                    else:
                        size_token = size_field
                    if not 1 <= len(size_token) <= 16 or any(
                        byte not in b"0123456789abcdefABCDEF" for byte in size_token
                    ):
                        raise ValueError
                    size = int(size_token, 16)
                except ValueError as exc:
                    raise PublicHTTPError(
                        "provider_response_invalid",
                        status_code=status_code,
                        response_failure_phase="transfer_framing",
                    ) from exc
                if size == 0:
                    trailer_bytes = 0
                    while True:
                        trailer = await _readline(
                            reader,
                            deadline,
                            response_failure_phase="transfer_framing",
                            status_code=status_code,
                        )
                        trailer_bytes += len(trailer)
                        if trailer_bytes > 8192:
                            raise PublicHTTPError("provider_headers_too_large")
                        if trailer in {b"\r\n", b"\n"}:
                            return
                        if b":" not in trailer or trailer[:1] in {b" ", b"\t"}:
                            raise PublicHTTPError(
                                "provider_response_invalid",
                                status_code=status_code,
                                response_failure_phase="transfer_framing",
                            )
                    continue
                if size > max_response_bytes - sent:
                    raise PublicHTTPError("provider_response_too_large")
                remaining_chunk = size
                while remaining_chunk:
                    take = min(remaining_chunk, 16_384)
                    part = await asyncio.wait_for(reader.read(take), timeout=_remaining(deadline))
                    if not part:
                        raise PublicHTTPError(
                            "provider_response_invalid",
                            status_code=status_code,
                            response_failure_phase="body_eof",
                        )
                    remaining_chunk -= len(part)
                    sent += len(part)
                    yield part
                try:
                    terminator = await asyncio.wait_for(
                        reader.readexactly(2), timeout=_remaining(deadline)
                    )
                except asyncio.IncompleteReadError as exc:
                    raise PublicHTTPError(
                        "provider_response_invalid",
                        status_code=status_code,
                        response_failure_phase="body_eof",
                    ) from exc
                if terminator != b"\r\n":
                    raise PublicHTTPError(
                        "provider_response_invalid",
                        status_code=status_code,
                        response_failure_phase="transfer_framing",
                    )
        content_length = response_headers.get("content-length")
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError as exc:
                raise PublicHTTPError(
                    "provider_response_invalid",
                    status_code=status_code,
                    response_failure_phase="transfer_framing",
                ) from exc
            if length < 0 or length > max_response_bytes:
                raise PublicHTTPError("provider_response_too_large")
            while sent < length:
                part = await asyncio.wait_for(
                    reader.read(min(16_384, length - sent)), timeout=_remaining(deadline)
                )
                if not part:
                    raise PublicHTTPError(
                        "provider_response_invalid",
                        status_code=status_code,
                        response_failure_phase="body_eof",
                    )
                sent += len(part)
                yield part
            return
        while True:
            part = await asyncio.wait_for(reader.read(16_384), timeout=_remaining(deadline))
            if not part:
                return
            sent += len(part)
            if sent > max_response_bytes:
                raise PublicHTTPError("provider_response_too_large")
            yield part
    except TimeoutError as exc:
        raise PublicHTTPError("provider_deadline_exceeded") from exc
    except (OSError, ssl.SSLError, asyncio.IncompleteReadError) as exc:
        raise PublicHTTPError(
            "provider_response_invalid",
            status_code=status_code,
            response_failure_phase="transport_io",
        ) from exc
    finally:
        if writer is not None:
            writer.close()
            remaining = deadline - time.monotonic()
            if remaining > 0:
                with suppress(OSError, ssl.SSLError, TimeoutError):
                    await asyncio.wait_for(writer.wait_closed(), timeout=min(remaining, 0.1))


async def _readline(
    reader: asyncio.StreamReader,
    deadline: float,
    *,
    response_failure_phase: str | None = None,
    status_code: int | None = None,
) -> bytes:
    value = await asyncio.wait_for(reader.readline(), timeout=_remaining(deadline))
    if not value or len(value) > MAX_HEADER_BYTES:
        raise PublicHTTPError(
            "provider_response_invalid",
            status_code=status_code,
            response_failure_phase=response_failure_phase,
        )
    return value


async def _read_response_body(
    reader: asyncio.StreamReader,
    headers: Mapping[str, str],
    *,
    deadline: float,
    max_bytes: int,
) -> bytes:
    body = bytearray()
    transfer = headers.get("transfer-encoding", "").lower()
    if transfer:
        if transfer != "chunked":
            raise PublicHTTPError("provider_response_invalid")
        while True:
            line = await _readline(reader, deadline)
            try:
                chunk_size = int(line.split(b";", 1)[0].strip(), 16)
            except ValueError as exc:
                raise PublicHTTPError("provider_response_invalid") from exc
            if chunk_size == 0:
                # Consume bounded trailers and the terminating blank line.
                trailers = 0
                while True:
                    trailer = await _readline(reader, deadline)
                    trailers += len(trailer)
                    if trailers > 8192:
                        raise PublicHTTPError("provider_headers_too_large")
                    if trailer in {b"\r\n", b"\n"}:
                        return bytes(body)
                    if trailer.endswith(b"\r\n"):
                        trailer = trailer[:-2]
                    elif trailer.endswith(b"\n"):
                        trailer = trailer[:-1]
                    if b":" not in trailer:
                        raise PublicHTTPError("provider_response_invalid")
                    name, value = trailer.split(b":", 1)
                    if not name or any(byte < 33 or byte > 126 for byte in name):
                        raise PublicHTTPError("provider_response_invalid")
                    if b"\r" in value or b"\n" in value:
                        raise PublicHTTPError("provider_response_invalid")
                continue
            if chunk_size < 0:
                raise PublicHTTPError("provider_response_invalid")
            if len(body) + chunk_size > max_bytes:
                raise PublicHTTPError("provider_response_too_large")
            chunk = await asyncio.wait_for(
                reader.readexactly(chunk_size + 2), timeout=_remaining(deadline)
            )
            if not chunk.endswith(b"\r\n"):
                raise PublicHTTPError("provider_response_invalid")
            body.extend(chunk[:-2])
    length = headers.get("content-length")
    if length is not None:
        try:
            total = int(length)
        except ValueError as exc:
            raise PublicHTTPError("provider_response_invalid") from exc
        if total < 0:
            raise PublicHTTPError("provider_response_invalid")
        if total > max_bytes:
            raise PublicHTTPError("provider_response_too_large")
        while len(body) < total:
            chunk = await asyncio.wait_for(
                reader.read(min(65_536, total - len(body))), timeout=_remaining(deadline)
            )
            if not chunk:
                raise PublicHTTPError("provider_response_invalid")
            body.extend(chunk)
        return bytes(body)
    while True:
        chunk = await asyncio.wait_for(reader.read(65_536), timeout=_remaining(deadline))
        if not chunk:
            return bytes(body)
        if len(body) + len(chunk) > max_bytes:
            raise PublicHTTPError("provider_response_too_large")
        body.extend(chunk)


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("deadline expired")
    return remaining
