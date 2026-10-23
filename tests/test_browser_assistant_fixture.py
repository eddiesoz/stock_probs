"""Exercise the maintained synthetic runtime over real loopback HTTP."""

from __future__ import annotations

import asyncio
import runpy
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from stock_probs.assistant.service import AssistantService
from stock_probs.assistant.storage import AssistantStorageExecutionStale


@pytest.mark.parametrize(
    "model,version,owner,accepted",
    [
        ("current", "current", 1, True),
        ("other", "current", 1, False),
        ("current", "stale", 1, False),
        ("current", "current", None, False),
        ("current", "current", 0, False),
        ("current", "current", -1, False),
        ("current", "current", True, False),
    ],
)
def test_browser_fixture_policy_authority_guards_real_service_writes(
    model, version, owner, accepted
):
    fixture = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "tools/browser/assistant_qa_server.py")
    )
    provider = fixture["_Providers"]()
    selected = fixture["_MODEL"]
    service = SimpleNamespace(providers=provider)
    before = provider.model_policy_state(selected.model_id, owner_id=1)
    scope = AssistantService._runtime_policy_scope(
        service,
        owner,
        selected.model_id if model == "current" else "unreviewed/model",
        selected.policy_version if version == "current" else "stale-policy",
    )
    entered = False
    if accepted:
        with scope as deadlines:
            entered = True
            assert deadlines == ()
    else:
        with pytest.raises(AssistantStorageExecutionStale, match="runtime_policy_changed"), scope:
            entered = True
    assert entered is accepted
    assert provider.model_policy_state(selected.model_id, owner_id=1) == before


@contextmanager
def _mcp_response(*, status: int, delay_seconds: float) -> Iterator[str]:
    finished = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            try:
                assert self.path == "/api/v1/assistant/internal/mcp/fixture-execution"
                length = int(self.headers.get("Content-Length", "0"))
                assert 0 < length < 2048
                self.rfile.read(length)
                # A controlled response beyond three seconds exercises the fixture client bound.
                time.sleep(delay_seconds)
                payload = b'{"result":{"content":[],"isError":false}}'
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                # The original premature client timeout can close the red run's socket.
                with suppress(BrokenPipeError):
                    self.wfile.write(payload)
            finally:
                finished.set()

        def log_message(self, format: str, *args: object) -> None:
            return None

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join(timeout=5)
            assert not thread.is_alive()
            assert finished.wait(timeout=5)


@pytest.mark.parametrize("status,delay_seconds", [(200, 3.25), (503, 0.0)])
def test_browser_runtime_preserves_delayed_mcp_success_and_http_failures(
    status: int, delay_seconds: float
) -> None:
    fixture = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "tools/browser/assistant_qa_server.py")
    )
    context = SimpleNamespace(
        execution_id="fixture-execution",
        capability="synthetic-loopback-fixture-capability",
        model_id=fixture["_MODEL"].model_id,
        context_version="fixture-context",
    )
    emitted: list[Mapping[str, object]] = []

    async def emit(event: Mapping[str, object]) -> None:
        emitted.append(event)

    with _mcp_response(status=status, delay_seconds=delay_seconds) as origin:
        runtime = fixture["_Runtime"](origin)
        turn = runtime.run_turn(context=context, prompt="Explain the fixture", emit=emit)
        if status == 503:
            with pytest.raises(RuntimeError, match="HTTP 503"):
                asyncio.run(turn)
            assert emitted == []
        else:
            result = asyncio.run(turn)
            assert result.status == "completed"
            assert [event["type"] for event in emitted] == ["meta", "token", "proposed_action"]


@pytest.mark.parametrize(
    "enabled,failure,expected_dumps,dump_fails",
    [
        ("0", "coordination", 0, False),
        ("1", "coordination", 1, False),
        ("1", "body", 0, False),
        ("1", "other", 0, False),
        ("1", None, 0, False),
        pytest.param("1", "coordination", 1, True, id="dump_failure"),
    ],
)
def test_lock_failure_stack_diagnostic_is_opt_in_once_and_preserves_errors(
    monkeypatch, capsys, enabled, failure, expected_dumps, dump_fails
):
    fixture = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "tools/browser/assistant_qa_server.py")
    )
    monkeypatch.setenv("STOCK_PROBS_BROWSER_LOCK_DIAGNOSTIC", enabled)
    error = (
        fixture["RepositoryOperationalError"](
            "database coordination lock timed out"
            if failure in {"coordination", "body"}
            else "other"
        )
        if failure is not None
        else None
    )
    entries = []

    @contextmanager
    def original():
        entries.append("entered")
        if error is not None and failure != "body":
            raise error
        yield

    dumps = []

    def dump(**kwargs):
        dumps.append(kwargs)
        if dump_fails:
            raise OSError("Synthetic stack output failure")

    monkeypatch.setattr(fixture["faulthandler"], "dump_traceback", dump)
    repository = SimpleNamespace(_coordinated=original)
    fixture["_install_lock_failure_diagnostic"](repository)
    if enabled == "0":
        assert repository._coordinated is original
    for _ in range(2):
        if error is None:
            with repository._coordinated():
                pass
        else:
            with pytest.raises(type(error)) as captured, repository._coordinated():
                if failure == "body":
                    raise error
            assert captured.value is error
    assert entries == ["entered", "entered"]
    assert len(dumps) == expected_dumps
    assert all(call["all_threads"] is True for call in dumps)
    stderr = capsys.readouterr().err
    assert stderr == ("Fixture repository coordination timeout stack:\n" if expected_dumps else "")
