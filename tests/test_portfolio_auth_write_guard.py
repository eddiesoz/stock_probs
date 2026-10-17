"""Exercise portfolio write authorization after middleware has read a bounded request body."""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from stock_probs.api import create_app
from stock_probs.auth import SESSION_COOKIE_NAME
from stock_probs.domain import DomainError
from stock_probs.portfolio_store import PortfolioStore
from stock_probs.provider import FixtureProvider
from stock_probs.repository import Repository


def test_store_defaults_to_rejecting_writes_without_auth_context(tmp_path):
    """Direct store callers must opt into no-auth only for configured development fixtures."""
    repository = Repository(tmp_path / "portfolio.db")
    repository.migrate()

    with pytest.raises(DomainError) as raised:
        PortfolioStore(repository).create_account(
            1, "Denied", "tfsa", str(uuid4()), datetime.now(UTC)
        )

    assert raised.value.code == "authentication_required"
    assert raised.value.status_code == 401


def test_account_create_rechecks_session_revocation_after_body_read(settings):
    """A session revoked while the middleware waits for the body cannot create an account."""
    now = datetime.now(UTC)
    config = replace(
        settings,
        auth_mode="local",
        environment="test",
        auth_public_origin="http://testserver",
        portfolio_features_enabled=True,
        portfolio_features_canary_only=False,
        bootstrap_username="fixture-admin",
        bootstrap_password="fixture-admin-password-123",  # noqa: S106
    )
    app = create_app(config, FixtureProvider(), lambda: now)
    body = json.dumps(
        {
            "label": "Revoked request",
            "account_type": "tfsa",
            "idempotency_key": str(uuid4()),
        }
    ).encode()
    body_waiting = threading.Event()
    allow_body = threading.Event()
    sent: list[dict[str, object]] = []
    errors: list[BaseException] = []

    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/local/login",
            json={"username": "fixture-admin", "password": "fixture-admin-password-123"},
        )
        assert login.status_code == 200, login.text
        token = client.cookies.get(SESSION_COOKIE_NAME)
        assert token
        context = app.state.auth.authenticate(token, datetime.now(UTC))
        cookie_header = "; ".join(f"{name}={value}" for name, value in client.cookies.items())
        path = "/api/v1/portfolio/accounts"
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"testserver"),
                (b"origin", b"http://testserver"),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"cookie", cookie_header.encode()),
                (b"x-csrf-token", login.json()["csrf_token"].encode()),
            ],
            "client": ("127.0.0.1", 43122),
            "server": ("testserver", 80),
            "state": {},
            "app": app,
        }

        async def receive() -> dict[str, object]:
            body_waiting.set()
            if not await asyncio.to_thread(allow_body.wait, 5):
                raise RuntimeError("test timed out waiting to release the request body")
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

        def invoke() -> None:
            try:
                asyncio.run(app(scope, receive, send))
            except BaseException as error:
                errors.append(error)

        request_thread = threading.Thread(target=invoke)
        request_thread.start()
        try:
            assert body_waiting.wait(5), "the application did not reach bounded body reading"
            with app.state.repository.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "UPDATE sessions SET revoked_at=?, revocation_reason=? "
                    "WHERE session_id=? AND revoked_at IS NULL",
                    (datetime.now(UTC).isoformat(), "test-revocation", context.session_id),
                )
                connection.commit()
        finally:
            allow_body.set()
            request_thread.join(10)

        assert not request_thread.is_alive(), "the delayed request did not finish"
        assert not errors, repr(errors)
        start = next(message for message in sent if message["type"] == "http.response.start")
        assert start["status"] == 401
        with app.state.repository.connect() as connection:
            created = connection.execute(
                "SELECT count(*) FROM portfolio_accounts WHERE owner_user_id=?",
                (context.user.id,),
            ).fetchone()[0]
        assert created == 0
