"""M01/M02/M03/M06/M09 resource and portability checks keep local work bounded."""

from __future__ import annotations

import subprocess
import tomllib
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path

import pytest
from setuptools import Distribution
from setuptools.command.build_py import build_py

from scripts import build_frontend
from stock_probs.provider import FixtureProvider
from stock_probs.repository import Repository
from stock_probs.service import ForecastService

FIXED_NOW = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)
ROOT = Path(__file__).parents[1]


def test_package_and_local_gate_cover_portable_runtime_assets():
    package_data = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]
    makefile = (ROOT / "Makefile").read_text()
    local_gate = (ROOT / "scripts/local-gate.sh").read_text()
    arm64_gate = (ROOT / "scripts/arm64-smoke.sh").read_text()
    bootstrap = (ROOT / "scripts/bootstrap.sh").read_text()
    package_smoke = (ROOT / "scripts/package_smoke.py").read_text()
    arm64_compose = (ROOT / "scripts/compose.arm64.yml").read_text()
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]

    assert package_data["package-data"]["stock_probs"] == [
        "static/*",
        "static/next/**/*",
        "migrations/*.sql",
        "fixtures/*.json",
    ]
    assert "./scripts/build-frontend.sh" in makefile
    assert "frontend-build:" in makefile
    assert "npm --prefix frontend ci" not in makefile
    assert "dev: frontend-build" in makefile
    assert "acceptance: frontend-build check browser-test" in makefile
    assert all(
        target in makefile
        for target in ("package-check:", "m01-gate:", "m02-gate:", "m03-gate:", "m09-gate:")
    )
    assert "set -euo pipefail" in local_gate and '"result": result' in local_gate
    assert "make " not in local_gate and "run_check" in local_gate and "m03)" in local_gate
    assert '"$ROOT/scripts/build-frontend.sh"' in local_gate
    assert 'COMPLETED_CHECKS+=("browser")' in local_gate
    assert 'COMPLETED_CHECKS+=("playwright-mcp")' in local_gate
    assert 'COMPLETED_CHECKS+=("arm64-functional-package-runtime")' in local_gate
    assert 'os.getenv("STOCK_PROBS_TASK_ID", "M01")' in package_smoke
    assert '"stock_probs/migrations/002_historical_analysis.sql"' in package_smoke
    assert '"stock_probs/static/theme.js"' in package_smoke
    assert 'f"http://127.0.0.1:{port}/assets/theme.js"' in package_smoke
    assert "uv python install" in bootstrap and "3.11.15" in bootstrap
    assert metadata["requires-python"] == ">=3.11,<3.12"
    assert "docker compose" in arm64_gate and "docker run" not in arm64_gate
    assert "emulated ARM64" in arm64_gate
    assert "down --volumes --remove-orphans" in arm64_gate
    assert 'PROJECT="stock-probs-$TASK_SLUG-arm64-' in arm64_gate
    assert '"task": task' in arm64_gate
    assert "com.docker.compose.project" in arm64_gate and '"$attached" == "0"' in arm64_gate
    assert "qemu-user-static:7.2.0-1@sha256:" in arm64_compose
    assert "/opt/stock-probs-deps" in arm64_compose
    assert "/tmp/stock-probs-deps" not in arm64_compose  # noqa: S108
    assert not (ROOT / ".github/workflows/ci.yml").exists()


def test_generated_next_stage_is_ignored_but_authored_assets_are_not():
    ignored = subprocess.run(  # noqa: S603, S607 - exercises the repository Git contract.
        [
            "/usr/bin/git",
            "check-ignore",
            "--no-index",
            "-q",
            "--",
            "src/stock_probs/static/next/index.html",
        ],
        cwd=ROOT,
        check=False,
    )
    authored = subprocess.run(  # noqa: S603, S607 - exercises the repository Git contract.
        [
            "/usr/bin/git",
            "check-ignore",
            "--no-index",
            "-q",
            "--",
            "src/stock_probs/static/app.css",
        ],
        cwd=ROOT,
        check=False,
    )

    assert ignored.returncode == 0
    assert authored.returncode == 1


