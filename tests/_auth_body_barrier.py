"""Small ASGI body barrier for authorization race regressions."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping

from starlette.types import ASGIApp, Message, Scope

from stock_probs.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME


async def request_with_body_barrier(
    application: ASGIApp,
    session_token: str,
    csrf_token: str,
    *,
    method: str,
    path: str,
    body: bytes,
    extra_headers: Mapping[str, str] | None = None,
    on_body_paused: Callable[[], None],
) -> tuple[int, bytes]:
    """Pause between body chunks after middleware auth, mutate session, then finish the request."""

    split_at = len(body) // 2
    assert 0 < split_at < len(body)
    request_messages: list[Message] = [
        {"type": "http.request", "body": body[:split_at], "more_body": True},
        {"type": "http.request", "body": body[split_at:], "more_body": False},
    ]
    paused_before_final_chunk = asyncio.Event()
    release_final_chunk = asyncio.Event()
    response_messages: list[Message] = []
    next_request_message = 0

    async def receive() -> Message:
        nonlocal next_request_message
        if next_request_message >= len(request_messages):
            return {"type": "http.disconnect"}
        message = request_messages[next_request_message]
        next_request_message += 1
        if next_request_message == len(request_messages):
            paused_before_final_chunk.set()
            await release_final_chunk.wait()
        return message

    async def send(message: Message) -> None:
        response_messages.append(message)

    cookie = f"{SESSION_COOKIE_NAME}={session_token}; {CSRF_COOKIE_NAME}={csrf_token}"
    headers = [
        (b"host", b"testserver"),
        (b"origin", b"http://testserver"),
        (b"sec-fetch-site", b"same-origin"),
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cookie", cookie.encode("ascii")),
        (b"x-csrf-token", csrf_token.encode("ascii")),
    ]
    if extra_headers is not None:
        headers.extend(
            (name.lower().encode("ascii"), value.encode("ascii"))
            for name, value in extra_headers.items()
        )
    request_path = path.encode("ascii")
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path,
        "raw_path": request_path,
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 43210),
        "server": ("testserver", 80),
        "state": {},
    }
    request_task = asyncio.create_task(application(scope, receive, send))
    try:
        await asyncio.wait_for(paused_before_final_chunk.wait(), timeout=5)
    except TimeoutError as error:
        release_final_chunk.set()
        request_task.cancel()
        await asyncio.gather(request_task, return_exceptions=True)
        raise AssertionError("The request did not pause before its final body chunk.") from error

    mutation_error: Exception | None = None
    try:
        on_body_paused()
    except Exception as error:
        mutation_error = error
    finally:
        release_final_chunk.set()
    await asyncio.wait_for(request_task, timeout=5)
    if mutation_error is not None:
        raise mutation_error

    start = next(
        message for message in response_messages if message["type"] == "http.response.start"
    )
    response_body = b"".join(
        message.get("body", b"")
        for message in response_messages
        if message["type"] == "http.response.body"
    )
    return int(start["status"]), response_body
