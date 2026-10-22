"""Real provider metadata changes must stop delayed runtime persistence."""

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stock_probs.assistant.model_catalog import AssistantModel
from stock_probs.config import Settings
from tests import test_assistant_runtime_event_http_flows as flows
from tests.test_assistant_providers import (
    _policy_manager,
    _policy_model,
    _reviewed_zen_model_ids,
)
from tests.test_assistant_runtime_event_http_flows import (
    _freeze_http_auth_clock as _freeze_http_auth_clock,
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data/app.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
    )


@pytest.mark.parametrize("change", ["live", "disabled"])
def test_delayed_runtime_write_rechecks_provider_policy(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    """A completed admin disable must reject a subsequently committed runtime token."""
    model_id, _ = _reviewed_zen_model_ids()
    model = AssistantModel(**vars(_policy_model(model_id)))
    manager = _policy_manager(tmp_path / "policy", model)
    monkeypatch.setattr(manager.catalog, "list_models", lambda: (model,), raising=False)
    monkeypatch.setattr(flows, "_MODEL_ID", model_id)
    runtime = flows._PausedRuntime()
    app = flows._make_app(settings, runtime)
    app.state.assistant.catalog = manager.catalog
    app.state.assistant.providers = manager
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    with TestClient(app, client=("127.0.0.1", 51068)) as browser:
        identity = flows._add_signed_in_user(app, 80111)
        flows._set_browser_session(browser, identity)
        context, conversation, selected = flows._prepare_conversation(browser, identity)
        turn = flows._start_turn(browser, identity, context, conversation, selected)
        assert runtime.ready_for_first_event.wait(timeout=3)
        storage = app.state.assistant.storage
        original = storage.append_event

        def held_append(*args: object, **kwargs: object) -> object:
            if kwargs.get("event_type") == "token" and not entered.is_set():
                entered.set()
                assert release.wait(timeout=5)
                try:
                    return original(*args, **kwargs)
                finally:
                    returned.set()
            return original(*args, **kwargs)

        monkeypatch.setattr(storage, "append_event", held_append)
        try:
            runtime.loop.call_soon_threadsafe(runtime.start_first_event.set)
            assert entered.wait(timeout=3)
            if change == "disabled":
                state = manager.model_policy_state(model_id, owner_id=int(identity["user_id"]))
                disabled = manager.update_model_policy(
                    model_id,
                    owner_id=int(identity["user_id"]),
                    enabled=False,
                    acknowledged_privacy_policy_version=None,
                    acknowledged_billing_policy_version=None,
                    expected_revision=state["revision"],
                )
                assert disabled["enabled"] is False
            release.set()
            assert returned.wait(timeout=5)
            events = storage.events_after(
                int(identity["user_id"]), conversation["id"], turn["id"], after=0
            )
            tokens = [e["data"].get("text", "") for e in events if e["type"] == "token"]
            visible = any("visible-before-revocation:" in token for token in tokens)
            assert visible is (change == "live"), "runtime token committed after policy changed"
        finally:
            release.set()
            runtime.loop.call_soon_threadsafe(runtime.resume.set)
