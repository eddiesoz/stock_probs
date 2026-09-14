"""Focused tests keep M06/M09 performance artifacts and thresholds fail closed."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "performance_harness", ROOT / "scripts/performance_harness.py"
)
assert SPEC is not None and SPEC.loader is not None
performance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(performance)
COMMENT_SPEC = importlib.util.spec_from_file_location(
    "comment_audit", ROOT / "scripts/comment_audit.py"
)
assert COMMENT_SPEC is not None and COMMENT_SPEC.loader is not None
comment_audit = importlib.util.module_from_spec(COMMENT_SPEC)
COMMENT_SPEC.loader.exec_module(comment_audit)


def complete_artifact(**overrides):
    payload = {
        "schema_version": 1,
        "task_id": "M06",
        "row": "process-rss",
        "fixture_identity": {"name": "fixture"},
        "isolation": {"process_pid": 1, "port": 1234, "temp_dir": "isolated-fixture"},
        "environment": {"architecture": "x86_64", "execution": "native x86_64"},
        "revision": {"commit": "a" * 40, "dirty": False},
        "utc": {"start": "2026-01-01T00:00:00Z", "end": "2026-01-01T00:01:00Z"},
        "command": ["python", "scripts/performance_harness.py"],
        "warmups": {"count": 5, "excluded": True, "raw": []},
        "measured_samples": {"count": 30, "unit": "bytes", "raw": [1] * 30},
        "statistics": {"p50": 1, "p95": 1, "max": 1, "unit": "bytes"},
        "raw": {"rss": [1] * 30},
        "threshold": {"class": "existing numeric threshold", "operator": "<", "value": 2},
        "result": "Pass",
        "limitation": None,
        "artifact": "process-rss.json",
        "reviewer": "LUNA MAX QA",
    }
    payload.update(overrides)
    return payload


def test_artifact_schema_requires_every_evidence_field():
    payload = complete_artifact()
    performance.validate_artifact(payload)

    del payload["raw"]
    with pytest.raises(ValueError, match="missing required fields"):
        performance.validate_artifact(payload)


@pytest.mark.parametrize(
    "task_id",
    [
        *(f"M{milestone:02}" for milestone in range(10)),
        *(f"EXP-M{milestone:02}" for milestone in range(10)),
        *(f"R-M{milestone:02}-1" for milestone in range(10)),
        "R-M07-5",
        "R-M09-55",
        *(f"m{milestone:02}" for milestone in range(1, 10)),
        "check",
        "release",
    ],
)
def test_artifact_schema_accepts_harness_task_identities(task_id):
    performance.validate_artifact(complete_artifact(task_id=task_id))


@pytest.mark.parametrize(
    "task_id",
    [
        "M10",
        "M100",
        "EXP-M10",
        "EXP-M100",
        "R-M10-1",
        "R-M100-1",
        "R-M07-0",
        "R-M07-nope",
        "R-M09-0",
        "R-M09-nope",
        "m00",
        "m10",
        "M07-extra",
        "arbitrary",
    ],
)
def test_artifact_schema_rejects_invalid_harness_task_identities(task_id):
    with pytest.raises(ValueError, match="task identity is invalid"):
        performance.validate_artifact(complete_artifact(task_id=task_id))


@pytest.mark.parametrize(
    ("values", "bound", "operator", "expected"),
    [
        ([999.0] * 30, 1_000.0, "<", "Pass"),
        ([1_000.0] * 30, 1_000.0, "<", "Fail"),
        ([250.0] * 30, 250.0, "<", "Fail"),
        ([1.0] * 29, 1_000.0, "<", "Fail"),
        ([float("nan")] * 30, 1_000.0, "<", "Fail"),
    ],
)
def test_strict_threshold_and_sample_failures(values, bound, operator, expected):
    assert performance.sample_result(values, bound, operator, 30) == expected


def test_acceptance_validation_rejects_unavailable_baseline_row():
    payload = complete_artifact(
        row="package-size-build-time",
        result="Unavailable",
        limitation="No approved bound supplied.",
    )

    with pytest.raises(ValueError, match="did not pass"):
        performance.validate_artifact(payload, acceptance=True)


@pytest.mark.parametrize(
    "reviewer", ["", "QA", "PENDING_INDEPENDENT_REVIEW", "todo reviewer", "Unavailable"]
)
def test_acceptance_validation_rejects_missing_or_placeholder_reviewer(reviewer):
    payload = complete_artifact(reviewer=reviewer)

    with pytest.raises(ValueError, match="non-placeholder named reviewer"):
        performance.validate_artifact(payload, acceptance=True)


def test_release_requires_clean_commit_while_m06_allows_reviewed_dirty_measurement():
    assert performance.acceptance_precondition_errors("m06", True, "LUNA MAX QA") == []
    assert performance.acceptance_precondition_errors("release", False, "LUNA MAX QA") == []
    assert performance.acceptance_precondition_errors("release", True, "LUNA MAX QA") == [
        "release performance requires a clean committed working tree"
    ]
    assert performance.acceptance_precondition_errors(
        "development", True, "PENDING_INDEPENDENT_REVIEW"
    ) == ["PERFORMANCE_REVIEWER is missing or is a placeholder"]


def test_artifact_schema_rejects_claimed_pass_with_missing_workload_samples():
    payload = complete_artifact(
        row="fixture-cache-hit-forecast",
        warmups={"count": 4, "excluded": True, "raw_ms": [1.0] * 4},
        measured_samples={"count": 29, "unit": "ms", "raw": [1.0] * 29},
    )

    with pytest.raises(ValueError, match="too few warmups or samples"):
        performance.validate_artifact(payload, acceptance=True)


@pytest.mark.parametrize(
    "row",
    [
        "theme-action-to-painted-theme",
        "news-cache-hit-endpoint",
        "ten-item-news-render",
        "news-response-bytes",
    ],
)
def test_m09_claimed_pass_rejects_missing_samples(row):
    payload = complete_artifact(
        task_id="M09",
        row=row,
        measured_samples={"count": 0, "unit": "ms", "raw": []},
        threshold={"class": "M09", "operator": "<=", "value": 100},
    )

    with pytest.raises(ValueError, match="too few warmups or samples"):
        performance.validate_artifact(payload, acceptance=True)


def test_m09_row_rejects_missing_numeric_bound():
    payload = complete_artifact(
        task_id="M09",
        row="provider-deadline",
        measured_samples={"count": 1, "unit": "seconds", "raw": [10.0]},
        threshold={"class": "M09 numeric threshold", "operator": "<="},
    )

    with pytest.raises(ValueError, match="threshold bound is missing"):
        performance.validate_artifact(payload)


def test_m09_and_release_profiles_add_rows_without_removing_m06_rows():
    assert performance.required_rows("m06") == performance.M06_REQUIRED_ROWS
    assert performance.required_rows("m09") > performance.M06_REQUIRED_ROWS
    assert performance.required_rows("release") == performance.M09_REQUIRED_ROWS


def test_idle_cpu_statistics_recompute_exactly_and_reject_one_ulp_mutation():
    values = [0.0, 0.1234567890123456]
    payload = json.loads(
        json.dumps(
            complete_artifact(
                row="idle-cpu",
                measured_samples={"count": len(values), "unit": "core-percent", "raw": values},
                statistics=performance.idle_cpu_statistics(values),
                raw={"duration_seconds": 60.0},
            )
        )
    )

    assert payload["statistics"] == performance.idle_cpu_statistics(
        payload["measured_samples"]["raw"]
    )
    performance.validate_artifact(payload)
    payload["measured_samples"]["raw"][-1] = math.nextafter(values[-1], math.inf)
    with pytest.raises(ValueError, match="do not exactly match serialized samples"):
        performance.validate_artifact(payload)


def test_local_gate_profiles_make_performance_mandatory_for_m06_m09_and_release():
    gate = (ROOT / "scripts/local-gate.sh").read_text()
    m04 = gate[gate.index("  m04)") : gate.index("  m06)")]
    m06 = gate[gate.index("  m06)") : gate.index("  m09)")]
    m09 = gate[gate.index("  m09)") : gate.index("  release)")]
    release = gate[gate.index("  release)") : gate.index("esac")]

    assert "run_performance" not in m04
    assert "run_performance" in m06
    assert "run_performance" in m09
    assert "run_performance" in release
    assert 'STOCK_PROBS_PERFORMANCE_ARTIFACT_DIR="$RUN_DIR/performance"' in gate
    assert m04.count("run_ponytail_precondition") == 0
    assert m06.count("run_ponytail_precondition") == 1
    assert m09.count("run_ponytail_precondition") == 1
    assert release.count("run_ponytail_precondition") == 1
    assert m06.count("require_performance_acceptance") == 1
    assert m09.count("require_performance_acceptance") == 1
    assert release.count("require_performance_acceptance") == 1
    assert "ponytail-review.sh\" \"$TASK_ID" not in m06 + m09 + release


def test_proposed_native_bounds_are_explicit_and_not_environment_overrides():
    assert performance.CONCURRENCY_P95_LIMIT_MS == 3_000
    assert performance.CONCURRENCY_BATCH_LIMIT_MS == 5_000
    assert performance.PACKAGE_LIMIT_BYTES == 328 * 1024
    assert performance.PACKAGE_BUILD_LIMIT_MS == 5_000
    assert performance.BACKUP_LIMIT_MS == 5_000
    assert performance.RESTORE_LIMIT_MS == 5_000
    assert performance.READINESS_LIMIT_MS == 20_000
    assert performance.THEME_ACTION_P95_LIMIT_MS == 100
    assert performance.NEWS_ENDPOINT_P95_LIMIT_MS == 100
    assert performance.NEWS_RENDER_P95_LIMIT_MS == 250
    assert performance.NEWS_RESPONSE_LIMIT_BYTES == 32 * 1024
    assert performance.NEWS_PROVIDER_DEADLINE_SECONDS == 10
    assert performance.STATIC_LIMIT_BYTES == 736 * 1024
    source = (ROOT / "scripts/performance_harness.py").read_text()
    assert "STOCK_PROBS_PERF_CONCURRENCY_P95_MS" not in source
    assert "STOCK_PROBS_PERF_PACKAGE_MAX_BYTES" not in source
    assert "STOCK_PROBS_PERF_BACKUP_MAX_MS" not in source


def test_m09_browser_rows_reuse_the_playwright_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(performance, "_git_revision", lambda: ("a" * 40, True))
    harness = performance.Harness(tmp_path, 60, "m09")
    playwright = complete_artifact(
        task_id="M09",
        row="browser-budgets",
        raw={
            "m09_browser": {
                "startedUtc": "2026-01-01T00:00:00Z",
                "themeWarmups": [1.0] * 5,
                "themeSamples": [10.0] * 30,
                "renderWarmups": [2.0] * 5,
                "renderSamples": [20.0] * 30,
                "itemCounts": [10] * 30,
            }
        },
    )
    command = ["npx", "playwright", "test", "tools/browser/tests/performance.spec.js"]
    completed = performance.subprocess.CompletedProcess(command, 0, "passed", "")

    harness._write_m09_browser_rows(playwright, completed)

    assert harness.rows["theme-action-to-painted-theme"]["result"] == "Pass"
    news = harness.rows["ten-item-news-render"]
    assert news["result"] == "Pass"
    assert news["raw"]["item_counts"] == [10] * 30
    assert news["command"] == command
    source = (ROOT / "scripts/performance_harness.py").read_text()
    assert "m09-browser-measurements.cjs" not in source
    assert "navigation_request_counts" not in source


def test_readiness_poll_aggregates_refusals_and_retains_unexpected_errors(monkeypatch):
    outcomes = iter(
        [
            ConnectionRefusedError("server is starting"),
            ValueError("invalid readiness payload"),
            (4.25, 200, b'{"status":"ready"}'),
        ]
    )

    def request(*_args, **_kwargs):
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    class RunningProcess:
        returncode = None

        @staticmethod
        def poll():
            return None

    clocks = iter([10.0, 10.05, 10.1, 10.15])
    timestamps = iter(["2026-01-01T00:00:00Z", "2026-01-01T00:00:00.100000Z"])
    monkeypatch.setattr(performance, "_request", request)
    monkeypatch.setattr(performance.time, "perf_counter", lambda: next(clocks))
    monkeypatch.setattr(performance.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(performance, "utc_now", lambda: next(timestamps))

    elapsed_ms, body, attempts = performance._poll_readiness(8000, RunningProcess(), 10.0)

    assert elapsed_ms == pytest.approx(150)
    assert body == b'{"status":"ready"}'
    assert attempts == {
        "attempt_count": 3,
        "startup_refusal_count": 1,
        "not_ready_response_count": 0,
        "success": {
            "attempt": 3,
            "utc": "2026-01-01T00:00:00.100000Z",
            "request_elapsed_ms": 4.25,
            "status": 200,
        },
        "total_elapsed_ms": 150.0,
        "unexpected_errors": [
            {
                "attempt": 2,
                "utc": "2026-01-01T00:00:00Z",
                "type": "ValueError",
                "message": "invalid readiness payload",
            }
        ],
    }


def test_make_performance_is_explicit_development_and_release_uses_one_local_gate():
    makefile = (ROOT / "Makefile").read_text()
    performance_recipe = makefile[
        makefile.index("performance: browser-setup") : makefile.index("acceptance:")
    ]
    release_recipe = makefile[
        makefile.index("release-check:") : makefile.index("release: release-check")
    ]

    assert "--profile development" in performance_recipe
    assert "./scripts/local-gate.sh release" in release_recipe
    assert "acceptance performance" not in release_recipe
    assert "m09-gate:" in makefile
    assert "./scripts/local-gate.sh m09" in makefile


def test_browser_budget_manifest_pins_required_protocol_and_bounds():
    manifest = json.loads((ROOT / "tools/browser/performance-budgets.json").read_text())

    assert manifest["warmups"] == 5
    assert manifest["measured_samples"] >= 30
    assert manifest["render_p95_ms"] == 2_000
    assert manifest["interaction_p95_ms"] == 250
    assert manifest["cls_max"] == 0.1
    assert manifest["viewports"] == [360, 390, 768, 1280, 1440]
    assert manifest["designated_response_bytes_strict_max"] == 8 * 1024
    assert manifest["static_shell_bytes_strict_max"] == 736 * 1024
    assert manifest["response_bytes_max_per_navigation"] == 640 * 1024
    assert manifest["request_count_max_per_navigation"] == 16
    assert "/assets/theme.js" in manifest["allowed_paths"]
    assert not any(path.startswith("/_next/") for path in manifest["allowed_paths"])
    assert manifest["justification"]


def test_static_row_inventory_is_recursive_sorted_and_exact(tmp_path, monkeypatch):
    static = tmp_path / "src/stock_probs/static"
    (static / "next/_next/static/chunks").mkdir(parents=True)
    (static / "next/index.html").write_bytes(b"dashboard")
    (static / "next/api-docs.html").write_bytes(b"docs")
    (static / "next/_next/static/chunks/hash1234.js").write_bytes(b"chunk")
    (static / "app.js").write_bytes(b"app")
    monkeypatch.setattr(performance, "ROOT", tmp_path)
    monkeypatch.setattr(performance, "_git_revision", lambda: ("a" * 40, True))
    harness = performance.Harness(tmp_path / "artifacts", 60)
    harness.rows["browser-budgets"] = {"result": "Pass"}

    harness._write_static_row(b"x")

    row = harness.rows["static-and-response-bytes"]
    assert row["result"] == "Pass"
    assert row["raw"]["static_total_raw_bytes"] == 21
    assert [item["path"] for item in row["raw"]["static_files"]] == sorted(
        item["path"] for item in row["raw"]["static_files"]
    )


@pytest.mark.parametrize(
    ("artifact_result", "returncode", "expected"),
    [("Pass", 0, "Pass"), ("Fail", 0, "Fail"), ("Pass", 1, "Fail")],
)
def test_browser_artifact_or_process_failure_stays_failed(
    tmp_path, monkeypatch, artifact_result, returncode, expected
):
    monkeypatch.setattr(performance, "_git_revision", lambda: ("a" * 40, True))
    harness = performance.Harness(tmp_path, 60)
    artifact = tmp_path / "browser-budgets.json"
    artifact.write_text(
        json.dumps(
            complete_artifact(
                task_id=harness.task_id,
                row="browser-budgets",
                environment={"architecture": harness.architecture},
                revision={"commit": "a" * 40, "dirty": harness.dirty},
                result=artifact_result,
                artifact=artifact.name,
                reviewer=harness.reviewer,
            )
        )
    )

    assert harness._load_browser_budget(artifact, returncode)["result"] == expected


@pytest.mark.parametrize("browser_result", ["Pass", "Fail"])
def test_static_row_requires_browser_result(tmp_path, monkeypatch, browser_result):
    monkeypatch.setattr(performance, "_git_revision", lambda: ("a" * 40, True))
    harness = performance.Harness(tmp_path, 60)
    harness.rows["browser-budgets"] = {"result": browser_result}

    harness._write_static_row(b"{}")

    row = harness.rows["static-and-response-bytes"]
    assert row["result"] == browser_result
    assert "initial_navigation" not in row["raw"]
    assert set(row["threshold"]) == {"class", "static", "response"}


def test_local_gate_builds_and_stages_frontend_before_profile_gates():
    gate = (ROOT / "scripts/local-gate.sh").read_text()
    frontend_path = ROOT / "scripts/build-frontend.sh"
    frontend = frontend_path.read_text()
    makefile = (ROOT / "Makefile").read_text()

    assert gate.index('\n  "$ROOT/scripts/build-frontend.sh"\n') < gate.index(
        "\ncase \"$PROFILE\" in"
    )
    assert frontend_path.stat().st_mode & 0o111
    assert all(
        command in frontend
        for command in (
            '"$ROOT/scripts/install-node.sh"',
            '"$NODE_BIN/npm" --prefix "$ROOT/frontend" ci',
            '"$NODE_BIN/npm" --prefix "$ROOT/frontend" run typecheck',
            '"$NODE_BIN/npm" --prefix "$ROOT/frontend" test',
            '"$NODE_BIN/npm" --prefix "$ROOT/frontend" run build',
            '"$ROOT/.dev-venv/bin/python" "$ROOT/scripts/build_frontend.py"',
        )
    )
    assert "frontend-build:\n\t./scripts/build-frontend.sh\n" in makefile
    assert "frontend-npm-ci-typecheck-test-build-stage" in gate


def test_comment_audit_includes_frontend_typescript_but_not_generated_next(tmp_path):
    source = tmp_path / "frontend/app"
    generated = tmp_path / "frontend/.next/types"
    source.mkdir(parents=True)
    generated.mkdir(parents=True)
    component = source / "page.tsx"
    component.write_text("// route intent\nexport default function Page() {}\n")
    (generated / "route.ts").write_text("generated\n")

    checked = comment_audit.checked_paths(tmp_path)

    assert component in checked
    assert generated / "route.ts" not in checked


def test_comment_audit_exempts_only_opencode_metadata_json(tmp_path):
    skill_metadata = tmp_path / ".opencode/skills/example/metadata.json"
    other_metadata = tmp_path / "tools/example/metadata.json"
    skill_metadata.parent.mkdir(parents=True)
    other_metadata.parent.mkdir(parents=True)
    skill_metadata.write_text('{"name": "example"}\n')
    other_metadata.write_text('{"name": "example"}\n')

    checked = comment_audit.checked_paths(tmp_path)

    assert skill_metadata not in checked
    assert other_metadata in checked


def test_playwright_project_config_is_not_changed_for_the_performance_lane():
    config = (ROOT / "tools/browser/playwright.config.js").read_text()

    assert "STOCK_PROBS_PERFORMANCE" not in config
    assert 'command: "../../scripts/run-browser-app.sh"' in config
