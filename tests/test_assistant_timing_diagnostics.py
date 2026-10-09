"""Regression tests for bounded, owner-bound timing diagnostics and late callbacks."""

from __future__ import annotations

import asyncio
import json

import pytest

from stock_probs.assistant import api as assistant_api
from stock_probs.assistant import runtime as assistant_runtime
from stock_probs.assistant.service import AssistantUnavailable

EXECUTION_ID = "a" * 32


def test_runtime_timing_diagnostic_is_bounded_anonymous_and_owner_bound() -> None:
    now = [50.0]
    diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: now[0])
    diagnostics.begin(EXECUTION_ID, 7)
    assert diagnostics.provider_started(EXECUTION_ID, 8) is None
    diagnostics.workspace_summary_completed(EXECUTION_ID, 8)

    now[0] += 0.012
    ordinal = diagnostics.provider_started(EXECUTION_ID, 7)
    assert ordinal == 1
    diagnostics.provider_first_sanitized_chunk(EXECUTION_ID, 8, ordinal)
    diagnostics.provider_sanitized_yield(EXECUTION_ID, 8, ordinal, 4)
    assert diagnostics.provider_started(EXECUTION_ID, 8) is None
    now[0] += 0.021
    diagnostics.provider_first_sanitized_chunk(EXECUTION_ID, 7, ordinal)
    diagnostics.workspace_summary_completed(EXECUTION_ID, 7)
    diagnostics.provider_sanitized_yield(EXECUTION_ID, 7, ordinal, 4)
    now[0] += 0.025
    diagnostics.provider_finished(EXECUTION_ID, 7, ordinal, "ended", "clean_eof")
    now[0] += 0.010
    receipt = diagnostics.finish(EXECUTION_ID, 7, "completed")

    assert receipt == {
        "event": "assistant_turn_timing_v5",
        "version": 5,
        "scope": "diagnostic_only",
        "terminal_status": "completed",
        "turn_elapsed_ms": 68,
        "workspace_summary_completed_ms": 33,
        "pre_session_phase": None,
        "pre_session_failure_code": None,
        "provider_requests": [
            {
                "ordinal": 1,
                "start_ms": 12,
                "first_sanitized_chunk_ms": 33,
                "sanitized_chunk_count": 1,
                "sanitized_byte_count": 4,
                "last_sanitized_yield_ms": 33,
                "end_ms": 58,
                "outcome": "ended",
                "stream_lifecycle": "clean_eof",
                "stream_lifecycle_observed": True,
                "failure_diagnostic": None,
            }
        ],
    }
    encoded = json.dumps(receipt)
    assert EXECUTION_ID not in encoded
    assert '"owner_id"' not in encoded
    assert diagnostics.finish(EXECUTION_ID, 7, "completed") is None


def test_runtime_distinguishes_observed_late_close_from_unresolved_timeout() -> None:
    now = [20.0]
    diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: now[0])
    diagnostics.begin(EXECUTION_ID, 9)
    observed_ordinal = diagnostics.provider_started(EXECUTION_ID, 9)
    unresolved_ordinal = diagnostics.provider_started(EXECUTION_ID, 9)
    assert observed_ordinal == 1
    assert unresolved_ordinal == 2

    now[0] += 120.5
    diagnostics.provider_finished(EXECUTION_ID, 9, observed_ordinal, "ended", "clean_eof")
    assert diagnostics._contexts[EXECUTION_ID]["provider_requests"][0]["end_ms"] is None
    assert diagnostics._contexts[EXECUTION_ID]["provider_requests"][0]["outcome"] == "ended"
    now[0] += 1.25
    receipt = diagnostics.finish(EXECUTION_ID, 9, "timed_out")

    assert receipt is not None
    assert receipt["turn_elapsed_ms"] == 121_750
    assert receipt["terminal_status"] == "timed_out"
    assert receipt["pre_session_phase"] is None
    assert receipt["pre_session_failure_code"] is None
    assert receipt["provider_requests"] == [
        {
            "ordinal": 1,
            "start_ms": 0,
            "first_sanitized_chunk_ms": None,
            "sanitized_chunk_count": 0,
            "sanitized_byte_count": 0,
            "last_sanitized_yield_ms": None,
            "end_ms": None,
            "outcome": "ended",
            "stream_lifecycle": "clean_eof",
            "stream_lifecycle_observed": True,
            "failure_diagnostic": None,
        },
        {
            "ordinal": 2,
            "start_ms": 0,
            "first_sanitized_chunk_ms": None,
            "sanitized_chunk_count": 0,
            "sanitized_byte_count": 0,
            "last_sanitized_yield_ms": None,
            "end_ms": None,
            "outcome": "cancelled",
            "stream_lifecycle": "unresolved_at_turn_timeout",
            "stream_lifecycle_observed": False,
            "failure_diagnostic": None,
        },
    ]


