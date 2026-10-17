"""Exercise monitoring-control authorization after the bounded body is received."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.types import ASGIApp, Message, Scope

from stock_probs.api import create_app
from stock_probs.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME, AuthContext
from stock_probs.config import Settings
from stock_probs.provider import FixtureProvider
from stock_probs.totp import code_for_step, time_step

_CONTROL_PATH = "/api/v1/admin/monitoring/control"
_LOCAL_PASSWORD = "r3-development-admin-password"  # noqa: S105


def _authenticate_admin_with_totp(
    client: TestClient, application: FastAPI
) -> tuple[str, str, AuthContext]:
    """Create a disposable admin session and prove TOTP through the real HTTP routes."""

    login = client.post(
        "/api/v1/auth/local/login",
        json={"username": "admin", "password": _LOCAL_PASSWORD},
    )
    assert login.status_code == 200, login.text
    csrf_token = login.json()["csrf_token"]
    headers = {"x-csrf-token": csrf_token}

    started = client.post("/api/v1/auth/totp/enroll/start", headers=headers)
    assert started.status_code == 200, started.text
    secret = started.json()["secret"]
    finished = client.post(
        "/api/v1/auth/totp/enroll/finish",
        json={"code": code_for_step(secret, time_step())},
        headers=headers,
    )
    assert finished.status_code == 200, finished.text
    csrf_token = finished.json()["csrf_token"]
    session_token = client.cookies.get(SESSION_COOKIE_NAME)
    assert isinstance(session_token, str)

    now = datetime.now(UTC)
    context = application.state.auth.authenticate(session_token, now)
    assert context.user.role == "admin"
    assert context.mfa_method == "totp"
    assert application.state.auth.has_recent_step_up(context, now)
    return session_token, csrf_token, context


async def _put_control_with_body_barrier(
    application: ASGIApp,
    session_token: str,
    csrf_token: str,
    expected_revision: int,
    enabled: bool,
    on_body_paused: Callable[[], None],
) -> tuple[int, bytes]:
    """Hold the final JSON chunk after middleware authentication, then finish the request."""

    body = (
        f'{{"expected_revision":{expected_revision},"enabled":{"true" if enabled else "false"}}}'
    ).encode("ascii")
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
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "PUT",
        "scheme": "http",
        "path": _CONTROL_PATH,
        "raw_path": _CONTROL_PATH.encode("ascii"),
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


@pytest.mark.parametrize(
    ("scenario", "expected_status"),
    [
        ("live", 200),
        ("session-revoked", 401),
        ("role-demoted", 403),
        ("account-disabled", 401),
        ("step-up-expired", 403),
    ],
)
def test_monitoring_control_revalidates_after_body_read(
    settings: Settings, scenario: str, expected_status: int
) -> None:
    """Current session, account, role, and TOTP state govern the final mutation."""

    configured = replace(
        settings,
        auth_mode="local",
        auth_session_secret="r" * 48,
        auth_public_origin="http://testserver",
        bootstrap_username="admin",
        bootstrap_password=_LOCAL_PASSWORD,
    )
    application = create_app(configured, FixtureProvider(), lambda: datetime.now(UTC))
    with TestClient(application) as client:
        session_token, csrf_token, context = _authenticate_admin_with_totp(client, application)
        control_before = application.state.monitoring_store.get_control()
        revision = int(control_before["revision"])
        enabled = not bool(control_before["enabled"])
        auth_manager = application.state.auth

        def change_state_after_initial_auth() -> None:
            """Apply one durable authorization change while the final body chunk is held."""

            now = datetime.now(UTC)
            if scenario == "session-revoked":
                auth_manager.store.auth_revoke_session_by_id(
                    context.user.id, context.session_id, now.isoformat()
                )
            elif scenario == "role-demoted":
                assert (
                    auth_manager.store.auth_update_user(context.user.id, {"role": "member"})
                    is not None
                )
            elif scenario == "account-disabled":
                assert (
                    auth_manager.store.auth_update_user(context.user.id, {"status": "disabled"})
                    is not None
                )
            elif scenario == "step-up-expired":
                assert context.mfa_factor_id is not None
                expired_at = now - timedelta(seconds=301)
                assert auth_manager.store.auth_set_session_mfa(
                    context.token_hash,
                    "totp",
                    expired_at.isoformat(),
                    context.mfa_factor_id,
                )

        status, _body = asyncio.run(
            _put_control_with_body_barrier(
                application,
                session_token,
                csrf_token,
                revision,
                enabled,
                change_state_after_initial_auth,
            )
        )

        assert status == expected_status
        control_after = application.state.monitoring_store.get_control()
        if scenario == "live":
            assert control_after["revision"] == revision + 1
            assert control_after["enabled"] is enabled
        else:
            assert control_after == control_before
