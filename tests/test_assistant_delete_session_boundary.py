"""HTTP delete checks revalidate authorization across runtime cache-purge awaits."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from stock_probs.assistant.storage import AssistantStorageNotFound
from stock_probs.config import Settings


def _load_assistant_api_helpers() -> ModuleType:
    """Load the established synthetic auth and runtime fixtures from the API tests."""

    helper_path = Path(__file__).with_name("test_assistant_api.py")
    spec = importlib.util.spec_from_file_location("assistant_delete_api_test_helpers", helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("assistant API test helpers could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_HELPERS = _load_assistant_api_helpers()


class _PurgeRuntime(_HELPERS.FakeRuntime):
    """Invoke a test-owned auth mutation while the HTTP delete awaits cache clearing."""

    def __init__(self) -> None:
        self.on_cancel: Callable[[], None] | None = None
        self.on_purge: Callable[[], None] | None = None
        self.cancelled: list[str] = []
        self.purged: list[str] = []

    async def cancel_execution(self, execution_id: str) -> None:
        self.cancelled.append(execution_id)
        if self.on_cancel is not None:
            self.on_cancel()

    async def clear_conversation_cache(self, conversation_id: str) -> bool:
        self.purged.append(conversation_id)
        if self.on_purge is not None:
            self.on_purge()
        return True


def _create_conversation(browser: TestClient, identity: dict[str, str | int]) -> dict[str, object]:
    context_response = browser.get("/api/v1/assistant/context", params={"route": "/overview"})
    assert context_response.status_code == 200, context_response.text
    response = browser.post(
        "/api/v1/assistant/conversations",
        json={"context": context_response.json()["context"]},
        headers={"x-csrf-token": str(identity["csrf"])},
    )
    assert response.status_code == 201, response.text
    return response.json()["conversation"]["conversation"]


def _delete(
    browser: TestClient, identity: dict[str, str | int], row: dict[str, object]
) -> Response:
    conversation_id = str(row["id"])
    return browser.request(
        "DELETE",
        f"/api/v1/assistant/conversations/{conversation_id}",
        headers={"x-csrf-token": str(identity["csrf"])},
        json={
            "expected_revision": int(row["revision"]),
            "confirmation_phrase": str(row["delete_confirmation_phrase"]),
        },
    )


def _assert_conversation_retained(
    app: FastAPI, identity: dict[str, str | int], row: dict[str, object]
) -> None:
    conversation_id = str(row["id"])
    saved = app.state.assistant.storage.get_conversation(int(identity["user_id"]), conversation_id)
    assert saved["conversation"]["id"] == conversation_id


def _change_auth_state(app: FastAPI, identity: dict[str, str | int], change: str) -> None:
    repository = app.state.repository
    user_id = int(identity["user_id"])
    if change == "session_revoked":
        repository.auth_revoke_session(str(identity["token_hash"]), _HELPERS.NOW.isoformat())
    elif change == "factor_rotated":
        factor = repository.auth_get_totp_factor(user_id)
        assert factor is not None
        now = app.state.assistant.now().isoformat()
        with repository.connect() as connection:
            connection.execute("DELETE FROM totp_factors WHERE id = ?", (int(factor["id"]),))
            connection.execute(
                """INSERT INTO totp_factors
                (user_id, secret_ciphertext, created_at, confirmed_at,
                 last_accepted_step, updated_at)
                VALUES (?, ?, ?, ?, -1, ?)""",
                (user_id, "replacement-encrypted-factor", now, now, now),
            )
            connection.commit()
    elif change == "account_deactivated":
        assert repository.auth_update_user(user_id, {"status": "disabled"}) is not None
    elif change == "rollout_changed":
        app.state.assistant.settings = replace(
            app.state.assistant.settings, assistant_rollout_mode="disabled"
        )
    elif change == "operator_disabled":
        app.state.assistant.runtime.operator_disabled = True
    else:
        raise AssertionError(f"unknown auth mutation: {change}")


@pytest.mark.parametrize(
    ("auth_change", "expected_status", "expected_code"),
    [
        ("session_revoked", 403, "session_revoked"),
        ("factor_rotated", 403, "session_revoked"),
        ("account_deactivated", 403, "session_revoked"),
        ("rollout_changed", 403, "session_revoked"),
        ("operator_disabled", 403, "session_revoked"),
    ],
)
def test_delete_rechecks_live_authorization_after_cache_purge(
    settings: Settings, auth_change: str, expected_status: int, expected_code: str
) -> None:
    runtime = _PurgeRuntime()
    app = _HELPERS.create_app(
        _HELPERS._auth_settings(settings),
        _HELPERS.FixtureProvider(),
        lambda: _HELPERS.NOW,
        assistant_runtime=runtime,
        assistant_catalog=_HELPERS.FakeCatalog(),
        assistant_providers=_HELPERS.FakeProviders(),
    )
    with (
        pytest.MonkeyPatch.context() as patcher,
        TestClient(app, client=("127.0.0.1", 51041)),
    ):
        patcher.setattr(_HELPERS.application_api, "datetime", _HELPERS._FrozenHTTPDatetime)
        patcher.setattr(_HELPERS.assistant_api, "datetime", _HELPERS._AssistantHTTPDatetime)
        identity = _HELPERS._add_signed_in_user(app, 88100)
        runtime.on_purge = lambda: _change_auth_state(app, identity, auth_change)
        browser = _HELPERS._browser_client(app, identity)
        try:
            conversation = _create_conversation(browser, identity)
            response = _delete(browser, identity, conversation)
            assert response.status_code == expected_status, response.text
            assert response.json()["error"]["code"] == expected_code
            assert runtime.purged == [str(conversation["id"])]
            _assert_conversation_retained(app, identity, conversation)
        finally:
            browser.close()


def test_delete_rechecks_live_authorization_after_cancellation_before_purge(
    settings: Settings,
) -> None:
    runtime = _PurgeRuntime()
    app = _HELPERS.create_app(
        _HELPERS._auth_settings(settings),
        _HELPERS.FixtureProvider(),
        lambda: _HELPERS.NOW,
        assistant_runtime=runtime,
        assistant_catalog=_HELPERS.FakeCatalog(),
        assistant_providers=_HELPERS.FakeProviders(),
    )
    with (
        pytest.MonkeyPatch.context() as patcher,
        TestClient(app, client=("127.0.0.1", 51042)),
    ):
        patcher.setattr(_HELPERS.application_api, "datetime", _HELPERS._FrozenHTTPDatetime)
        patcher.setattr(_HELPERS.assistant_api, "datetime", _HELPERS._AssistantHTTPDatetime)
        identity = _HELPERS._add_signed_in_user(app, 88110)
        runtime.on_cancel = lambda: _change_auth_state(app, identity, "session_revoked")
        browser = _HELPERS._browser_client(app, identity)
        try:
            conversation = _create_conversation(browser, identity)
            patcher.setattr(
                app.state.assistant.storage,
                "active_conversation_executions",
                lambda *_args: ["synthetic-execution"],
            )
            response = _delete(browser, identity, conversation)
            assert response.status_code == 403, response.text
            assert response.json()["error"]["code"] == "session_revoked"
            assert runtime.cancelled == ["synthetic-execution"]
            assert runtime.purged == []
            _assert_conversation_retained(app, identity, conversation)
        finally:
            browser.close()


def test_delete_removes_only_confirmed_owner_conversation(settings: Settings) -> None:
    runtime = _PurgeRuntime()
    app = _HELPERS.create_app(
        _HELPERS._auth_settings(settings),
        _HELPERS.FixtureProvider(),
        lambda: _HELPERS.NOW,
        assistant_runtime=runtime,
        assistant_catalog=_HELPERS.FakeCatalog(),
        assistant_providers=_HELPERS.FakeProviders(),
    )
    with (
        pytest.MonkeyPatch.context() as patcher,
        TestClient(app, client=("127.0.0.1", 51043)),
    ):
        patcher.setattr(_HELPERS.application_api, "datetime", _HELPERS._FrozenHTTPDatetime)
        patcher.setattr(_HELPERS.assistant_api, "datetime", _HELPERS._AssistantHTTPDatetime)
        owner = _HELPERS._add_signed_in_user(app, 88120)
        peer = _HELPERS._add_signed_in_user(app, 88121)
        owner_browser = _HELPERS._browser_client(app, owner)
        peer_browser = _HELPERS._browser_client(app, peer)
        try:
            owner_conversation = _create_conversation(owner_browser, owner)
            peer_conversation = _create_conversation(peer_browser, peer)
            response = _delete(owner_browser, owner, owner_conversation)
            assert response.status_code == 200, response.text
            assert response.json()["canonical_content_removed"] is True
            assert runtime.purged == [str(owner_conversation["id"])]
            with pytest.raises(AssistantStorageNotFound):
                app.state.assistant.storage.get_conversation(
                    int(owner["user_id"]), str(owner_conversation["id"])
                )
            _assert_conversation_retained(app, peer, peer_conversation)
        finally:
            owner_browser.close()
            peer_browser.close()