def test_runtime_timing_diagnostic_ignores_callbacks_after_finish() -> None:
    now = [75.0]
    diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: now[0])
    diagnostics.begin(EXECUTION_ID, 12)
    ordinal = diagnostics.provider_started(EXECUTION_ID, 12)
    assert ordinal == 1

    now[0] += 0.025
    receipt = diagnostics.finish(EXECUTION_ID, 12, "timed_out")
    assert receipt is not None
    assert diagnostics._contexts == {}

    now[0] += 0.010
    diagnostics.provider_first_sanitized_chunk(EXECUTION_ID, 12, ordinal)
    diagnostics.provider_sanitized_yield(EXECUTION_ID, 12, ordinal, 10)
    diagnostics.provider_finished(EXECUTION_ID, 12, ordinal, "ended", "clean_eof")
    diagnostics.provider_failed(
        EXECUTION_ID, 12, ordinal, "proxy_guard", "upstream_error_unknown", None
    )
    assert diagnostics.finish(EXECUTION_ID, 12, "timed_out") is None
    assert receipt["provider_requests"][0]["stream_lifecycle"] == "unresolved_at_turn_timeout"
    assert receipt["provider_requests"][0]["stream_lifecycle_observed"] is False
    assert receipt["provider_requests"][0]["failure_diagnostic"] is None
    assert diagnostics._contexts == {}


def test_runtime_timing_diagnostic_wrong_owner_finish_preserves_context() -> None:
    now = [90.0]
    diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: now[0])
    diagnostics.begin(EXECUTION_ID, 17)
    ordinal = diagnostics.provider_started(EXECUTION_ID, 17)
    assert ordinal == 1
    now[0] += 0.015

    assert diagnostics.finish(EXECUTION_ID, 18, "failed") is None
    assert diagnostics._contexts[EXECUTION_ID]["owner_id"] == 17
    receipt = diagnostics.finish(EXECUTION_ID, 17, "failed")
    assert receipt is not None
    assert receipt["event"] == "assistant_turn_timing_v5"
    assert receipt["provider_requests"] == [
        {
            "ordinal": 1,
            "start_ms": 0,
            "first_sanitized_chunk_ms": None,
            "sanitized_chunk_count": 0,
            "sanitized_byte_count": 0,
            "last_sanitized_yield_ms": None,
            "end_ms": None,
            "outcome": "failed",
            "stream_lifecycle": "unresolved_at_turn_terminal",
            "stream_lifecycle_observed": False,
            "failure_diagnostic": None,
        }
    ]
    assert diagnostics._contexts == {}
    assert diagnostics.finish(EXECUTION_ID, 17, "failed") is None


def test_runtime_timing_diagnostic_bounds_chunk_counters_and_lifecycle() -> None:
    now = [0.0]
    diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: now[0])
    diagnostics.begin(EXECUTION_ID, 19)
    ordinal = diagnostics.provider_started(EXECUTION_ID, 19)
    assert ordinal == 1
    diagnostics.provider_sanitized_yield(EXECUTION_ID, 19, ordinal, 32 * 1024 + 1)
    row = diagnostics._contexts[EXECUTION_ID]["provider_requests"][0]
    assert row["sanitized_chunk_count"] == 0
    row["sanitized_chunk_count"] = assistant_runtime._TURN_TIMING_MAX_PROVIDER_CHUNKS
    row["first_sanitized_chunk_ms"] = 0
    row["last_sanitized_yield_ms"] = 0
    diagnostics.provider_sanitized_yield(EXECUTION_ID, 19, ordinal, 0)
    assert row["sanitized_chunk_count"] == assistant_runtime._TURN_TIMING_MAX_PROVIDER_CHUNKS
    diagnostics.provider_finished(EXECUTION_ID, 19, ordinal, "ended", "unknown")
    assert row["stream_lifecycle_observed"] is False
    receipt = diagnostics.finish(EXECUTION_ID, 19, "completed")
    assert receipt is not None
    assert receipt["provider_requests"][0]["stream_lifecycle"] == "unresolved_at_turn_terminal"

    second_execution = "b" * 32
    diagnostics.begin(second_execution, 20)
    second_ordinal = diagnostics.provider_started(second_execution, 20)
    assert second_ordinal == 1
    second_row = diagnostics._contexts[second_execution]["provider_requests"][0]
    second_row["sanitized_chunk_count"] = 1
    second_row["sanitized_byte_count"] = assistant_runtime._TURN_TIMING_MAX_PROVIDER_BYTES
    second_row["first_sanitized_chunk_ms"] = 0
    second_row["last_sanitized_yield_ms"] = 0
    diagnostics.provider_sanitized_yield(second_execution, 20, second_ordinal, 1)
    assert second_row["sanitized_chunk_count"] == 1
    assert second_row["sanitized_byte_count"] == assistant_runtime._TURN_TIMING_MAX_PROVIDER_BYTES


def test_runtime_timing_diagnostic_caps_contexts_and_provider_requests() -> None:
    now = [0.0]
    diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: now[0])
    first = "1" * 32
    second = "2" * 32
    third = "3" * 32
    diagnostics.begin(first, 1)
    diagnostics.begin(second, 2)
    diagnostics.begin(third, 3)
    assert len(diagnostics._contexts) == 2
    assert diagnostics.provider_started(third, 3) is None
    for expected in range(1, 9):
        assert diagnostics.provider_started(first, 1) == expected
    assert diagnostics.provider_started(first, 1) is None
    assert len(diagnostics._contexts[first]["provider_requests"]) == 8
    diagnostics.clear()
    assert diagnostics._contexts == {}


