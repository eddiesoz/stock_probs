"""Run deterministic native-host M06/M09 performance checks and retain row-level evidence."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import http.client
import json
import math
import os
import platform
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stock_probs.repository import Repository

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "M06"
SCHEMA_VERSION = 1
WARMUP_COUNT = 5
MEASURED_COUNT = 30
HISTORY_ROWS = 100_000
HISTORY_SEED_ROWS = HISTORY_ROWS - 1 - WARMUP_COUNT - MEASURED_COUNT
RSS_LIMIT_BYTES = 500 * 1024 * 1024
FORECAST_P95_LIMIT_MS = 1_000.0
HISTORY_P95_LIMIT_MS = 250.0
READINESS_LIMIT_MS = 20_000.0
IDLE_CPU_LIMIT_CORE_PERCENT = 1.0
STATIC_LIMIT_BYTES = 96 * 1024
RESPONSE_LIMIT_BYTES = 8 * 1024
NEWS_RESPONSE_LIMIT_BYTES = 32 * 1024
NEWS_ENDPOINT_P95_LIMIT_MS = 100.0
THEME_ACTION_P95_LIMIT_MS = 100.0
NEWS_RENDER_P95_LIMIT_MS = 250.0
NEWS_PROVIDER_DEADLINE_SECONDS = 10.0
CONCURRENCY_P95_LIMIT_MS = 3_000.0
CONCURRENCY_BATCH_LIMIT_MS = 5_000.0
PACKAGE_LIMIT_BYTES = 131_072
PACKAGE_BUILD_LIMIT_MS = 5_000.0
BACKUP_LIMIT_MS = 5_000.0
RESTORE_LIMIT_MS = 5_000.0
M06_REQUIRED_ROWS = {
    "runtime-isolation",
    "sample-protocol",
    "process-rss",
    "fixture-cache-hit-forecast",
    "indexed-100k-history-query",
    "idle-cpu",
    "concurrency-elapsed",
    "readiness",
    "package-size-build-time",
    "backup-restore-duration",
    "static-and-response-bytes",
    "browser-budgets",
    "arm64-performance-limitation",
}
M09_REQUIRED_ROWS = M06_REQUIRED_ROWS | {
    "theme-action-to-painted-theme",
    "news-cache-hit-endpoint",
    "ten-item-news-render",
    "news-response-bytes",
    "provider-deadline",
}
ALL_ROWS = M09_REQUIRED_ROWS
REQUIRED_FIELDS = {
    "schema_version",
    "task_id",
    "row",
    "fixture_identity",
    "isolation",
    "environment",
    "revision",
    "utc",
    "command",
    "warmups",
    "measured_samples",
    "statistics",
    "raw",
    "threshold",
    "result",
    "limitation",
    "artifact",
    "reviewer",
}
RESULTS = {"Pass", "Fail", "Skipped", "Unavailable"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def percentile(values: Iterable[float], fraction: float) -> float:
    """Use a pinned nearest-rank percentile so artifacts are reproducible across tools."""

    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("percentile requires at least one sample")
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def statistics_for(values: list[float], unit: str) -> dict[str, Any]:
    if not values:
        return {"p50": None, "p95": None, "max": None, "unit": unit}
    return {
        "p50": round(percentile(values, 0.50), 3),
        "p95": round(percentile(values, 0.95), 3),
        "max": round(max(values), 3),
        "unit": unit,
    }


def idle_cpu_statistics(values: list[float]) -> dict[str, Any]:
    """Keep idle summaries exactly derivable from the JSON-serialized sample values."""

    return {
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "max": max(values),
        "mean": sum(values) / len(values),
        "unit": "core-percent",
    }


def strict_threshold(value: float, operator: str, bound: float) -> bool:
    if not math.isfinite(value) or not math.isfinite(bound):
        return False
    if operator == "<":
        return value < bound
    if operator == "<=":
        return value <= bound
    raise ValueError(f"unsupported threshold operator: {operator}")


def named_reviewer(value: object) -> bool:
    """Reject empty and workflow-placeholder reviewer labels at acceptance boundaries."""

    if not isinstance(value, str) or len(value.strip()) < 3:
        return False
    normalized = value.strip().upper().replace("-", "_").replace(" ", "_")
    placeholders = {"PENDING", "PLACEHOLDER", "TODO", "TBD", "UNKNOWN", "UNAVAILABLE", "N/A"}
    return not any(token in normalized for token in placeholders)


def acceptance_precondition_errors(profile: str, dirty: bool, reviewer: object) -> list[str]:
    errors = []
    if not named_reviewer(reviewer):
        errors.append("PERFORMANCE_REVIEWER is missing or is a placeholder")
    if profile == "release" and dirty:
        errors.append("release performance requires a clean committed working tree")
    return errors


def required_rows(profile: str) -> set[str]:
    return M09_REQUIRED_ROWS if profile in {"m09", "release"} else M06_REQUIRED_ROWS


def validate_artifact(payload: dict[str, Any], *, acceptance: bool = False) -> None:
    missing = REQUIRED_FIELDS - set(payload)
    if missing:
        raise ValueError(f"artifact is missing required fields: {sorted(missing)}")
    task_id = payload["task_id"]
    if payload["schema_version"] != SCHEMA_VERSION or not isinstance(task_id, str):
        raise ValueError("artifact schema/task identity is invalid")
    if re.fullmatch(
        r"(?:M0[0-9]|EXP-M0[0-9]|R-M0[0-9]-[1-9][0-9]*|m0[1-9]|check|release)",
        task_id,
    ) is None:
        raise ValueError("artifact schema/task identity is invalid")
    if payload["row"] not in ALL_ROWS or payload["result"] not in RESULTS:
        raise ValueError("artifact row/result is invalid")
    if not isinstance(payload["command"], list) or not payload["command"]:
        raise ValueError("artifact command must be a non-empty argv list")
    if not isinstance(payload["utc"], dict) or not {"start", "end"} <= set(payload["utc"]):
        raise ValueError("artifact must contain UTC start/end")
    if not isinstance(payload["raw"], dict) or not isinstance(payload["reviewer"], str):
        raise ValueError("artifact raw values and reviewer are required")
    warmups = payload["warmups"]
    measured = payload["measured_samples"]
    if (
        not isinstance(warmups, dict)
        or type(warmups.get("count")) is not int
        or warmups["count"] < 0
        or "raw" not in warmups
        and "raw_ms" not in warmups
    ):
        raise ValueError("artifact warmup metrics are missing or invalid")
    if (
        not isinstance(measured, dict)
        or type(measured.get("count")) is not int
        or measured["count"] < 0
        or "raw" not in measured
    ):
        raise ValueError("artifact measured metrics are missing or invalid")
    row = payload["row"]
    if payload["result"] == "Pass" and row in {
        "fixture-cache-hit-forecast",
        "indexed-100k-history-query",
        "theme-action-to-painted-theme",
        "news-cache-hit-endpoint",
        "ten-item-news-render",
        "news-response-bytes",
    } and (
        warmups["count"] < WARMUP_COUNT or measured["count"] < MEASURED_COUNT
    ):
        raise ValueError("designated request workload has too few warmups or samples")
    if row in {
        "theme-action-to-painted-theme",
        "news-cache-hit-endpoint",
        "ten-item-news-render",
        "news-response-bytes",
        "provider-deadline",
    }:
        samples = measured["raw"]
        threshold = payload["threshold"]
        if payload["result"] == "Pass" and (
            not isinstance(samples, list) or len(samples) != measured["count"] or not samples
        ):
            raise ValueError("M09 performance samples are missing or inconsistent")
        if (
            not isinstance(threshold, dict)
            or threshold.get("operator") not in {"<", "<="}
            or not isinstance(threshold.get("value"), int | float)
        ):
            raise ValueError("M09 performance threshold bound is missing or invalid")
    if row == "browser-budgets" and (
        warmups["count"] < WARMUP_COUNT or measured["count"] < MEASURED_COUNT
    ):
        raise ValueError("browser workload has too few warmups or samples")
    if row == "idle-cpu" and payload["raw"].get("duration_seconds", 0) < 60:
        raise ValueError("idle CPU workload is shorter than 60 seconds")
    if row == "idle-cpu":
        values = measured["raw"]
        if not isinstance(values, list) or not values:
            raise ValueError("idle CPU samples are missing or invalid")
        if payload["statistics"] != idle_cpu_statistics(values):
            raise ValueError("idle CPU statistics do not exactly match serialized samples")
    if (
        acceptance
        and payload["row"] != "arm64-performance-limitation"
        and payload["result"] != "Pass"
    ):
        raise ValueError(f"acceptance row {payload['row']} did not pass")
    if acceptance and not named_reviewer(payload["reviewer"]):
        raise ValueError("acceptance artifact requires a non-placeholder named reviewer")


def sample_result(values: list[float], bound: float, operator: str, minimum: int) -> str:
    """Fail closed when samples are missing before evaluating the numerical threshold."""

    if len(values) < minimum or any(not math.isfinite(value) or value < 0 for value in values):
        return "Fail"
    return "Pass" if strict_threshold(percentile(values, 0.95), operator, bound) else "Fail"


def _git_revision() -> tuple[str, bool]:
    git = shutil.which("git")
    if git is None:
        return "unavailable", True
    revision = subprocess.run(  # noqa: S603
        [git, "-C", str(ROOT), "rev-parse", "--verify", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(  # noqa: S603
            [git, "-C", str(ROOT), "status", "--porcelain=v1", "--untracked-files=normal"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    return revision, dirty


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _request(
    port: int,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 5.0,
) -> tuple[float, int, bytes]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    headers = (
        {}
        if body is None
        else {"Content-Type": "application/json", "Content-Length": str(len(body))}
    )
    started = time.perf_counter()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        content = response.read()
        status = response.status
    finally:
        connection.close()
    return (time.perf_counter() - started) * 1_000, status, content


def _poll_readiness(
    port: int, process: subprocess.Popen[bytes], process_started: float
) -> tuple[float, bytes, dict[str, Any]]:
    attempt_count = 0
    startup_refusal_count = 0
    not_ready_response_count = 0
    unexpected_errors: list[dict[str, Any]] = []
    deadline = process_started + READINESS_LIMIT_MS / 1_000
    while time.perf_counter() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"application exited before readiness ({process.returncode})")
        attempt_count += 1
        try:
            request_ms, status, body = _request(port, "GET", "/api/v1/readiness", timeout=1)
            if status == 503:
                not_ready_response_count += 1
            elif status != 200:
                raise ValueError(f"readiness returned HTTP {status}")
            elif json.loads(body)["status"] == "ready":
                success_utc = utc_now()
                total_ms = (time.perf_counter() - process_started) * 1_000
                return total_ms, body, {
                    "attempt_count": attempt_count,
                    "startup_refusal_count": startup_refusal_count,
                    "not_ready_response_count": not_ready_response_count,
                    "success": {
                        "attempt": attempt_count,
                        "utc": success_utc,
                        "request_elapsed_ms": round(request_ms, 3),
                        "status": status,
                    },
                    "total_elapsed_ms": round(total_ms, 3),
                    "unexpected_errors": unexpected_errors,
                }
            else:
                raise ValueError("readiness returned 200 without ready status")
        except ConnectionRefusedError:
            # Refusal is the expected state until the bounded local server opens its socket.
            startup_refusal_count += 1
        except (OSError, TypeError, ValueError, KeyError) as exc:
            unexpected_errors.append(
                {
                    "attempt": attempt_count,
                    "utc": utc_now(),
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            )
        time.sleep(0.05)
    raise RuntimeError(
        "application did not become ready within 20 seconds "
        f"after {attempt_count} attempts ({startup_refusal_count} startup refusals, "
        f"{len(unexpected_errors)} unexpected errors)"
    )


def _process_status(pid: int) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith(("VmRSS:", "VmHWM:")):
            name, value, unit = line.split()
            if unit != "kB":
                raise RuntimeError(f"unexpected /proc memory unit: {unit}")
            values[name.rstrip(":")] = int(value) * 1024
    if set(values) != {"VmRSS", "VmHWM"}:
        raise RuntimeError("/proc did not expose RSS and high-water RSS")
    return values


def _cpu_seconds(pid: int) -> float:
    text = Path(f"/proc/{pid}/stat").read_text()
    fields = text[text.rfind(")") + 2 :].split()
    ticks = int(fields[11]) + int(fields[12])
    return ticks / int(os.sysconf("SC_CLK_TCK"))


def _seed_history(database: Path) -> dict[str, Any]:
    started = time.perf_counter()
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA recursive_triggers = ON")
        connection.execute("BEGIN IMMEDIATE")
        connection.executemany(
            """INSERT INTO search_events (
                request_id, submitted_symbol, normalized_symbol, asset_type, status,
                is_repeat, error_code, error_message, submitted_at, completed_at
            ) VALUES (?, 'FAIL', NULL, 'stock', 'failed', 0, 'fixture_failure',
                'Deterministic performance fixture failure.', ?, ?)""",
            (
                (
                    f"perf-history-{index:06d}",
                    f"2025-01-01T00:00:{index % 60:02d}.{index:06d}Z",
                    f"2025-01-01T00:00:{index % 60:02d}.{index:06d}Z",
                )
                for index in range(1, HISTORY_SEED_ROWS + 1)
            ),
        )
        connection.execute(
            """INSERT INTO history_facets (
                event_id, canonical_symbol, display_name, company_name, exchange, quote_type,
                model_name, model_version, forecast_contract_version, submitted_at_us
            )
            SELECT id, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
                   1735689600000000 + id
            FROM search_events"""
        )
        connection.commit()
        count = int(connection.execute("SELECT COUNT(*) FROM search_events").fetchone()[0])
    finally:
        connection.close()
    recipe = f"failed-events-v1:{HISTORY_SEED_ROWS}:fixture-now=2025-01-10T17:03:00Z"
    return {
        "name": "deterministic-100k-audit-ledger-v1",
        "seed_rows": count,
        "target_rows_after_forecast_protocol": HISTORY_ROWS,
        "recipe_sha256": hashlib.sha256(recipe.encode()).hexdigest(),
        "seed_elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
    }


class Harness:
    def __init__(self, artifact_dir: Path, idle_seconds: int, profile: str = "development") -> None:
        self.artifact_dir = artifact_dir.resolve()
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.idle_seconds = idle_seconds
        self.revision, self.dirty = _git_revision()
        self.architecture = platform.machine().lower()
        self.profile = profile
        self.task_id = os.getenv("STOCK_PROBS_TASK_ID", "M09" if profile == "m09" else TASK_ID)
        self.reviewer = os.getenv("PERFORMANCE_REVIEWER", "PENDING_INDEPENDENT_REVIEW")
        self.command = [sys.executable, "scripts/performance_harness.py", "--profile", profile]
        self.rows: dict[str, dict[str, Any]] = {}
        self.fixture: dict[str, Any] = {"name": "not-initialized"}
        self.isolation: dict[str, Any] = {}
        self.rss_samples: list[dict[str, Any]] = []

    def write_row(
        self,
        row: str,
        *,
        started: str,
        warmups: dict[str, Any],
        measured: dict[str, Any],
        statistics: dict[str, Any],
        raw: dict[str, Any],
        threshold: dict[str, Any],
        result: str,
        limitation: str | None = None,
        fixture: dict[str, Any] | None = None,
        isolation: dict[str, Any] | None = None,
        command: list[str] | None = None,
    ) -> dict[str, Any]:
        artifact_name = f"{row}.json"
        payload = {
            "schema_version": SCHEMA_VERSION,
            "task_id": self.task_id,
            "row": row,
            "fixture_identity": fixture or self.fixture,
            "isolation": isolation or self.isolation,
            "environment": {
                "architecture": self.architecture,
                "execution": f"native {self.architecture}",
                "platform": platform.platform(),
                "python": platform.python_version(),
            },
            "revision": {"commit": self.revision, "dirty": self.dirty},
            "utc": {"start": started, "end": utc_now()},
            "command": command or self.command,
            "warmups": warmups,
            "measured_samples": measured,
            "statistics": statistics,
            "raw": raw,
            "threshold": threshold,
            "result": result,
            "limitation": limitation,
            "artifact": artifact_name,
            "reviewer": self.reviewer,
        }
        validate_artifact(payload)
        (self.artifact_dir / artifact_name).write_text(json.dumps(payload, indent=2) + "\n")
        self.rows[row] = payload
        return payload

    def sample_rss(self, pid: int, label: str) -> dict[str, int]:
        status = _process_status(pid)
        self.rss_samples.append({"utc": utc_now(), "label": label, **status})
        return status

    def _measure_requests(
        self,
        count: int,
        request: Callable[[], tuple[float, int, bytes]],
        expected_status: int,
        pid: int,
        label: str,
    ) -> tuple[list[float], list[dict[str, Any]]]:
        timings: list[float] = []
        responses: list[dict[str, Any]] = []
        for index in range(count):
            elapsed, status, body = request()
            timings.append(elapsed)
            responses.append({"sample": index + 1, "status": status, "bytes": len(body)})
            self.sample_rss(pid, label)
        if any(item["status"] != expected_status for item in responses):
            raise RuntimeError(f"{label} returned an unexpected status")
        return timings, responses

    def run_native(self) -> int:
        if self.architecture not in {"x86_64", "amd64"}:
            started = utc_now()
            self.write_row(
                "runtime-isolation",
                started=started,
                warmups={"count": 0, "excluded": True, "raw": []},
                measured={"count": 0, "unit": "not-run", "raw": []},
                statistics=statistics_for([], "not-run"),
                raw={"observed_architecture": self.architecture},
                threshold={"class": "existing platform requirement", "target": "native x86_64"},
                result="Unavailable",
                limitation="Mandatory M06 x86 performance runs only on a native x86_64 host.",
            )
            return self.finish()

        with tempfile.TemporaryDirectory(prefix="stock-probs-m06-performance-") as temporary:
            temp = Path(temporary)
            runtime = temp / "runtime"
            runtime.mkdir()
            database = runtime / "stock_probs.sqlite3"
            Repository(database).migrate()
            self.fixture = _seed_history(database)
            port = _free_port()
            log_path = self.artifact_dir / "application.log"
            environment = os.environ.copy()
            environment.update(
                {
                    "STOCK_PROBS_DATA_DIR": str(runtime),
                    "STOCK_PROBS_PROVIDER": "fixture",
                    "STOCK_PROBS_FIXTURE_NOW": "2025-01-10T17:03:00+00:00",
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            process_command = [
                sys.executable,
                "-m",
                "stock_probs.cli",
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ]
            process_started_utc = utc_now()
            process_started = time.perf_counter()
            with log_path.open("wb") as log:
                process = subprocess.Popen(  # noqa: S603
                    process_command,
                    cwd=ROOT,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                self.isolation = {
                    "host": "127.0.0.1",
                    "port": port,
                    "temp_dir": str(temp),
                    "runtime_dir": str(runtime),
                    "process_pid": process.pid,
                    "process_tree": [process.pid],
                    "process_scope": "single uvicorn application process; no workers or children",
                    "cleanup": "registered",
                }
                try:
                    readiness_ms, readiness_body, readiness_attempts = _poll_readiness(
                        port, process, process_started
                    )
                    readiness_passed = (
                        not readiness_attempts["unexpected_errors"]
                        and strict_threshold(readiness_ms, "<=", READINESS_LIMIT_MS)
                    )
                    self.sample_rss(process.pid, "readiness")
                    self.write_row(
                        "readiness",
                        started=process_started_utc,
                        warmups={"count": 0, "excluded": True, "raw": []},
                        measured={"count": 1, "unit": "ms", "raw": [round(readiness_ms, 3)]},
                        statistics=statistics_for([readiness_ms], "ms"),
                        raw={
                            "attempts": readiness_attempts,
                            "readiness_path": "/api/v1/readiness",
                            "hidden_retries": False,
                        },
                        threshold={
                            "class": "proposed numeric threshold",
                            "operator": "<=",
                            "value": READINESS_LIMIT_MS,
                            "unit": "ms",
                        },
                        result="Pass" if readiness_passed else "Fail",
                        limitation=(
                            None
                            if not readiness_attempts["unexpected_errors"]
                            else "Unexpected readiness polling errors were recorded before success."
                        ),
                        command=process_command,
                    )

                    forecast_request = lambda: _request(  # noqa: E731
                        port,
                        "POST",
                        "/api/v1/forecasts",
                        {"symbol": "ACDC", "asset_type": "stock"},
                    )
                    prime_elapsed, prime_status, prime_body = forecast_request()
                    if prime_status != 201 or json.loads(prime_body).get("repeated"):
                        raise RuntimeError(
                            "forecast cache prime did not create the expected first run"
                        )
                    forecast_started = utc_now()
                    forecast_warmups, warmup_responses = self._measure_requests(
                        WARMUP_COUNT, forecast_request, 201, process.pid, "forecast-warmup"
                    )
                    forecast_samples, forecast_responses = self._measure_requests(
                        MEASURED_COUNT, forecast_request, 201, process.pid, "forecast-measured"
                    )
                    stats = statistics_for(forecast_samples, "ms")
                    self.write_row(
                        "fixture-cache-hit-forecast",
                        started=forecast_started,
                        warmups={
                            "count": len(forecast_warmups),
                            "excluded": True,
                            "raw_ms": [round(value, 3) for value in forecast_warmups],
                        },
                        measured={
                            "count": len(forecast_samples),
                            "unit": "ms",
                            "raw": [round(value, 3) for value in forecast_samples],
                        },
                        statistics=stats,
                        raw={
                            "route": "POST /api/v1/forecasts",
                            "input": {"symbol": "ACDC", "asset_type": "stock"},
                            "cache_condition": (
                                "prime created one run; all warmups and samples reused it"
                            ),
                            "prime": {
                                "elapsed_ms": round(prime_elapsed, 3),
                                "status": prime_status,
                                "bytes": len(prime_body),
                            },
                            "warmup_responses": warmup_responses,
                            "measured_responses": forecast_responses,
                        },
                        threshold={
                            "class": "existing numeric threshold",
                            "operator": "<",
                            "value": FORECAST_P95_LIMIT_MS,
                            "unit": "ms",
                        },
                        result=sample_result(
                            forecast_samples, FORECAST_P95_LIMIT_MS, "<", MEASURED_COUNT
                        ),
                    )

                    if self.profile in {"m09", "release"}:
                        self._measure_news(port, process.pid)

                    history_started = utc_now()
                    connection = sqlite3.connect(database)
                    try:
                        count = int(
                            connection.execute("SELECT COUNT(*) FROM search_events").fetchone()[0]
                        )
                        plan = [
                            str(row[3])
                            for row in connection.execute(
                                """EXPLAIN QUERY PLAN
                                SELECT event.id FROM search_events AS event
                                LEFT JOIN history_facets AS facet ON facet.event_id = event.id
                                WHERE event.request_id = ?
                                ORDER BY facet.submitted_at_us DESC, event.id DESC LIMIT 20""",
                                ("perf-history-050000",),
                            )
                        ]
                        indexes = [
                            {"name": row[0], "sql": row[1]}
                            for row in connection.execute(
                                "SELECT name, sql FROM sqlite_master "
                                "WHERE type = 'index' ORDER BY name"
                            )
                        ]
                        schema_versions = [
                            int(row[0])
                            for row in connection.execute(
                                "SELECT version FROM schema_migrations ORDER BY version"
                            )
                        ]
                    finally:
                        connection.close()
                    indexed = any(
                        "SEARCH event USING" in step and "INDEX" in step for step in plan
                    )
                    history_request = lambda: _request(  # noqa: E731
                        port, "GET", "/api/v1/history?request_id=perf-history-050000&page_size=20"
                    )
                    history_warmups, history_warmup_responses = self._measure_requests(
                        WARMUP_COUNT, history_request, 200, process.pid, "history-warmup"
                    )
                    history_samples, history_responses = self._measure_requests(
                        MEASURED_COUNT, history_request, 200, process.pid, "history-measured"
                    )
                    history_result = sample_result(
                        history_samples, HISTORY_P95_LIMIT_MS, "<", MEASURED_COUNT
                    )
                    if count != HISTORY_ROWS or not indexed or len(history_samples) < 10:
                        history_result = "Fail"
                    self.write_row(
                        "indexed-100k-history-query",
                        started=history_started,
                        warmups={
                            "count": len(history_warmups),
                            "excluded": True,
                            "raw_ms": [round(value, 3) for value in history_warmups],
                        },
                        measured={
                            "count": len(history_samples),
                            "unit": "ms",
                            "raw": [round(value, 3) for value in history_samples],
                        },
                        statistics=statistics_for(history_samples, "ms"),
                        raw={
                            "route": "GET /api/v1/history",
                            "query": "request_id=perf-history-050000&page_size=20",
                            "exact_row_count": count,
                            "minimum_repetitions": 10,
                            "query_plan": plan,
                            "indexed_plan": indexed,
                            "indexes": indexes,
                            "schema_versions": schema_versions,
                            "warmup_responses": history_warmup_responses,
                            "measured_responses": history_responses,
                        },
                        threshold={
                            "class": "existing numeric threshold",
                            "operator": "<",
                            "value": HISTORY_P95_LIMIT_MS,
                            "unit": "ms",
                        },
                        result=history_result,
                    )

                    concurrency_started = utc_now()
                    concurrency_raw: dict[str, Any] = {}
                    all_concurrency_samples: list[float] = []
                    all_concurrency_warmups: list[float] = []
                    concurrency_errors = 0
                    for level in (1, 4, 8):
                        warmups, warmup_responses = self._measure_requests(
                            WARMUP_COUNT,
                            forecast_request,
                            201,
                            process.pid,
                            f"concurrency-{level}-warmup",
                        )
                        sample_count = max(
                            MEASURED_COUNT, math.ceil(MEASURED_COUNT / level) * level
                        )
                        batch_started = time.perf_counter()
                        with concurrent.futures.ThreadPoolExecutor(max_workers=level) as executor:
                            futures = [
                                executor.submit(forecast_request) for _ in range(sample_count)
                            ]
                            responses = [future.result() for future in futures]
                        batch_ms = (time.perf_counter() - batch_started) * 1_000
                        samples = [item[0] for item in responses]
                        errors = sum(item[1] != 201 for item in responses)
                        concurrency_errors += errors
                        all_concurrency_warmups.extend(warmups)
                        all_concurrency_samples.extend(samples)
                        self.sample_rss(process.pid, f"concurrency-{level}-complete")
                        concurrency_raw[str(level)] = {
                            "declared_concurrency": level,
                            "warmup_count": len(warmups),
                            "warmup_responses": warmup_responses,
                            "measured_count": len(samples),
                            "elapsed_ms": [round(value, 3) for value in samples],
                            "batch_wall_ms": round(batch_ms, 3),
                            "statistics": statistics_for(samples, "ms"),
                            "errors": errors,
                        }
                    valid_counts = all(
                        item["warmup_count"] >= WARMUP_COUNT
                        and item["measured_count"] >= MEASURED_COUNT
                        for item in concurrency_raw.values()
                    )
                    concurrency_passed = valid_counts and concurrency_errors == 0 and all(
                        strict_threshold(
                            item["statistics"]["p95"], "<=", CONCURRENCY_P95_LIMIT_MS
                        )
                        and strict_threshold(
                            item["batch_wall_ms"], "<=", CONCURRENCY_BATCH_LIMIT_MS
                        )
                        for item in concurrency_raw.values()
                    )
                    self.write_row(
                        "concurrency-elapsed",
                        started=concurrency_started,
                        warmups={
                            "count": len(all_concurrency_warmups),
                            "excluded": True,
                            "raw_ms": [round(value, 3) for value in all_concurrency_warmups],
                            "per_level": WARMUP_COUNT,
                        },
                        measured={
                            "count": len(all_concurrency_samples),
                            "unit": "ms",
                            "raw": [round(value, 3) for value in all_concurrency_samples],
                            "per_level_minimum": MEASURED_COUNT,
                        },
                        statistics=statistics_for(all_concurrency_samples, "ms"),
                        raw={"levels": concurrency_raw, "errors": concurrency_errors},
                        threshold={
                            "class": "proposed numeric thresholds",
                            "per_level_p95": {
                                "operator": "<=",
                                "value": CONCURRENCY_P95_LIMIT_MS,
                                "unit": "ms",
                            },
                            "per_level_batch": {
                                "operator": "<=",
                                "value": CONCURRENCY_BATCH_LIMIT_MS,
                                "unit": "ms",
                            },
                            "evidence_basis": (
                                "Bounded 30-request fixture bursts at levels 1, 4, and 8 retain "
                                "per-request and wall-clock proof for low-resource local operation."
                            ),
                        },
                        result="Pass" if concurrency_passed else "Fail",
                    )

                    browser_artifact = self.artifact_dir / "browser-budgets.json"
                    performance_config = self.artifact_dir / "playwright.performance.config.js"
                    performance_config.write_text(
                        "const base = require("
                        + json.dumps(str(ROOT / "tools/browser/playwright.config.js"))
                        + ");\nmodule.exports = { ...base, testDir: "
                        + json.dumps(str(ROOT / "tools/browser/tests"))
                        + ", webServer: undefined };\n"
                    )
                    browser_command = [
                        str(ROOT / ".tools/node/bin/npx"),
                        "--prefix",
                        str(ROOT / "tools/browser"),
                        "playwright",
                        "test",
                        "--config",
                        str(performance_config),
                        str(ROOT / "tools/browser/tests/performance.spec.js"),
                        "--project=desktop-chromium",
                    ]
                    browser_env = os.environ.copy()
                    browser_env.update(
                        {
                            "PATH": f"{ROOT / '.tools/node/bin'}:{browser_env.get('PATH', '')}",
                            "STOCK_PROBS_PERFORMANCE": "1",
                            "STOCK_PROBS_PERFORMANCE_M09": str(
                                self.profile in {"m09", "release"}
                            ).lower(),
                            "STOCK_PROBS_PERFORMANCE_ARTIFACT": str(browser_artifact),
                            "STOCK_PROBS_TASK_ID": self.task_id,
                            "PERFORMANCE_REVIEWER": self.reviewer,
                            "STOCK_PROBS_REVISION": self.revision,
                            "STOCK_PROBS_WORKING_TREE_DIRTY": str(self.dirty).lower(),
                            "STOCK_PROBS_PERFORMANCE_CONFIG": str(performance_config),
                            "STOCK_PROBS_BROWSER_ARTIFACT_DIR": str(
                                self.artifact_dir / "browser-playwright"
                            ),
                        }
                    )
                    completed = subprocess.run(  # noqa: S603
                        browser_command,
                        cwd=ROOT,
                        env=browser_env,
                        check=False,
                        text=True,
                        capture_output=True,
                    )
                    (self.artifact_dir / "browser-command.log").write_text(
                        completed.stdout + completed.stderr
                    )
                    if not browser_artifact.is_file():
                        self.write_row(
                            "browser-budgets",
                            started=utc_now(),
                            warmups={"count": 0, "excluded": True, "raw": []},
                            measured={"count": 0, "unit": "ms", "raw": []},
                            statistics=statistics_for([], "ms"),
                            raw={"exit_code": completed.returncode},
                            threshold={"class": "proposed browser budgets"},
                            result="Fail",
                            limitation="Browser runner did not produce its required artifact.",
                            command=browser_command,
                        )
                    else:
                        browser_payload = json.loads(browser_artifact.read_text())
                        validate_artifact(browser_payload)
                        if completed.returncode != 0:
                            browser_payload["result"] = "Fail"
                            browser_payload["limitation"] = (
                                browser_payload.get("limitation")
                                or f"Playwright exited with status {completed.returncode}."
                            )
                            browser_artifact.write_text(
                                json.dumps(browser_payload, indent=2) + "\n"
                            )
                        self.rows["browser-budgets"] = browser_payload

                    if self.profile in {"m09", "release"}:
                        self._write_m09_browser_rows(
                            self.rows["browser-budgets"],
                            completed,
                        )

                    idle_started = utc_now()
                    cpu_samples: list[dict[str, float]] = []
                    wall_start = time.monotonic()
                    cpu_start = _cpu_seconds(process.pid)
                    previous_wall = wall_start
                    previous_cpu = cpu_start
                    while time.monotonic() - wall_start < self.idle_seconds:
                        remaining = self.idle_seconds - (time.monotonic() - wall_start)
                        time.sleep(min(1.0, max(0.0, remaining)))
                        current_wall = time.monotonic()
                        current_cpu = _cpu_seconds(process.pid)
                        interval_percent = (current_cpu - previous_cpu) / (
                            current_wall - previous_wall
                        ) * 100
                        cpu_samples.append(
                            {
                                "wall_seconds": round(current_wall - wall_start, 3),
                                "cpu_seconds": round(current_cpu - cpu_start, 6),
                                "interval_core_percent": interval_percent,
                            }
                        )
                        previous_wall, previous_cpu = current_wall, current_cpu
                        self.sample_rss(process.pid, "idle")
                    elapsed_idle = time.monotonic() - wall_start
                    cpu_end = _cpu_seconds(process.pid)
                    cpu_values = [item["interval_core_percent"] for item in cpu_samples]
                    idle_statistics = idle_cpu_statistics(cpu_values)
                    idle_result = (
                        "Pass"
                        if elapsed_idle >= 60.0
                        and cpu_samples
                        and strict_threshold(
                            idle_statistics["mean"], "<=", IDLE_CPU_LIMIT_CORE_PERCENT
                        )
                        else "Fail"
                    )
                    self.write_row(
                        "idle-cpu",
                        started=idle_started,
                        warmups={"count": 0, "excluded": True, "raw": []},
                        measured={
                            "count": len(cpu_samples),
                            "unit": "core-percent",
                            "raw": cpu_values,
                        },
                        statistics=idle_statistics,
                        raw={
                            "duration_seconds": round(elapsed_idle, 3),
                            "sampling_interval_seconds": 1.0,
                            "cpu_time_start_seconds": round(cpu_start, 6),
                            "cpu_time_end_seconds": round(cpu_end, 6),
                            "samples": cpu_samples,
                            "sample_value_precision": "IEEE-754 binary64 JSON round-trip",
                            "normalization": "process CPU seconds / wall seconds * 100; one core",
                            "process_scope": "application PID only; no child processes observed",
                        },
                        threshold={
                            "class": "proposed numeric threshold",
                            "operator": "<=",
                            "value": IDLE_CPU_LIMIT_CORE_PERCENT,
                            "unit": "mean core-percent over >=60 seconds",
                        },
                        result=idle_result,
                        limitation=(
                            None
                            if elapsed_idle >= 60.0
                            else "Idle sample was shorter than 60 seconds."
                        ),
                    )
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                    self.isolation["cleanup"] = "application process terminated"

            self._write_rss_row()
            self._write_protocol_row()
            self._write_static_row(readiness_body)
            if self.profile in {"m09", "release"}:
                self._write_provider_deadline_row()
            self._write_package_row(temp)
            self._write_backup_row(runtime)
            self.write_row(
                "runtime-isolation",
                started=process_started_utc,
                warmups={"count": 0, "excluded": True, "raw": []},
                measured={"count": 1, "unit": "process", "raw": [process.pid]},
                statistics={"p50": None, "p95": None, "max": None, "unit": "not-applicable"},
                raw={
                    "fixture_provider": "checked-in compact fixture",
                    "fixture_now": "2025-01-10T17:03:00+00:00",
                    "process_exit_code": process.returncode,
                    "port_isolated": True,
                    "runtime_isolated": True,
                    "cleanup": self.isolation["cleanup"],
                },
                threshold={"class": "proposed protocol", "requirement": "fresh isolated runtime"},
                result="Pass" if process.returncode in {0, -15} else "Fail",
                command=process_command,
            )

        self.isolation["cleanup"] = "application process terminated; temporary directory removed"
        for payload in self.rows.values():
            if payload["isolation"].get("process_pid") != self.isolation.get("process_pid"):
                continue
            payload["isolation"]["cleanup"] = self.isolation["cleanup"]
            (self.artifact_dir / payload["artifact"]).write_text(
                json.dumps(payload, indent=2) + "\n"
            )
        self._write_arm_row()
        return self.finish()

    def _write_m09_browser_rows(
        self,
        browser_payload: dict[str, Any],
        completed: subprocess.CompletedProcess[str],
    ) -> None:
        raw = browser_payload.get("raw", {}).get("m09_browser") or {}
        started = raw.get("startedUtc", browser_payload["utc"]["start"])
        for row, warmup_key, sample_key, limit in (
            (
                "theme-action-to-painted-theme",
                "themeWarmups",
                "themeSamples",
                THEME_ACTION_P95_LIMIT_MS,
            ),
            ("ten-item-news-render", "renderWarmups", "renderSamples", NEWS_RENDER_P95_LIMIT_MS),
        ):
            warmups = [float(value) for value in raw.get(warmup_key, [])]
            samples = [float(value) for value in raw.get(sample_key, [])]
            valid_items = row != "ten-item-news-render" or (
                len(raw.get("itemCounts", [])) >= MEASURED_COUNT
                and all(count == 10 for count in raw["itemCounts"])
            )
            result = sample_result(samples, limit, "<=", MEASURED_COUNT)
            if (
                completed.returncode != 0
                or browser_payload.get("result") != "Pass"
                or not valid_items
            ):
                result = "Fail"
            self.write_row(
                row,
                started=started,
                warmups={
                    "count": len(warmups),
                    "excluded": True,
                    "raw_ms": [round(value, 3) for value in warmups],
                },
                measured={
                    "count": len(samples),
                    "unit": "ms",
                    "raw": [round(value, 3) for value in samples],
                },
                statistics=statistics_for(samples, "ms"),
                raw={
                    "browser": "pinned Playwright Chromium",
                    "action": (
                        "actual theme control action through two animation frames"
                        if row == "theme-action-to-painted-theme"
                        else (
                            "ten validated news items from responseEnd through two animation frames"
                        )
                    ),
                    "item_counts": raw.get("itemCounts", []) if "news" in row else None,
                    "exit_code": completed.returncode,
                    "stdout": completed.stdout[-4_096:],
                    "stderr": completed.stderr[-4_096:],
                },
                threshold={
                    "class": "M09 numeric threshold",
                    "operator": "<=",
                    "value": limit,
                    "unit": "ms p95",
                },
                result=result,
                limitation=(
                    None
                    if result == "Pass"
                    else "Browser samples, painted state, or ten-item validation failed."
                ),
                fixture={
                    "name": (
                        "deterministic ten-item browser response"
                        if "news" in row
                        else "dashboard theme control"
                    ),
                    "symbol": "ACDC",
                    "news_items_required": 10 if "news" in row else None,
                },
                isolation=browser_payload["isolation"],
                command=completed.args,
            )

    def _measure_news(self, port: int, pid: int) -> None:
        started = utc_now()
        request = lambda: _request(  # noqa: E731
            port, "GET", "/api/v1/news?symbol=ACDC&limit=10"
        )
        prime_ms, prime_status, prime_body = request()
        if prime_status != 200:
            raise RuntimeError(f"news cache prime returned HTTP {prime_status}")
        warmups, warmup_responses = self._measure_requests(
            WARMUP_COUNT, request, 200, pid, "news-warmup"
        )
        samples, responses = self._measure_requests(
            MEASURED_COUNT, request, 200, pid, "news-measured"
        )
        decoded = [
            json.loads(_request(port, "GET", "/api/v1/news?symbol=ACDC&limit=10")[2])
        ]
        cache_states = [
            json.loads(body).get("cache_state") for _, _, body in [request() for _ in range(2)]
        ]
        endpoint_result = sample_result(
            samples, NEWS_ENDPOINT_P95_LIMIT_MS, "<=", MEASURED_COUNT
        )
        if any(state != "hit" for state in cache_states):
            endpoint_result = "Fail"
        common_raw = {
            "route": "GET /api/v1/news",
            "query": "symbol=ACDC&limit=10",
            "cache_condition": "one prime request precedes all excluded warmups and samples",
            "prime": {
                "elapsed_ms": round(prime_ms, 3),
                "status": prime_status,
                "bytes": len(prime_body),
                "cache_state": json.loads(prime_body).get("cache_state"),
            },
            "verification_cache_states": cache_states,
            "decoded_item_count": len(decoded[0].get("items", [])),
            "warmup_responses": warmup_responses,
            "measured_responses": responses,
        }
        self.write_row(
            "news-cache-hit-endpoint",
            started=started,
            warmups={
                "count": len(warmups),
                "excluded": True,
                "raw_ms": [round(value, 3) for value in warmups],
            },
            measured={
                "count": len(samples),
                "unit": "ms",
                "raw": [round(value, 3) for value in samples],
            },
            statistics=statistics_for(samples, "ms"),
            raw=common_raw,
            threshold={
                "class": "M09 numeric threshold",
                "operator": "<=",
                "value": NEWS_ENDPOINT_P95_LIMIT_MS,
                "unit": "ms p95",
            },
            result=endpoint_result,
        )
        response_sizes = [float(item["bytes"]) for item in responses]
        self.write_row(
            "news-response-bytes",
            started=started,
            warmups={
                "count": len(warmup_responses),
                "excluded": True,
                "raw": [item["bytes"] for item in warmup_responses],
            },
            measured={
                "count": len(response_sizes),
                "unit": "bytes",
                "raw": response_sizes,
            },
            statistics=statistics_for(response_sizes, "bytes"),
            raw={**common_raw, "measurement": "decoded HTTP response-body bytes"},
            threshold={
                "class": "M09 numeric threshold",
                "operator": "<=",
                "value": NEWS_RESPONSE_LIMIT_BYTES,
                "unit": "bytes maximum",
            },
            result=(
                "Pass"
                if len(response_sizes) >= MEASURED_COUNT
                and all(
                    strict_threshold(value, "<=", NEWS_RESPONSE_LIMIT_BYTES)
                    for value in response_sizes
                )
                else "Fail"
            ),
        )

    def _write_rss_row(self) -> None:
        started = self.rows["readiness"]["utc"]["start"]
        values = [float(sample["VmRSS"]) for sample in self.rss_samples]
        peak = max(max(values), max(float(sample["VmHWM"]) for sample in self.rss_samples))
        self.write_row(
            "process-rss",
            started=started,
            warmups={"count": 0, "excluded": True, "raw": []},
            measured={"count": len(values), "unit": "bytes", "raw": values},
            statistics={
                **statistics_for(values, "bytes"),
                "high_water_max": peak,
            },
            raw={
                "samples": self.rss_samples,
                "measurement_method": "/proc/<pid>/status VmRSS and VmHWM",
                "process_scope": self.isolation["process_scope"],
            },
            threshold={
                "class": "existing numeric threshold",
                "operator": "<",
                "value": RSS_LIMIT_BYTES,
                "unit": "bytes",
            },
            result=("Pass" if values and strict_threshold(peak, "<", RSS_LIMIT_BYTES) else "Fail"),
        )

    def _write_protocol_row(self) -> None:
        workloads = {"fixture-cache-hit-forecast", "indexed-100k-history-query"}
        if self.profile in {"m09", "release"}:
            workloads |= {
                "theme-action-to-painted-theme",
                "news-cache-hit-endpoint",
                "ten-item-news-render",
                "news-response-bytes",
            }
        designated = {
            row: {
                "warmups": payload["warmups"].get("count", 0),
                "samples": payload["measured_samples"].get("count", 0),
            }
            for row, payload in self.rows.items()
            if row in workloads
        }
        passed = all(
            item["warmups"] >= WARMUP_COUNT and item["samples"] >= MEASURED_COUNT
            for item in designated.values()
        ) and set(designated) == workloads
        self.write_row(
            "sample-protocol",
            started=min(payload["utc"]["start"] for payload in self.rows.values()),
            warmups={
                "count": sum(item["warmups"] for item in designated.values()),
                "excluded": True,
                "raw": designated,
            },
            measured={
                "count": sum(item["samples"] for item in designated.values()),
                "unit": "requests",
                "raw": designated,
            },
            statistics={"p50": None, "p95": None, "max": None, "unit": "request-count"},
            raw={"designated_workloads": designated},
            threshold={
                "class": "proposed protocol",
                "minimum_warmups_per_workload": WARMUP_COUNT,
                "minimum_samples_per_workload": MEASURED_COUNT,
            },
            result="Pass" if passed else "Fail",
        )

    def _write_static_row(self, readiness_body: bytes) -> None:
        started = utc_now()
        static_root = ROOT / "src/stock_probs/static"
        files: list[dict[str, Any]] = [
            {"path": str(path.relative_to(ROOT)), "raw_bytes": path.stat().st_size}
            for path in sorted(static_root.iterdir())
            if path.is_file()
        ]
        static_bytes = sum(item["raw_bytes"] for item in files)
        response_bytes = len(readiness_body)
        passed = strict_threshold(static_bytes, "<", STATIC_LIMIT_BYTES) and strict_threshold(
            response_bytes, "<", RESPONSE_LIMIT_BYTES
        )
        self.write_row(
            "static-and-response-bytes",
            started=started,
            warmups={"count": 0, "excluded": True, "raw": []},
            measured={
                "count": len(files) + 1,
                "unit": "raw bytes",
                "raw": [item["raw_bytes"] for item in files] + [response_bytes],
            },
            statistics=statistics_for(
                [float(item["raw_bytes"]) for item in files] + [float(response_bytes)], "raw bytes"
            ),
            raw={
                "static_files": files,
                "static_total_raw_bytes": static_bytes,
                "designated_response": {
                    "path": "/api/v1/readiness",
                    "raw_body_bytes": response_bytes,
                },
                "compression": "none; filesystem and decoded response-body bytes",
            },
            threshold={
                "class": "proposed numeric thresholds",
                "static": {"operator": "<", "value": STATIC_LIMIT_BYTES, "unit": "raw bytes"},
                "response": {"operator": "<", "value": RESPONSE_LIMIT_BYTES, "unit": "raw bytes"},
            },
            result="Pass" if passed else "Fail",
        )

    def _write_provider_deadline_row(self) -> None:
        started = utc_now()
        import stock_probs.provider as provider_module

        observed: list[float] = []

        class Response:
            status_code = 200

        class Session:
            def __enter__(self) -> Session:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def get(self, _url: str, **kwargs: Any) -> Response:
                observed.append(float(kwargs["timeout"]))
                callback = kwargs["content_callback"]
                callback(b'{"news":[]}')
                return Response()

        original_session = provider_module.curl_requests.Session
        try:
            provider_module.curl_requests.Session = Session
            now = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)
            for configured in (8.0, 20.0):
                provider_module.YahooProvider(configured).fetch_news("ACDC", 10, now)
        finally:
            provider_module.curl_requests.Session = original_session
        expected = [min(value, NEWS_PROVIDER_DEADLINE_SECONDS) for value in (8.0, 20.0)]
        passed = len(observed) == len(expected) and all(
            0 <= expected_value - observed_value < 0.1
            and strict_threshold(observed_value, "<=", NEWS_PROVIDER_DEADLINE_SECONDS)
            for observed_value, expected_value in zip(observed, expected, strict=True)
        )
        self.write_row(
            "provider-deadline",
            started=started,
            warmups={"count": 0, "excluded": True, "raw": []},
            measured={"count": len(observed), "unit": "seconds", "raw": observed},
            statistics=statistics_for(observed, "seconds"),
            raw={
                "configured_provider_timeout_seconds": [8.0, 20.0],
                "expected_effective_seconds": expected,
                "captured_transport_timeout_seconds": observed,
                "network_used": False,
                "fixture": "in-process transport captures the actual Yahoo news timeout argument",
            },
            threshold={
                "class": "M09 numeric threshold",
                "operator": "<=",
                "value": NEWS_PROVIDER_DEADLINE_SECONDS,
                "unit": "seconds",
                "effective": "min(provider_timeout, 10 seconds)",
            },
            result="Pass" if passed else "Fail",
            limitation=(
                None
                if passed
                else "Provider timeout propagation did not match the required cap."
            ),
        )

    def _write_package_row(self, temp: Path) -> None:
        started_utc = utc_now()
        build_source = temp / "package-source"
        wheelhouse = temp / "wheelhouse"
        build_source.mkdir()
        wheelhouse.mkdir()
        shutil.copy2(ROOT / "pyproject.toml", build_source / "pyproject.toml")
        shutil.copytree(ROOT / "src", build_source / "src")
        command = [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--disable-pip-version-check",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheelhouse),
            str(build_source),
        ]
        started = time.perf_counter()
        completed = subprocess.run(  # noqa: S603
            command, cwd=temp, check=False, capture_output=True, text=True
        )
        elapsed_ms = (time.perf_counter() - started) * 1_000
        wheels = list(wheelhouse.glob("stock_probs-*.whl"))
        wheel_bytes = wheels[0].stat().st_size if len(wheels) == 1 else None
        if wheels:
            shutil.copy2(wheels[0], self.artifact_dir / wheels[0].name)
        if completed.returncode != 0 or wheel_bytes is None:
            result, limitation = "Fail", "Clean isolated wheel build failed."
        else:
            passed = strict_threshold(
                float(wheel_bytes), "<=", PACKAGE_LIMIT_BYTES
            ) and strict_threshold(
                elapsed_ms, "<=", PACKAGE_BUILD_LIMIT_MS
            )
            result, limitation = ("Pass" if passed else "Fail"), None
        self.write_row(
            "package-size-build-time",
            started=started_utc,
            warmups={"count": 0, "excluded": True, "raw": []},
            measured={"count": 2, "unit": "mixed", "raw": [wheel_bytes, round(elapsed_ms, 3)]},
            statistics={"p50": None, "p95": None, "max": None, "unit": "mixed"},
            raw={
                "wheel": wheels[0].name if len(wheels) == 1 else None,
                "wheel_bytes": wheel_bytes,
                "clean_build_elapsed_ms": round(elapsed_ms, 3),
                "tool": f"pip {self._pip_version()}",
                "stdout": completed.stdout[-4_096:],
                "stderr": completed.stderr[-4_096:],
                "measurement_commit": self.revision,
            },
            threshold={
                "class": "proposed numeric thresholds",
                "package_bytes_max": PACKAGE_LIMIT_BYTES,
                "build_ms_max": PACKAGE_BUILD_LIMIT_MS,
                "evidence_basis": (
                    "The clean source-copy wheel command records exact output bytes and elapsed "
                    "time against a 128 KiB wheel and five-second local-build budget."
                ),
            },
            result=result,
            limitation=limitation,
            command=command,
        )

    @staticmethod
    def _pip_version() -> str:
        try:
            import pip

            return pip.__version__
        except ImportError:
            return "unavailable"

    def _timed_process(self, command: list[str], environment: dict[str, str]) -> dict[str, Any]:
        started = time.perf_counter()
        process = subprocess.Popen(  # noqa: S603
            command,
            cwd=ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        rss: list[dict[str, int]] = []
        while process.poll() is None:
            try:
                rss.append(_process_status(process.pid))
            except (FileNotFoundError, RuntimeError):
                break
            time.sleep(0.01)
        stdout, stderr = process.communicate(timeout=5)
        return {
            "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
            "exit_code": process.returncode,
            "stdout": stdout.decode(errors="replace")[-4_096:],
            "stderr": stderr.decode(errors="replace")[-4_096:],
            "rss_samples": rss,
            "peak_rss_bytes": max((sample["VmHWM"] for sample in rss), default=None),
        }

    def _write_backup_row(self, runtime: Path) -> None:
        started = utc_now()
        environment = os.environ.copy()
        environment.update(
            {"STOCK_PROBS_DATA_DIR": str(runtime), "STOCK_PROBS_PROVIDER": "fixture"}
        )
        name = "m06-performance-representative.spbackup"
        backup_command = [sys.executable, "-m", "stock_probs.cli", "backup", "--name", name]
        restore_command = [sys.executable, "-m", "stock_probs.cli", "restore", name]
        backup = self._timed_process(backup_command, environment)
        restore = (
            self._timed_process(restore_command, environment)
            if backup["exit_code"] == 0
            else None
        )
        artifact = runtime / "backups" / name
        artifact_bytes = artifact.stat().st_size if artifact.is_file() else None
        database_bytes = (runtime / "stock_probs.sqlite3").stat().st_size
        verified = False
        if restore is not None and restore["exit_code"] == 0:
            try:
                verified = bool(json.loads(restore["stdout"])["verified"])
            except (json.JSONDecodeError, KeyError, TypeError):
                verified = False
        if backup["exit_code"] != 0 or restore is None or restore["exit_code"] != 0 or not verified:
            result, limitation = "Fail", "Representative backup or verified restore failed."
        else:
            passed = strict_threshold(
                backup["elapsed_ms"], "<=", BACKUP_LIMIT_MS
            ) and strict_threshold(restore["elapsed_ms"], "<=", RESTORE_LIMIT_MS)
            result, limitation = ("Pass" if passed else "Fail"), None
        durations = [backup["elapsed_ms"]]
        if restore is not None:
            durations.append(restore["elapsed_ms"])
        self.write_row(
            "backup-restore-duration",
            started=started,
            warmups={"count": 0, "excluded": True, "raw": []},
            measured={"count": len(durations), "unit": "ms", "raw": durations},
            statistics=statistics_for(durations, "ms"),
            raw={
                "fixture": "100k audit ledger plus deterministic cache-hit/concurrency events",
                "database_bytes": database_bytes,
                "artifact_bytes": artifact_bytes,
                "backup": backup,
                "restore": restore,
                "restore_verified": verified,
                "restore_promoted": False,
                "measurement_commit": self.revision,
            },
            threshold={
                "class": "proposed numeric thresholds",
                "backup_ms_max": BACKUP_LIMIT_MS,
                "restore_ms_max": RESTORE_LIMIT_MS,
                "evidence_basis": (
                    "The representative 100k-row fixture records separate process timing, RSS, "
                    "artifact size, and restore verification within five seconds per operation."
                ),
            },
            result=result,
            limitation=limitation,
            command=[*backup_command, "&&", *restore_command],
        )

    def _write_arm_row(self) -> None:
        started = utc_now()
        self.write_row(
            "arm64-performance-limitation",
            started=started,
            warmups={"count": 0, "excluded": True, "raw": []},
            measured={"count": 0, "unit": "not-run", "raw": []},
            statistics=statistics_for([], "not-run"),
            raw={
                "host_architecture": self.architecture,
                "emulation_attempted": False,
                "native_arm64_available": self.architecture in {"aarch64", "arm64"},
            },
            threshold={
                "class": "architecture limitation",
                "requirement": "native physical ARM64 only",
            },
            result="Unavailable",
            limitation=(
                "Host is native x86_64; ARM64 performance was not run or inferred from emulation."
            ),
            fixture={"name": "none; architecture limitation receipt"},
            command=[sys.executable, "scripts/performance_harness.py", "--native-host-only"],
        )

    def finish(self) -> int:
        expected_rows = required_rows(self.profile)
        missing = sorted(expected_rows - set(self.rows))
        invalid: list[str] = []
        for row, payload in self.rows.items():
            try:
                artifact_path = self.artifact_dir / payload["artifact"]
                if not artifact_path.is_file():
                    raise ValueError(f"artifact file for {row} is missing")
                on_disk = json.loads(artifact_path.read_text())
                if on_disk["row"] != row:
                    raise ValueError(f"artifact file for {row} contains the wrong row")
                validate_artifact(on_disk, acceptance=True)
            except (json.JSONDecodeError, KeyError, OSError, ValueError) as exc:
                if row != "arm64-performance-limitation":
                    invalid.append(str(exc))
        acceptance_errors = acceptance_precondition_errors(
            self.profile, self.dirty, self.reviewer
        )
        summary = {
            "schema_version": SCHEMA_VERSION,
            "task_id": self.task_id,
            "revision": {"commit": self.revision, "dirty": self.dirty},
            "architecture": self.architecture,
            "required_rows": sorted(expected_rows),
            "artifacts": {row: payload["artifact"] for row, payload in sorted(self.rows.items())},
            "missing_rows": missing,
            "nonpassing_rows": sorted(
                row
                for row, payload in self.rows.items()
                if row != "arm64-performance-limitation" and payload["result"] != "Pass"
            ),
            "arm64_result": self.rows.get("arm64-performance-limitation", {}).get("result"),
            "reviewer": self.reviewer,
            "profile": self.profile,
            "acceptance_errors": acceptance_errors,
            "result": "Pass" if not missing and not invalid else "Fail",
            "validation_errors": invalid,
        }
        # A limitation receipt is expected on x86; every executable row must still pass.
        if summary["nonpassing_rows"] or acceptance_errors:
            summary["result"] = "Fail"
        (self.artifact_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2), flush=True)
        return 0 if summary["result"] == "Pass" else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path(
            os.getenv(
                "STOCK_PROBS_PERFORMANCE_ARTIFACT_DIR",
                f"test-results/performance/{TASK_ID}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}",
            )
        ),
    )
    parser.add_argument("--idle-seconds", type=int, default=60, help=argparse.SUPPRESS)
    parser.add_argument(
        "--profile",
        choices=("development", "m06", "m09", "release"),
        default="development",
        help="Choose explicit development evidence or an acceptance boundary.",
    )
    args = parser.parse_args()
    if args.idle_seconds < 60:
        parser.error("acceptance idle measurement must be at least 60 seconds")
    raise SystemExit(Harness(args.artifact_dir, args.idle_seconds, args.profile).run_native())


if __name__ == "__main__":
    main()
