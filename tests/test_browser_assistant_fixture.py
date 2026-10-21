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
