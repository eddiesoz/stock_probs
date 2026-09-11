"""M01/M02/M03/M06 resource and portability checks keep local work explicitly bounded."""

from __future__ import annotations

import tomllib
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path

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
        "migrations/*.sql",
        "fixtures/*.json",
    ]
    assert "scripts/install-node.sh" in makefile
    assert "package-check:" in makefile and "m01-gate:" in makefile and "m02-gate:" in makefile
    assert "set -euo pipefail" in local_gate and '"result": result' in local_gate
    assert "make " not in local_gate and "run_check" in local_gate and "m02)" in local_gate
    assert 'COMPLETED_CHECKS+=("browser")' in local_gate
    assert 'COMPLETED_CHECKS+=("playwright-mcp")' in local_gate
    assert 'os.getenv("STOCK_PROBS_TASK_ID", "M01")' in package_smoke
    assert '"stock_probs/migrations/002_historical_analysis.sql"' in package_smoke
    assert "uv python install" in bootstrap and "3.11.15" in bootstrap
    assert metadata["requires-python"] == ">=3.11,<3.12"
    assert "docker compose" in arm64_gate and "docker run" not in arm64_gate
    assert "emulated ARM64" in arm64_gate
    assert "down --volumes --remove-orphans" in arm64_gate
    assert "stock-probs-m01-arm64-" in arm64_gate
    assert "com.docker.compose.project" in arm64_gate and '"$attached" == "0"' in arm64_gate
    assert "qemu-user-static:7.2.0-1@sha256:" in arm64_compose
    assert "/opt/stock-probs-deps" in arm64_compose
    assert "/tmp/stock-probs-deps" not in arm64_compose  # noqa: S108
    assert not (ROOT / ".github/workflows/ci.yml").exists()


def test_m02_dashboard_uses_only_versioned_api_controls():
    static = ROOT / "src/stock_probs/static"
    html = (static / "index.html").read_text()
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
    # The shell/docs have no framework bundle, and chart consumers request a tiny captured slice.
    asset_bytes = sum(
        len(client.get(path).content)
        for path in (
            "/",
            "/api/v1/docs",
            "/assets/app.css",
            "/assets/app.js",
            "/assets/favicon.svg",
        )
    )
    created = client.post(
        "/api/v1/forecasts", json={"symbol": "ACDC", "asset_type": "stock"}
    ).json()
    prices = client.get(
        f"/api/v1/history/{created['event']['id']}/prices",
        params={"series": "daily", "limit": 10},
    )

    assert asset_bytes < 96 * 1024
    assert prices.status_code == 200
    assert len(prices.content) < 8 * 1024