def test_runtime_timing_log_reaches_default_stderr_handler(capsys: pytest.CaptureFixture) -> None:
    runtime = assistant_runtime.OpenCodeV2Runtime.__new__(assistant_runtime.OpenCodeV2Runtime)
    runtime._turn_timing_diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: 1.0)
    runtime._begin_turn_timing_diagnostic(EXECUTION_ID, 11)

    runtime._finish_turn_timing_diagnostic(EXECUTION_ID, 11, "failed")

    stderr = capsys.readouterr().err
    assert stderr.startswith(assistant_runtime._TURN_TIMING_LOG_MARKER)
    encoded = stderr.removeprefix(assistant_runtime._TURN_TIMING_LOG_MARKER).strip()
    receipt = json.loads(encoded)
    assert set(receipt) == {
        "event",
        "version",
        "scope",
        "terminal_status",
        "turn_elapsed_ms",
        "workspace_summary_completed_ms",
        "pre_session_phase",
        "pre_session_failure_code",
        "provider_requests",
    }
    assert receipt["event"] == "assistant_turn_timing_v5"
    assert receipt["pre_session_phase"] is None
    assert receipt["pre_session_failure_code"] is None
    assert EXECUTION_ID not in encoded
    assert "owner_id" not in encoded


def test_runtime_timing_keeps_concurrent_pre_session_failures_owner_bound() -> None:
    diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: 30.0)
    first_execution = "c" * 32
    second_execution = "d" * 32
    diagnostics.begin(first_execution, 31)
    diagnostics.begin(second_execution, 32)

    diagnostics.pre_session_failure(second_execution, 32, "startup", "worker_unavailable")
    diagnostics.pre_session_failure(
        first_execution, 31, "model_discovery", "model_alias_unavailable"
    )
    first = diagnostics.finish(first_execution, 31, "failed")
    second = diagnostics.finish(second_execution, 32, "failed")

    assert first is not None
    assert (first["pre_session_phase"], first["pre_session_failure_code"]) == (
        "model_discovery",
        "model_alias_unavailable",
    )
    assert second is not None
    assert (second["pre_session_phase"], second["pre_session_failure_code"]) == (
        "startup",
        "worker_unavailable",
    )
    encoded = json.dumps([first, second])
    assert first_execution not in encoded
    assert second_execution not in encoded
    assert "owner_id" not in encoded


@pytest.mark.parametrize("contamination", ["workspace_summary", "provider_request"])
def test_runtime_timing_rejects_pre_session_failure_with_post_session_evidence(
    contamination: str,
) -> None:
    diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: 35.0)
    diagnostics.begin(EXECUTION_ID, 35)
    diagnostics.pre_session_failure(EXECUTION_ID, 35, "model_discovery", "model_alias_unavailable")
    if contamination == "workspace_summary":
        diagnostics.workspace_summary_completed(EXECUTION_ID, 35)
    else:
        assert diagnostics.provider_started(EXECUTION_ID, 35) == 1

    assert diagnostics.finish(EXECUTION_ID, 35, "failed") is None
    assert diagnostics._contexts == {}


@pytest.mark.parametrize(
    ("phase", "failure_code"),
    [
        ("startup", "unknown_code"),
        ("forged phase=private", "worker_unavailable"),
        ("model_discovery", "credential=synthetic-private-marker"),
    ],
)
def test_runtime_timing_drops_unknown_pre_session_values(
    phase: object, failure_code: object
) -> None:
    diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: 40.0)
    diagnostics.begin(EXECUTION_ID, 41)

    diagnostics.pre_session_failure(EXECUTION_ID, 42, "startup", "worker_unavailable")
    diagnostics.pre_session_failure(EXECUTION_ID, 41, phase, failure_code)
    receipt = diagnostics.finish(EXECUTION_ID, 41, "failed")

    assert receipt is not None
    assert receipt["pre_session_phase"] is None
    assert receipt["pre_session_failure_code"] is None
    assert "synthetic-private-marker" not in json.dumps(receipt)


def test_runtime_timing_failure_correlation_is_removed_after_finish_or_clear() -> None:
    diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: 50.0)
    completed_execution = "e" * 32
    cleared_execution = "f" * 32
    diagnostics.begin(completed_execution, 51)
    diagnostics.pre_session_failure(completed_execution, 51, "startup", "worker_unavailable")
    receipt = diagnostics.finish(completed_execution, 51, "failed")
    assert receipt is not None
    diagnostics.pre_session_failure(
        completed_execution, 51, "model_discovery", "model_alias_unavailable"
    )
    assert diagnostics.finish(completed_execution, 51, "failed") is None

    diagnostics.begin(cleared_execution, 52)
    diagnostics.pre_session_failure(cleared_execution, 52, "startup", "worker_unavailable")
    diagnostics.clear()
    diagnostics.pre_session_failure(cleared_execution, 52, "startup", "worker_unavailable")
    assert diagnostics.finish(cleared_execution, 52, "failed") is None


