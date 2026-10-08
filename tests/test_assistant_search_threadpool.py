"""HTTP regressions for loop-owned completion of search approval waiters."""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stock_probs import api as application_api
from stock_probs.assistant import api as assistant_api
from stock_probs.assistant.schemas import AssistantTurnContext
from stock_probs.assistant.service import AssistantService
from stock_probs.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from stock_probs.config import Settings
from stock_probs.provider import FixtureProvider

_HELPER_SPEC = importlib.util.spec_from_file_location(
    "assistant_api_search_test_support", Path(__file__).with_name("test_assistant_api.py")
)
assert _HELPER_SPEC is not None and _HELPER_SPEC.loader is not None
_API_TESTS = importlib.util.module_from_spec(_HELPER_SPEC)
_HELPER_SPEC.loader.exec_module(_API_TESTS)

NOW = _API_TESTS.NOW
MODEL = _API_TESTS.MODEL


@pytest.fixture(autouse=True)
def _freeze_http_auth_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(application_api, "datetime", _API_TESTS._FrozenHTTPDatetime)
    monkeypatch.setattr(assistant_api, "datetime", _API_TESTS._AssistantHTTPDatetime)


def _browser_client(application, identity: dict[str, str | int], port: int) -> TestClient:
    client = TestClient(application, client=("127.0.0.1", port), raise_server_exceptions=False)
    client.cookies.set(SESSION_COOKIE_NAME, str(identity["token"]), path="/")
    client.cookies.set(CSRF_COOKIE_NAME, str(identity["csrf"]), path="/")
    return client


def _runtime_context(
    page_context, conversation, turn, identity, capability
) -> AssistantTurnContext:
    return AssistantTurnContext(
        user_id=int(identity["user_id"]),
        app_id="signal-ledger",
        conversation_id=str(conversation["id"]),
        turn_id=str(turn["id"]),
        execution_id=str(turn["execution_id"]),
        capability=capability,
        model_id=MODEL.model_id,
        policy_version=MODEL.policy_version,
        context_version=str(page_context["context_version"]),
        page_context=page_context,
        history=(),
    )


def _start_waiting_search(app, runtime_context, query: str):
    preview_seen = threading.Event()
    state: dict[str, object] = {"events": []}

    async def emit(event: dict[str, object]) -> None:
        asyncio.get_running_loop().set_debug(True)
        state["events"].append(event)
        preview_seen.set()

    async def run_waiter() -> str | None:
        loop = asyncio.get_running_loop()
        loop.set_debug(True)
        task = asyncio.create_task(app.await_search_approval(runtime_context, query, emit))
        state["loop"] = loop
        state["task"] = task
        return await task

    executor = ThreadPoolExecutor(max_workers=1)
    pending = executor.submit(lambda: asyncio.run(run_waiter()))
    assert preview_seen.wait(timeout=3), "the search waiter did not emit its approval preview"
    event = state["events"][0]
    return executor, pending, state, event["data"]


def _stop_waiting_search(
    executor: ThreadPoolExecutor, pending: Future, state: dict[str, object]
) -> None:
    if not pending.done():
        loop = state.get("loop")
        task = state.get("task")
        assert isinstance(loop, asyncio.AbstractEventLoop)
        assert isinstance(task, asyncio.Task)
        loop.call_soon_threadsafe(task.cancel)
        with contextlib.suppress(asyncio.CancelledError):
            pending.result(timeout=3)
    executor.shutdown(wait=True, cancel_futures=True)


def _application(settings: Settings):
    return _API_TESTS.create_app(
        _API_TESTS._auth_settings(settings),
        FixtureProvider(),
        lambda: NOW,
        assistant_runtime=_API_TESTS.FakeRuntime(),
        assistant_catalog=_API_TESTS.FakeCatalog(),
        assistant_providers=_API_TESTS.FakeProviders(),
    )


def _create_waiting_turn(browser, identity):
    page_context, conversation, turn, _lease, capability = (
        _API_TESTS._conversation_and_running_turn(browser, identity)
    )
    return (
        page_context,
        conversation,
        turn,
        capability,
        _runtime_context(page_context, conversation, turn, identity, capability),
    )


