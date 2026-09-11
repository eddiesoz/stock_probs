"""M03/M06 resource smoke tests keep deterministic local work within explicit bounds."""

from __future__ import annotations

import tracemalloc
from datetime import UTC, datetime

from stock_probs.provider import FixtureProvider
from stock_probs.repository import Repository
from stock_probs.service import ForecastService

FIXED_NOW = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)


def test_bounded_fixture_forecast_batch_stays_small(settings):
    repository = Repository(settings.database_path)
    repository.migrate()
    service = ForecastService(repository, FixtureProvider(), lambda: FIXED_NOW)

    tracemalloc.start()
    for index in range(20):
        service.search(f"LOAD{index}", "stock")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Twenty immutable snapshots cover a useful burst without desktop-scale memory or disk use.
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
