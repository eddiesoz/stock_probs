"""SQLite migration and repositories enforce durable append-only audit behavior."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext, suppress
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Final, TypedDict, TypeGuard, cast

from stock_probs.config import ensure_private_directory, ensure_private_file
from stock_probs.domain import HistoryFilters

SCHEMA_VERSION = 4
OUTCOME_RECONSTRUCTION_LIMIT = 100
HISTORY_EXPORT_LIMIT = 100
COORDINATION_TIMEOUT_SECONDS = 5.0
MIGRATION_NAME = re.compile(r"^(?P<version>[0-9]{3})_[a-z0-9_]+\.sql$")
PERSISTENCE_FAILURE_CATEGORY = "persistence_unavailable"
# Digests make shipped migrations immutable; changing any SQL file requires a new number.
MIGRATION_SHA256 = {
    1: "0c92dcfb596b6a1b1ce07cf6b4bca15c00f642c7ca69ea5e41e124b49926c98e",
    2: "d51a8a64f5c32fb77875f0e81642146947be3db43437a1269339343e64225cc2",
    3: "ebbf91670e8ad0a4f9a80603459c4eb1d2e66459cda500d5c376b1d563949cda",
    4: "4ca9d80a988f59c2c0c289ac34efffc5df170053c0b968180f85fbdf6edc17ea",
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

    def migrate(self, before_migration: Callable[[int], None] | None = None) -> None:
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

        backup_completed = False
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
                    if applied and before_migration is not None and not backup_completed:
                        # The hook runs under the migration write lock, immediately before the
                        # first upgrade, so a failed backup prevents every pending schema change.
                        before_migration(applied[-1])
                        backup_completed = True
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

    @staticmethod
    def _utc_microseconds(value: datetime) -> int:
        """Return an exact integer UTC key without a float timestamp conversion."""

        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("stored audit timestamps must include a timezone offset")
        utc_value = value.astimezone(UTC)
        epoch_delta = utc_value - datetime(1970, 1, 1, tzinfo=UTC)
        return (
            (epoch_delta.days * 86_400 + epoch_delta.seconds) * 1_000_000
            + epoch_delta.microseconds
        )

    @staticmethod
    def _record_history_facet(
        connection: sqlite3.Connection,
        *,
        event_id: int,
        submitted_at: datetime,
        normalized_symbol: str | None,
        input_snapshot: dict[str, Any] | None,
    ) -> None:
        """Append the small indexed projection in the same transaction as its audit event."""

        identity = input_snapshot.get("instrument_identity") if input_snapshot else None
        model = input_snapshot.get("model") if input_snapshot else None
        connection.execute(
            """INSERT INTO history_facets
            (event_id, canonical_symbol, display_name, company_name, exchange, quote_type,
             model_name, model_version, forecast_contract_version, submitted_at_us)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                (
                    identity.get("canonical_symbol")
                    if isinstance(identity, dict)
                    else normalized_symbol
                ),
                identity.get("display_name") if isinstance(identity, dict) else None,
                identity.get("company_name") if isinstance(identity, dict) else None,
                identity.get("exchange") if isinstance(identity, dict) else None,
                identity.get("quote_type") if isinstance(identity, dict) else None,
                model.get("name") if isinstance(model, dict) else None,
                model.get("version") if isinstance(model, dict) else None,
                input_snapshot.get("forecast_contract_version") if input_snapshot else None,
                Repository._utc_microseconds(submitted_at),
            ),
        )

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
            event_id = self._insert_id(cursor)
            self._record_history_facet(
                connection,
                event_id=event_id,
                submitted_at=submitted_at,
                normalized_symbol=normalized_symbol,
                input_snapshot=None,
            )
            connection.commit()
            return event_id

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
            event_id = self._insert_id(event_cursor)
            self._record_history_facet(
                connection,
                event_id=event_id,
                submitted_at=submitted_at,
                normalized_symbol=symbol,
                input_snapshot=input_snapshot,
            )
            connection.commit()
            return event_id, run_id, repeated, reused

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
        symbol: str | None = None,
        company: str | None = None,
        semantics: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        model: str | None = None,
        model_version: str | None = None,
        request_id: str | None = None,
        event_id: int | None = None,
        include_facets: bool = False,
    ) -> dict[str, Any]:
        """Return an indexed, bounded audit page in deterministic append order."""

        if type(page) is not int or type(page_size) is not int:
            raise ValueError("history page and page_size must be integers")
        if not 1 <= page <= 10_000 or not 1 <= page_size <= 100:
            raise ValueError("history page must be 1-10000 and page_size must be 1-100")
        filters = HistoryFilters(
            query=query,
            symbol=symbol,
            company=company,
            asset_type=asset_type,
            status=status,
            semantics=semantics,
            date_from=date_from,
            date_to=date_to,
            model=model,
            model_version=model_version,
            request_id=request_id,
            analysis_kind=analysis_kind,
            event_id=event_id,
        )
        with self.connect() as connection:
            # COUNT and page rows share one snapshot, so concurrent appends cannot disagree about
            # this response's total even when another local process bypasses the process lock.
            connection.execute("BEGIN")
            return self._history_page(
                connection,
                filters,
                page=page,
                page_size=page_size,
                include_analysis=include_analysis,
                include_facets=include_facets,
            )

    @staticmethod
    def _escaped_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    @classmethod
    def _history_where(cls, filters: HistoryFilters) -> tuple[str, list[Any]]:
        """Compile only fixed clauses; user values always remain bound parameters."""

        clauses = ["1 = 1"]
        values: list[Any] = []
        if filters.query:
            clauses.append(
                "(event.normalized_symbol LIKE ? ESCAPE '\\' COLLATE NOCASE "
                "OR event.submitted_symbol LIKE ? ESCAPE '\\' COLLATE NOCASE "
                "OR event.request_id LIKE ? ESCAPE '\\' COLLATE NOCASE "
                "OR facet.company_name LIKE ? ESCAPE '\\' COLLATE NOCASE "
                "OR facet.display_name LIKE ? ESCAPE '\\' COLLATE NOCASE)"
            )
            match = f"%{cls._escaped_like(filters.query)}%"
            values.extend([match] * 5)
        if filters.symbol:
            clauses.append("facet.canonical_symbol = ? COLLATE NOCASE")
            values.append(filters.symbol)
        if filters.company:
            clauses.append("facet.company_name LIKE ? ESCAPE '\\' COLLATE NOCASE")
            values.append(f"%{cls._escaped_like(filters.company.strip())}%")
        if filters.status:
            clauses.append("event.status = ?")
            values.append(filters.status)
        if filters.asset_type:
            clauses.append("event.asset_type = ?")
            values.append(filters.asset_type)
        if filters.analysis_kind:
            clauses.append("event.analysis_kind = ?")
            values.append(filters.analysis_kind)
        semantic_clauses = {
            "success": "event.run_id IS NOT NULL",
            "failure": "event.status = 'failed'",
            # is_repeat also includes a repeated failed submission, unlike status='repeated'.
            "repeat": "event.is_repeat = 1",
            "fresh": "event.analysis_kind = 'fresh_historical_reconstruction'",
            "saved": (
                "event.analysis_kind = 'submitted_forecast' AND event.run_id IS NOT NULL"
            ),
        }
        if filters.semantics:
            clauses.append(semantic_clauses[filters.semantics])
        if filters.date_from:
            clauses.append("facet.submitted_at_us >= ?")
            values.append(cls._utc_microseconds(filters.date_from))
        if filters.date_to:
            clauses.append("facet.submitted_at_us <= ?")
            values.append(cls._utc_microseconds(filters.date_to))
        if filters.model:
            clauses.append(
                "(facet.model_name LIKE ? ESCAPE '\\' COLLATE NOCASE "
                "OR facet.model_version LIKE ? ESCAPE '\\' COLLATE NOCASE)"
            )
            model_match = f"%{cls._escaped_like(filters.model)}%"
            values.extend([model_match, model_match])
        if filters.model_version:
            clauses.append("facet.model_version = ? COLLATE NOCASE")
            values.append(filters.model_version.strip())
        if filters.request_id:
            clauses.append("event.request_id = ?")
            values.append(filters.request_id.strip())
        if filters.event_id is not None:
            # Apply exact identity in the indexed source query, before pagination/export limits.
            clauses.append("event.id = ?")
            values.append(filters.event_id)
        return " AND ".join(clauses), values

    @classmethod
    def _history_page(
        cls,
        connection: sqlite3.Connection,
        filters: HistoryFilters,
        *,
        page: int,
        page_size: int,
        include_analysis: bool,
        include_facets: bool,
        sort_by: str | None = None,
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        where, values = cls._history_where(filters)
        analysis_columns = (
            ", event.analysis_kind, event.source_event_id, event.requested_cutoff, "
            "event.requested_source_event_id"
            if include_analysis
            else ""
        )
        facet_columns = (
            ", facet.canonical_symbol, facet.display_name, facet.company_name, facet.exchange, "
            "facet.quote_type, facet.model_name, facet.model_version, "
            "facet.forecast_contract_version"
            if include_facets
            else ""
        )
        joined = (
            "search_events AS event LEFT JOIN history_facets AS facet "
            "ON facet.event_id = event.id"
        )
        total = int(
            connection.execute(
                f"SELECT COUNT(*) FROM {joined} WHERE {where}",  # noqa: S608
                values,
            ).fetchone()[0]
        )
        if sort_by is None:
            order_by = "facet.submitted_at_us DESC, event.id DESC"
        else:
            sort_expressions = {
                "event_id": "event.id",
                "submitted_at": "event.submitted_at COLLATE NOCASE",
                "completed_at": "event.completed_at COLLATE NOCASE",
                "symbol": (
                    "COALESCE(event.normalized_symbol, event.submitted_symbol) COLLATE NOCASE"
                ),
                "company": "facet.company_name COLLATE NOCASE",
                "asset_type": "event.asset_type COLLATE NOCASE",
                "status": "event.status COLLATE NOCASE",
                "model": "COALESCE(facet.model_version, facet.model_name) COLLATE NOCASE",
                "horizon": (
                    "CASE WHEN event.run_id IS NOT NULL "
                    "THEN 'close_to_close,completed_5m_to_close' END"
                ),
                "request_id": "event.request_id COLLATE NOCASE",
            }
            if sort_by not in sort_expressions or sort_order not in {"asc", "desc"}:
                raise ValueError("history export sort is not supported")
            expression = sort_expressions[sort_by]
            # Missing display facets stay last; event ID is the stable tie-breaker.
            order_by = f"({expression}) IS NULL, {expression} {sort_order.upper()}, event.id ASC"
        rows = connection.execute(
            f"""SELECT event.id, event.request_id, event.submitted_symbol,
            event.normalized_symbol, event.asset_type, event.status, event.is_repeat,
            event.error_code, event.error_message, event.submitted_at, event.completed_at,
            event.run_id {analysis_columns} {facet_columns}
            FROM {joined} WHERE {where}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?""",  # noqa: S608
            [*values, page_size, (page - 1) * page_size],
        ).fetchall()
        return {
            "items": [dict(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    def reconstruction(self, event_id: int) -> dict[str, Any] | None:
        """Reconstruct immutable display data with a fixed number of bounded queries."""

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
            details = self._load_run_details(connection, [int(event["run_id"])])
            detail = details.get(int(event["run_id"]))
            if detail is None:
                return response
            response["input"] = detail["input"]
            response["results"] = detail["results"]
            return response

    @classmethod
    def _load_run_details(
        cls, connection: sqlite3.Connection, run_ids: list[int]
    ) -> dict[int, dict[str, Any]]:
        """Load up to one export page in three queries, independent of event count."""

        if not run_ids:
            return {}
        if len(run_ids) > HISTORY_EXPORT_LIMIT:
            raise ValueError("history detail batch exceeds the export bound")
        placeholders = ",".join("?" for _ in run_ids)
        input_rows = connection.execute(
            f"""SELECT id, run_id, snapshot_json FROM forecast_inputs
            WHERE run_id IN ({placeholders})""",  # noqa: S608
            run_ids,
        ).fetchall()
        details: dict[int, dict[str, Any]] = {
            int(row["run_id"]): {
                "input": {"id": row["id"], **json.loads(row["snapshot_json"])},
                "results": [],
            }
            for row in input_rows
        }
        input_to_run = {int(row["id"]): int(row["run_id"]) for row in input_rows}
        if not input_to_run:
            return details
        input_ids = list(input_to_run)
        input_placeholders = ",".join("?" for _ in input_ids)
        result_rows = connection.execute(
            f"""SELECT id, input_id, result_json, created_at FROM forecast_results
            WHERE input_id IN ({input_placeholders}) ORDER BY input_id, id""",  # noqa: S608
            input_ids,
        ).fetchall()
        result_ids = [int(row["id"]) for row in result_rows]
        outcomes_by_result: dict[int, list[dict[str, Any]]] = {item: [] for item in result_ids}
        if result_ids:
            result_placeholders = ",".join("?" for _ in result_ids)
            # Window ranking bounds returned memory per result while retaining a truncation row.
            outcome_rows = connection.execute(
                f"""WITH ranked AS (
                    SELECT id, result_id, observed_close, observed_return, observed_at,
                           comparison_rule, state, note, created_at,
                           ROW_NUMBER() OVER (PARTITION BY result_id ORDER BY id DESC) AS rank
                    FROM outcomes WHERE result_id IN ({result_placeholders})
                )
                SELECT id, result_id, observed_close, observed_return, observed_at,
                       comparison_rule, state, note, created_at, rank
                FROM ranked WHERE rank <= ? ORDER BY result_id, id DESC""",  # noqa: S608
                [*result_ids, OUTCOME_RECONSTRUCTION_LIMIT + 1],
            ).fetchall()
            for row in outcome_rows:
                payload = dict(row)
                payload.pop("rank")
                outcomes_by_result[int(row["result_id"])].append(payload)
        for row in result_rows:
            result_id = int(row["id"])
            outcomes = outcomes_by_result[result_id]
            run_id = input_to_run[int(row["input_id"])]
            details[run_id]["results"].append(
                {
                    "id": result_id,
                    "recorded_at": row["created_at"],
                    **json.loads(row["result_json"]),
                    # Return the newest bounded window in chronological append order.
                    "outcomes": list(reversed(outcomes[:OUTCOME_RECONSTRUCTION_LIMIT])),
                    "outcomes_truncated": len(outcomes) > OUTCOME_RECONSTRUCTION_LIMIT,
                }
            )
        return details

    def history_export(
        self,
        *,
        generated_at: datetime,
        query: str = "",
        status: str | None = None,
        asset_type: str | None = None,
        analysis_kind: str | None = None,
        symbol: str | None = None,
        company: str | None = None,
        semantics: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        model: str | None = None,
        model_version: str | None = None,
        request_id: str | None = None,
        event_id: int | None = None,
        max_events: int = HISTORY_EXPORT_LIMIT,
        sort_by: str = "event_id",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        """Return one faithful bounded record stream without per-event detail queries."""

        if generated_at.tzinfo is None:
            raise ValueError("history export time must include a timezone offset")
        if type(max_events) is not int or not 1 <= max_events <= HISTORY_EXPORT_LIMIT:
            raise ValueError(f"history export max_events must be 1-{HISTORY_EXPORT_LIMIT}")
        filters = HistoryFilters(
            query=query,
            symbol=symbol,
            company=company,
            asset_type=asset_type,
            status=status,
            semantics=semantics,
            date_from=date_from,
            date_to=date_to,
            model=model,
            model_version=model_version,
            request_id=request_id,
            analysis_kind=analysis_kind,
            event_id=event_id,
        )
        with self.connect() as connection:
            connection.execute("BEGIN")
            page = self._history_page(
                connection,
                filters,
                page=1,
                page_size=max_events,
                include_analysis=True,
                include_facets=False,
                sort_by=sort_by,
                sort_order=sort_order,
            )
            run_ids = list(
                dict.fromkeys(
                    int(event["run_id"])
                    for event in page["items"]
                    if event["run_id"] is not None
                )
            )
            details = self._load_run_details(connection, run_ids)
            records: list[dict[str, Any]] = []
            seen_runs: set[int] = set()
            result_count = 0
            for event in page["items"]:
                event_id = int(event["id"])
                run_id = int(event["run_id"]) if event["run_id"] is not None else None
                records.append(
                    {
                        "record_type": "event",
                        "event_id": event_id,
                        "run_id": run_id,
                        "data": event,
                    }
                )
                if run_id is None or run_id in seen_runs:
                    continue
                detail = details.get(run_id)
                if detail is None:
                    raise RepositoryDatabaseError(
                        "forecast run is missing its immutable input"
                    )
                seen_runs.add(run_id)
                snapshot = detail["input"]
                input_id = int(snapshot["id"])
                records.append(
                    {
                        "record_type": "run",
                        "run_id": run_id,
                        "input_id": input_id,
                        "data": snapshot,
                    }
                )
                for result in detail["results"]:
                    result_count += 1
                    records.append(
                        {
                            "record_type": "result",
                            "run_id": run_id,
                            "input_id": input_id,
                            "result_id": int(result["id"]),
                            "data": result,
                        }
                    )
        exported_events = len(page["items"])
        return {
            "format": "stock-probs-history",
            "format_version": 1,
            "generated_at": generated_at.astimezone(UTC).isoformat(),
            "filters": {
                "query": filters.query,
                "symbol": filters.symbol,
                "company": filters.company,
                "status": filters.status,
                "asset_type": filters.asset_type,
                "semantics": filters.semantics,
                "date_from": (
                    filters.date_from.astimezone(UTC).isoformat() if filters.date_from else None
                ),
                "date_to": (
                    filters.date_to.astimezone(UTC).isoformat() if filters.date_to else None
                ),
                "model": filters.model,
                "model_version": filters.model_version,
                "request_id": filters.request_id,
                "analysis_kind": filters.analysis_kind,
                "event_id": filters.event_id,
            },
            "total_events": page["total"],
            "exported_events": exported_events,
            "truncated": page["total"] > exported_events,
            "counts": {
                "events": exported_events,
                "runs": len(seen_runs),
                "results": result_count,
            },
            "records": records,
        }

    def historical_series(
        self, event_id: int, *, series: str = "daily", limit: int = 120
    ) -> dict[str, Any] | None:
        """Slice immutable chart and text-equivalent prices to a caller-selected hard limit."""

        if series not in {"daily", "intraday"}:
            raise ValueError("history price series is not supported")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("history price limit must be 1-500")
        detail = self.reconstruction(event_id)
        if detail is None:
            return None
        snapshot = detail.get("input")
        if snapshot is None:
            return {"event_id": event_id, "available": False}
        key = "selected_daily_bars" if series == "daily" else "selected_intraday_bars"
        available = snapshot.get(key, [])
        items = available[-limit:]
        return {
            "event_id": event_id,
            "symbol": snapshot["symbol"],
            "series": series,
            "interval": "1d" if series == "daily" else "5m",
            "currency": snapshot["currency"],
            "provider_as_of": snapshot["provider_as_of"],
            "quality": snapshot["quality"],
            "items": items,
            "total_available": len(available),
            "truncated": len(items) < len(available),
            "available": True,
        }

    def outcome_history(
        self,
        result_id: int,
        *,
        page: int = 1,
        page_size: int = 20,
        state: str | None = None,
    ) -> dict[str, Any]:
        """Page append-only observations newest-first without loading a result's full ledger."""

        if type(page) is not int or type(page_size) is not int:
            raise ValueError("outcome page and page_size must be integers")
        if not 1 <= page <= 10_000 or not 1 <= page_size <= 100:
            raise ValueError("outcome page must be 1-10000 and page_size must be 1-100")
        if state not in {None, "observed", "unavailable", "provisional", "corrected"}:
            raise ValueError("outcome state is not supported")
        clause = "result_id = ?" + (" AND state = ?" if state else "")
        values: list[Any] = [result_id, *([state] if state else [])]
        with self.connect() as connection:
            connection.execute("BEGIN")
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM outcomes WHERE {clause}",  # noqa: S608
                    values,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""SELECT id, result_id, observed_close, observed_return, observed_at,
                comparison_rule, state, note, created_at FROM outcomes WHERE {clause}
                ORDER BY id DESC LIMIT ? OFFSET ?""",  # noqa: S608
                [*values, page_size, (page - 1) * page_size],
            ).fetchall()
        return {
            "items": [dict(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

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
