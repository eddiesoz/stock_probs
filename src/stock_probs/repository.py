"""SQLite migration and repositories enforce durable append-only audit behavior."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from threading import RLock
from typing import Any

from stock_probs.config import ensure_private_directory, ensure_private_file

SCHEMA_VERSION = 1
OUTCOME_RECONSTRUCTION_LIMIT = 100


class Repository:
    """Open short-lived WAL connections so one local process remains restart-safe."""

    def __init__(self, database_path: Path):
        self.database_path = database_path
        # One process-wide lock makes restore promotion exclusive with short-lived queries.
        self._lock = RLock()

    def _harden_sqlite_files(self, *, create_database: bool) -> None:
        """Protect the database and any SQLite sidecars without following attacker links."""

        ensure_private_file(self.database_path, create=create_database)
        for suffix in ("-wal", "-shm", "-journal"):
            try:
                ensure_private_file(Path(f"{self.database_path}{suffix}"))
            except FileNotFoundError:
                # Sidecars exist only while SQLite needs their current journal mode.
                continue

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            # Prepare with no-follow descriptors before SQLite can open a permissive or linked file.
            ensure_private_directory(self.database_path.parent)
            self._harden_sqlite_files(create_database=True)
            connection = sqlite3.connect(self.database_path, timeout=5.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            # SQLite REPLACE fires delete triggers only with recursive triggers enabled.
            connection.execute("PRAGMA recursive_triggers = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            self._harden_sqlite_files(create_database=False)
            try:
                yield connection
            finally:
                connection.close()
                # SQLite may replace/create its own files, so reassert the active file mode.
                self._harden_sqlite_files(create_database=False)

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        """Hold the repository lock across multi-step backup or restore operations."""

        with self._lock:
            yield

    def migrate(self) -> None:
        """Apply each packaged migration once inside an exclusive transaction."""

        ensure_private_directory(self.database_path.parent)
        migration_dir = files("stock_probs.migrations")
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {
                row[0] for row in connection.execute("SELECT version FROM schema_migrations")
            }
            for migration in sorted(migration_dir.iterdir(), key=lambda item: item.name):
                if migration.suffix != ".sql":
                    continue
                version = int(migration.name.split("_", 1)[0])
                if version in applied:
                    continue
                # executescript owns its transaction, and the version insert is part of that script.
                timestamp = datetime.now(UTC).isoformat().replace("'", "")
                script = migration.read_text() + (
                    "\nINSERT INTO schema_migrations(version, applied_at) "
                    f"VALUES ({version}, '{timestamp}');\n"
                )
                connection.executescript("BEGIN IMMEDIATE;\n" + script + "COMMIT;\n")

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def record_failure(
        self,
        *,
        request_id: str,
        submitted_symbol: str,
        normalized_symbol: str | None,
        asset_type: str,
        error_code: str,
        error_message: str,
        submitted_at: datetime,
        completed_at: datetime,
    ) -> int:
        """A provider/domain failure still commits exactly one complete search event."""

        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            repeated = self._has_prior_submission(
                connection, submitted_symbol, normalized_symbol, asset_type
            )
            cursor = connection.execute(
                """INSERT INTO search_events
                (request_id, submitted_symbol, normalized_symbol, asset_type, status, is_repeat,
                 error_code, error_message, submitted_at, completed_at)
                VALUES (?, ?, ?, ?, 'failed', ?, ?, ?, ?, ?)""",
                (
                    request_id,
                    submitted_symbol[:64],
                    normalized_symbol,
                    asset_type,
                    int(repeated),
                    error_code,
                    error_message,
                    submitted_at.isoformat(),
                    completed_at.isoformat(),
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    @staticmethod
    def _has_prior_submission(
        connection: sqlite3.Connection,
        submitted_symbol: str,
        normalized_symbol: str | None,
        asset_type: str,
    ) -> bool:
        """Detect repeats even for invalid symbols that could not be normalized."""

        if normalized_symbol is not None:
            row = connection.execute(
                "SELECT 1 FROM search_events "
                "WHERE normalized_symbol = ? AND asset_type = ? LIMIT 1",
                (normalized_symbol, asset_type),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT 1 FROM search_events "
                "WHERE submitted_symbol = ? AND asset_type = ? LIMIT 1",
                (submitted_symbol[:64], asset_type),
            ).fetchone()
        return row is not None

    def record_success(
        self,
        *,
        request_id: str,
        submitted_symbol: str,
        asset_type: str,
        input_snapshot: dict[str, Any],
        results: list[dict[str, Any]],
        submitted_at: datetime,
        completed_at: datetime,
    ) -> tuple[int, int, bool, bool]:
        """Append a repeated event while reusing only an exact immutable input snapshot."""

        symbol = input_snapshot["symbol"]
        fingerprint = input_snapshot["content_fingerprint"]
        horizons = [result.get("horizon") for result in results]
        if sorted(horizons) != ["close_to_close", "completed_5m_to_close"]:
            raise ValueError("exactly one result for each supported horizon is required")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                "SELECT id FROM forecast_runs "
                "WHERE symbol = ? AND asset_type = ? AND content_fingerprint = ?",
                (symbol, asset_type, fingerprint),
            ).fetchone()
            repeated = self._has_prior_submission(
                connection, submitted_symbol, symbol, asset_type
            )
            reused = prior is not None
            if reused:
                run_id = int(prior["id"])
            else:
                run_cursor = connection.execute(
                    "INSERT INTO forecast_runs"
                    "(symbol, asset_type, content_fingerprint, created_at) VALUES (?, ?, ?, ?)",
                    (symbol, asset_type, fingerprint, completed_at.isoformat()),
                )
                run_id = int(run_cursor.lastrowid)
                input_cursor = connection.execute(
                    "INSERT INTO forecast_inputs"
                    "(run_id, snapshot_json, created_at) VALUES (?, ?, ?)",
                    (run_id, self._json(input_snapshot), completed_at.isoformat()),
                )
                input_id = int(input_cursor.lastrowid)
                connection.executemany(
                    "INSERT INTO forecast_results"
                    "(input_id, horizon, result_json, created_at) VALUES (?, ?, ?, ?)",
                    [
                        (input_id, result["horizon"], self._json(result), completed_at.isoformat())
                        for result in results
                    ],
                )
            event_cursor = connection.execute(
                """INSERT INTO search_events
                (request_id, submitted_symbol, normalized_symbol, asset_type, status, is_repeat,
                 run_id, submitted_at, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    request_id,
                    submitted_symbol[:64],
                    symbol,
                    asset_type,
                    "repeated" if repeated else "successful",
                    int(repeated),
                    run_id,
                    submitted_at.isoformat(),
                    completed_at.isoformat(),
                ),
            )
            connection.commit()
            return int(event_cursor.lastrowid), run_id, repeated, reused

    def history(
        self,
        *,
        query: str = "",
        status: str | None = None,
        asset_type: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """Return bounded newest-first history and a stable total for pagination."""

        if not 1 <= page <= 10_000 or not 1 <= page_size <= 100:
            raise ValueError("history page must be 1-10000 and page_size must be 1-100")
        if len(query) > 30:
            raise ValueError("history query must not exceed 30 characters")
        clauses = ["1 = 1"]
        values: list[Any] = []
        if query:
            clauses.append(
                "(normalized_symbol LIKE ? ESCAPE '\\' OR submitted_symbol LIKE ? ESCAPE '\\')"
            )
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            values.extend([f"%{escaped}%", f"%{escaped}%"])
        if status:
            clauses.append("status = ?")
            values.append(status)
        if asset_type:
            clauses.append("asset_type = ?")
            values.append(asset_type)
        where = " AND ".join(clauses)
        with self.connect() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM search_events WHERE {where}",  # noqa: S608
                    values,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""SELECT id, request_id, submitted_symbol, normalized_symbol, asset_type,
                status, is_repeat, error_code, error_message, submitted_at, completed_at, run_id
                FROM search_events WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?""",  # noqa: S608
                [*values, page_size, (page - 1) * page_size],
            ).fetchall()
        return {
            "items": [dict(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    def reconstruction(self, event_id: int) -> dict[str, Any] | None:
        """Reconstruct what was displayed from immutable JSON and later append-only outcomes."""

        with self.connect() as connection:
            event = connection.execute(
                "SELECT * FROM search_events WHERE id = ?", (event_id,)
            ).fetchone()
            if event is None:
                return None
            response: dict[str, Any] = {"event": dict(event), "input": None, "results": []}
            if event["run_id"] is None:
                return response
            input_row = connection.execute(
                "SELECT * FROM forecast_inputs WHERE run_id = ?", (event["run_id"],)
            ).fetchone()
            if input_row is None:
                return response
            response["input"] = {"id": input_row["id"], **json.loads(input_row["snapshot_json"])}
            result_rows = connection.execute(
                "SELECT * FROM forecast_results WHERE input_id = ? ORDER BY id", (input_row["id"],)
            ).fetchall()
            for row in result_rows:
                outcomes = connection.execute(
                    "SELECT * FROM outcomes WHERE result_id = ? ORDER BY id DESC LIMIT ?",
                    (row["id"], OUTCOME_RECONSTRUCTION_LIMIT + 1),
                ).fetchall()
                outcomes_truncated = len(outcomes) > OUTCOME_RECONSTRUCTION_LIMIT
                # Keep the newest bounded window but return it in append order for audit reading.
                bounded_outcomes = list(reversed(outcomes[:OUTCOME_RECONSTRUCTION_LIMIT]))
                response["results"].append(
                    {
                        "id": row["id"],
                        "recorded_at": row["created_at"],
                        **json.loads(row["result_json"]),
                        "outcomes": [dict(item) for item in bounded_outcomes],
                        "outcomes_truncated": outcomes_truncated,
                    }
                )
            return response

    def forecast_result(self, result_id: int) -> dict[str, Any] | None:
        """Return one immutable result for domain-level outcome validation."""

        with self.connect() as connection:
            row = connection.execute(
                "SELECT result_json FROM forecast_results WHERE id = ?", (result_id,)
            ).fetchone()
        return json.loads(row["result_json"]) if row is not None else None

    def append_outcome(
        self,
        result_id: int,
        observed_close: float | None,
        observed_return: float | None,
        observed_at: datetime,
        state: str,
        note: str,
        comparison_rule: str,
        created_at: datetime,
    ) -> dict[str, Any] | None:
        """Persist an already validated observation without mutating its forecast."""

        with self.connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM forecast_results WHERE id = ?", (result_id,)
            ).fetchone()
            if exists is None:
                return None
            created_at_text = created_at.astimezone(UTC).isoformat()
            cursor = connection.execute(
                """INSERT INTO outcomes
                (result_id, observed_close, observed_return, observed_at,
                 comparison_rule, state, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result_id,
                    observed_close,
                    observed_return,
                    observed_at.isoformat(),
                    comparison_rule,
                    state,
                    note,
                    created_at_text,
                ),
            )
            connection.commit()
            return {
                "id": int(cursor.lastrowid),
                "result_id": result_id,
                "observed_close": observed_close,
                "observed_return": observed_return,
                "observed_at": observed_at.isoformat(),
                "state": state,
                "note": note,
                "created_at": created_at_text,
                "comparison_rule": comparison_rule,
            }

    def representative_counts(self, database_path: Path | None = None) -> dict[str, int]:
        """Use a fixed table allowlist so backup manifests cannot inject SQL identifiers."""

        path = database_path or self.database_path
        connection = sqlite3.connect(path)
        try:
            return {
                table: int(
                    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
                )
                for table in (
                    "search_events",
                    "forecast_runs",
                    "forecast_inputs",
                    "forecast_results",
                    "outcomes",
                )
            }
        finally:
            connection.close()
