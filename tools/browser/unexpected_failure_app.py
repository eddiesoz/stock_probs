"""Launch a browser-only app that deterministically exercises the generic error boundary."""

from __future__ import annotations

import uvicorn

from stock_probs.api import create_app
from stock_probs.config import Settings


def main() -> None:
    """Replace one operation adapter with a hostile unexpected failure and serve on loopback."""

    settings = Settings.from_env()
    application = create_app(settings=settings)

    def injected_failure(_: str) -> None:
        # The browser must receive none of these engine, table, statement, or machine details.
        raise RuntimeError(
            "SQLite database /srv/private/main.sqlite3 failed: "
            "SELECT * FROM forecast_runs"
        )

    application.state.backups.create = injected_failure
    uvicorn.run(
        application,
        host="127.0.0.1",
        port=settings.port,
        workers=1,
        limit_concurrency=8,
        backlog=8,
        timeout_keep_alive=2,
        timeout_graceful_shutdown=5,
    )


if __name__ == "__main__":
    main()