class _TimingRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []

    def _record_provider_stream_start(self, execution_id: str, owner_id: int) -> int:
        self.events.append(("start", execution_id, owner_id))
        return 1

    def _record_provider_first_sanitized_chunk(
        self, execution_id: str, owner_id: int, ordinal: int
    ) -> None:
        self.events.append(("first", execution_id, owner_id, ordinal))

    def _record_provider_sanitized_yield(
        self, execution_id: str, owner_id: int, ordinal: int, byte_count: int
    ) -> None:
        self.events.append(("yield", execution_id, owner_id, ordinal, byte_count))

    def _record_provider_stream_end(
        self,
        execution_id: str,
        owner_id: int,
        ordinal: int,
        outcome: str,
        lifecycle: str,
    ) -> None:
        self.events.append(("end", execution_id, owner_id, ordinal, outcome, lifecycle))

    def _record_provider_stream_failure(
        self,
        execution_id: str,
        owner_id: int,
        ordinal: int,
        stage: str,
        error_code: str,
        status_code: int | None,
        content_type_class: str | None = None,
        cf_mitigated_class: str | None = None,
        provider_error_type_class: str | None = None,
        response_failure_phase: str | None = None,
    ) -> None:
        del content_type_class, cf_mitigated_class, provider_error_type_class
        event = ("failure", execution_id, owner_id, ordinal, stage, error_code, status_code)
        self.events.append(
            event + (response_failure_phase,) if response_failure_phase is not None else event
        )

    def _record_workspace_summary_completion(self, execution_id: str, owner_id: int) -> None:
        self.events.append(("workspace", execution_id, owner_id))


def _timing_wrapper(recorder: _TimingRecorder, upstream):
    return assistant_api._provider_proxy_chunks_with_timing(
        upstream,
        lambda: True,
        runtime=recorder,
        execution_id=EXECUTION_ID,
        owner_id=4,
    )


def test_provider_timing_wrapper_preserves_sanitized_chunks_and_clean_eof() -> None:
    recorder = _TimingRecorder()

    async def upstream():
        yield b"event: message\ndata: safe\n\n"

    async def run() -> list[bytes]:
        return [chunk async for chunk in _timing_wrapper(recorder, upstream())]

    chunk = b"event: message\ndata: safe\n\n"
    assert asyncio.run(run()) == [chunk]
    assert recorder.events == [
        ("start", EXECUTION_ID, 4),
        ("first", EXECUTION_ID, 4, 1),
        ("yield", EXECUTION_ID, 4, 1, len(chunk)),
        ("end", EXECUTION_ID, 4, 1, "ended", "clean_eof"),
    ]


def test_provider_timing_wrapper_records_denial_as_safe_protocol_error() -> None:
    recorder = _TimingRecorder()
    contacted = False

    async def upstream():
        nonlocal contacted
        contacted = True
        yield b"never"

    async def run() -> None:
        async for _chunk in assistant_api._provider_proxy_chunks_with_timing(
            upstream(),
            lambda: False,
            runtime=recorder,
            execution_id=EXECUTION_ID,
            owner_id=4,
        ):
            pytest.fail("denied provider stream produced a chunk")

    with pytest.raises(AssistantUnavailable):
        asyncio.run(run())
    assert not contacted
    assert recorder.events == [
        ("start", EXECUTION_ID, 4),
        (
            "failure",
            EXECUTION_ID,
            4,
            1,
            "proxy_guard",
            "request_superseded",
            None,
        ),
        ("end", EXECUTION_ID, 4, 1, "failed", "safe_protocol_error"),
    ]


def test_provider_timing_wrapper_distinguishes_generator_close() -> None:
    recorder = _TimingRecorder()
    upstream_closed = asyncio.Event()

    async def upstream():
        try:
            yield b"first"
            await asyncio.sleep(60)
        finally:
            upstream_closed.set()

    async def run() -> None:
        bridge = _timing_wrapper(recorder, upstream())
        assert await bridge.__anext__() == b"first"
        await bridge.aclose()
        assert upstream_closed.is_set()

    asyncio.run(run())
    assert not any(event[0] == "failure" for event in recorder.events)
    assert recorder.events[-1] == (
        "end",
        EXECUTION_ID,
        4,
        1,
        "cancelled",
        "generator_closed",
    )


def test_provider_timing_wrapper_records_consumer_cancellation() -> None:
    recorder = _TimingRecorder()
    upstream_closed = asyncio.Event()

    async def upstream():
        try:
            yield b"first"
            await asyncio.Event().wait()
        finally:
            upstream_closed.set()

    async def run() -> None:
        bridge = _timing_wrapper(recorder, upstream())
        assert await bridge.__anext__() == b"first"
        next_chunk = asyncio.create_task(bridge.__anext__())
        await asyncio.sleep(0)
        next_chunk.cancel()
        with pytest.raises(asyncio.CancelledError):
            await next_chunk
        assert upstream_closed.is_set()

    asyncio.run(run())
    assert not any(event[0] == "failure" for event in recorder.events)
    assert recorder.events[-1] == (
        "end",
        EXECUTION_ID,
        4,
        1,
        "cancelled",
        "cancelled_error",
    )


