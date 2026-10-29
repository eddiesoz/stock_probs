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
from fastapi.testclient import TestClient

from stock_probs.assistant.service import AssistantService
from stock_probs.assistant.storage import AssistantStorageExecutionStale
from stock_probs.repository import Repository


@pytest.mark.parametrize("stream_fails", [False, True])
def test_browser_stream_audit_reports_pending_emission_without_body_content(stream_fails):
    fixture = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "tools/browser/assistant_qa_server.py")
    )

    async def exercise():
        started = asyncio.Event()
        release = asyncio.Event()
        failure = RuntimeError("synthetic stream failure")
        frames = [
            b'id: 1\nevent: meta\ndata: {"private_text":"not retained"}\n\n',
            b'id: 2\nevent: webfetch_preview\ndata: {"private_url":"not retained"}\n\n',
        ]

        async def application(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            for frame in frames:
                split = frame.index(b"event:") + len(b"event: ")
                for chunk in (frame[:split], frame[split:]):
                    await send({"type": "http.response.body", "body": chunk, "more_body": True})
            started.set()
            await release.wait()
            if stream_fails:
                raise failure
            await send({"type": "http.response.body", "body": b"", "more_body": False})

        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            return None

        records = []
        audit = fixture["_AssistantStreamAudit"](application, records)
        task = asyncio.create_task(
            audit(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/api/v1/assistant/conversations/fixture/turns/fixture/events",
                },
                receive,
                send,
            )
        )
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            assert records == [], "completed records must keep their original terminal meaning"
            assert len(audit.active_records) == 1
            pending = audit.active_records[0]
            assert pending["status"] == 200
            assert pending["body_bytes"] == sum(map(len, frames))
            assert pending["body_bytes_sent"] == pending["body_bytes"]
            assert pending["sent_event_types"] == ["meta", "webfetch_preview"]
            assert pending["body_end"] is False
            assert pending["send_pending"] is False
            assert "not retained" not in str(pending)
        finally:
            release.set()
            outcome = (await asyncio.gather(task, return_exceptions=True))[0]
        assert outcome is failure if stream_fails else outcome is None
        assert audit.active_records == []
        assert len(records) == 1
        assert records[0]["error"] == ("RuntimeError" if stream_fails else None)
        assert records[0]["body_end"] is (not stream_fails)

    asyncio.run(exercise())


@pytest.mark.parametrize("seed_fails", [False, True])
def test_browser_fixture_seeds_inside_one_canonical_lifespan(monkeypatch, tmp_path, seed_fails):
    fixture = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "tools/browser/assistant_qa_server.py")
    )
    monkeypatch.setenv("STOCK_PROBS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STOCK_PROBS_FIXTURE_NOW", "2025-01-10T17:03:00+00:00")
    monkeypatch.setattr("sys.argv", ["assistant_qa_server.py", "--port", "8765"])
    migrations = []
    original_migrate = Repository.migrate

    def migrate(repository, *args, **kwargs):
        migrations.append(repository.database_path)
        return original_migrate(repository, *args, **kwargs)

    monkeypatch.setattr(Repository, "migrate", migrate)
    captured = []

    def serve(server, **kwargs):
        application = server.application
        captured.append(application)
        with TestClient(server, base_url="http://127.0.0.1:8765") as client:
            assert application.state.ready is True
            assert client.get("/api/v1/readiness").status_code == 200
            client.cookies.set("signal_ledger_session", fixture["_SESSION"])
            client.cookies.set("signal_ledger_csrf", fixture["_CSRF"])
            session = client.get("/api/v1/auth/session")
            assert session.status_code == 200
            assert session.json()["authenticated"] is True
            assert session.json()["user"]["role"] == "admin"
            assert client.get("/api/v1/assistant/status").status_code == 200

    monkeypatch.setattr(fixture["uvicorn"], "run", serve)
    if seed_fails:

        def reject_seed(*_args, **_kwargs):
            raise RuntimeError("synthetic fixture seed failure")

        monkeypatch.setitem(fixture["main"].__globals__, "_seed_session", reject_seed)
        with pytest.raises(RuntimeError, match="synthetic fixture seed failure"):
            fixture["main"]()
    else:
        fixture["main"]()
    assert len(captured) == 1, "seeding must run within the actual server lifespan"
    assert migrations == [tmp_path / "stock_probs.sqlite3"]
    assert captured[0].state.ready is False
    assert captured[0].state.assistant._started is False


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
