"""Assistant authorization, confirmation, and receipt recovery security regressions."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient

from stock_probs.assistant import storage as assistant_storage
from stock_probs.assistant.storage import AssistantStorageError
from tests.test_assistant_release_contract import (
    _add_user,
    _application,
    _browser,
    _create_conversation,
    _create_running_turn,
    _mcp_call,
)


def _propose_action(
    app: Any,
    browser: TestClient,
    machine: TestClient,
    identity: Mapping[str, str | int],
    model: Mapping[str, object],
    *,
    action_type: str,
    payload: Mapping[str, object],
    route: str = "/overview",
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    page_context, conversation = _create_conversation(browser, identity, model, route=route)
    turn, capability = _create_running_turn(app, identity, model, page_context, conversation)
    proposed = _mcp_call(
        machine,
        turn,
        capability,
        "assistant.propose_action",
        {"action_type": action_type, "payload": dict(payload)},
    )
    assert proposed.status_code == 200, proposed.text
    card = next(
        event["data"]
        for event in app.state.assistant.storage.events_after(
            int(identity["user_id"]),
            str(conversation["id"]),
            str(turn["id"]),
            after=0,
        )
        if event["type"] == "proposed_action"
    )
    assistant = app.state.assistant
    assert assistant.storage.set_turn_status(
        int(identity["user_id"]),
        str(conversation["id"]),
        str(turn["id"]),
        status="completed",
        now=assistant.now(),
    )
    assistant.storage.close_execution(str(turn["execution_id"]), now=assistant.now())
    return page_context, conversation, card


def _confirm(
    browser: TestClient,
    identity: Mapping[str, str | int],
    page_context: Mapping[str, object],
    conversation: Mapping[str, object],
    card: Mapping[str, object],
    *,
    extra_headers: Mapping[str, str] | None = None,
):
    headers = {"x-csrf-token": str(identity["csrf"])}
    headers.update(extra_headers or {})
    return browser.post(
        f"/api/v1/assistant/conversations/{conversation['id']}/actions/{card['action_id']}/confirm",
        headers=headers,
        json={
            "action_version": card["version"],
            "context": dict(page_context),
            "allow": True,
            "confirmation_phrase": card["confirmation_phrase"],
        },
    )


def _portfolio_add_payload(app: Any) -> dict[str, object]:
    item = app.state.service.lookup("SPY", 1)["items"][0]
    return {
        "symbol": item["canonical_symbol"],
        "asset_type": item["asset_type"],
        "provider": item["provider"],
        "exchange": item["exchange"],
        "quantity": 1.0,
    }


def _make_admin_and_mark_fresh_totp(app: Any, identity: Mapping[str, str | int]) -> None:
    repository = app.state.repository
    user_id = int(identity["user_id"])
    assert repository.auth_update_user(user_id, {"role": "admin"}) is not None
    factor = repository.auth_get_totp_factor(user_id)
    assert factor is not None
    assert repository.auth_set_session_mfa(
        str(identity["token_hash"]),
        "totp",
        app.state.assistant.now().isoformat(),
        int(factor["id"]),
    )


def _record_dispatches(assistant: Any, monkeypatch: Any) -> list[str]:
    calls: list[str] = []
    original = assistant.dispatch_confirmed_action

    def record(user_id: int, action_type: str, *args: object, **kwargs: object):
        calls.append(action_type)
        return original(user_id, action_type, *args, **kwargs)

    monkeypatch.setattr(assistant, "dispatch_confirmed_action", record)
    return calls


def test_authenticated_assistant_confirmation_rejects_host_origin_and_forwarded_spoofs(
    settings,
):
    app, model = _application(settings)
    with TestClient(app) as _lifecycle:
        identity = _add_user(app, 51300)
        browser = _browser(app, identity)
        machine = TestClient(app, client=("127.0.0.1", 51301))
        try:
            context, conversation, card = _propose_action(
                app,
                browser,
                machine,
                identity,
                model,
                action_type="portfolio.add",
                payload=_portfolio_add_payload(app),
            )
            attempts = (
                ({"Host": "attacker.example"}, 400, "host_rejected"),
                ({"Origin": "https://attacker.example"}, 403, "origin_rejected"),
                (
                    {
                        "Origin": "https://attacker.example",
                        "X-Forwarded-Host": "attacker.example",
                        "X-Forwarded-Proto": "https",
                    },
                    403,
                    "origin_rejected",
                ),
            )
            for headers, status, code in attempts:
                response = _confirm(
                    browser,
                    identity,
                    context,
                    conversation,
                    card,
                    extra_headers=headers,
                )
                assert response.status_code == status, response.text
                assert response.json()["error"]["code"] == code
                saved_action = app.state.assistant.storage.get_action(
                    int(identity["user_id"]), str(card["action_id"])
                )
                assert saved_action["status"] == "pending"
                assert (
                    app.state.assistant.storage.get_action_receipt(
                        int(identity["user_id"]), str(card["action_id"])
                    )
                    is None
                )
                assert (
                    app.state.repository.instrument_list_items(
                        int(identity["user_id"]), "portfolio"
                    )
                    == []
                )
        finally:
            machine.close()
            browser.close()


def test_sensitive_admin_action_rejects_stale_totp_proof_before_dispatch(settings, monkeypatch):
    app, model = _application(settings)
    with TestClient(app) as _lifecycle:
        identity = _add_user(app, 51302)
        _make_admin_and_mark_fresh_totp(app, identity)
        browser = _browser(app, identity)
        machine = TestClient(app, client=("127.0.0.1", 51303))
        try:
            context, conversation, card = _propose_action(
                app,
                browser,
                machine,
                identity,
                model,
                action_type="provider.settings",
                payload={},
            )
            assistant = app.state.assistant
            factor = app.state.repository.auth_get_totp_factor(int(identity["user_id"]))
            assert factor is not None
            stale = assistant.now() - timedelta(minutes=10)
            assert app.state.repository.auth_set_session_mfa(
                str(identity["token_hash"]), "totp", stale.isoformat(), int(factor["id"])
            )
            dispatches = _record_dispatches(assistant, monkeypatch)

            response = _confirm(browser, identity, context, conversation, card)

            assert response.status_code == 403, response.text
            assert response.json()["error"]["code"] == "totp_step_up_required"
            assert dispatches == []
            assert (
                assistant.storage.get_action(int(identity["user_id"]), str(card["action_id"]))[
                    "status"
                ]
                == "pending"
            )
            assert (
                assistant.storage.get_action_receipt(
                    int(identity["user_id"]), str(card["action_id"])
                )
                is None
            )
        finally:
            machine.close()
            browser.close()


def test_sensitive_admin_action_rechecks_factor_after_target_validation(settings, monkeypatch):
    app, model = _application(settings)
    with TestClient(app) as _lifecycle:
        identity = _add_user(app, 51304)
        _make_admin_and_mark_fresh_totp(app, identity)
        browser = _browser(app, identity)
        machine = TestClient(app, client=("127.0.0.1", 51305))
        try:
            context, conversation, card = _propose_action(
                app,
                browser,
                machine,
                identity,
                model,
                action_type="provider.settings",
                payload={},
            )
            assistant = app.state.assistant
            repository = app.state.repository
            validate = assistant._validate_action_target

            def invalidate_factor_after_target(
                user_id: int, action_type: str, payload: Mapping[str, object]
            ) -> None:
                validate(user_id, action_type, payload)
                with repository.connect() as connection:
                    connection.execute(
                        "UPDATE sessions SET mfa_method = NULL, mfa_verified_at = NULL, "
                        "mfa_factor_id = NULL WHERE token_hash = ?",
                        (str(identity["token_hash"]),),
                    )
                    connection.commit()

            monkeypatch.setattr(
                assistant, "_validate_action_target", invalidate_factor_after_target
            )
            dispatches = _record_dispatches(assistant, monkeypatch)

            response = _confirm(browser, identity, context, conversation, card)

            assert response.status_code == 403, response.text
            assert dispatches == []
            assert (
                assistant.storage.get_action(int(identity["user_id"]), str(card["action_id"]))[
                    "status"
                ]
                == "pending"
            )
            assert (
                assistant.storage.get_action_receipt(
                    int(identity["user_id"]), str(card["action_id"])
                )
                is None
            )
        finally:
            machine.close()
            browser.close()


def test_receipt_capacity_denial_precedes_domain_dispatch(settings, monkeypatch):
    app, model = _application(settings)
    with TestClient(app) as _lifecycle:
        identity = _add_user(app, 51306)
        browser = _browser(app, identity)
        machine = TestClient(app, client=("127.0.0.1", 51307))
        try:
            context, conversation, card = _propose_action(
                app,
                browser,
                machine,
                identity,
                model,
                action_type="portfolio.add",
                payload=_portfolio_add_payload(app),
            )
            assistant = app.state.assistant
            usage_before = assistant.storage.usage(int(identity["user_id"]))
            monkeypatch.setattr(
                assistant_storage,
                "ASSISTANT_USER_HISTORY_LIMIT",
                usage_before["user_bytes"] + 512,
            )
            dispatches = _record_dispatches(assistant, monkeypatch)

            response = _confirm(browser, identity, context, conversation, card)

            assert response.status_code == 413, response.text
            assert response.json()["error"]["code"] == "assistant_quota_exceeded"
            assert dispatches == []
            assert (
                assistant.storage.get_action(int(identity["user_id"]), str(card["action_id"]))[
                    "status"
                ]
                == "pending"
            )
            assert (
                assistant.storage.get_action_receipt(
                    int(identity["user_id"]), str(card["action_id"])
                )
                is None
            )
            assert (
                app.state.repository.instrument_list_items(int(identity["user_id"]), "portfolio")
                == []
            )
            assert (
                assistant.storage.usage(int(identity["user_id"]))["user_bytes"]
                == (usage_before["user_bytes"])
            )
        finally:
            machine.close()
            browser.close()


def test_lost_reservation_commit_ack_recovers_unknown_and_never_replays(settings, monkeypatch):
    app, model = _application(settings)
    with TestClient(app) as _lifecycle:
        identity = _add_user(app, 51308)
        browser = _browser(app, identity)
        machine = TestClient(app, client=("127.0.0.1", 51309))
        try:
            context, conversation, card = _propose_action(
                app,
                browser,
                machine,
                identity,
                model,
                action_type="portfolio.add",
                payload=_portfolio_add_payload(app),
            )
            assistant = app.state.assistant
            dispatches = _record_dispatches(assistant, monkeypatch)
            claim = assistant.storage.claim_action

            def commit_then_lose_ack(*args: Any, **kwargs: Any) -> Any:
                claim(*args, **kwargs)
                raise AssistantStorageError("injected reservation commit acknowledgement loss")

            monkeypatch.setattr(assistant.storage, "claim_action", commit_then_lose_ack)
            ambiguous = _confirm(browser, identity, context, conversation, card)
            assert ambiguous.status_code == 503, ambiguous.text
            assert ambiguous.json()["error"]["code"] == "assistant_storage_unavailable"
            assert (
                assistant.storage.get_action(int(identity["user_id"]), str(card["action_id"]))[
                    "status"
                ]
                == "executing"
            )
            assert (
                assistant.storage.get_action_receipt(
                    int(identity["user_id"]), str(card["action_id"])
                )["outcome"]
                == "executing"
            )

            assistant._started = False
            asyncio.run(assistant.start())
            monkeypatch.setattr(assistant.storage, "claim_action", claim)

            action = assistant.storage.get_action(int(identity["user_id"]), str(card["action_id"]))
            receipt = assistant.storage.get_action_receipt(
                int(identity["user_id"]), str(card["action_id"])
            )
            assert action["status"] == "unknown"
            assert receipt is not None and receipt["outcome"] == "unknown"
            assert (
                app.state.repository.instrument_list_items(int(identity["user_id"]), "portfolio")
                == []
            )

            retry = _confirm(browser, identity, context, conversation, card)
            assert retry.status_code == 409, retry.text
            assert dispatches == []
            assert (
                assistant.storage.get_action(int(identity["user_id"]), str(card["action_id"]))[
                    "status"
                ]
                == "unknown"
            )
            assert (
                assistant.storage.get_action_receipt(
                    int(identity["user_id"]), str(card["action_id"])
                )["outcome"]
                == "unknown"
            )
        finally:
            machine.close()
            browser.close()


def test_maximal_filter_receipt_fits_user_and_global_reservation_at_capacity(settings, monkeypatch):
    """The largest typed handoff payload stays within the capacity reserved before dispatch."""

    app, model = _application(settings)
    with TestClient(app) as _lifecycle:
        identity = _add_user(app, 51310)
        browser = _browser(app, identity)
        machine = TestClient(app, client=("127.0.0.1", 51311))
        try:
            maximal_payload = {
                "query": "界" * 30,
                "asset_type": "stock",
                "status": "successful",
                "analysis_kind": "fresh_historical_reconstruction",
                "submitted_from": "2025-01-01",
                "submitted_to": "2025-12-31",
                "model": "m" * 120,
                "horizon": "completed_5m_to_close",
                "sort": "event_id:desc",
                "page_size": 50,
            }
            context, conversation, card = _propose_action(
                app,
                browser,
                machine,
                identity,
                model,
                action_type="filters.apply",
                payload=maximal_payload,
                route="/",
            )
            assistant = app.state.assistant
            limits: dict[str, int] = {}
            reserved_bytes: list[int] = []
            finalized_bytes: list[int] = []
            original_ensure_capacity = assistant_storage.AssistantStorage._ensure_capacity
            original_dispatch = assistant.dispatch_confirmed_action

            def ensure_at_exact_reservation_boundary(
                storage_type: type,
                connection: Any,
                user_id: int,
                additional_bytes: int,
            ) -> None:
                projected = additional_bytes + 192
                limits["user"] = storage_type._history_bytes(connection, user_id) + projected
                limits["global"] = storage_type._history_bytes(connection, None) + projected
                monkeypatch.setattr(
                    assistant_storage, "ASSISTANT_USER_HISTORY_LIMIT", limits["user"]
                )
                monkeypatch.setattr(
                    assistant_storage, "ASSISTANT_GLOBAL_HISTORY_LIMIT", limits["global"]
                )
                original_ensure_capacity(connection, user_id, additional_bytes)

            def inspect_real_dispatch(
                user_id: int,
                action_type: str,
                payload: Mapping[str, object],
                **kwargs: object,
            ):
                with app.state.repository.connect() as connection:
                    row = connection.execute(
                        "SELECT result_json FROM assistant_action_receipts "
                        "WHERE action_id = ? AND user_id = ? AND outcome = 'executing'",
                        (str(card["action_id"]), user_id),
                    ).fetchone()
                assert row is not None
                reserved_bytes.append(len(str(row["result_json"]).encode("utf-8")))
                outcome, result = original_dispatch(user_id, action_type, payload, **kwargs)
                finalized_bytes.append(len(assistant.storage._json(result).encode("utf-8")))
                return outcome, result

            monkeypatch.setattr(
                assistant_storage.AssistantStorage,
                "_ensure_capacity",
                classmethod(ensure_at_exact_reservation_boundary),
            )
            monkeypatch.setattr(assistant, "dispatch_confirmed_action", inspect_real_dispatch)

            response = _confirm(browser, identity, context, conversation, card)

            assert response.status_code == 200, response.text
            assert response.json()["status"] == "handed_off"
            assert response.json()["browser_action"] == {
                "type": "filters.apply",
                "payload": maximal_payload,
                "destination": {"kind": "current-page", "route": "/"},
            }
            assert len(reserved_bytes) == len(finalized_bytes) == 1
            assert finalized_bytes[0] < reserved_bytes[0]
            usage = assistant.storage.usage(int(identity["user_id"]))
            assert usage["user_bytes"] <= limits["user"]
            assert usage["global_bytes"] <= limits["global"]
            receipt = assistant.storage.get_action_receipt(
                int(identity["user_id"]), str(card["action_id"])
            )
            assert receipt is not None and receipt["outcome"] == "handed_off"
        finally:
            machine.close()
            browser.close()
