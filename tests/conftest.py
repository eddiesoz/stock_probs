"""Shared fixtures isolate every deterministic test from user data and live Yahoo calls."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from stock_probs.api import create_app
from stock_probs.config import Settings
from stock_probs.provider import FixtureProvider

FIXED_NOW = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)


@pytest.fixture
def settings(tmp_path):
    """Point all server-owned runtime state into a disposable directory."""

    return Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
    )


@pytest.fixture
def client(settings):
    """Run lifespan migrations exactly as production startup does."""

    app = create_app(settings, FixtureProvider(), lambda: FIXED_NOW)
    with TestClient(app) as test_client:
        yield test_client