def test_http_search_confirmation_from_worker_thread_resumes_once(settings):
    application = _application(settings)
    with TestClient(application, client=("127.0.0.1", 51120)):
        identity = _API_TESTS._add_signed_in_user(application, 50120)
        browser = _browser_client(application, identity, 51121)
        second_browser = _browser_client(application, identity, 51122)
        try:
            page_context, conversation, turn, _capability, runtime_context = _create_waiting_turn(
                browser, identity
            )
            app = application.state.assistant
            query = "private balance from this conversation"
            executor, pending, waiter_state, preview = _start_waiting_search(
                app, runtime_context, query
            )
            preview_id = str(preview["preview_id"])
            waiter = app._search_waiters[preview_id]
            assert waiter.get_loop().get_debug()
            confirm_path = (
                f"/api/v1/assistant/conversations/{conversation['id']}"
                f"/turns/{turn['id']}/search-previews/{preview_id}/confirm"
            )
            headers = {"x-csrf-token": str(identity["csrf"])}
            changed_context_response = browser.get(
                "/api/v1/assistant/context", params={"route": "/research"}
            )
            assert changed_context_response.status_code == 200
            changed_context = changed_context_response.json()["context"]
            stale = browser.post(
                confirm_path,
                json={
                    "context_version": preview["context_version"],
                    "context": changed_context,
                    "confirmation_phrase": preview["confirmation_phrase"],
                    "allow": True,
                },
                headers=headers,
            )
            assert stale.status_code == 409
            assert not waiter.done()

            payload = {
                "context_version": preview["context_version"],
                "context": page_context,
                "confirmation_phrase": preview["confirmation_phrase"],
                "allow": True,
            }
            with ThreadPoolExecutor(max_workers=2) as confirmations:
                first = confirmations.submit(
                    browser.post, confirm_path, json=payload, headers=headers
                )
                second = confirmations.submit(
                    second_browser.post, confirm_path, json=payload, headers=headers
                )
                responses = [first.result(timeout=4), second.result(timeout=4)]

            assert sorted(response.status_code for response in responses) == [200, 409]
            approved = next(response for response in responses if response.status_code == 200)
            assert approved.json() == {"preview_id": preview_id, "status": "approved"}
            assert pending.result(timeout=2) == query
            assert waiter.done()
            assert waiter.result() == query
            assert app._search_waiters == {}
            stored = app.storage.get_search_preview(
                int(identity["user_id"]),
                str(conversation["id"]),
                str(turn["id"]),
                preview_id,
            )
            assert stored["status"] == "approved"
            assert len(waiter_state["events"]) == 1

            replay = browser.post(confirm_path, json=payload, headers=headers)
            assert replay.status_code == 409
        finally:
            if "executor" in locals():
                _stop_waiting_search(executor, pending, waiter_state)
                assert app._search_waiters == {}
            second_browser.close()
            browser.close()


def test_http_search_confirmation_rejects_revoked_session(settings):
    application = _application(settings)
    with TestClient(application, client=("127.0.0.1", 51130)):
        identity = _API_TESTS._add_signed_in_user(application, 50130)
        browser = _browser_client(application, identity, 51131)
        try:
            page_context, conversation, turn, _capability, runtime_context = _create_waiting_turn(
                browser, identity
            )
            app = application.state.assistant
            executor, pending, waiter_state, preview = _start_waiting_search(
                app, runtime_context, "search requiring the current owner session"
            )
            preview_id = str(preview["preview_id"])
            confirm_path = (
                f"/api/v1/assistant/conversations/{conversation['id']}"
                f"/turns/{turn['id']}/search-previews/{preview_id}/confirm"
            )
            application.state.repository.auth_revoke_session(
                str(identity["token_hash"]), NOW.isoformat()
            )
            response = browser.post(
                confirm_path,
                json={
                    "context_version": preview["context_version"],
                    "context": page_context,
                    "confirmation_phrase": preview["confirmation_phrase"],
                    "allow": True,
                },
                headers={"x-csrf-token": str(identity["csrf"])},
            )
            assert response.status_code == 401
            stored = app.storage.get_search_preview(
                int(identity["user_id"]),
                str(conversation["id"]),
                str(turn["id"]),
                preview_id,
            )
            assert stored["status"] == "pending"
            assert app._search_waiters[preview_id].done() is False
        finally:
            if "executor" in locals():
                _stop_waiting_search(executor, pending, waiter_state)
                assert app._search_waiters == {}
            browser.close()