def test_provider_timing_wrapper_defers_close_until_cancelled_anext_finishes() -> None:
    recorder = _TimingRecorder()

    async def run() -> None:
        class SlowIterator:
            def __init__(self) -> None:
                self.started = asyncio.Event()
                self.cancel_seen = asyncio.Event()
                self.resume = asyncio.Event()
                self.closed = asyncio.Event()
                self.running = False
                self.closed_while_running = False

            def __aiter__(self):
                return self

            async def __anext__(self) -> bytes:
                self.running = True
                self.started.set()
                try:
                    await self.resume.wait()
                    return b"late"
                except asyncio.CancelledError:
                    self.cancel_seen.set()
                    await self.resume.wait()
                    return b"late"
                finally:
                    self.running = False

            async def aclose(self) -> None:
                if self.running:
                    self.closed_while_running = True
                    raise RuntimeError("close raced with __anext__")
                self.closed.set()

        upstream = SlowIterator()
        bridge = _timing_wrapper(recorder, upstream)
        consumer = asyncio.create_task(bridge.__anext__())
        await upstream.started.wait()
        consumer.cancel()
        await upstream.cancel_seen.wait()
        with pytest.raises(asyncio.CancelledError):
            await consumer
        assert not upstream.closed.is_set()
        upstream.resume.set()
        await asyncio.wait_for(upstream.closed.wait(), timeout=1.0)
        assert not upstream.closed_while_running

    asyncio.run(run())


def test_provider_timing_wrapper_records_its_fixed_proxy_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _TimingRecorder()
    monkeypatch.setattr(assistant_api, "_PROXY_STREAM_TIMEOUT_SECONDS", 0.001)

    async def upstream():
        await asyncio.sleep(60)
        yield b"late"

    async def run() -> None:
        async for _chunk in _timing_wrapper(recorder, upstream()):
            pytest.fail("timed out provider stream produced a chunk")

    with pytest.raises(AssistantUnavailable):
        asyncio.run(run())
    assert recorder.events[-1] == (
        "end",
        EXECUTION_ID,
        4,
        1,
        "failed",
        "proxy_timeout",
    )
    assert recorder.events[-2] == (
        "failure",
        EXECUTION_ID,
        4,
        1,
        "proxy_deadline",
        "stream_deadline_exceeded",
        None,
    )


def test_provider_timing_wrapper_sanitizes_unexpected_upstream_error() -> None:
    recorder = _TimingRecorder()

    async def upstream():
        raise RuntimeError("private upstream payload")
        yield b"unreachable"

    async def run() -> None:
        async for _chunk in _timing_wrapper(recorder, upstream()):
            pytest.fail("failed provider stream produced a chunk")

    with pytest.raises(AssistantUnavailable):
        asyncio.run(run())
    assert recorder.events[-1] == (
        "end",
        EXECUTION_ID,
        4,
        1,
        "failed",
        "safe_protocol_error",
    )
    assert recorder.events[-2] == (
        "failure",
        EXECUTION_ID,
        4,
        1,
        "upstream_stream",
        "upstream_error_unknown",
        None,
    )
    assert "private upstream payload" not in repr(recorder.events)


def test_provider_timing_wrapper_records_known_transport_code_and_status() -> None:
    recorder = _TimingRecorder()

    async def upstream():
        raise assistant_api.net.PublicHTTPError("provider_upstream_unavailable", status_code=503)
        yield b"unreachable"

    async def run() -> None:
        bridge = _timing_wrapper(recorder, upstream())
        with pytest.raises(AssistantUnavailable) as failure:
            await bridge.__anext__()
        assert failure.value.code == "provider_unavailable"
        await bridge.aclose()

    asyncio.run(run())
    assert recorder.events[-2:] == [
        (
            "failure",
            EXECUTION_ID,
            4,
            1,
            "upstream_stream",
            "provider_upstream_unavailable",
            503,
        ),
        ("end", EXECUTION_ID, 4, 1, "failed", "safe_protocol_error"),
    ]


def test_provider_timing_wrapper_forwards_closed_response_failure_phase() -> None:
    recorder = _TimingRecorder()

    async def upstream():
        raise assistant_api.net.PublicHTTPError(
            "provider_response_invalid",
            status_code=200,
            response_failure_phase="body_eof",
        )
        yield b"unreachable"

    async def run() -> None:
        bridge = _timing_wrapper(recorder, upstream())
        with pytest.raises(AssistantUnavailable):
            await bridge.__anext__()
        await bridge.aclose()

    asyncio.run(run())
    assert recorder.events[-2:] == [
        (
            "failure",
            EXECUTION_ID,
            4,
            1,
            "upstream_stream",
            "provider_response_invalid",
            200,
            "body_eof",
        ),
        ("end", EXECUTION_ID, 4, 1, "failed", "safe_protocol_error"),
    ]


