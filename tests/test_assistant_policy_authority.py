"""Real provider metadata changes must stop delayed runtime persistence."""

import asyncio
import json
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stock_probs.assistant import providers
from stock_probs.assistant.model_catalog import (
    AssistantModel,
    AssistantModelCatalog,
    ModelCatalogAuthorizationError,
)
from stock_probs.assistant.providers import AssistantProviderManager, ProviderUnavailable
from stock_probs.assistant.storage import AssistantStorageExecutionStale
from stock_probs.config import Settings
from tests import test_assistant_runtime_event_http_flows as flows
from tests.test_assistant_providers import (
    _configure_custom_endpoint,
    _NativeOAuthRuntime,
    _oauth_manager,
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


def _policy_app(
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[FastAPI, AssistantProviderManager, flows._PausedRuntime, AssistantModel]:
    """Use production policy/catalog objects with synthetic generation and no network."""

    model_id, _ = _reviewed_zen_model_ids()
    model = AssistantModel(**vars(_policy_model(model_id)))

    async def reject_network(_url: str) -> object:
        raise AssertionError("policy authority fixtures must not request a model inventory")

    catalog = AssistantModelCatalog(requester=reject_network, clock=clock)
    catalog._publish_zen((model,), clock(), 0.0)
    runtime = flows._PausedRuntime()
    app = flows._make_app(settings, runtime)
    manager = AssistantProviderManager(
        app.state.assistant.settings,
        catalog,
        vault_dir=tmp_path / "policy",
        clock=clock,
    )
    assert manager._lock is catalog.policy_lock
    app.state.assistant.catalog = catalog
    app.state.assistant.providers = manager
    monkeypatch.setattr(flows, "_MODEL_ID", model_id)
    return app, manager, runtime, model


@pytest.mark.parametrize("operation", ["models", "update"])
@pytest.mark.parametrize("health_path", ["/api/v1/health", "/api/v1/readiness"])
def test_policy_contention_preserves_application_health(
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    health_path: str,
) -> None:
    """An admitted policy request must wait off-loop while another write owns authority."""

    app, manager, _runtime, model = _policy_app(settings, tmp_path, monkeypatch)
    held, release, returned, requested = (threading.Event() for _ in range(4))
    with TestClient(app, client=("127.0.0.1", 51068)) as browser:
        identity = flows._add_signed_in_user(app, 80112, role="admin")
        flows._set_browser_session(browser, identity)
        _context, _conversation, selected = flows._prepare_conversation(browser, identity)
        original_storage = app.state.assistant._policy_projection
        original_policy = manager._policy_call

        async def fixed_inventory(**_kwargs: object) -> tuple[AssistantModel, ...]:
            return (model,)

        async def observe_storage(function: Callable, *args: object, **kwargs: object) -> object:
            if getattr(function, "__name__", "") == "model_response":
                requested.set()
            return await original_storage(function, *args, **kwargs)

        async def observe_policy(function: Callable, *args: object, **kwargs: object) -> object:
            if getattr(function, "__name__", "") == "update_model_policy":
                requested.set()
            return await original_policy(function, *args, **kwargs)

        monkeypatch.setattr(app.state.assistant, "ensure_model_inventory", fixed_inventory)
        monkeypatch.setattr(app.state.assistant, "_policy_projection", observe_storage)
        monkeypatch.setattr(manager, "_policy_call", observe_policy)

        def hold_authority() -> None:
            with manager.runtime_policy_scope(
                model.model_id, str(selected["policy_version"]), owner_id=int(identity["user_id"])
            ):
                held.set()
                release.wait(timeout=1.5)
            returned.set()

        def request() -> object:
            if operation == "models":
                return browser.get("/api/v1/assistant/models")
            return browser.put(
                f"/api/v1/assistant/models/{model.model_id}/policy",
                headers={"x-csrf-token": str(identity["csrf"])},
                json={"enabled": False, "expected_revision": 1},
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            holder = executor.submit(hold_authority)
            pending = None
            try:
                assert held.wait(timeout=3)
                pending = executor.submit(request)
                assert requested.wait(timeout=3), "request did not reach policy authority"
                assert browser.get(health_path).status_code == 200
                assert not returned.is_set(), "health waited for the policy authority holder"
            finally:
                release.set()
                holder.result(timeout=3)
                result = pending.result(timeout=5) if pending is not None else None
            assert result is not None and result.status_code == 200, getattr(result, "text", "")


@pytest.mark.parametrize("expired", [False, True])
def test_runtime_policy_expiry_is_checked_after_database_wait(
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    expired: bool,
) -> None:
    """The SQL predicate uses the cache deadline after waiting for repository ownership."""

    now = [10.0]
    app, manager, runtime, model = _policy_app(settings, tmp_path, monkeypatch, lambda: now[0])
    entered = threading.Event()
    with TestClient(app, client=("127.0.0.1", 51068)) as browser:
        identity = flows._add_signed_in_user(app, 80113)
        flows._set_browser_session(browser, identity)
        context, conversation, selected = flows._prepare_conversation(browser, identity)
        turn = flows._start_turn(browser, identity, context, conversation, selected)
        assert runtime.ready_for_first_event.wait(timeout=3)
        assistant = app.state.assistant
        owner = int(identity["user_id"])
        lease = assistant.storage.execution_for_turn(owner, conversation["id"], turn["id"])
        assert lease is not None
        lease = assistant.storage.execution_lease(str(lease["execution_id"]))
        assert lease is not None
        policy = assistant.policy(model.model_id, owner_id=owner)
        guard = assistant._runtime_write_guard(
            str(lease["execution_id"]),
            model.model_id,
            policy,
            str(lease["context_version"]),
            owner_id=owner,
        )
        original_scope = manager.runtime_policy_scope

        @contextmanager
        def observed_scope(
            *args: object, **kwargs: object
        ) -> Iterator[tuple[tuple[Callable[[], float], float], ...]]:
            with original_scope(*args, **kwargs) as deadlines:
                entered.set()
                yield deadlines

        monkeypatch.setattr(manager, "runtime_policy_scope", observed_scope)
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                with app.state.repository.exclusive():
                    pending = executor.submit(
                        assistant.storage.append_event,
                        owner,
                        conversation["id"],
                        turn["id"],
                        event_type="token",
                        data={"text": "after-database-wait"},
                        now=flows._NOW,
                        write_guard=guard,
                    )
                    assert entered.wait(timeout=3)
                    now[0] = 311.0 if expired else 100.0
                if expired:
                    with pytest.raises(
                        AssistantStorageExecutionStale, match="runtime_policy_expired"
                    ):
                        pending.result(timeout=5)
                else:
                    pending.result(timeout=5)
            events = assistant.storage.events_after(owner, conversation["id"], turn["id"], after=0)
            assert (
                any(e["data"].get("text") == "after-database-wait" for e in events) is not expired
            )
        finally:
            runtime.loop.call_soon_threadsafe(runtime.start_first_event.set)
            runtime.loop.call_soon_threadsafe(runtime.resume.set)


@pytest.mark.parametrize("status", [200, 500])
def test_stale_provider_inventory_cannot_replace_new_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """Neither a successful nor failed old fetch may overwrite a newer source snapshot."""

    catalog = AssistantModelCatalog()
    manager = AssistantProviderManager(
        SimpleNamespace(data_dir=tmp_path, auth_session_secret="s" * 64),
        catalog,
        vault_dir=tmp_path / "policy",
    )
    _configure_custom_endpoint(manager, "https://old-model.example/v1")
    requested, release = asyncio.Event(), asyncio.Event()

    async def fake_request(_url: str, **_kwargs: object) -> SimpleNamespace:
        requested.set()
        await release.wait()
        return SimpleNamespace(status_code=status, content=b'{"data":[{"id":"old-model"}]}')

    monkeypatch.setattr(providers, "request_public_https", fake_request)

    async def exercise() -> None:
        pending = asyncio.create_task(manager.validate("custom"))
        await asyncio.wait_for(requested.wait(), timeout=1)
        await asyncio.to_thread(_configure_custom_endpoint, manager, "https://new-model.example/v1")

        def publish_new_source() -> tuple[AssistantModel, ...]:
            rows = manager._parse_provider_model_rows("custom", [{"id": "new-model"}])
            manager._replace_provider_models("custom", rows)
            return rows

        current = await manager._policy_call(publish_new_source)
        release.set()
        with pytest.raises(ProviderUnavailable):
            await pending
        assert manager._provider_models["custom"] == current
        assert catalog.get_model("custom/new-model") is not None
        assert catalog.get_model("custom/old-model") is None

    asyncio.run(exercise())


def test_catalog_publication_rechecks_authorization_after_authority_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refresh revoked while waiting to publish must preserve the complete prior snapshot."""

    suffix = _reviewed_zen_model_ids()[1]
    publishing, held, release = threading.Event(), threading.Event(), threading.Event()
    allowed = [True]

    async def requester(_url: str) -> SimpleNamespace:
        return SimpleNamespace(
            status_code=200, content=json.dumps({"data": [{"id": suffix}]}).encode()
        )

    catalog = AssistantModelCatalog(requester=requester, clock=lambda: 10.0)
    asyncio.run(catalog.refresh())
    previous = catalog._snapshot
    original_publish = catalog._publish_zen_authorized

    async def observe_publish(*args: object, **kwargs: object) -> None:
        publishing.set()
        await original_publish(*args, **kwargs)

    monkeypatch.setattr(catalog, "_publish_zen_authorized", observe_publish)

    def holder() -> None:
        with catalog.policy_lock:
            held.set()
            release.wait(timeout=3)

    async def exercise() -> None:
        pending = asyncio.create_task(catalog.refresh(authorization_check=lambda: allowed[0]))
        assert await asyncio.to_thread(publishing.wait, 1)
        allowed[0] = False
        release.set()
        with pytest.raises(ModelCatalogAuthorizationError):
            await pending

    with ThreadPoolExecutor(max_workers=1) as executor:
        holding = executor.submit(holder)
        try:
            assert held.wait(timeout=1)
            asyncio.run(exercise())
        finally:
            release.set()
            holding.result(timeout=3)
    assert catalog._snapshot == previous


def test_catalog_read_projects_one_immutable_generation() -> None:
    """Concurrent publication during a clock read must not mix model/timestamp generations."""

    model_id, _ = _reviewed_zen_model_ids()
    original = AssistantModel(**vars(_policy_model(model_id)))
    newer = replace(original, model_id="synthetic/newer-model")
    armed = [False]

    def clock() -> float:
        if armed[0]:
            armed[0] = False
            catalog._publish_zen((newer,), 10.0, 0.0)
            catalog.set_native_models((newer,))
        return 10.0

    catalog = AssistantModelCatalog(clock=clock)
    catalog._publish_zen((original,), 10.0, 0.0)
    catalog.set_native_models((original,))
    armed[0] = True
    assert catalog.list_models() == (original,)
    assert catalog.list_models() == (newer,)


@pytest.mark.parametrize("interrupt", ["deadline", "cancel"])
def test_admitted_policy_write_finishes_before_request_retires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupt: str
) -> None:
    """A slow vault write cannot outlive a reported timeout or cancellation."""

    model_id, _ = _reviewed_zen_model_ids()
    manager = _policy_manager(tmp_path, _policy_model(model_id))
    state = manager.model_policy_state(model_id, owner_id=41)
    entered, release, finished = (threading.Event() for _ in range(3))
    original = manager._write_metadata

    def slow_write(value: object) -> None:
        entered.set()
        assert release.wait(timeout=3)
        original(value)
        finished.set()

    monkeypatch.setattr(manager, "_write_metadata", slow_write)
    monkeypatch.setattr(providers, "_MODEL_DISCOVERY_TIMEOUT_SECONDS", 0.05)

    async def run() -> None:
        pending = asyncio.create_task(
            manager.update_model_policy_async(
                model_id,
                enabled=False,
                acknowledged_privacy_policy_version=None,
                acknowledged_billing_policy_version=None,
                expected_revision=int(state["revision"]),
                owner_id=41,
                authorization_check=lambda: True,
            )
        )
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            if interrupt == "cancel":
                pending.cancel()
            await asyncio.sleep(0.1)
            assert not pending.done(), "request retired while its vault write was still running"
            assert not finished.is_set()
            if interrupt == "cancel":
                pending.cancel()  # Repeated disconnects cannot detach the write either.
            release.set()
            if interrupt == "cancel":
                with pytest.raises(asyncio.CancelledError):
                    await pending
            else:
                result = await pending
                assert result["enabled"] is False
            assert finished.is_set()
        finally:
            release.set()
            await asyncio.gather(pending, return_exceptions=True)

    asyncio.run(run())
    assert manager.model_policy_state(model_id, owner_id=41)["enabled"] is False


def test_policy_admission_timeout_never_starts_a_late_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expiring while another transaction holds authority must leave policy unchanged."""

    model_id, _ = _reviewed_zen_model_ids()
    manager = _policy_manager(tmp_path, _policy_model(model_id))
    held, release = threading.Event(), threading.Event()
    changed = threading.Event()
    monkeypatch.setattr(providers, "_MODEL_DISCOVERY_TIMEOUT_SECONDS", 0.05)

    def hold() -> None:
        with manager._lock:
            held.set()
            assert release.wait(timeout=3)

    async def run() -> None:
        with ThreadPoolExecutor(max_workers=1) as executor:
            holder = executor.submit(hold)
            assert await asyncio.to_thread(held.wait, 2)
            try:
                with pytest.raises(ProviderUnavailable, match="provider_config_unavailable"):
                    await manager._policy_call(changed.set, authorization_check=lambda: True)
            finally:
                release.set()
                await asyncio.to_thread(holder.result, 2)
        assert not changed.is_set()

    asyncio.run(run())


def test_native_turn_policy_contention_keeps_event_loop_responsive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real native turn admission must wait for policy authority on a worker thread."""

    from stock_probs.assistant.runtime import OpenCodeV2Runtime
    from stock_probs.assistant.schemas import AssistantRuntimeStatus
    from tests.test_assistant_runtime import _context

    model_id, _ = _reviewed_zen_model_ids()
    manager = _policy_manager(tmp_path, _policy_model(model_id))
    manager.update_model_policy(
        model_id,
        enabled=False,
        acknowledged_privacy_policy_version=None,
        acknowledged_billing_policy_version=None,
        expected_revision=1,
        owner_id=41,
    )
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True), providers=manager, catalog=manager.catalog
    )
    held, release, requested, watchdog = (threading.Event() for _ in range(4))
    original = manager._policy_call

    async def observe_policy(*args: object, **kwargs: object) -> object:
        requested.set()
        return await original(*args, **kwargs)

    async def ready(**_kwargs: object) -> None:
        runtime._status = AssistantRuntimeStatus("ready", "Synthetic transport readiness.")
        runtime._enabled = True
        runtime._client = object()

    async def emit(_event: object) -> None:
        raise AssertionError("a disabled model must not start native work")

    monkeypatch.setattr(manager, "_policy_call", observe_policy)
    monkeypatch.setattr(runtime, "start", ready)

    def hold() -> None:
        with manager._lock:
            held.set()
            if not release.wait(timeout=1.5):
                watchdog.set()

    async def run() -> None:
        with ThreadPoolExecutor(max_workers=1) as executor:
            holder = executor.submit(hold)
            assert await asyncio.to_thread(held.wait, 2)
            pending = asyncio.create_task(
                runtime.run_turn(
                    context=replace(_context(), model_id=model_id),
                    prompt="Read summary.",
                    emit=emit,
                )
            )
            try:
                assert await asyncio.to_thread(requested.wait, 2)
                await asyncio.sleep(0)
                assert not watchdog.is_set(), "policy lock blocked the native event loop"
            finally:
                release.set()
                await asyncio.to_thread(holder.result, 2)
                result = await pending
            assert result.status == "failed"
            assert result.error_code == "provider_unavailable"

    asyncio.run(run())


@pytest.mark.parametrize("caller", ["provider", "native"])
def test_expired_policy_waiters_leave_executor_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caller: str
) -> None:
    """Expired admissions cannot occupy workers needed by authentication and storage."""

    from stock_probs.assistant.runtime import OpenCodeV2Runtime

    model_id, _ = _reviewed_zen_model_ids()
    manager = _policy_manager(tmp_path, _policy_model(model_id))
    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True), providers=manager, catalog=manager.catalog
    )
    held, release = threading.Event(), threading.Event()
    monkeypatch.setattr(providers, "_MODEL_DISCOVERY_TIMEOUT_SECONDS", 0.05)

    def hold() -> None:
        with manager._lock:
            held.set()
            assert release.wait(timeout=3)

    async def read() -> object:
        if caller == "native":
            return await runtime._policy_projection(
                manager.model_policy_state, model_id, owner_id=41
            )
        return await manager._policy_call(manager.model_policy_state, model_id, owner_id=41)

    async def run() -> None:
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=2))
        with ThreadPoolExecutor(max_workers=1) as holders:
            holder = holders.submit(hold)
            assert await asyncio.to_thread(held.wait, 2)
            try:
                outcomes = await asyncio.gather(*(read() for _ in range(4)), return_exceptions=True)
                assert all(isinstance(value, ProviderUnavailable) for value in outcomes)
                assert not release.is_set()
                assert await asyncio.wait_for(asyncio.to_thread(lambda: "ready"), 0.2) == "ready"
            finally:
                release.set()
                await asyncio.to_thread(holder.result, 2)

    asyncio.run(run())


def test_policy_dispatch_timeout_abandons_queued_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Executor saturation must not extend admission or permit a later queued commit."""

    manager = _policy_manager(tmp_path)
    held, release, watchdog, changed = (threading.Event() for _ in range(4))
    monkeypatch.setattr(providers, "_MODEL_DISCOVERY_TIMEOUT_SECONDS", 0.05)

    def occupy_worker() -> None:
        held.set()
        if not release.wait(timeout=1.5):
            watchdog.set()

    async def authorize() -> bool:
        return True

    async def run() -> None:
        executor = ThreadPoolExecutor(max_workers=1)
        asyncio.get_running_loop().set_default_executor(executor)
        holder = executor.submit(occupy_worker)
        assert held.wait(timeout=1)
        try:
            with pytest.raises(ProviderUnavailable, match="provider_config_unavailable"):
                await manager._policy_call(changed.set, authorization_check=authorize)
            assert not watchdog.is_set(), "queued dispatch extended the admission deadline"
            assert not changed.is_set()
        finally:
            release.set()
            await asyncio.to_thread(holder.result, 2)
        # Drain the same executor queue; abandonment must survive eventual worker availability.
        await asyncio.to_thread(lambda: None)
        assert not changed.is_set()

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True])
def test_oauth_handoff_write_is_off_loop_and_retains_connected_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    """An interrupted vault publication must retain its matching connected attempt state."""

    native = _NativeOAuthRuntime(status="handoff_ready")
    manager = _oauth_manager(tmp_path, native)
    entered, release = threading.Event(), threading.Event()
    writer_threads: list[int] = []
    original = manager._write_oauth_credential

    def held_write(*args: object) -> None:
        writer_threads.append(threading.get_ident())
        entered.set()
        assert release.wait(timeout=3)
        original(*args)

    monkeypatch.setattr(manager, "_write_oauth_credential", held_write)

    async def authorize() -> bool:
        return True

    async def run() -> None:
        loop_thread = threading.get_ident()
        attempt = await manager.begin_native_oauth(
            "openai",
            "chatgpt-headless",
            owner_id=17,
            session_id="a" * 32,
            session_token_hash="b" * 64,
        )
        pending = asyncio.create_task(
            manager.complete_native_oauth(
                str(attempt["attempt_id"]),
                owner_id=17,
                session_id="a" * 32,
                authorization_check=authorize,
            )
        )
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            assert writer_threads and writer_threads[0] != loop_thread
            if cancel:
                pending.cancel()
            await asyncio.sleep(0)
            assert not pending.done()
            release.set()
            if cancel:
                with pytest.raises(asyncio.CancelledError):
                    await pending
            else:
                assert (await pending)["status"] == "connected"
            assert manager._oauth_attempts[str(attempt["attempt_id"])].status == "connected"
            assert manager._oauth_credential_path("openai", 17, "chatgpt-headless").exists()
        finally:
            release.set()
            await asyncio.gather(pending, return_exceptions=True)

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["timeout", "cancel", "expiry"])
def test_consumed_oauth_handoff_retires_when_publication_is_abandoned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """A consumed handoff cannot remain pending or connect after its attempt expires."""

    native = _NativeOAuthRuntime(status="handoff_ready")
    manager = _oauth_manager(tmp_path, native)
    held, release, requested = (threading.Event() for _ in range(3))
    original_policy = manager._policy_call
    original_cancel = native.cancel_native_oauth
    if failure == "timeout":
        monkeypatch.setattr(providers, "_MODEL_DISCOVERY_TIMEOUT_SECONDS", 0.05)

    async def observe_policy(function: Callable, *args: object, **kwargs: object) -> object:
        if getattr(function, "__name__", "") == "publish_connection":
            requested.set()
        return await original_policy(function, *args, **kwargs)

    async def authorize() -> bool:
        return True

    def hold() -> None:
        with manager._lock:
            held.set()
            assert release.wait(timeout=3)

    async def run() -> None:
        cleanup_started, cleanup_release = asyncio.Event(), asyncio.Event()

        async def held_cancel(*args: object, **kwargs: object) -> None:
            cleanup_started.set()
            await cleanup_release.wait()
            await original_cancel(*args, **kwargs)

        attempt = await manager.begin_native_oauth(
            "openai",
            "chatgpt-headless",
            owner_id=17,
            session_id="a" * 32,
            session_token_hash="b" * 64,
        )
        monkeypatch.setattr(manager, "_policy_call", observe_policy)
        if failure == "cancel":
            monkeypatch.setattr(native, "cancel_native_oauth", held_cancel)
        with ThreadPoolExecutor(max_workers=1) as executor:
            holder = executor.submit(hold)
            assert await asyncio.to_thread(held.wait, 2)
            pending = asyncio.create_task(
                manager.complete_native_oauth(
                    str(attempt["attempt_id"]),
                    owner_id=17,
                    session_id="a" * 32,
                    authorization_check=authorize,
                )
            )
            try:
                assert await asyncio.to_thread(requested.wait, 2)
                if failure == "cancel":
                    pending.cancel()
                    await asyncio.wait_for(cleanup_started.wait(), 2)
                    pending.cancel()
                    await asyncio.sleep(0)
                    assert not pending.done(), "repeated cancellation detached handoff cleanup"
                    cleanup_release.set()
                    with pytest.raises(asyncio.CancelledError):
                        await pending
                else:
                    if failure == "expiry":
                        manager._oauth_attempts[str(attempt["attempt_id"])].expires_at = (
                            time.time() - 1
                        )
                        release.set()
                    with pytest.raises(ProviderUnavailable):
                        await pending
                record = manager._oauth_attempts[str(attempt["attempt_id"])]
                assert record.status == ("expired" if failure == "expiry" else "cancelled")
                assert record.authorization_url is None and record.callback_state is None
                assert not manager._oauth_credential_path("openai", 17, "chatgpt-headless").exists()
                assert native.calls[-1] == "cancel"
                assert record.transport_capability is None
            finally:
                cleanup_release.set()
                release.set()
                await asyncio.gather(pending, return_exceptions=True)
                await asyncio.to_thread(holder.result, 2)

    asyncio.run(run())