def test_next_export_stages_only_served_files_and_packages_them_recursively():
    source = ROOT / "frontend/out"
    staged = ROOT / "src/stock_probs/static/next"

    assert {path.name for path in staged.iterdir()} == {"index.html", "api-docs.html", "_next"}
    assert (staged / "index.html").read_bytes() == (source / "index.html").read_bytes()
    assert (staged / "api-docs.html").read_bytes() == (source / "api-docs.html").read_bytes()
    source_next = {
        path.relative_to(source / "_next").as_posix(): path.read_bytes()
        for path in (source / "_next").rglob("*")
        if path.is_file()
    }
    staged_next = {
        path.relative_to(staged / "_next").as_posix(): path.read_bytes()
        for path in (staged / "_next").rglob("*")
        if path.is_file()
    }
    assert staged_next == source_next
    assert any(path.startswith("static/chunks/") for path in staged_next)

    package_data = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]
    distribution = Distribution(
        {
            "packages": ["stock_probs"],
            "package_dir": {"": "src"},
            "package_data": package_data["package-data"],
        }
    )
    command = build_py(distribution)
    command.ensure_finalized()
    command.analyze_manifest()
    packaged = {
        Path(path).resolve().relative_to(ROOT / "src/stock_probs").as_posix()
        for path in command.find_data_files("stock_probs", "src/stock_probs")
    }
    staged_files = {
        path.relative_to(staged).as_posix() for path in staged.rglob("*") if path.is_file()
    }
    assert {f"static/next/{path}" for path in staged_files} <= packaged


def test_frontend_staging_rejects_invalid_sources_and_destination_symlink(tmp_path, monkeypatch):
    source = tmp_path / "out"
    destination = tmp_path / "static/next"
    source.mkdir()
    destination.parent.mkdir()
    monkeypatch.setattr(build_frontend, "SOURCE", source)
    monkeypatch.setattr(build_frontend, "DESTINATION", destination)

    with pytest.raises(SystemExit, match="not a complete Next export"):
        build_frontend.main()

    for name in ("index.html", "api-docs.html"):
        (source / name).write_text("new")
    with pytest.raises(SystemExit, match="not a complete Next export"):
        build_frontend.main()

    (source / "_next").mkdir()
    linked = source / "_next/linked.js"
    linked.symlink_to(source / "index.html")
    with pytest.raises(SystemExit, match="must not contain symlinks"):
        build_frontend.main()

    linked.unlink()
    destination.symlink_to(source, target_is_directory=True)
    with pytest.raises(SystemExit, match="static/next must not be a symlink"):
        build_frontend.main()


def test_frontend_staging_replaces_stale_export(tmp_path, monkeypatch):
    source = tmp_path / "out"
    destination = tmp_path / "static/next"
    source.mkdir()
    destination.mkdir(parents=True)
    for name in ("index.html", "api-docs.html"):
        (source / name).write_text("new")
    chunks = source / "_next/static/chunks"
    chunks.mkdir(parents=True)
    (chunks / "app.js").write_text("chunk")
    (destination / "stale.txt").write_text("stale")
    monkeypatch.setattr(build_frontend, "SOURCE", source)
    monkeypatch.setattr(build_frontend, "DESTINATION", destination)

    build_frontend.main()

    assert {path.name for path in destination.iterdir()} == {"index.html", "api-docs.html", "_next"}
    assert (destination / "_next/static/chunks/app.js").read_text() == "chunk"


def test_m02_dashboard_uses_only_versioned_api_controls():
    static = ROOT / "src/stock_probs/static"
    html = (static / "next/index.html").read_text()
    script = (static / "app.js").read_text()

    assert "Reopen saved forecast" in script
    assert "Run fresh cutoff analysis" in script
    assert "Download CSV" in html and "Download JSON" in html
    assert 'page_size: pageSize' in script
    assert "/saved-forecasts/${id}" in script
    assert "/history/${id}/reconstructions" in script
    assert "hasPriorRunReference" in script and "item.is_repeat" in script
    assert "knownRunDispositions" not in script
    for forbidden in ("sqlite", "yahoo.com", "querySelector(\"#database", "file://"):
        assert forbidden not in script.lower()


def test_bounded_fixture_forecast_batch_stays_small(settings):
    repository = Repository(settings.database_path)
    repository.migrate()
    service = ForecastService(repository, FixtureProvider(), lambda: FIXED_NOW)

    tracemalloc.start()
    for _ in range(20):
        service.search("ACDC", "stock")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Twenty audited requests cover a useful repeated-search burst without desktop-scale use.
    assert peak < 64 * 1024 * 1024
    assert settings.database_path.stat().st_size < 16 * 1024 * 1024
    assert repository.history(page_size=100)["total"] == 20


def test_dashboard_and_price_slice_stay_lightweight(client):
    # Exported route HTML and preserved assets remain bounded; charts request a tiny captured slice.
    responses = [
        client.get(path)
        for path in (
            "/", "/api/v1/docs", "/assets/app.css", "/assets/app.js",
            "/assets/theme.js", "/assets/favicon.svg",
        )
    ]
    assert all(response.status_code == 200 for response in responses)
    asset_bytes = sum(len(response.content) for response in responses)
    created = client.post(
        "/api/v1/forecasts", json={"symbol": "ACDC", "asset_type": "stock"}
    ).json()
    prices = client.get(
        f"/api/v1/history/{created['event']['id']}/prices",
        params={"series": "daily", "limit": 10},
    )

    assert asset_bytes < 128 * 1024
    assert prices.status_code == 200
    assert len(prices.content) < 8 * 1024