def test_runtime_provider_failure_diagnostic_is_owner_bound_closed_and_single_assignment() -> None:
    now = [30.0]
    diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: now[0])
    diagnostics.begin(EXECUTION_ID, 21)
    ordinal = diagnostics.provider_started(EXECUTION_ID, 21)
    assert ordinal == 1

    diagnostics.provider_failed(
        EXECUTION_ID,
        22,
        ordinal,
        "upstream_stream",
        "provider_upstream_unavailable",
        503,
    )
    diagnostics.provider_failed(
        EXECUTION_ID,
        21,
        ordinal,
        "upstream_stream",
        "provider_upstream_unavailable",
        503,
    )
    diagnostics.provider_failed(
        EXECUTION_ID,
        21,
        ordinal,
        "proxy_guard",
        "upstream_error_unknown",
        None,
    )
    diagnostics.provider_failed(
        EXECUTION_ID,
        21,
        ordinal,
        "untrusted-stage token=private",
        "private-code token=private",
        999,
    )
    diagnostics.provider_finished(EXECUTION_ID, 21, ordinal, "failed", "safe_protocol_error")
    receipt = diagnostics.finish(EXECUTION_ID, 21, "failed")

    assert receipt is not None
    assert receipt["provider_requests"][0]["failure_diagnostic"] == {
        "stage": "upstream_stream",
        "error_code": "provider_upstream_unavailable",
        "http_status": 503,
    }
    encoded = json.dumps(receipt)
    assert EXECUTION_ID not in encoded
    assert "private" not in encoded
    assert diagnostics._contexts == {}


def test_runtime_provider_response_failure_phase_is_closed_and_private() -> None:
    diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: 30.0)
    diagnostics.begin(EXECUTION_ID, 81)
    ordinal = diagnostics.provider_started(EXECUTION_ID, 81)
    assert ordinal == 1
    diagnostics.provider_failed(
        EXECUTION_ID,
        81,
        ordinal,
        "upstream_stream",
        "provider_response_invalid",
        200,
        response_failure_phase="body_eof",
    )
    diagnostics.provider_finished(EXECUTION_ID, 81, ordinal, "failed", "safe_protocol_error")

    receipt = diagnostics.finish(EXECUTION_ID, 81, "failed")

    assert receipt is not None
    assert receipt["provider_requests"][0]["failure_diagnostic"] == {
        "stage": "upstream_stream",
        "error_code": "provider_response_invalid",
        "http_status": 200,
        "response_failure_phase": "body_eof",
    }
    assert EXECUTION_ID not in json.dumps(receipt)
    assert "owner_id" not in json.dumps(receipt)


@pytest.mark.parametrize(
    ("stage", "error_code", "response_failure_phase"),
    [
        ("proxy_guard", "provider_response_invalid", "body_eof"),
        ("upstream_stream", "provider_upstream_unavailable", "body_eof"),
        ("upstream_stream", "provider_response_invalid", True),
        ("upstream_stream", "provider_response_invalid", "private token=synthetic"),
    ],
)
def test_runtime_provider_response_failure_phase_rejects_wrong_or_untrusted_values(
    stage: str, error_code: str, response_failure_phase: object
) -> None:
    diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: 30.0)
    diagnostics.begin(EXECUTION_ID, 82)
    ordinal = diagnostics.provider_started(EXECUTION_ID, 82)
    assert ordinal == 1
    diagnostics.provider_failed(
        EXECUTION_ID,
        82,
        ordinal,
        stage,
        error_code,
        200,
        response_failure_phase=response_failure_phase,
    )
    diagnostics.provider_finished(EXECUTION_ID, 82, ordinal, "failed", "safe_protocol_error")

    receipt = diagnostics.finish(EXECUTION_ID, 82, "failed")

    assert receipt is not None
    assert receipt["provider_requests"][0]["failure_diagnostic"] is None
    assert "synthetic" not in json.dumps(receipt)


def test_runtime_provider_failure_v4_keeps_only_valid_403_classes() -> None:
    diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: 30.0)
    diagnostics.begin(EXECUTION_ID, 24)
    ordinal = diagnostics.provider_started(EXECUTION_ID, 24)
    assert ordinal == 1
    diagnostics.provider_failed(
        EXECUTION_ID,
        24,
        ordinal,
        "upstream_stream",
        "provider_upstream_unavailable",
        403,
        "html",
        "challenge",
    )
    diagnostics.provider_finished(EXECUTION_ID, 24, ordinal, "failed", "safe_protocol_error")

    receipt = diagnostics.finish(EXECUTION_ID, 24, "failed")

    assert receipt is not None
    assert receipt["event"] == "assistant_turn_timing_v5"
    assert receipt["version"] == 5
    assert receipt["provider_requests"][0]["failure_diagnostic"] == {
        "stage": "upstream_stream",
        "error_code": "provider_upstream_unavailable",
        "http_status": 403,
        "content_type_class": "html",
        "cf_mitigated_class": "challenge",
    }


def test_runtime_provider_failure_v4_keeps_closed_error_type_class() -> None:
    diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: 30.0)
    diagnostics.begin(EXECUTION_ID, 27)
    ordinal = diagnostics.provider_started(EXECUTION_ID, 27)
    assert ordinal == 1
    diagnostics.provider_failed(
        EXECUTION_ID,
        27,
        ordinal,
        "upstream_stream",
        "provider_upstream_unavailable",
        403,
        provider_error_type_class="free_usage_limit_error",
    )
    diagnostics.provider_finished(EXECUTION_ID, 27, ordinal, "failed", "safe_protocol_error")

    receipt = diagnostics.finish(EXECUTION_ID, 27, "failed")

    assert receipt is not None
    assert receipt["provider_requests"][0]["failure_diagnostic"] == {
        "stage": "upstream_stream",
        "error_code": "provider_upstream_unavailable",
        "http_status": 403,
        "provider_error_type_class": "free_usage_limit_error",
    }
    assert "execution_id" not in json.dumps(receipt)
    assert "owner_id" not in json.dumps(receipt)


