"""Loopback-only development-auth fixture for monitoring browser regressions.

The server uses the checked-in deterministic provider. Monitoring's persisted control is enabled
through its typed store method only after the ordinary application lifespan has migrated the
disposable database, bootstrapped its local fixture account, and started the bounded scheduler.
The simulated provider is intentionally not accepted as trusted baseline evidence.
"""

from __future__ import annotations

import argparse
import os
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI

from stock_probs.api import create_app
from stock_probs.config import Settings
from stock_probs.provider import FixtureProvider
from stock_probs.totp import code_for_step, time_step

FIXTURE_NOW = datetime(2025, 1, 10, 22, 3, tzinfo=UTC)


class AuditedFixtureProvider(FixtureProvider):
    """Retain only bounded operation kinds to distinguish scheduler work from page reads."""

    def __init__(self) -> None:
        super().__init__()
        self._audit_lock = threading.Lock()
        self._calls: list[dict[str, str]] = []

    def _record(self, kind: str) -> None:
        with self._audit_lock:
            if len(self._calls) < 64:
                self._calls.append({"kind": kind})

    def lookup(self, query: str, limit: int = 5, now: datetime | None = None):
        self._record("lookup")
        return super().lookup(query, limit, now)

    def quote_snapshot(self, symbol: str, asset_type: str, now: datetime | None = None):
        self._record("quote_snapshot")
        return super().quote_snapshot(symbol, asset_type, now)

    def audit_snapshot(self) -> list[dict[str, str]]:
        with self._audit_lock:
            return [dict(item) for item in self._calls]


def _port(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 65_535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return parsed


def _monitoring_fixture_app(port: int) -> FastAPI:
    origin = f"http://127.0.0.1:{port}"
    bootstrap_phrase = f"monitoring-local-fixture:{port}:not-a-secret"
    data_dir_value = os.environ.get("STOCK_PROBS_DATA_DIR")
    if not data_dir_value:
        raise RuntimeError("the browser harness must supply a disposable data directory")
    data_dir = Path(data_dir_value).absolute()
    settings = Settings(
        data_dir=data_dir,
        database_path=data_dir / "stock_probs.sqlite3",
        backup_dir=data_dir / "backups",
        provider="fixture",
        provider_timeout=2.0,
        host="127.0.0.1",
        port=port,
        environment="test",
        auth_mode="local",
        auth_public_origin=origin,
        auth_cookie_secure=False,
        auth_cookie_domain=None,
        bootstrap_username="monitoring-browser-admin",
        bootstrap_password=bootstrap_phrase,
        monitoring_features_enabled=True,
        monitoring_features_canary_only=True,
        monitoring_scheduler_enabled=True,
        fixture_now=FIXTURE_NOW,
    )
    provider = AuditedFixtureProvider()
    application = create_app(settings, provider, lambda: FIXTURE_NOW)
    original_lifespan = application.router.lifespan_context

    @asynccontextmanager
    async def monitoring_fixture_lifespan(app: FastAPI):
        async with original_lifespan(app):
            # The scheduler starts with the persisted switch disabled and therefore performs no
            # work during startup. Enable only this disposable fixture after a real local login
            # and authenticator proof, using the same AuthManager methods as the HTTP routes.
            store = app.state.monitoring_store
            control = store.get_control()
            if control["enabled"] is not True:
                auth_manager = app.state.auth
                if not isinstance(settings.bootstrap_username, str) or not isinstance(
                    settings.bootstrap_password, str
                ):
                    raise RuntimeError("the fixture admin credentials are not configured")
                auth_now = datetime.now(UTC)
                local_session = auth_manager.local_login(
                    settings.bootstrap_username, settings.bootstrap_password, auth_now
                )
                login_context = auth_manager.authenticate(local_session.session_token, auth_now)
                enrollment = auth_manager.begin_totp_enrollment(login_context, auth_now)
                secret = enrollment.get("secret")
                if not isinstance(secret, str):
                    raise RuntimeError("the fixture authenticator proof is unavailable")
                proof_time = datetime.now(UTC)
                stepped_up_session, _recovery_codes = auth_manager.finish_totp_enrollment(
                    login_context,
                    code_for_step(secret, time_step(proof_time)),
                    proof_time,
                )
                fixture_context = auth_manager.authenticate(
                    stepped_up_session.session_token, proof_time
                )
                if (
                    fixture_context.user.role != "admin"
                    or not auth_manager.has_recent_step_up(fixture_context, proof_time)
                ):
                    raise RuntimeError("the fixture admin session lacks fresh authenticator proof")
                store.set_control(
                    control["revision"], True, FIXTURE_NOW, auth_context=fixture_context
                )
            yield

    application.router.lifespan_context = monitoring_fixture_lifespan

    async def provider_audit() -> dict[str, Any]:
        return {"items": provider.audit_snapshot()}

    application.add_api_route(
        "/__qa/monitoring-provider-audit",
        provider_audit,
        methods=["GET"],
        include_in_schema=False,
    )
    return application


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=_port)
    args = parser.parse_args()
    application = _monitoring_fixture_app(args.port)
    uvicorn.run(
        application,
        host="127.0.0.1",
        port=args.port,
        access_log=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