def test_cancelled_search_waiter_keeps_preview_pending_and_cannot_be_claimed(settings):
    application = _application(settings)
    with TestClient(application, client=("127.0.0.1", 51135)):
        identity = _API_TESTS._add_signed_in_user(application, 50135)
        browser = _browser_client(application, identity, 51136)
        try:
            page_context, conversation, turn, _capability, runtime_context = _create_waiting_turn(
                browser, identity
            )
            app = application.state.assistant
            executor, pending, waiter_state, preview = _start_waiting_search(
                app, runtime_context, "cancelled request must remain unapproved"
            )
            preview_id = str(preview["preview_id"])
            _stop_waiting_search(executor, pending, waiter_state)
            assert app._search_waiters == {}

            confirm_path = (
                f"/api/v1/assistant/conversations/{conversation['id']}"
                f"/turns/{turn['id']}/search-previews/{preview_id}/confirm"
            )
            response = browser.post(
                confirm_path,
                json={
                    "context_version": preview["context_version"],
                    "context": page_context,
                    "confirmation_phrase": preview["confirmation_phrase"],
                    "allow": True,
                },
                headers={"x-csrf-token": str(identity["csrf"])},
            )
            assert response.status_code == 409
            stored = app.storage.get_search_preview(
                int(identity["user_id"]),
                str(conversation["id"]),
                str(turn["id"]),
                preview_id,
            )
            assert stored["status"] == "pending"
        finally:
            if "executor" in locals():
                _stop_waiting_search(executor, pending, waiter_state)
            browser.close()


def test_search_waiter_completion_ignores_cancelled_and_already_finished_futures():
    async def check_completion_races() -> None:
        loop = asyncio.get_running_loop()
        cancelled = loop.create_future()
        cancelled.cancel()
        AssistantService._finish_search_waiter(cancelled, "late approval")
        assert cancelled.cancelled()

        completed = loop.create_future()
        completed.set_result("first approval")
        AssistantService._finish_search_waiter(completed, "late approval")
        assert completed.result() == "first approval"

    asyncio.run(check_completion_races())


def test_alert_removal_hands_off_to_existing_controls_without_threshold_guidance(settings):
    application = _application(settings)
    with TestClient(application, client=("127.0.0.1", 51140)):
        identity = _API_TESTS._add_signed_in_user(application, 50140)
        assistant = application.state.assistant
        context = application.state.auth.authenticate(str(identity["token"]), assistant.now())
        instrument = assistant.forecast_service.lookup("ACDC", 1)["items"][0]
        payload = {
            key: instrument[key]
            for key in ("canonical_symbol", "asset_type", "provider", "exchange")
        }

        outcome, result = assistant.dispatch_confirmed_action(
            int(identity["user_id"]),
            "alerts.remove",
            {
                "symbol": payload["canonical_symbol"],
                "asset_type": payload["asset_type"],
                "provider": payload["provider"],
                "exchange": payload["exchange"],
            },
            confirmed_by=context,
        )

        assert outcome == "handed_off"
        assert "select and remove the existing browser alert" in result["message"].lower()
        assert "threshold" not in result["message"].lower()
        assert "no alert was changed here" in result["message"].lower()
        assert result["browser_action"]["type"] == "alerts.remove"
        assert result["browser_action"]["destination"] == {
            "kind": "current-page",
            "route": "/tools/live-trading",
            "focus": "alerts-heading",
        }