@pytest.mark.parametrize(
    ("stage", "error_code", "status_code", "provider_error_type_class"),
    [
        ("upstream_stream", "provider_upstream_unavailable", 403, True),
        ("upstream_stream", "provider_upstream_unavailable", 403, "private token=synthetic"),
        ("upstream_stream", "provider_upstream_unavailable", 503, "free_usage_limit_error"),
        ("proxy_guard", "upstream_error_unknown", 403, "free_usage_limit_error"),
    ],
)
def test_runtime_provider_failure_drops_invalid_error_type_class(
    stage: str,
    error_code: str,
    status_code: int,
    provider_error_type_class: object,
) -> None:
    diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: 30.0)
    diagnostics.begin(EXECUTION_ID, 28)
    ordinal = diagnostics.provider_started(EXECUTION_ID, 28)
    assert ordinal == 1
    diagnostics.provider_failed(
        EXECUTION_ID,
        28,
        ordinal,
        stage,
        error_code,
        status_code,
        provider_error_type_class=provider_error_type_class,
    )
    diagnostics.provider_finished(EXECUTION_ID, 28, ordinal, "failed", "safe_protocol_error")

    receipt = diagnostics.finish(EXECUTION_ID, 28, "failed")

    assert receipt is not None
    diagnostic = receipt["provider_requests"][0]["failure_diagnostic"]
    assert diagnostic is None
    assert "synthetic" not in json.dumps(receipt)


def test_runtime_timing_projection_rejects_tampered_error_type_class() -> None:
    diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: 30.0)
    diagnostics.begin(EXECUTION_ID, 29)
    ordinal = diagnostics.provider_started(EXECUTION_ID, 29)
    assert ordinal == 1
    diagnostics.provider_failed(
        EXECUTION_ID,
        29,
        ordinal,
        "upstream_stream",
        "provider_upstream_unavailable",
        403,
        provider_error_type_class="free_usage_limit_error",
    )
    diagnostics.provider_finished(EXECUTION_ID, 29, ordinal, "failed", "safe_protocol_error")
    context = diagnostics._contexts[EXECUTION_ID]
    rows = context["provider_requests"]
    assert isinstance(rows, list) and isinstance(rows[0], dict)
    failure = rows[0]["failure_diagnostic"]
    assert isinstance(failure, dict)
    failure["provider_error_type_class"] = "private token=synthetic"

    assert diagnostics.finish(EXECUTION_ID, 29, "failed") is None
    assert diagnostics._contexts == {}


def test_runtime_provider_failure_v4_preserves_legacy_unclassified_403_shape() -> None:
    diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: 30.0)
    diagnostics.begin(EXECUTION_ID, 26)
    ordinal = diagnostics.provider_started(EXECUTION_ID, 26)
    assert ordinal == 1
    diagnostics.provider_failed(
        EXECUTION_ID,
        26,
        ordinal,
        "upstream_stream",
        "provider_upstream_unavailable",
        403,
    )
    diagnostics.provider_finished(EXECUTION_ID, 26, ordinal, "failed", "safe_protocol_error")

    receipt = diagnostics.finish(EXECUTION_ID, 26, "failed")

    assert receipt is not None
    assert receipt["provider_requests"][0]["failure_diagnostic"] == {
        "stage": "upstream_stream",
        "error_code": "provider_upstream_unavailable",
        "http_status": 403,
    }


@pytest.mark.parametrize(
    ("stage", "error_code", "status_code", "content_type_class", "cf_mitigated_class"),
    [
        ("upstream_stream", "provider_upstream_unavailable", 403, "application/json", "absent"),
        ("upstream_stream", "provider_upstream_unavailable", 403, "json", "private"),
        ("upstream_stream", "provider_upstream_unavailable", 403, True, "challenge"),
        ("upstream_stream", "provider_upstream_unavailable", 503, "json", "challenge"),
        ("proxy_guard", "upstream_error_unknown", 403, "json", "challenge"),
    ],
)
def test_runtime_provider_failure_v4_drops_unclassified_or_misapplied_403_classes(
    stage: str,
    error_code: str,
    status_code: int,
    content_type_class: object,
    cf_mitigated_class: object,
) -> None:
    diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: 30.0)
    diagnostics.begin(EXECUTION_ID, 25)
    ordinal = diagnostics.provider_started(EXECUTION_ID, 25)
    assert ordinal == 1
    diagnostics.provider_failed(
        EXECUTION_ID,
        25,
        ordinal,
        stage,
        error_code,
        status_code,
        content_type_class,
        cf_mitigated_class,
    )
    diagnostics.provider_finished(EXECUTION_ID, 25, ordinal, "failed", "safe_protocol_error")

    receipt = diagnostics.finish(EXECUTION_ID, 25, "failed")

    assert receipt is not None
    assert receipt["provider_requests"][0]["failure_diagnostic"] is None


