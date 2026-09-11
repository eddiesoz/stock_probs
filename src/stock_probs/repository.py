"""SQLite migration and repositories enforce durable append-only audit behavior."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext, suppress
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Final, TypedDict, TypeGuard, cast

from stock_probs.config import ensure_private_directory, ensure_private_file

SCHEMA_VERSION = 3
OUTCOME_RECONSTRUCTION_LIMIT = 100
COORDINATION_TIMEOUT_SECONDS = 5.0
MIGRATION_NAME = re.compile(r"^(?P<version>[0-9]{3})_[a-z0-9_]+\.sql$")
PERSISTENCE_FAILURE_CATEGORY = "persistence_unavailable"
# Digests make shipped migrations immutable; changing any SQL file requires a new number.
MIGRATION_SHA256 = {
    1: "0c92dcfb596b6a1b1ce07cf6b4bca15c00f642c7ca69ea5e41e124b49926c98e",
    2: "d51a8a64f5c32fb77875f0e81642146947be3db43437a1269339343e64225cc2",
    3: "ebbf91670e8ad0a4f9a80603459c4eb1d2e66459cda500d5c376b1d563949cda",
}


class _RepresentativeStorageCounts(TypedDict):
    """Private physical-row counts used for backup integrity, not domain/API vocabulary."""

    search_events: int
    forecast_runs: int
    forecast_inputs: int
    forecast_results: int
    outcomes: int


# Keep the SQL allowlist and authenticated manifest shape on one persistence-owned contract.
_REPRESENTATIVE_STORAGE_TABLES: Final = (
    "search_events",
    "forecast_runs",
    "forecast_inputs",
    "forecast_results",
    "outcomes",
)
_REPRESENTATIVE_STORAGE_KEYS: Final = frozenset(_REPRESENTATIVE_STORAGE_TABLES)


def _is_representative_storage_counts(value: object) -> TypeGuard[_RepresentativeStorageCounts]:
    """Validate exact internal table keys and non-negative, non-boolean physical row counts."""

    return (
        isinstance(value, dict)
        and set(value) == _REPRESENTATIVE_STORAGE_KEYS
        and all(type(count) is int and count >= 0 for count in value.values())
    )

# Repository and backup objects for one database must coordinate around atomic restore. The
# registry lock is held only while resolving an RLock, so unrelated databases never serialize.
_DATABASE_LOCKS: dict[Path, RLock] = {}
_DATABASE_LOCKS_GUARD = Lock()


class RepositoryError(sqlite3.Error):
    """Base for controlled persistence failures with API-safe classification only."""

    public_category = PERSISTENCE_FAILURE_CATEGORY


class RepositoryOperationalError(sqlite3.OperationalError, RepositoryError):
    """Hide low-level path/SQLite text while retaining it in the exception chain."""


class RepositoryDatabaseError(sqlite3.DatabaseError, RepositoryError):
    """Report controlled migration/schema diagnostics through the same safe category."""


def _database_lock(path: Path) -> tuple[Path, RLock]:
    canonical_path = path.expanduser().resolve(strict=False)
    with _DATABASE_LOCKS_GUARD:
        return canonical_path, _DATABASE_LOCKS.setdefault(canonical_path, RLock())


class Repository:
    """Open short-lived WAL connections so one local process remains restart-safe."""

    def __init__(self, database_path: Path):
        try:
            self.database_path, self._lock = _database_lock(database_path)
        except (OSError, RuntimeError) as exc:
            raise RepositoryOperationalError(
                "Local database location could not be resolved safely."
            ) from exc

    @contextmanager
    def _coordinated(self) -> Iterator[None]:
        """Bound waits on the per-database process lock rather than hanging local operations."""

        if not self._lock.acquire(timeout=COORDINATION_TIMEOUT_SECONDS):
            raise RepositoryOperationalError("database coordination lock timed out")
        try:
            yield
        finally:
            self._lock.release()

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
        with self._coordinated():
            connection: sqlite3.Connection | None = None
            try:
                # Prepare with no-follow descriptors before SQLite can open a permissive or linked
                # file. Raw OS/SQLite messages remain chained for operator diagnosis, while the
                # outer exception is safe for normal repr and structured public classification.
                ensure_private_directory(self.database_path.parent)
                self._harden_sqlite_files(create_database=True)
                connection = sqlite3.connect(self.database_path, timeout=5.0)
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys = ON")
                # SQLite REPLACE fires delete triggers only with recursive triggers enabled.
                connection.execute("PRAGMA recursive_triggers = ON")
                connection.execute("PRAGMA busy_timeout = 5000")
                self._harden_sqlite_files(create_database=False)
            except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
                if connection is not None:
                    # The original preparation failure remains the useful chained diagnosis.
                    with suppress(sqlite3.Error):
                        connection.close()
                raise RepositoryOperationalError(
                    "Local database connection could not be prepared safely."
                ) from exc
            try:
                yield connection
            finally:
                try:
                    connection.close()
                except sqlite3.Error as exc:
                    raise RepositoryOperationalError(
                        "Local database connection could not be closed safely."
                    ) from exc
                # SQLite may replace/create its own files, so reassert the active file mode.
                try:
                    self._harden_sqlite_files(create_database=False)
                except (OSError, ValueError) as exc:
                    raise RepositoryOperationalError(
                        "Local database files could not be secured after use."
                    ) from exc

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        """Hold the repository lock across multi-step backup or restore operations."""

        with self._coordinated():
            yield

    def migrate(self) -> None:
        """Validate and append each packaged migration in its own exclusive transaction."""

        try:
            ensure_private_directory(self.database_path.parent)
        except (OSError, ValueError) as exc:
            raise RepositoryOperationalError(
                "Local database storage could not be prepared for migration."
            ) from exc
        migration_dir = files("stock_probs.migrations")
        packaged: list[tuple[int, str, str]] = []
        for migration in sorted(migration_dir.iterdir(), key=lambda item: item.name):
            if not migration.name.endswith(".sql"):
                continue
            match = MIGRATION_NAME.fullmatch(migration.name)
            if match is None:
                raise RepositoryDatabaseError(
                    f"invalid packaged migration name: {migration.name}"
                )
            version = int(match.group("version"))
            script = migration.read_text()
            digest = hashlib.sha256(script.encode()).hexdigest()
            if MIGRATION_SHA256.get(version) != digest:
                raise RepositoryDatabaseError(
                    f"packaged migration {version:03d} failed its immutable checksum"
                )
            packaged.append((version, migration.name, script))
        versions = [version for version, _, _ in packaged]
        if versions != list(range(1, SCHEMA_VERSION + 1)):
            raise RepositoryDatabaseError("packaged migrations must be contiguous and complete")

        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            connection.commit()

        for version, _, script in packaged:
            # BEGIN IMMEDIATE serializes separate Repository instances. The applied check
            # occurs after taking the database lock, avoiding a check-then-apply race.
            with self.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    applied = [
                        int(row[0])
                        for row in connection.execute(
                            "SELECT version FROM schema_migrations ORDER BY version"
                        )
                    ]
                    if applied != list(range(1, len(applied) + 1)) or any(
                        item > SCHEMA_VERSION for item in applied
                    ):
                        raise RepositoryDatabaseError(
                            "database migration history is non-contiguous or newer than this app"
                        )
                    if version in applied:
                        connection.rollback()
                        continue
                    if version != len(applied) + 1:
                        raise RepositoryDatabaseError("database migration history has a gap")
                    self._execute_migration(connection, script)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (version, datetime.now(UTC).isoformat()),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise

    @staticmethod
    def _execute_migration(connection: sqlite3.Connection, script: str) -> None:
        """Execute complete SQLite statements without executescript's implicit commit."""

        statement = ""
        for line in script.splitlines(keepends=True):
            statement += line
            if sqlite3.complete_statement(statement):
                connection.execute(statement)
                statement = ""
        if statement.strip():
            raise RepositoryDatabaseError(
                "packaged migration ends with an incomplete statement"
            )

    @staticmethod
    def _json(value: Any) -> str:
        # Forecast/domain objects cross this boundary only after explicit serialization. Rejecting
        # NaN and unknown objects prevents SQLite from preserving non-portable pseudo-JSON.
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)

    @staticmethod
    def _insert_id(cursor: sqlite3.Cursor) -> int:
        """Make SQLite's optional typing explicit for successful INSERT statements."""

        row_id = cursor.lastrowid
        if row_id is None:
            raise RepositoryDatabaseError("SQLite INSERT did not produce a row identifier")
        return row_id

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
        analysis_kind: str = "submitted_forecast",
        source_event_id: int | None = None,
        requested_cutoff: datetime | None = None,
    ) -> int:
        """A provider/domain failure still commits exactly one complete search event."""

        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            resolved_source_event_id = self._resolved_analysis_source(
                connection, analysis_kind, source_event_id
            )
            repeated = self._has_prior_submission(
                connection, submitted_symbol, normalized_symbol, asset_type
            )
            cursor = connection.execute(
                """INSERT INTO search_events
                (request_id, submitted_symbol, normalized_symbol, asset_type, status, is_repeat,
                  error_code, error_message, submitted_at, completed_at, analysis_kind,
                  source_event_id, requested_cutoff, requested_source_event_id)
                VALUES (?, ?, ?, ?, 'failed', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    analysis_kind,
                    resolved_source_event_id,
                    requested_cutoff.isoformat() if requested_cutoff is not None else None,
                    source_event_id,
                ),
            )
            connection.commit()
            return self._insert_id(cursor)

    @staticmethod
    def _resolved_analysis_source(
        connection: sqlite3.Connection,
        analysis_kind: str,
        requested_source_event_id: int | None,
    ) -> int | None:
        """Use an FK only for a real successful source while retaining the requested ID."""

        if analysis_kind != "fresh_historical_reconstruction":
            return requested_source_event_id
        if type(requested_source_event_id) is not int or requested_source_event_id < 1:
            return None
        row = connection.execute(
            "SELECT id FROM search_events WHERE id = ? AND run_id IS NOT NULL",
            (requested_source_event_id,),
        ).fetchone()
        return int(row["id"]) if row is not None else None

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
        analysis_kind: str = "submitted_forecast",
        source_event_id: int | None = None,
        requested_cutoff: datetime | None = None,
        reuse_exact_input: bool = True,
    ) -> tuple[int, int, bool, bool]:
        """Append a repeated event while reusing only an exact immutable input snapshot."""

        self._validate_instrument_provenance(input_snapshot, asset_type)
        self._validate_forecast_contract(input_snapshot, results)
        symbol = input_snapshot["symbol"]
        fingerprint = input_snapshot["content_fingerprint"]
        horizons = [result.get("horizon") for result in results]
        if (
            len(horizons) != 2
            or horizons.count("close_to_close") != 1
            or horizons.count("completed_5m_to_close") != 1
        ):
            raise ValueError("exactly one result for each supported horizon is required")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            resolved_source_event_id = self._resolved_analysis_source(
                connection, analysis_kind, source_event_id
            )
            prior = (
                connection.execute(
                    "SELECT id FROM forecast_runs "
                    "WHERE symbol = ? AND asset_type = ? AND content_fingerprint = ?",
                    (symbol, asset_type, fingerprint),
                ).fetchone()
                if reuse_exact_input
                else None
            )
            repeated = self._has_prior_submission(
                connection, submitted_symbol, symbol, asset_type
            )
            reused = prior is not None
            if prior is not None:
                run_id = int(prior["id"])
            else:
                run_cursor = connection.execute(
                    "INSERT INTO forecast_runs"
                    "(symbol, asset_type, content_fingerprint, created_at) VALUES (?, ?, ?, ?)",
                    (symbol, asset_type, fingerprint, completed_at.isoformat()),
                )
                run_id = self._insert_id(run_cursor)
                input_cursor = connection.execute(
                    "INSERT INTO forecast_inputs"
                    "(run_id, snapshot_json, created_at) VALUES (?, ?, ?)",
                    (run_id, self._json(input_snapshot), completed_at.isoformat()),
                )
                input_id = self._insert_id(input_cursor)
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
                  run_id, submitted_at, completed_at, analysis_kind, source_event_id,
                   requested_cutoff, requested_source_event_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    analysis_kind,
                    resolved_source_event_id,
                    requested_cutoff.isoformat() if requested_cutoff is not None else None,
                    source_event_id,
                ),
            )
            connection.commit()
            return self._insert_id(event_cursor), run_id, repeated, reused

    @staticmethod
    def _validate_instrument_provenance(
        input_snapshot: dict[str, Any], asset_type: str
    ) -> None:
        """Reject writes that detach selected identity from the immutable provider snapshot."""

        identity = input_snapshot.get("instrument_identity")
        provenance = input_snapshot.get("provenance")
        required = {
            "canonical_symbol",
            "display_name",
            "company_name",
            "exchange",
            "currency",
            "timezone",
            "quote_type",
            "asset_type",
            "provider",
            "provider_as_of",
        }
        identity_fingerprint = (
            hashlib.sha256(
                json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if isinstance(identity, dict)
            else None
        )
        if (
            not isinstance(identity, dict)
            or not required <= set(identity)
            or not isinstance(provenance, dict)
            or provenance.get("instrument_identity") != identity
            or identity.get("canonical_symbol") != input_snapshot.get("symbol")
            or identity.get("canonical_symbol") != input_snapshot.get("canonical_symbol")
            or identity.get("display_name") != input_snapshot.get("display_name")
            or identity.get("company_name") != input_snapshot.get("company_name")
            or identity.get("asset_type") != asset_type
            or identity.get("exchange") != input_snapshot.get("exchange")
            or identity.get("currency") != input_snapshot.get("currency")
            or identity.get("timezone") != input_snapshot.get("exchange_timezone")
            or identity.get("quote_type") != input_snapshot.get("quote_type")
            or identity.get("provider") != input_snapshot.get("provider")
            or identity.get("provider_as_of") != input_snapshot.get("provider_as_of")
            or provenance.get("identity_fingerprint")
            != input_snapshot.get("identity_fingerprint")
            or input_snapshot.get("identity_fingerprint") != identity_fingerprint
            or provenance.get("content_fingerprint")
            != input_snapshot.get("content_fingerprint")
        ):
            raise ValueError("instrument identity must match immutable forecast provenance")

    @staticmethod
    def _validate_forecast_contract(
        input_snapshot: dict[str, Any], results: list[dict[str, Any]]
    ) -> None:
        """Reject detached model metadata or result digests before immutable insertion."""

        provenance = input_snapshot.get("provenance")
        model_fingerprint = input_snapshot.get("model_fingerprint")
        contract_version = input_snapshot.get("forecast_contract_version")
        content_fingerprint = input_snapshot.get("content_fingerprint")
        model_payload = {
            "contract_version": contract_version,
            "model": input_snapshot.get("model"),
            "parameters": input_snapshot.get("parameters"),
            "calendar": input_snapshot.get("calendar"),
        }
        calculated_model_fingerprint = hashlib.sha256(
            json.dumps(
                model_payload, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
        if (
            not isinstance(provenance, dict)
            or provenance.get("model_fingerprint") != model_fingerprint
            or provenance.get("forecast_contract_version") != contract_version
            or not Repository._is_sha256(model_fingerprint)
            or not Repository._is_sha256(content_fingerprint)
            or model_fingerprint != calculated_model_fingerprint
        ):
            raise ValueError(
                "forecast model and content provenance must be complete and consistent"
            )
        for result in results:
            expected = result.get("forecast_fingerprint")
            fingerprint_payload = dict(result)
            fingerprint_payload.pop("forecast_fingerprint", None)
            calculated = hashlib.sha256(
                json.dumps(
                    fingerprint_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode()
            ).hexdigest()
            evaluation = result.get("evaluation")
            if (
                result.get("model_fingerprint") != model_fingerprint
                or result.get("forecast_contract_version") != contract_version
                or expected != calculated
                or not isinstance(evaluation, dict)
                or evaluation.get("method")
                != "bounded chronological expanding-window walk-forward"
            ):
                raise ValueError(
                    "forecast result must match immutable model and evaluation provenance"
                )

    @staticmethod
    def _is_sha256(value: object) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )

    def history(
        self,
        *,
        query: str = "",
        status: str | None = None,
        asset_type: str | None = None,
        page: int = 1,
        page_size: int = 20,
        analysis_kind: str | None = None,
        include_analysis: bool = False,
    ) -> dict[str, Any]:
        """Return bounded newest-first history and a stable total for pagination."""

        if not 1 <= page <= 10_000 or not 1 <= page_size <= 100:
            raise ValueError("history page must be 1-10000 and page_size must be 1-100")
        if len(query) > 30:
            raise ValueError("history query must not exceed 30 characters")
        if status not in {None, "successful", "failed", "repeated"}:
            raise ValueError("history status is not supported")
        if asset_type not in {None, "stock", "etf"}:
            raise ValueError("history asset_type is not supported")
        if analysis_kind not in {
            None,
            "submitted_forecast",
            "fresh_historical_reconstruction",
        }:
            raise ValueError("history analysis_kind is not supported")
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
        if analysis_kind:
            clauses.append("analysis_kind = ?")
            values.append(analysis_kind)
        where = " AND ".join(clauses)
        analysis_columns = (
            ", analysis_kind, source_event_id, requested_cutoff, requested_source_event_id"
            if include_analysis
            else ""
        )
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
                {analysis_columns}
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
                """SELECT id, request_id, submitted_symbol, normalized_symbol, asset_type,
                status, is_repeat, error_code, error_message, run_id, submitted_at, completed_at,
                analysis_kind, source_event_id, requested_cutoff, requested_source_event_id
                FROM search_events WHERE id = ?""",
                (event_id,),
            ).fetchone()
            if event is None:
                return None
            event_payload = dict(event)
            # Preserve compatibility for ordinary saved reopen. Fresh records retain explicit
            # fields and therefore cannot be mistaken for replay of an original submission.
            if event_payload["analysis_kind"] == "submitted_forecast":
                for key in (
                    "analysis_kind",
                    "source_event_id",
                    "requested_cutoff",
                    "requested_source_event_id",
                ):
                    event_payload.pop(key)
            response: dict[str, Any] = {"event": event_payload, "input": None, "results": []}
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
                "id": self._insert_id(cursor),
                "result_id": result_id,
                "observed_close": observed_close,
                "observed_return": observed_return,
                "observed_at": observed_at.isoformat(),
                "state": state,
                "note": note,
                "created_at": created_at_text,
                "comparison_rule": comparison_rule,
            }

    def representative_counts(
        self, database_path: Path | None = None
    ) -> _RepresentativeStorageCounts:
        """Count fixed internal storage tables; these keys are not domain record vocabulary."""

        path = database_path or self.database_path
        # Staging databases are private to backup code; only the active canonical path shares
        # the promotion lock with independent repository and manager instances.
        try:
            coordinated = path.expanduser().resolve(strict=False) == self.database_path
        except (OSError, RuntimeError) as exc:
            raise RepositoryOperationalError(
                "Representative database location could not be resolved safely."
            ) from exc
        lock_context = self._coordinated() if coordinated else nullcontext()
        with lock_context:
            connection: sqlite3.Connection | None = None
            try:
                connection = sqlite3.connect(path)
                counts = {
                    table: int(
                        connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
                    )
                    for table in _REPRESENTATIVE_STORAGE_TABLES
                }
                # Construction from the fixed allowlist narrows this beyond dict[str, int].
                return cast(_RepresentativeStorageCounts, counts)
            except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
                raise RepositoryOperationalError(
                    "Representative database counts could not be read."
                ) from exc
            finally:
                if connection is not None:
                    try:
                        connection.close()
                    except sqlite3.Error as exc:
                        raise RepositoryOperationalError(
                            "Representative database connection could not be closed safely."
                        ) from exc