@pytest.mark.parametrize("status_code", [True, 99, 600, "503"])
def test_runtime_provider_failure_status_must_be_exact_bounded_integer(
    status_code: object,
) -> None:
    diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: 30.0)
    diagnostics.begin(EXECUTION_ID, 31)
    ordinal = diagnostics.provider_started(EXECUTION_ID, 31)
    assert ordinal == 1
    diagnostics.provider_failed(
        EXECUTION_ID,
        31,
        ordinal,
        "upstream_stream",
        "provider_upstream_unavailable",
        status_code,
    )
    diagnostics.provider_finished(EXECUTION_ID, 31, ordinal, "failed", "safe_protocol_error")
    receipt = diagnostics.finish(EXECUTION_ID, 31, "failed")
    assert receipt is not None
    assert receipt["provider_requests"][0]["failure_diagnostic"] == {
        "stage": "upstream_stream",
        "error_code": "provider_upstream_unavailable",
        "http_status": None,
    }


def test_runtime_provider_failure_ignores_unavailable_wrong_owner_late_and_capped_callbacks() -> (
    None
):
    now = [0.0]
    diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: now[0])
    diagnostics.provider_failed(
        EXECUTION_ID, 41, 1, "upstream_stream", "provider_upstream_unavailable", 503
    )
    diagnostics.begin(EXECUTION_ID, 41)
    for expected_ordinal in range(1, 9):
        ordinal = diagnostics.provider_started(EXECUTION_ID, 41)
        assert ordinal == expected_ordinal
        diagnostics.provider_failed(
            EXECUTION_ID,
            42,
            ordinal,
            "upstream_stream",
            "provider_upstream_unavailable",
            503,
        )
        diagnostics.provider_failed(
            EXECUTION_ID,
            41,
            ordinal,
            "upstream_stream",
            "provider_upstream_unavailable",
            503,
        )
        diagnostics.provider_finished(EXECUTION_ID, 41, ordinal, "failed", "safe_protocol_error")
    assert diagnostics.provider_started(EXECUTION_ID, 41) is None
    diagnostics.provider_failed(
        EXECUTION_ID, 41, 9, "upstream_stream", "provider_upstream_unavailable", 503
    )
    receipt = diagnostics.finish(EXECUTION_ID, 41, "failed")
    assert receipt is not None
    assert len(receipt["provider_requests"]) == 8
    assert all(row["failure_diagnostic"] is not None for row in receipt["provider_requests"])
    diagnostics.provider_failed(EXECUTION_ID, 41, 1, "proxy_guard", "upstream_error_unknown", None)
    assert diagnostics.finish(EXECUTION_ID, 41, "failed") is None


def test_runtime_provider_failure_rejects_unknown_stage_or_error_code() -> None:
    diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: 1.0)
    diagnostics.begin(EXECUTION_ID, 51)
    ordinal = diagnostics.provider_started(EXECUTION_ID, 51)
    assert ordinal == 1
    diagnostics.provider_failed(EXECUTION_ID, 51, ordinal, "untrusted-stage", "untrusted-code", 503)

    receipt = diagnostics.finish(EXECUTION_ID, 51, "failed")

    assert receipt is not None
    assert receipt["provider_requests"][0]["failure_diagnostic"] is None
    assert "untrusted" not in json.dumps(receipt)


def test_runtime_provider_failure_total_producer_bound_is_two_contexts_by_eight_requests() -> None:
    diagnostics = assistant_runtime._TurnTimingDiagnostics(clock=lambda: 1.0)
    executions = (("1" * 32, 61), ("2" * 32, 62))
    for execution_id, owner_id in executions:
        diagnostics.begin(execution_id, owner_id)
        for expected_ordinal in range(1, 9):
            ordinal = diagnostics.provider_started(execution_id, owner_id)
            assert ordinal == expected_ordinal
            diagnostics.provider_failed(
                execution_id,
                owner_id,
                ordinal,
                "upstream_stream",
                "provider_upstream_unavailable",
                503,
            )
            diagnostics.provider_finished(
                execution_id, owner_id, ordinal, "failed", "safe_protocol_error"
            )
    assert len(diagnostics._contexts) == 2
    assert diagnostics.begin("3" * 32, 63) is None

    receipts = [
        diagnostics.finish(execution_id, owner_id, "failed")
        for execution_id, owner_id in executions
    ]

    assert all(receipt is not None for receipt in receipts)
    assert (
        sum(
            sum(row["failure_diagnostic"] is not None for row in receipt["provider_requests"])
            for receipt in receipts
            if receipt is not None
        )
        == 16
    )


def test_workspace_summary_timing_requires_exact_completed_tool() -> None:
    recorder = _TimingRecorder()
    assistant_api._record_completed_workspace_summary_timing(
        recorder, EXECUTION_ID, 4, tool_name="workspace.summary", completed=False
    )
    assistant_api._record_completed_workspace_summary_timing(
        recorder, EXECUTION_ID, 4, tool_name="other", completed=True
    )
    assert recorder.events == []

    assistant_api._record_completed_workspace_summary_timing(
        recorder, EXECUTION_ID, 4, tool_name="workspace.summary", completed=True
    )
    assert recorder.events == [("workspace", EXECUTION_ID, 4)]
