"""SQLite migration and repositories enforce durable append-only audit behavior."""

from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import sqlite3
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, nullcontext, suppress
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Final, TypedDict, TypeGuard, cast

from stock_probs.config import ensure_private_directory, ensure_private_file
from stock_probs.domain import FORECAST_INTERVAL_HORIZONS, HistoryFilters

SCHEMA_VERSION = 9
OUTCOME_RECONSTRUCTION_LIMIT = 100
HISTORY_EXPORT_LIMIT = 100
INSTRUMENT_LIST_ITEM_LIMIT = 100
COORDINATION_TIMEOUT_SECONDS = 5.0
_ROLLING_RESULT_HORIZONS = frozenset(FORECAST_INTERVAL_HORIZONS.values())
MIGRATION_NAME = re.compile(r"^(?P<version>[0-9]{3})_[a-z0-9_]+\.sql$")
PERSISTENCE_FAILURE_CATEGORY = "persistence_unavailable"
# Digests make shipped migrations immutable; changing any SQL file requires a new number.
MIGRATION_SHA256 = {
    1: "0c92dcfb596b6a1b1ce07cf6b4bca15c00f642c7ca69ea5e41e124b49926c98e",
    2: "d51a8a64f5c32fb77875f0e81642146947be3db43437a1269339343e64225cc2",
    3: "ebbf91670e8ad0a4f9a80603459c4eb1d2e66459cda500d5c376b1d563949cda",
    4: "4ca9d80a988f59c2c0c289ac34efffc5df170053c0b968180f85fbdf6edc17ea",
    5: "c7be8e52cedc9d4e476bc36994115148ccaa11b62aaffb3e01b5a308accddc6f",
    6: "1218aa2c8b762f441feebcd870053f374af326a4b852bd4789e66e3c5f824e69",
    7: "770484cb124161d2da58aefea5dc6376a8dbc35624e552019c2111e8b0246e05",
    8: "e79a6e6a5510b826ef98430b334199b12353a672eaf38ea4b49c6c8a72ca8fae",
    9: "bca47a59aef43ce4c4750c2a11f822903cb3e6a599d50e8eaff4690dc4ba9c6c",
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
MAX_PENDING_OAUTH_STATES: Final = 128
MAX_TOTP_RECOVERY_CODES: Final = 32
MAX_TOTP_SECRET_CIPHERTEXT_LENGTH: Final = 16_384
MAX_TOTP_ATTEMPTS_PER_WINDOW: Final = 100
_UNSET: Final = object()


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
                raise RepositoryDatabaseError(f"invalid packaged migration name: {migration.name}")
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
            # Only receipts present before this migration loop represent an existing schema.
            schema_existed_before = (
                connection.execute("SELECT 1 FROM schema_migrations LIMIT 1").fetchone() is not None
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
                    if (
                        schema_existed_before
                        and applied
                        and before_migration is not None
                        and not backup_completed
                    ):
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
            raise RepositoryDatabaseError("packaged migration ends with an incomplete statement")

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
    def _require_owner_id(owner_user_id: int | None) -> int:
        """Require an authenticated principal for every owner-scoped repository operation."""

        if type(owner_user_id) is not int or owner_user_id < 1:
            raise ValueError("owner_user_id is required")
        return owner_user_id

    @staticmethod
    def _iso_datetime(value: datetime, field: str) -> str:
        """Normalize a timezone-aware datetime before storing it in an auth table."""

        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError(f"{field} must include a timezone offset")
        return value.astimezone(UTC).isoformat()

    @staticmethod
    def _parse_iso_datetime(value: object, field: str) -> datetime:
        """Parse an auth adapter timestamp while requiring an explicit timezone offset."""

        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
        else:
            raise ValueError(f"{field} must be an ISO-8601 timestamp")
        if parsed.tzinfo is None:
            raise ValueError(f"{field} must include a timezone offset")
        return parsed.astimezone(UTC)

    @staticmethod
    def _require_token_hash(value: str, field: str) -> str:
        """Validate an opaque SHA-256 token digest without accepting raw session material."""

        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError(f"{field} must be a lowercase SHA-256 digest")
        return value

    @staticmethod
    def _require_factor_id(value: object, field: str = "expected_factor_id") -> int:
        """Validate the immutable TOTP factor id used as the generation fence."""

        if type(value) is not int or value < 1:
            raise ValueError(f"{field} must be a positive integer")
        return value

    @classmethod
    def _optional_factor_id(cls, value: object, field: str = "expected_factor_id") -> int | None:
        """Validate an optional generation fence while preserving first-enrollment state."""

        if value is None:
            return None
        return cls._require_factor_id(value, field)

    @staticmethod
    def _require_totp_secret_ciphertext(value: str) -> str:
        """Validate encrypted TOTP material without accepting an empty database value."""

        if (
            not isinstance(value, str)
            or not 16 <= len(value.strip()) <= MAX_TOTP_SECRET_CIPHERTEXT_LENGTH
        ):
            raise ValueError("secret_ciphertext length is invalid")
        return value.strip()

    @staticmethod
    def _require_totp_step(value: int) -> int:
        """Validate a non-negative RFC 6238 time-step before the replay CAS."""

        if type(value) is not int or value < 0:
            raise ValueError("TOTP step must be a non-negative integer")
        return value

    @staticmethod
    def _require_totp_attempt_limits(
        window_seconds: int, max_attempts: int, lockout_seconds: int
    ) -> tuple[int, int, int]:
        """Keep the durable throttle bounded even when called by an untrusted adapter."""

        if type(window_seconds) is not int or not 1 <= window_seconds <= 86_400:
            raise ValueError("TOTP attempt window must be 1-86400 seconds")
        if type(max_attempts) is not int or not 1 <= max_attempts <= MAX_TOTP_ATTEMPTS_PER_WINDOW:
            raise ValueError("TOTP attempt limit must be 1-100")
        if type(lockout_seconds) is not int or not 1 <= lockout_seconds <= 86_400:
            raise ValueError("TOTP lockout must be 1-86400 seconds")
        return window_seconds, max_attempts, lockout_seconds

    @classmethod
    def _normalize_recovery_code_hashes(cls, code_hashes: Sequence[str]) -> list[str]:
        """Validate the bounded recovery set before any factor transaction can mutate state."""

        if isinstance(code_hashes, str | bytes) or not isinstance(code_hashes, Sequence):
            raise ValueError("code_hashes must be a sequence")
        if not 1 <= len(code_hashes) <= MAX_TOTP_RECOVERY_CODES:
            raise ValueError("recovery code count must be 1-32")
        normalized: list[str] = []
        for code_hash in code_hashes:
            value = cls._require_token_hash(code_hash, "code_hash")
            if value in normalized:
                raise ValueError("recovery code hashes must be unique")
            normalized.append(value)
        return normalized

    @staticmethod
    def _ensure_user_exists(connection: sqlite3.Connection, user_id: int) -> None:
        """Reject an ownership write that references an unknown account."""

        if type(user_id) is not int or user_id < 1:
            raise ValueError("user_id must be a positive integer")
        if connection.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
            raise ValueError("user_id does not exist")

    @staticmethod
    def _ensure_owner_can_write(connection: sqlite3.Connection, owner_user_id: int) -> None:
        """Require an existing active principal before appending research data."""

        Repository._ensure_user_exists(connection, owner_user_id)
        row = connection.execute(
            "SELECT status FROM users WHERE id = ?", (owner_user_id,)
        ).fetchone()
        if row is None or row[0] != "active":
            raise ValueError("owner_user_id is not an active user")

    def legacy_owner_id(self) -> int:
        """Return the explicit migration owner used only for controlled legacy import."""

        with self.connect() as connection:
            row = connection.execute(
                """SELECT id FROM users WHERE id = 1
                AND (login = 'legacy-owner' OR legacy_owner_claimed_at IS NOT NULL)"""
            ).fetchone()
        if row is None:
            raise RepositoryDatabaseError("designated legacy owner is unavailable")
        return int(row[0])

    def claim_legacy_owner(
        self,
        *,
        login: str,
        display_name: str,
        claimed_at: datetime,
        github_user_id: int | None = None,
        email: str | None = None,
        password_hash: str | None = None,
    ) -> dict[str, Any]:
        """Bind the reserved legacy account to one explicitly designated administrator.

        Migration sidecars remain untouched.  The placeholder can be claimed once through a
        local bootstrap password hash or a verified GitHub numeric identity; every later claim
        attempt fails closed instead of reassigning historical data to another account.
        """

        if not isinstance(login, str) or not 1 <= len(login.strip()) <= 80:
            raise ValueError("login must be 1-80 characters")
        normalized_login = login.strip()
        if normalized_login.casefold() == "legacy-owner":
            raise ValueError("legacy placeholder login cannot be retained")
        if not isinstance(display_name, str) or not 1 <= len(display_name.strip()) <= 200:
            raise ValueError("display_name must be 1-200 characters")
        if email is not None and (not isinstance(email, str) or not 1 <= len(email.strip()) <= 320):
            raise ValueError("email must be 1-320 characters or null")
        if github_user_id is not None and (type(github_user_id) is not int or github_user_id < 1):
            raise ValueError("github_user_id must be a positive integer or null")
        if github_user_id is None:
            if not isinstance(password_hash, str) or not password_hash:
                raise ValueError("a local legacy owner requires a password hash")
        elif password_hash is not None:
            raise ValueError("a GitHub legacy owner cannot use local credentials")
        timestamp = self._iso_datetime(claimed_at, "claimed_at")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT id, login, github_user_id, password_hash, legacy_owner_claimed_at
                FROM users WHERE id = 1"""
            ).fetchone()
            if row is None:
                connection.rollback()
                raise RepositoryDatabaseError("designated legacy owner is unavailable")
            if (
                row["legacy_owner_claimed_at"] is not None
                or row["login"] != "legacy-owner"
                or row["github_user_id"] is not None
                or row["password_hash"] is not None
            ):
                connection.rollback()
                raise ValueError("legacy owner is already claimed or has unexpected state")
            if (
                connection.execute(
                    "SELECT 1 FROM users WHERE id != 1 AND login = ? COLLATE NOCASE",
                    (normalized_login,),
                ).fetchone()
                is not None
            ):
                connection.rollback()
                raise ValueError("legacy owner login is already assigned")
            if (
                github_user_id is not None
                and connection.execute(
                    "SELECT 1 FROM users WHERE id != 1 AND github_user_id = ?",
                    (github_user_id,),
                ).fetchone()
                is not None
            ):
                connection.rollback()
                raise ValueError("legacy owner GitHub identity is already assigned")
            connection.execute(
                """UPDATE users SET github_user_id = ?, login = ?, email = ?,
                display_name = ?, password_hash = ?, role = 'admin', status = 'active',
                created_at = ?, updated_at = ?, legacy_owner_claimed_at = ?
                WHERE id = 1 AND legacy_owner_claimed_at IS NULL""",
                (
                    github_user_id,
                    normalized_login,
                    email.strip() if email is not None else None,
                    display_name.strip(),
                    password_hash,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            claimed = connection.execute(
                """SELECT id, github_user_id, login, email, display_name, role, status,
                created_at, updated_at, last_login_at FROM users WHERE id = 1"""
            ).fetchone()
        if claimed is None:
            raise RepositoryDatabaseError("legacy owner claim could not be read")
        return dict(claimed)

    def create_user(
        self,
        *,
        github_user_id: int | None,
        login: str | None,
        display_name: str,
        password_hash: str | None,
        created_at: datetime,
        email: str | None = None,
        role: str = "member",
        status: str = "active",
    ) -> dict[str, Any]:
        """Create an account row while keeping provider and local identifiers unique."""

        if github_user_id is not None and (type(github_user_id) is not int or github_user_id < 1):
            raise ValueError("github_user_id must be a positive integer or null")
        if login is not None and (not isinstance(login, str) or not 1 <= len(login.strip()) <= 80):
            raise ValueError("login must be 1-80 characters or null")
        if email is not None and (not isinstance(email, str) or not 1 <= len(email.strip()) <= 320):
            raise ValueError("email must be 1-320 characters or null")
        if not isinstance(display_name, str) or not 1 <= len(display_name.strip()) <= 200:
            raise ValueError("display_name must be 1-200 characters")
        if role not in {"admin", "member"} or status not in {"active", "invited", "disabled"}:
            raise ValueError("unsupported user role or status")
        timestamp = self._iso_datetime(created_at, "created_at")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """INSERT INTO users
                (github_user_id, login, email, display_name, password_hash, role, status,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    github_user_id,
                    login.strip() if login is not None else None,
                    email.strip() if email is not None else None,
                    display_name.strip(),
                    password_hash,
                    role,
                    status,
                    timestamp,
                    timestamp,
                ),
            )
            user_id = self._insert_id(cursor)
            connection.commit()
            row = connection.execute(
                """SELECT id, github_user_id, login, email, display_name, role, status,
                created_at, updated_at, last_login_at FROM users WHERE id = ?""",
                (user_id,),
            ).fetchone()
        if row is None:
            raise RepositoryDatabaseError("created user could not be read")
        return dict(row)

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        """Return one account without exposing authentication secrets to callers."""

        if type(user_id) is not int or user_id < 1:
            return None
        with self.connect() as connection:
            row = connection.execute(
                """SELECT id, github_user_id, login, email, display_name, role, status,
                created_at, updated_at, last_login_at FROM users WHERE id = ?""",
                (user_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_user_by_github_id(self, github_user_id: int) -> dict[str, Any] | None:
        """Resolve an account by GitHub's stable numeric identity."""

        if type(github_user_id) is not int or github_user_id < 1:
            return None
        with self.connect() as connection:
            row = connection.execute(
                """SELECT id, github_user_id, login, email, display_name, role, status,
                created_at, updated_at, last_login_at FROM users WHERE github_user_id = ?""",
                (github_user_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_user_by_login(self, login: str) -> dict[str, Any] | None:
        """Resolve a development-local account by its normalized login name."""

        if not isinstance(login, str) or not login.strip():
            return None
        with self.connect() as connection:
            row = connection.execute(
                """SELECT id, github_user_id, login, email, display_name, role, status,
                created_at, updated_at, last_login_at, password_hash
                FROM users WHERE login = ? COLLATE NOCASE""",
                (login.strip(),),
            ).fetchone()
        return dict(row) if row is not None else None

    @staticmethod
    def _auth_user_row(
        connection: sqlite3.Connection,
        where: str,
        value: int | str,
        *,
        include_password: bool = False,
    ) -> dict[str, Any] | None:
        """Return an auth-shaped account with derived passkey enrollment state."""

        password_column = ", user.password_hash" if include_password else ""
        row = connection.execute(
            f"""SELECT user.id, user.github_user_id AS github_id, user.login,
            user.login AS username, user.login AS github_login, user.email,
            user.display_name, user.role, user.status,
            (user.status = 'active') AS active,
            EXISTS(
                SELECT 1 FROM passkeys AS key
                WHERE key.user_id = user.id AND key.revoked_at IS NULL
            ) AS passkey_enrolled{password_column}
            FROM users AS user WHERE {where}""",  # noqa: S608
            (value,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["passkey_required"] = result["role"] != "admin"
        result["passkey_enrolled"] = bool(result["passkey_enrolled"])
        result["active"] = bool(result["active"])
        return result

    def auth_get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        """Resolve a user for the authentication adapter without leaking password hashes."""

        if type(user_id) is not int or user_id < 1:
            return None
        with self.connect() as connection:
            return self._auth_user_row(connection, "user.id = ?", user_id)

    def auth_get_user_by_username(self, username: str) -> dict[str, Any] | None:
        """Resolve a local bootstrap account and retain its password hash for verification."""

        if not isinstance(username, str) or not username.strip():
            return None
        with self.connect() as connection:
            return self._auth_user_row(
                connection,
                "user.login = ? COLLATE NOCASE",
                username.strip(),
                include_password=True,
            )

    def auth_get_user_by_github_id(self, github_id: int) -> dict[str, Any] | None:
        """Resolve the stable GitHub numeric identity used by OAuth."""

        if type(github_id) is not int or github_id < 1:
            return None
        with self.connect() as connection:
            return self._auth_user_row(connection, "user.github_user_id = ?", github_id)

    def auth_create_user(self, fields: Mapping[str, object]) -> dict[str, Any]:
        """Create an account from the auth manager's provider-neutral field mapping."""

        github_value = fields.get("github_id", fields.get("github_user_id"))
        github_id = github_value if type(github_value) is int else None
        login_value = fields.get("github_login", fields.get("username", fields.get("login")))
        login = login_value if isinstance(login_value, str) else None
        display_value = fields.get("display_name", login or "Signal Ledger user")
        if not isinstance(display_value, str):
            raise ValueError("display_name must be text")
        password_hash = fields.get("password_hash")
        if password_hash is not None and not isinstance(password_hash, str):
            raise ValueError("password_hash must be text or null")
        email = fields.get("email")
        if email is not None and not isinstance(email, str):
            raise ValueError("email must be text or null")
        created_value = fields.get("created_at", datetime.now(UTC))
        created_at = self._parse_iso_datetime(created_value, "created_at")
        role = fields.get("role", "member")
        status = fields.get("status", "active")
        if not isinstance(role, str) or not isinstance(status, str):
            raise ValueError("user role and status must be text")
        self.create_user(
            github_user_id=github_id,
            login=login,
            email=email,
            display_name=display_value,
            password_hash=password_hash,
            role=role,
            status=status,
            created_at=created_at,
        )
        if github_id is not None:
            result = self.auth_get_user_by_github_id(github_id)
        elif login is not None:
            result = self.auth_get_user_by_username(login)
        else:
            raise ValueError("an account requires a login or GitHub identity")
        if result is None:
            raise RepositoryDatabaseError("created user could not be resolved")
        return result

    def auth_update_user(self, user_id: int, fields: Mapping[str, object]) -> dict[str, Any] | None:
        """Apply non-secret account changes and return fresh derived auth state."""

        role_value = fields.get("role")
        status_value = fields.get("status")
        display_value = fields.get("display_name")
        email_value = fields.get("email")
        role = role_value if isinstance(role_value, str) else None
        status = status_value if isinstance(status_value, str) else None
        display_name = display_value if isinstance(display_value, str) else None
        email = email_value if isinstance(email_value, str) else None
        self.update_user_security(
            user_id,
            at=datetime.now(UTC),
            role=role,
            status=status,
            display_name=display_name,
            email=email,
        )
        return self.auth_get_user_by_id(user_id)

    def update_user_last_login(self, user_id: int, at: datetime) -> bool:
        """Record a successful login without changing immutable research records."""

        timestamp = self._iso_datetime(at, "at")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
                (timestamp, timestamp, user_id),
            )
            connection.commit()
        return bool(cursor.rowcount)

    def update_user_security(
        self,
        user_id: int,
        *,
        at: datetime,
        role: str | None = None,
        status: str | None = None,
        display_name: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any] | None:
        """Update operator-controlled account state while retaining an audit-friendly timestamp."""

        if role is not None and role not in {"admin", "member"}:
            raise ValueError("unsupported user role")
        if status is not None and status not in {"active", "invited", "disabled"}:
            raise ValueError("unsupported user status")
        if display_name is not None and not 1 <= len(display_name.strip()) <= 200:
            raise ValueError("display_name must be 1-200 characters")
        if email is not None and not 1 <= len(email.strip()) <= 320:
            raise ValueError("email must be 1-320 characters")
        timestamp = self._iso_datetime(at, "at")
        updates: list[str] = ["updated_at = ?"]
        values: list[Any] = [timestamp]
        if role is not None:
            updates.append("role = ?")
            values.append(role)
        if status is not None:
            updates.append("status = ?")
            values.append(status)
        if display_name is not None:
            updates.append("display_name = ?")
            values.append(display_name.strip())
        if email is not None:
            updates.append("email = ?")
            values.append(email.strip())
        values.append(user_id)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE id = ?",  # noqa: S608
                values,
            )
            connection.commit()
            if not cursor.rowcount:
                return None
            row = connection.execute(
                """SELECT id, github_user_id, login, email, display_name, role, status,
                created_at, updated_at, last_login_at FROM users WHERE id = ?""",
                (user_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def create_invitation(
        self,
        *,
        github_user_id: int,
        token_hash: str,
        invited_by_user_id: int,
        expires_at: datetime,
        created_at: datetime,
        github_login: str | None = None,
    ) -> dict[str, Any]:
        """Create one expiring, single-use invitation using only a token digest."""

        if type(github_user_id) is not int or github_user_id < 1:
            raise ValueError("github_user_id must be a positive integer")
        token_hash = self._require_token_hash(token_hash, "token_hash")
        expires = self._iso_datetime(expires_at, "expires_at")
        created = self._iso_datetime(created_at, "created_at")
        if expires <= created:
            raise ValueError("invitation must expire after creation")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_user_exists(connection, invited_by_user_id)
            cursor = connection.execute(
                """INSERT INTO invitations
                (github_user_id, github_login, token_hash, invited_by_user_id,
                 expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (github_user_id, github_login, token_hash, invited_by_user_id, expires, created),
            )
            invitation_id = self._insert_id(cursor)
            connection.commit()
            row = connection.execute(
                """SELECT id, github_user_id, github_login, invited_by_user_id, expires_at,
                used_at, created_at FROM invitations WHERE id = ?""",
                (invitation_id,),
            ).fetchone()
        if row is None:
            raise RepositoryDatabaseError("created invitation could not be read")
        return dict(row)

    def consume_invitation(self, *, token_hash: str, now: datetime) -> dict[str, Any] | None:
        """Atomically consume an unexpired invitation and return its resolved identity."""

        token_hash = self._require_token_hash(token_hash, "token_hash")
        now_text = self._iso_datetime(now, "now")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT id, github_user_id, github_login, invited_by_user_id, expires_at,
                used_at, created_at FROM invitations
                WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?""",
                (token_hash, now_text),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            cursor = connection.execute(
                "UPDATE invitations SET used_at = ? WHERE id = ? AND used_at IS NULL",
                (now_text, int(row["id"])),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return None
            connection.commit()
        return dict(row) | {"used_at": now_text}

    def auth_create_invitation(self, fields: Mapping[str, object]) -> dict[str, Any]:
        """Persist an auth invitation from the AuthManager's field vocabulary."""

        github_value = fields.get("github_id", fields.get("github_user_id"))
        invited_by_value = fields.get("invited_by", fields.get("invited_by_user_id"))
        token_hash = fields.get("code_hash", fields.get("token_hash"))
        github_login = fields.get("github_login")
        if type(github_value) is not int or type(invited_by_value) is not int:
            raise ValueError("invitation identities must be positive integers")
        if not isinstance(token_hash, str):
            raise ValueError("invitation token hash is required")
        created_at = self._parse_iso_datetime(fields.get("created_at"), "created_at")
        expires_at = self._parse_iso_datetime(fields.get("expires_at"), "expires_at")
        result = self.create_invitation(
            github_user_id=github_value,
            github_login=github_login if isinstance(github_login, str) else None,
            token_hash=token_hash,
            invited_by_user_id=invited_by_value,
            expires_at=expires_at,
            created_at=created_at,
        )
        return result | {
            "github_id": result["github_user_id"],
            "invited_by": result["invited_by_user_id"],
            "code_hash": token_hash,
        }

    def auth_consume_invitation(self, code_hash: str, consumed_at: str) -> dict[str, Any] | None:
        """Atomically consume one invitation and expose the auth protocol aliases."""

        result = self.consume_invitation(
            token_hash=code_hash,
            now=self._parse_iso_datetime(consumed_at, "consumed_at"),
        )
        if result is None:
            return None
        return result | {
            "github_id": result["github_user_id"],
            "consumed_at": result["used_at"],
        }

    def auth_get_invitation(self, code_hash: str) -> dict[str, Any] | None:
        """Inspect invitation state without consuming it or exposing its token digest."""

        code_hash = self._require_token_hash(code_hash, "code_hash")
        with self.connect() as connection:
            row = connection.execute(
                """SELECT id, github_user_id, github_login, invited_by_user_id,
                expires_at, used_at, created_at FROM invitations WHERE token_hash = ?""",
                (code_hash,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["github_id"] = result["github_user_id"]
        result["consumed_at"] = result["used_at"]
        return result

    def list_invitations(self) -> list[dict[str, Any]]:
        """Return bounded invitation metadata for the administrator security screen."""

        with self.connect() as connection:
            rows = connection.execute(
                """SELECT id, github_user_id, github_login, invited_by_user_id,
                expires_at, used_at, created_at FROM invitations ORDER BY id DESC LIMIT 100"""
            ).fetchall()
        return [
            dict(row) | {"github_id": row["github_user_id"], "consumed_at": row["used_at"]}
            for row in rows
        ]

    def auth_list_invitations(self) -> list[dict[str, Any]]:
        """Expose the invitation listing under the auth adapter's explicit method name."""

        return self.list_invitations()

    def auth_store_oauth_state(self, fields: Mapping[str, object]) -> None:
        """Store a short-lived OAuth state and PKCE verifier as one server-side record."""

        state_hash = fields.get("state_hash")
        verifier = fields.get("code_verifier")
        redirect_uri = fields.get("redirect_uri")
        created_at = fields.get("created_at")
        expires_at = fields.get("expires_at")
        invitation_hash = fields.get("invitation_code_hash")
        if not isinstance(state_hash, str) or not isinstance(verifier, str):
            raise ValueError("OAuth state and verifier are required")
        state_hash = self._require_token_hash(state_hash, "state_hash")
        if not isinstance(redirect_uri, str) or not 1 <= len(redirect_uri) <= 2048:
            raise ValueError("redirect_uri is invalid")
        if invitation_hash is not None:
            invitation_hash = self._require_token_hash(invitation_hash, "invitation_code_hash")
        created = self._parse_iso_datetime(created_at, "created_at")
        expires = self._parse_iso_datetime(expires_at, "expires_at")
        if expires <= created:
            raise ValueError("OAuth state must expire after creation")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # Every anonymous OAuth start writes a transaction. Prune completed/expired rows
            # and cap outstanding states so a public sign-in link cannot grow SQLite forever.
            connection.execute(
                "DELETE FROM oauth_states WHERE expires_at <= ? OR consumed_at IS NOT NULL",
                (created.isoformat(),),
            )
            pending = connection.execute("SELECT COUNT(*) FROM oauth_states").fetchone()[0]
            if pending >= MAX_PENDING_OAUTH_STATES:
                raise RepositoryError("OAuth sign-in capacity is temporarily full.")
            connection.execute(
                """INSERT INTO oauth_states
                (state_hash, code_verifier, redirect_uri, invitation_code_hash,
                 created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    state_hash,
                    verifier,
                    redirect_uri,
                    invitation_hash,
                    created.isoformat(),
                    expires.isoformat(),
                ),
            )
            connection.commit()

    def auth_consume_oauth_state(self, state_hash: str, consumed_at: str) -> dict[str, Any] | None:
        """Consume OAuth state once; expired state is never accepted by the adapter."""

        state_hash = self._require_token_hash(state_hash, "state_hash")
        consumed = self._parse_iso_datetime(consumed_at, "consumed_at")
        consumed_text = consumed.isoformat()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT id, state_hash, code_verifier, redirect_uri,
                invitation_code_hash, created_at, expires_at, consumed_at
                FROM oauth_states
                WHERE state_hash = ? AND consumed_at IS NULL AND expires_at > ?""",
                (state_hash, consumed_text),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            cursor = connection.execute(
                "UPDATE oauth_states SET consumed_at = ? WHERE id = ? AND consumed_at IS NULL",
                (consumed_text, int(row["id"])),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return None
            connection.commit()
        return dict(row) | {"consumed_at": consumed_text}

    def create_session(
        self,
        *,
        user_id: int,
        token_hash: str,
        csrf_token_hash: str,
        issued_at: datetime,
        last_seen_at: datetime,
        idle_expires_at: datetime,
        absolute_expires_at: datetime,
        session_id: str | None = None,
        auth_method: str = "local",
        last_passkey_at: datetime | None = None,
        mfa_method: str | None = None,
        mfa_verified_at: datetime | None = None,
        mfa_factor_id: int | None = None,
    ) -> dict[str, Any]:
        """Persist an opaque server-side session and its CSRF digest."""

        token_hash = self._require_token_hash(token_hash, "token_hash")
        csrf_token_hash = self._require_token_hash(csrf_token_hash, "csrf_token_hash")
        issued = self._iso_datetime(issued_at, "issued_at")
        last_seen = self._iso_datetime(last_seen_at, "last_seen_at")
        idle_expires = self._iso_datetime(idle_expires_at, "idle_expires_at")
        absolute_expires = self._iso_datetime(absolute_expires_at, "absolute_expires_at")
        if not issued <= last_seen <= idle_expires <= absolute_expires:
            raise ValueError("session timestamps are not ordered")
        if session_id is None:
            session_id = secrets.token_hex(16)
        if not isinstance(session_id, str) or not 16 <= len(session_id) <= 128:
            raise ValueError("session_id length is invalid")
        if auth_method not in {"local", "github", "passkey"}:
            raise ValueError("auth_method is not supported")
        last_passkey = (
            self._iso_datetime(last_passkey_at, "last_passkey_at")
            if last_passkey_at is not None
            else None
        )
        if mfa_method not in {None, "totp", "recovery"}:
            raise ValueError("mfa_method is not supported")
        if mfa_verified_at is not None and mfa_method is None:
            raise ValueError("mfa_verified_at requires mfa_method")
        if mfa_method is not None and mfa_verified_at is None:
            raise ValueError("mfa_method requires mfa_verified_at")
        if mfa_method is not None and mfa_factor_id is None:
            raise ValueError("MFA sessions require a current factor generation")
        if mfa_method is None and mfa_factor_id is not None:
            raise ValueError("factor generation requires an MFA method")
        factor_id = (
            self._require_factor_id(mfa_factor_id)
            if mfa_factor_id is not None
            else None
        )
        mfa_verified = (
            self._iso_datetime(mfa_verified_at, "mfa_verified_at")
            if mfa_verified_at is not None
            else None
        )
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_user_exists(connection, user_id)
            if factor_id is not None and connection.execute(
                "SELECT 1 FROM totp_factors WHERE id = ? AND user_id = ?",
                (factor_id, user_id),
            ).fetchone() is None:
                connection.rollback()
                raise ValueError("factor generation is not current for this user")
            cursor = connection.execute(
                """INSERT INTO sessions
                (user_id, session_id, token_hash, csrf_token_hash, issued_at, last_seen_at,
                 idle_expires_at, absolute_expires_at, auth_method, last_passkey_at,
                 mfa_method, mfa_verified_at, mfa_factor_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    session_id,
                    token_hash,
                    csrf_token_hash,
                    issued,
                    last_seen,
                    idle_expires,
                    absolute_expires,
                    auth_method,
                    last_passkey,
                    mfa_method,
                    mfa_verified,
                    factor_id,
                ),
            )
            row_id = self._insert_id(cursor)
            connection.commit()
            row = connection.execute(
                """SELECT id, session_id, user_id, token_hash, csrf_token_hash, issued_at,
                last_seen_at, idle_expires_at, absolute_expires_at, auth_method,
                last_passkey_at, mfa_method, mfa_verified_at, mfa_factor_id,
                revoked_at, revocation_reason
                FROM sessions WHERE id = ?""",
                (row_id,),
            ).fetchone()
        if row is None:
            raise RepositoryDatabaseError("created session could not be read")
        return dict(row)

    def get_session(
        self, token_hash: str, *, now: datetime, touch: bool = False
    ) -> dict[str, Any] | None:
        """Return a live session joined to its account, optionally updating idle activity."""

        token_hash = self._require_token_hash(token_hash, "token_hash")
        now_text = self._iso_datetime(now, "now")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE" if touch else "BEGIN")
            row = connection.execute(
                """SELECT session.id, session.session_id, session.user_id,
                session.csrf_token_hash, session.issued_at, session.last_seen_at,
                session.idle_expires_at, session.absolute_expires_at, session.auth_method,
                session.last_passkey_at, session.mfa_method, session.mfa_verified_at,
                session.mfa_factor_id,
                session.revoked_at, session.revocation_reason,
                user.github_user_id, user.login, user.email, user.display_name,
                user.role, user.status
                FROM sessions AS session JOIN users AS user ON user.id = session.user_id
                WHERE session.token_hash = ? AND session.revoked_at IS NULL
                  AND session.idle_expires_at > ? AND session.absolute_expires_at > ?
                  AND (session.mfa_method IS NULL OR EXISTS (
                      SELECT 1 FROM totp_factors AS factor
                      WHERE factor.id = session.mfa_factor_id AND factor.user_id = session.user_id
                  ))
                  AND user.status = 'active'""",
                (token_hash, now_text, now_text),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            result = dict(row)
            if touch:
                connection.execute(
                    "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
                    (now_text, token_hash),
                )
                result["last_seen_at"] = now_text
            connection.commit()
        return result

    def auth_create_session(self, fields: Mapping[str, object]) -> dict[str, Any] | None:
        """Persist the auth manager's opaque session fields in the durable session table."""

        user_id = fields.get("user_id")
        if type(user_id) is not int:
            raise ValueError("user_id must be a positive integer")
        token_hash = fields.get("token_hash")
        csrf_hash = fields.get("csrf_token_hash")
        if not isinstance(token_hash, str) or not isinstance(csrf_hash, str):
            raise ValueError("session token hashes are required")
        token_hash = self._require_token_hash(token_hash, "token_hash")
        csrf_hash = self._require_token_hash(csrf_hash, "csrf_token_hash")
        issued_at = self._parse_iso_datetime(
            fields.get("issued_at", fields.get("created_at")), "created_at"
        )
        last_seen_at = self._parse_iso_datetime(fields.get("last_seen_at"), "last_seen_at")
        idle_expires_at = self._parse_iso_datetime(fields.get("idle_expires_at"), "idle_expires_at")
        absolute_expires_at = self._parse_iso_datetime(
            fields.get("absolute_expires_at", fields.get("expires_at")), "expires_at"
        )
        session_id_value = fields.get("session_id")
        session_id = session_id_value if isinstance(session_id_value, str) else None
        if session_id is None:
            session_id = secrets.token_hex(16)
        if not 16 <= len(session_id) <= 128:
            raise ValueError("session_id length is invalid")
        auth_method_value = fields.get("auth_method", "local")
        if not isinstance(auth_method_value, str):
            raise ValueError("auth_method is not supported")
        if auth_method_value not in {"local", "github", "passkey"}:
            raise ValueError("auth_method is not supported")
        last_passkey_value = fields.get("last_passkey_at")
        last_passkey_at = (
            self._parse_iso_datetime(last_passkey_value, "last_passkey_at")
            if last_passkey_value is not None
            else None
        )
        mfa_method_value = fields.get("mfa_method")
        mfa_method = mfa_method_value if isinstance(mfa_method_value, str) else None
        if mfa_method not in {None, "totp", "recovery"}:
            raise ValueError("mfa_method is not supported")
        mfa_verified_value = fields.get("mfa_verified_at")
        mfa_verified_at = (
            self._parse_iso_datetime(mfa_verified_value, "mfa_verified_at")
            if mfa_verified_value is not None
            else None
        )
        mfa_factor_value = fields.get("mfa_factor_id", fields.get("expected_factor_id"))
        mfa_factor_id = self._optional_factor_id(mfa_factor_value)
        origin_value = fields.get("origin_token_hash")
        origin_token_hash = (
            self._require_token_hash(origin_value, "origin_token_hash")
            if origin_value is not None
            else None
        )
        revoke_other_sessions = fields.get("revoke_other_sessions", False)
        if type(revoke_other_sessions) is not bool:
            raise ValueError("revoke_other_sessions must be a boolean")
        # Every factor-bound session must be issued from the live provisional session captured
        # by the proof transaction, including the first enrollment session.
        if mfa_method in {"totp", "recovery"} and mfa_factor_id is None:
            raise ValueError("MFA sessions require expected_factor_id")
        if mfa_method in {"totp", "recovery"} and mfa_verified_at is None:
            raise ValueError("MFA sessions require mfa_verified_at")
        if mfa_method in {"totp", "recovery"} and origin_token_hash is None:
            return None
        if origin_token_hash == token_hash:
            return None
        return self._create_auth_session_transaction(
            user_id=user_id,
            token_hash=token_hash,
            csrf_token_hash=csrf_hash,
            issued_at=issued_at,
            last_seen_at=last_seen_at,
            idle_expires_at=idle_expires_at,
            absolute_expires_at=absolute_expires_at,
            session_id=session_id,
            auth_method=auth_method_value,
            last_passkey_at=last_passkey_at,
            mfa_method=mfa_method,
            mfa_verified_at=mfa_verified_at,
            mfa_factor_id=mfa_factor_id,
            origin_token_hash=origin_token_hash,
            revoke_other_sessions=revoke_other_sessions,
        )

    def _create_auth_session_transaction(
        self,
        *,
        user_id: int,
        token_hash: str,
        csrf_token_hash: str,
        issued_at: datetime,
        last_seen_at: datetime,
        idle_expires_at: datetime,
        absolute_expires_at: datetime,
        session_id: str | None,
        auth_method: str,
        last_passkey_at: datetime | None,
        mfa_method: str | None,
        mfa_verified_at: datetime | None,
        mfa_factor_id: int | None,
        origin_token_hash: str | None,
        revoke_other_sessions: bool,
    ) -> dict[str, Any] | None:
        """Insert an MFA session only after an atomic generation and origin check.

        The caller has already validated the opaque fields.  Keeping the generation check,
        live-origin lookup, insert, and revocation in this one write transaction closes the
        window in which a factor replacement could otherwise mint a session from an old proof.
        """

        issued = self._iso_datetime(issued_at, "issued_at")
        last_seen = self._iso_datetime(last_seen_at, "last_seen_at")
        idle_expires = self._iso_datetime(idle_expires_at, "idle_expires_at")
        absolute_expires = self._iso_datetime(absolute_expires_at, "absolute_expires_at")
        if not issued <= last_seen <= idle_expires <= absolute_expires:
            raise ValueError("session timestamps are not ordered")
        last_passkey = (
            self._iso_datetime(last_passkey_at, "last_passkey_at")
            if last_passkey_at is not None
            else None
        )
        mfa_verified = (
            self._iso_datetime(mfa_verified_at, "mfa_verified_at")
            if mfa_verified_at is not None
            else None
        )
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_user_exists(connection, user_id)
            if mfa_method in {"totp", "recovery"}:
                if mfa_factor_id is None:
                    connection.rollback()
                    return None
                if connection.execute(
                    "SELECT 1 FROM totp_factors WHERE id = ? AND user_id = ?",
                    (mfa_factor_id, user_id),
                ).fetchone() is None:
                    connection.rollback()
                    return None
                if origin_token_hash is None:
                    connection.rollback()
                    return None
                if origin_token_hash is not None:
                    origin = connection.execute(
                        """SELECT id FROM sessions
                        WHERE token_hash = ? AND user_id = ? AND revoked_at IS NULL
                          AND idle_expires_at > ? AND absolute_expires_at > ?""",
                        (origin_token_hash, user_id, issued, issued),
                    ).fetchone()
                    if origin is None:
                        connection.rollback()
                        return None
            elif origin_token_hash is not None or mfa_factor_id is not None:
                connection.rollback()
                return None
            cursor = connection.execute(
                """INSERT INTO sessions
                (user_id, session_id, token_hash, csrf_token_hash, issued_at, last_seen_at,
                 idle_expires_at, absolute_expires_at, auth_method, last_passkey_at,
                 mfa_method, mfa_verified_at, mfa_factor_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    session_id,
                    token_hash,
                    csrf_token_hash,
                    issued,
                    last_seen,
                    idle_expires,
                    absolute_expires,
                    auth_method,
                    last_passkey,
                    mfa_method,
                    mfa_verified,
                    mfa_factor_id,
                ),
            )
            row_id = self._insert_id(cursor)
            if origin_token_hash is not None:
                if revoke_other_sessions:
                    connection.execute(
                        """UPDATE sessions SET revoked_at = ?, revocation_reason =
                        'security-change' WHERE user_id = ? AND token_hash != ?
                        AND revoked_at IS NULL""",
                        (issued, user_id, token_hash),
                    )
                else:
                    connection.execute(
                        """UPDATE sessions SET revoked_at = ?, revocation_reason =
                        'mfa-upgrade' WHERE token_hash = ? AND revoked_at IS NULL""",
                        (issued, origin_token_hash),
                    )
            connection.commit()
            row = connection.execute(
                """SELECT id, session_id, user_id, token_hash, csrf_token_hash, issued_at,
                last_seen_at, idle_expires_at, absolute_expires_at, auth_method,
                last_passkey_at, mfa_method, mfa_verified_at, mfa_factor_id,
                revoked_at, revocation_reason FROM sessions WHERE id = ?""",
                (row_id,),
            ).fetchone()
        if row is None:
            raise RepositoryDatabaseError("created auth session could not be read")
        return dict(row)

    def auth_get_session(self, token_hash: str) -> dict[str, Any] | None:
        """Return raw session lifecycle state for AuthManager's bounded expiry checks."""

        token_hash = self._require_token_hash(token_hash, "token_hash")
        with self.connect() as connection:
            row = connection.execute(
                """SELECT session.id, session.session_id, session.user_id,
                session.token_hash, session.csrf_token_hash, session.auth_method,
                session.issued_at AS created_at, session.last_seen_at,
                session.idle_expires_at, session.absolute_expires_at AS expires_at,
                session.last_passkey_at, session.mfa_method, session.mfa_verified_at,
                session.mfa_factor_id,
                session.revoked_at, session.revocation_reason
                FROM sessions AS session
                WHERE session.token_hash = ?
                  AND (session.mfa_method IS NULL OR EXISTS (
                      SELECT 1 FROM totp_factors AS factor
                      WHERE factor.id = session.mfa_factor_id AND factor.user_id = session.user_id
                  ))""",
                (token_hash,),
            ).fetchone()
        return dict(row) if row is not None else None

    def auth_touch_session(self, fields: Mapping[str, object]) -> None:
        """Refresh only the bounded idle timestamp of an active session."""

        token_hash_value = fields.get("token_hash")
        if not isinstance(token_hash_value, str):
            raise ValueError("session token hash is required")
        token_hash = token_hash_value
        token_hash = self._require_token_hash(token_hash, "token_hash")
        updates: list[str] = []
        values: list[Any] = []
        if "last_seen_at" in fields:
            last_seen = self._parse_iso_datetime(fields["last_seen_at"], "last_seen_at")
            updates.append("last_seen_at = ?")
            values.append(last_seen.isoformat())
        if "idle_expires_at" in fields:
            idle_expires = self._parse_iso_datetime(fields["idle_expires_at"], "idle_expires_at")
            updates.append("idle_expires_at = ?")
            values.append(idle_expires.isoformat())
        if not updates:
            return
        values.append(token_hash)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                f"UPDATE sessions SET {', '.join(updates)} "  # noqa: S608
                "WHERE token_hash = ? AND revoked_at IS NULL",  # noqa: S608
                values,
            )
            connection.commit()

    def auth_revoke_session(self, token_hash: str, revoked_at: str) -> None:
        """Revoke one auth session through the AuthStore protocol."""

        self.revoke_session(
            token_hash,
            revoked_at=self._parse_iso_datetime(revoked_at, "revoked_at"),
            reason="auth-manager",
        )

    def auth_revoke_all_sessions(self, user_id: int, revoked_at: str) -> None:
        """Revoke all sessions for a user through the AuthStore protocol."""

        self.revoke_user_sessions(
            user_id,
            revoked_at=self._parse_iso_datetime(revoked_at, "revoked_at"),
        )

    def auth_set_session_mfa(
        self, token_hash: str, method: str, verified_at: str, expected_factor_id: int
    ) -> bool:
        """Bind one proof to a live session and the factor generation it verified."""

        token_hash = self._require_token_hash(token_hash, "token_hash")
        if method not in {"totp", "recovery"}:
            raise ValueError("mfa method is not supported")
        factor_id = self._require_factor_id(expected_factor_id)
        verified = self._parse_iso_datetime(verified_at, "verified_at")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """UPDATE sessions SET mfa_method = ?, mfa_verified_at = ?, mfa_factor_id = ?
                WHERE token_hash = ? AND revoked_at IS NULL
                  AND idle_expires_at > ? AND absolute_expires_at > ?
                  AND EXISTS (
                      SELECT 1 FROM totp_factors AS factor
                      WHERE factor.id = ? AND factor.user_id = sessions.user_id
                  )""",
                (
                    method,
                    verified.isoformat(),
                    factor_id,
                    token_hash,
                    verified.isoformat(),
                    verified.isoformat(),
                    factor_id,
                ),
            )
            connection.commit()
        return bool(cursor.rowcount)

    def auth_list_sessions(self, user_id: int) -> list[dict[str, Any]]:
        """List bounded session metadata for account security screens."""

        if type(user_id) is not int or user_id < 1:
            raise ValueError("user_id must be a positive integer")
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT id, session_id, user_id, auth_method, issued_at AS created_at,
                last_seen_at, idle_expires_at, absolute_expires_at AS expires_at,
                last_passkey_at, mfa_method, mfa_verified_at, mfa_factor_id,
                revoked_at, revocation_reason
                FROM sessions WHERE user_id = ? ORDER BY id DESC LIMIT 100""",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def auth_revoke_session_by_id(self, user_id: int, session_id: str, revoked_at: str) -> None:
        """Revoke a session only when its opaque identifier belongs to the caller."""

        if type(user_id) is not int or user_id < 1 or not isinstance(session_id, str):
            return
        timestamp = self._parse_iso_datetime(revoked_at, "revoked_at")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """UPDATE sessions SET revoked_at = ?, revocation_reason = 'account-security'
                WHERE user_id = ? AND session_id = ? AND revoked_at IS NULL""",
                (timestamp.isoformat(), user_id, session_id),
            )
            connection.commit()

    def revoke_session(self, token_hash: str, *, revoked_at: datetime, reason: str) -> bool:
        """Revoke one opaque session token without deleting security history."""

        token_hash = self._require_token_hash(token_hash, "token_hash")
        revoked = self._iso_datetime(revoked_at, "revoked_at")
        if not isinstance(reason, str) or not 1 <= len(reason) <= 200:
            raise ValueError("reason must be 1-200 characters")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """UPDATE sessions SET revoked_at = ?, revocation_reason = ?
                WHERE token_hash = ? AND revoked_at IS NULL""",
                (revoked, reason, token_hash),
            )
            connection.commit()
        return bool(cursor.rowcount)

    def revoke_user_sessions(self, user_id: int, *, revoked_at: datetime) -> int:
        """Revoke every active session for a user during security changes or restore."""

        revoked = self._iso_datetime(revoked_at, "revoked_at")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """UPDATE sessions SET revoked_at = ?, revocation_reason = 'security-change'
                WHERE user_id = ? AND revoked_at IS NULL""",
                (revoked, user_id),
            )
            connection.commit()
        return int(cursor.rowcount)

    def auth_begin_totp_enrollment(
        self,
        user_id: int,
        secret_ciphertext: str,
        created_at: str,
        expires_at: str,
        expected_factor_id: int | None = None,
        origin_token_hash: str | None = None,
    ) -> dict[str, Any]:
        """Store an enrollment bound to the current factor generation and live origin."""

        if type(user_id) is not int or user_id < 1:
            raise ValueError("user_id must be a positive integer")
        secret = self._require_totp_secret_ciphertext(secret_ciphertext)
        created = self._parse_iso_datetime(created_at, "created_at")
        expires = self._parse_iso_datetime(expires_at, "expires_at")
        lifetime = expires - created
        if lifetime <= timedelta(0) or lifetime > timedelta(minutes=10):
            raise ValueError("TOTP enrollment must expire within 10 minutes")
        expected_factor = self._optional_factor_id(expected_factor_id)
        if origin_token_hash is None:
            raise ValueError("TOTP enrollment requires an originating session")
        origin_token_hash = self._require_token_hash(origin_token_hash, "origin_token_hash")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_user_exists(connection, user_id)
            current_factor = connection.execute(
                "SELECT id FROM totp_factors WHERE user_id = ?", (user_id,)
            ).fetchone()
            current_factor_id = int(current_factor["id"]) if current_factor is not None else None
            if current_factor_id != expected_factor:
                connection.rollback()
                return None
            origin = connection.execute(
                """SELECT id FROM sessions
                WHERE token_hash = ? AND user_id = ? AND revoked_at IS NULL
                  AND idle_expires_at > ? AND absolute_expires_at > ?""",
                (origin_token_hash, user_id, created.isoformat(), created.isoformat()),
            ).fetchone()
            if origin is None:
                connection.rollback()
                return None
            connection.execute(
                """INSERT INTO totp_enrollments
                (user_id, secret_ciphertext, created_at, expires_at,
                 expected_factor_id, origin_token_hash)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    secret_ciphertext = excluded.secret_ciphertext,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at,
                    expected_factor_id = excluded.expected_factor_id,
                    origin_token_hash = excluded.origin_token_hash""",
                (
                    user_id,
                    secret,
                    created.isoformat(),
                    expires.isoformat(),
                    expected_factor,
                    origin_token_hash,
                ),
            )
            row = connection.execute(
                """SELECT id, user_id, secret_ciphertext, created_at, expires_at,
                expected_factor_id, origin_token_hash
                FROM totp_enrollments WHERE user_id = ?""",
                (user_id,),
            ).fetchone()
            connection.commit()
        if row is None:
            raise RepositoryDatabaseError("TOTP enrollment could not be read")
        return dict(row)

    def auth_get_totp_enrollment(
        self, user_id: int, now: str | None = None
    ) -> dict[str, Any] | None:
        """Return a pending enrollment only while its ten-minute window remains open."""

        if type(user_id) is not int or user_id < 1:
            return None
        current = self._parse_iso_datetime(now, "now") if now is not None else datetime.now(UTC)
        with self.connect() as connection:
            row = connection.execute(
                """SELECT id, user_id, secret_ciphertext, created_at, expires_at,
                expected_factor_id, origin_token_hash
                FROM totp_enrollments WHERE user_id = ? AND expires_at > ?""",
                (user_id, current.isoformat()),
            ).fetchone()
        return dict(row) if row is not None else None

    def auth_confirm_totp_enrollment(
        self,
        user_id: int,
        confirmed_at: str,
        expected_secret_ciphertext: str,
        accepted_step: int,
        recovery_code_hashes: Sequence[str],
        revoked_at: str,
        expected_factor_id: int | None | object = _UNSET,
        origin_token_hash: str | None = None,
    ) -> dict[str, Any] | None:
        """Promote a pending factor only when its generation and live origin still match."""

        if type(user_id) is not int or user_id < 1:
            return None
        expected_secret = self._require_totp_secret_ciphertext(expected_secret_ciphertext)
        confirmed_step = self._require_totp_step(accepted_step)
        normalized_recovery_hashes = self._normalize_recovery_code_hashes(recovery_code_hashes)
        confirmed = self._parse_iso_datetime(confirmed_at, "confirmed_at")
        confirmed_text = confirmed.isoformat()
        revoked = self._parse_iso_datetime(revoked_at, "revoked_at")
        revoked_text = revoked.isoformat()
        if expected_factor_id is _UNSET or origin_token_hash is None:
            return None
        supplied_expected_factor = self._optional_factor_id(expected_factor_id)
        supplied_origin = (
            self._require_token_hash(origin_token_hash, "origin_token_hash")
            if origin_token_hash is not None
            else None
        )
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT secret_ciphertext, created_at, expires_at,
                expected_factor_id, origin_token_hash
                FROM totp_enrollments
                WHERE user_id = ? AND secret_ciphertext = ? AND expires_at > ?""",
                (user_id, expected_secret, confirmed_text),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            self._ensure_user_exists(connection, user_id)
            enrolled_expected_factor = self._optional_factor_id(row["expected_factor_id"])
            enrolled_origin = row["origin_token_hash"]
            if not isinstance(enrolled_origin, str):
                connection.rollback()
                return None
            if (
                supplied_expected_factor != enrolled_expected_factor
                or supplied_origin != enrolled_origin
            ):
                connection.rollback()
                return None
            current_factor = connection.execute(
                "SELECT id FROM totp_factors WHERE user_id = ?", (user_id,)
            ).fetchone()
            current_factor_id = int(current_factor["id"]) if current_factor is not None else None
            if current_factor_id != enrolled_expected_factor:
                connection.rollback()
                return None
            origin = connection.execute(
                """SELECT id FROM sessions
                WHERE token_hash = ? AND user_id = ? AND revoked_at IS NULL
                  AND idle_expires_at > ? AND absolute_expires_at > ?""",
                (enrolled_origin, user_id, confirmed_text, confirmed_text),
            ).fetchone()
            if origin is None:
                connection.rollback()
                return None
            # Revoke every other active session while retaining the live origin for the
            # conditional post-confirmation session insert.  The origin is revoked by that
            # insert after the new generation has been checked.
            connection.execute(
                """UPDATE sessions SET revoked_at = ?, revocation_reason = 'security-change'
                WHERE user_id = ? AND token_hash != ? AND revoked_at IS NULL""",
                (revoked_text, user_id, enrolled_origin),
            )
            # Do not UPDATE the factor in place: its autoincrement id is the generation fence.
            connection.execute("DELETE FROM totp_factors WHERE user_id = ?", (user_id,))
            connection.execute(
                """INSERT INTO totp_factors
                (user_id, secret_ciphertext, created_at, confirmed_at,
                 last_accepted_step, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    row["secret_ciphertext"],
                    row["created_at"],
                    confirmed_text,
                    confirmed_step,
                    confirmed_text,
                ),
            )
            connection.execute(
                """UPDATE recovery_codes SET revoked_at = ?
                WHERE user_id = ? AND consumed_at IS NULL AND revoked_at IS NULL""",
                (revoked_text, user_id),
            )
            connection.executemany(
                """INSERT INTO recovery_codes(user_id, code_hash, created_at)
                VALUES (?, ?, ?)""",
                [(user_id, code_hash, confirmed_text) for code_hash in normalized_recovery_hashes],
            )
            connection.execute("DELETE FROM totp_attempt_throttles WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM totp_enrollments WHERE user_id = ?", (user_id,))
            factor = connection.execute(
                """SELECT id, user_id, secret_ciphertext, created_at, confirmed_at,
                last_accepted_step, updated_at FROM totp_factors WHERE user_id = ?""",
                (user_id,),
            ).fetchone()
            connection.commit()
        return dict(factor) if factor is not None else None

    def auth_get_totp_factor(self, user_id: int) -> dict[str, Any] | None:
        """Return the active factor for one account, including only encrypted secret material."""

        if type(user_id) is not int or user_id < 1:
            return None
        with self.connect() as connection:
            row = connection.execute(
                """SELECT id, user_id, secret_ciphertext, created_at, confirmed_at,
                last_accepted_step, updated_at FROM totp_factors WHERE user_id = ?""",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["encrypted_secret"] = result["secret_ciphertext"]
        # ``id`` is the immutable generation fence; aliases keep the repository contract
        # explicit for callers that should never infer generation from timestamps.
        result["factor_id"] = result["id"]
        result["generation"] = result["id"]
        return result

    def auth_accept_totp_step(
        self, user_id: int, expected_factor_id: int, step: int, accepted_at: str
    ) -> bool:
        """Accept a TOTP time-step once per account through an atomic monotonic CAS."""

        if type(user_id) is not int or user_id < 1:
            return False
        factor_id = self._require_factor_id(expected_factor_id)
        accepted_step = self._require_totp_step(step)
        accepted = self._parse_iso_datetime(accepted_at, "accepted_at")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """UPDATE totp_factors SET last_accepted_step = ?, updated_at = ?
                WHERE id = ? AND user_id = ? AND last_accepted_step < ?""",
                (accepted_step, accepted.isoformat(), factor_id, user_id, accepted_step),
            )
            connection.commit()
        return bool(cursor.rowcount)

    def auth_check_totp_attempt(self, user_id: int, attempted_at: str) -> dict[str, Any]:
        """Read the durable per-user throttle state without incrementing a failure."""

        if type(user_id) is not int or user_id < 1:
            raise ValueError("user_id must be a positive integer")
        attempted = self._parse_iso_datetime(attempted_at, "attempted_at")
        with self.connect() as connection:
            row = connection.execute(
                """SELECT user_id, window_started_at, attempt_count,
                last_attempt_at, locked_until FROM totp_attempt_throttles
                WHERE user_id = ?""",
                (user_id,),
            ).fetchone()
        if row is None:
            return {
                "user_id": user_id,
                "window_started_at": attempted.isoformat(),
                "attempt_count": 0,
                "last_attempt_at": attempted.isoformat(),
                "locked_until": None,
                "allowed": True,
            }
        locked_until = row["locked_until"]
        allowed = locked_until is None or attempted.isoformat() >= locked_until
        return dict(row) | {"allowed": allowed}

    def auth_reserve_totp_attempt(
        self,
        user_id: int,
        attempted_at: str,
        expected_factor_id: int | None = None,
        window_seconds: int = 300,
        max_attempts: int = 5,
        lockout_seconds: int = 900,
    ) -> bool:
        """Reserve one authenticator attempt before crypto, under the SQLite write lock.

        A reservation is counted before the caller compares a code.  Concurrent callers
        therefore cannot all observe the same pre-limit count and proceed past verification.
        The fifth reservation is admitted and closes the window; a successful caller clears
        it through ``auth_record_totp_attempt(..., successful=True)``.
        """

        if type(user_id) is not int or user_id < 1:
            raise ValueError("user_id must be a positive integer")
        window_seconds, max_attempts, lockout_seconds = self._require_totp_attempt_limits(
            window_seconds, max_attempts, lockout_seconds
        )
        attempted = self._parse_iso_datetime(attempted_at, "attempted_at")
        expected_factor = self._optional_factor_id(expected_factor_id)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_user_exists(connection, user_id)
            if expected_factor is not None and connection.execute(
                "SELECT 1 FROM totp_factors WHERE id = ? AND user_id = ?",
                (expected_factor, user_id),
            ).fetchone() is None:
                connection.rollback()
                return False
            row = connection.execute(
                """SELECT window_started_at, attempt_count, last_attempt_at, locked_until
                FROM totp_attempt_throttles WHERE user_id = ?""",
                (user_id,),
            ).fetchone()
            if row is None:
                window_started = attempted
                attempt_count = 0
                locked_until: datetime | None = None
            else:
                window_started = self._parse_iso_datetime(
                    row["window_started_at"], "window_started_at"
                )
                last_attempt = self._parse_iso_datetime(row["last_attempt_at"], "last_attempt_at")
                # Requests may capture their timestamp before waiting on BEGIN IMMEDIATE.
                # Clamp that normal scheduling skew instead of turning a valid concurrent
                # guess into a server error.
                if attempted < last_attempt:
                    attempted = last_attempt
                locked_until = (
                    self._parse_iso_datetime(row["locked_until"], "locked_until")
                    if row["locked_until"] is not None
                    else None
                )
                attempt_count = int(row["attempt_count"])
                if locked_until is not None and attempted < locked_until:
                    connection.rollback()
                    return False
                if attempted >= window_started + timedelta(seconds=window_seconds):
                    window_started = attempted
                    attempt_count = 0
                    locked_until = None
                elif locked_until is not None:
                    # A lock that reached its expiry starts a fresh bounded window.
                    window_started = attempted
                    attempt_count = 0
                    locked_until = None
            attempted_text = attempted.isoformat()
            if attempt_count >= max_attempts:
                connection.rollback()
                return False
            attempt_count += 1
            locked_until = (
                attempted + timedelta(seconds=lockout_seconds)
                if attempt_count >= max_attempts
                else None
            )
            connection.execute(
                """INSERT INTO totp_attempt_throttles
                (user_id, window_started_at, attempt_count, last_attempt_at, locked_until)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    window_started_at = excluded.window_started_at,
                    attempt_count = excluded.attempt_count,
                    last_attempt_at = excluded.last_attempt_at,
                    locked_until = excluded.locked_until""",
                (
                    user_id,
                    window_started.isoformat(),
                    attempt_count,
                    attempted_text,
                    locked_until.isoformat() if locked_until is not None else None,
                ),
            )
            connection.commit()
        return True

    def auth_record_totp_attempt(
        self,
        user_id: int,
        attempted_at: str,
        window_seconds: int = 300,
        max_attempts: int = 5,
        lockout_seconds: int = 900,
        successful: bool = False,
    ) -> dict[str, Any]:
        """Record a TOTP success/failure with a bounded, durable per-user throttle."""

        if type(user_id) is not int or user_id < 1:
            raise ValueError("user_id must be a positive integer")
        window_seconds, max_attempts, lockout_seconds = self._require_totp_attempt_limits(
            window_seconds, max_attempts, lockout_seconds
        )
        if type(successful) is not bool:
            raise ValueError("successful must be a boolean")
        attempted = self._parse_iso_datetime(attempted_at, "attempted_at")
        attempted_text = attempted.isoformat()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_user_exists(connection, user_id)
            row = connection.execute(
                """SELECT window_started_at, attempt_count, last_attempt_at, locked_until
                FROM totp_attempt_throttles WHERE user_id = ?""",
                (user_id,),
            ).fetchone()
            if row is None:
                window_started = attempted
                attempt_count = 0
                locked_until: datetime | None = None
            else:
                window_started = self._parse_iso_datetime(
                    row["window_started_at"], "window_started_at"
                )
                last_attempt = self._parse_iso_datetime(row["last_attempt_at"], "last_attempt_at")
                if attempted < last_attempt:
                    connection.rollback()
                    raise ValueError("attempted_at cannot precede the last TOTP attempt")
                locked_until = (
                    self._parse_iso_datetime(row["locked_until"], "locked_until")
                    if row["locked_until"] is not None
                    else None
                )
                attempt_count = int(row["attempt_count"])
                if not successful and last_attempt == attempted:
                    # The pre-verification reservation already counted this exact attempt.
                    # Keep compatibility callers from double-incrementing a failed guess.
                    connection.rollback()
                    return dict(row) | {
                        "user_id": user_id,
                        "allowed": locked_until is None or attempted >= locked_until,
                    }
                if not successful and locked_until is not None and attempted < locked_until:
                    connection.rollback()
                    return dict(row) | {
                        "user_id": user_id,
                        "allowed": False,
                    }
                if (
                    attempted >= window_started + timedelta(seconds=window_seconds)
                    or locked_until is not None
                ):
                    window_started = attempted
                    attempt_count = 0
                    locked_until = None
            if successful:
                attempt_count = 0
                window_started = attempted
                locked_until = None
                allowed = True
            else:
                attempt_count = min(attempt_count + 1, MAX_TOTP_ATTEMPTS_PER_WINDOW)
                allowed = attempt_count < max_attempts
                locked_until = (
                    attempted + timedelta(seconds=lockout_seconds) if not allowed else None
                )
            connection.execute(
                """INSERT INTO totp_attempt_throttles
                (user_id, window_started_at, attempt_count, last_attempt_at, locked_until)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    window_started_at = excluded.window_started_at,
                    attempt_count = excluded.attempt_count,
                    last_attempt_at = excluded.last_attempt_at,
                    locked_until = excluded.locked_until""",
                (
                    user_id,
                    window_started.isoformat(),
                    attempt_count,
                    attempted_text,
                    locked_until.isoformat() if locked_until is not None else None,
                ),
            )
            connection.commit()
        return {
            "user_id": user_id,
            "window_started_at": window_started.isoformat(),
            "attempt_count": attempt_count,
            "last_attempt_at": attempted_text,
            "locked_until": locked_until.isoformat() if locked_until is not None else None,
            "allowed": allowed,
        }

    def auth_create_recovery_codes(
        self,
        user_id: int,
        expected_factor_id: int,
        code_hashes: Sequence[str],
        created_at: str,
        origin_token_hash: str,
    ) -> bool:
        """Rotate recovery codes only for the current generation and a live origin."""

        if type(user_id) is not int or user_id < 1:
            raise ValueError("user_id must be a positive integer")
        factor_id = self._require_factor_id(expected_factor_id)
        if not isinstance(code_hashes, Sequence) or isinstance(code_hashes, str | bytes):
            raise ValueError("code_hashes must be a sequence")
        source_token = self._require_token_hash(origin_token_hash, "origin_token_hash")
        normalized = self._normalize_recovery_code_hashes(code_hashes)
        created = self._parse_iso_datetime(created_at, "created_at")
        created_text = created.isoformat()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_user_exists(connection, user_id)
            if connection.execute(
                "SELECT 1 FROM totp_factors WHERE id = ? AND user_id = ?",
                (factor_id, user_id),
            ).fetchone() is None:
                connection.rollback()
                return False
            if connection.execute(
                """SELECT 1 FROM sessions
                WHERE token_hash = ? AND user_id = ? AND revoked_at IS NULL
                  AND idle_expires_at > ? AND absolute_expires_at > ?""",
                (source_token, user_id, created_text, created_text),
            ).fetchone() is None:
                connection.rollback()
                return False
            connection.execute(
                """UPDATE recovery_codes SET revoked_at = ?
                WHERE user_id = ? AND consumed_at IS NULL AND revoked_at IS NULL""",
                (created_text, user_id),
            )
            connection.executemany(
                """INSERT INTO recovery_codes(user_id, code_hash, created_at)
                VALUES (?, ?, ?)""",
                [(user_id, code_hash, created_text) for code_hash in normalized],
            )
            connection.commit()
        return True

    def auth_consume_recovery_code(
        self,
        user_id: int,
        expected_factor_id: int,
        code_hash: str,
        consumed_at: str,
    ) -> bool:
        """Consume one code while fencing the current factor generation."""

        if type(user_id) is not int or user_id < 1:
            return False
        factor_id = self._require_factor_id(expected_factor_id)
        normalized = self._require_token_hash(code_hash, "code_hash")
        consumed = self._parse_iso_datetime(consumed_at, "consumed_at")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM totp_factors WHERE id = ? AND user_id = ?",
                (factor_id, user_id),
            ).fetchone() is None:
                connection.rollback()
                return False
            cursor = connection.execute(
                """UPDATE recovery_codes SET consumed_at = ?
                WHERE user_id = ? AND code_hash = ?
                  AND consumed_at IS NULL AND revoked_at IS NULL""",
                (consumed.isoformat(), user_id, normalized),
            )
            connection.commit()
        return bool(cursor.rowcount)

    def auth_get_recovery_code_status(self, user_id: int) -> dict[str, Any]:
        """Return recovery-code counts without exposing hashes or code material."""

        if type(user_id) is not int or user_id < 1:
            raise ValueError("user_id must be a positive integer")
        with self.connect() as connection:
            row = connection.execute(
                """SELECT
                    COUNT(*) AS total_count,
                    SUM(CASE WHEN consumed_at IS NULL AND revoked_at IS NULL THEN 1 ELSE 0 END)
                        AS available_count,
                    SUM(CASE WHEN consumed_at IS NOT NULL THEN 1 ELSE 0 END) AS consumed_count,
                    SUM(CASE WHEN revoked_at IS NOT NULL THEN 1 ELSE 0 END) AS revoked_count
                FROM recovery_codes WHERE user_id = ?""",
                (user_id,),
            ).fetchone()
        values = dict(row) if row is not None else {}
        return {
            "user_id": user_id,
            "total_count": int(values.get("total_count") or 0),
            "available_count": int(values.get("available_count") or 0),
            "consumed_count": int(values.get("consumed_count") or 0),
            "revoked_count": int(values.get("revoked_count") or 0),
        }

    def auth_list_recovery_code_status(self, user_id: int) -> list[dict[str, Any]]:
        """Return current recovery-code usage rows without exposing code hashes."""

        if type(user_id) is not int or user_id < 1:
            raise ValueError("user_id must be a positive integer")
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT id, user_id, created_at, consumed_at, revoked_at
                FROM recovery_codes WHERE user_id = ? AND revoked_at IS NULL ORDER BY id""",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def register_passkey(
        self,
        *,
        user_id: int,
        credential_id: str,
        public_key: str,
        sign_count: int,
        transports: str | None,
        created_at: datetime,
    ) -> dict[str, Any]:
        """Register a WebAuthn credential without ever persisting a private key."""

        if not isinstance(credential_id, str) or not 16 <= len(credential_id) <= 1024:
            raise ValueError("credential_id length is invalid")
        if not isinstance(public_key, str) or not 16 <= len(public_key) <= 16384:
            raise ValueError("public_key length is invalid")
        if type(sign_count) is not int or sign_count < 0:
            raise ValueError("sign_count must be a non-negative integer")
        timestamp = self._iso_datetime(created_at, "created_at")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_user_exists(connection, user_id)
            cursor = connection.execute(
                """INSERT INTO passkeys
                (user_id, credential_id, public_key, sign_count, transports, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, credential_id, public_key, sign_count, transports, timestamp),
            )
            passkey_id = self._insert_id(cursor)
            connection.commit()
            row = connection.execute(
                """SELECT id, user_id, credential_id, public_key, sign_count, transports,
                created_at, last_used_at, revoked_at FROM passkeys WHERE id = ?""",
                (passkey_id,),
            ).fetchone()
        if row is None:
            raise RepositoryDatabaseError("created passkey could not be read")
        return dict(row)

    def get_passkey(self, credential_id: str, *, user_id: int) -> dict[str, Any] | None:
        """Return one passkey only when it belongs to the expected account."""

        if not isinstance(credential_id, str) or not credential_id:
            return None
        if type(user_id) is not int or user_id < 1:
            return None
        with self.connect() as connection:
            row = connection.execute(
                """SELECT id, user_id, credential_id, public_key, sign_count, transports,
                created_at, last_used_at, revoked_at FROM passkeys
                WHERE credential_id = ? AND user_id = ? AND revoked_at IS NULL""",
                (credential_id, user_id),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_user_passkeys(self, user_id: int) -> list[dict[str, Any]]:
        """List passkey metadata for account settings without returning key material."""

        if type(user_id) is not int or user_id < 1:
            raise ValueError("user_id must be a positive integer")
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT id, credential_id, sign_count, transports, created_at,
                last_used_at, revoked_at FROM passkeys WHERE user_id = ? ORDER BY id DESC""",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_passkey_sign_count(
        self, credential_id: str, *, sign_count: int, used_at: datetime
    ) -> bool:
        """Advance a passkey counter monotonically after a verified assertion."""

        if type(sign_count) is not int or sign_count < 0:
            raise ValueError("sign_count must be a non-negative integer")
        timestamp = self._iso_datetime(used_at, "used_at")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """UPDATE passkeys SET sign_count = ?, last_used_at = ?
                WHERE credential_id = ? AND revoked_at IS NULL AND sign_count <= ?""",
                (sign_count, timestamp, credential_id, sign_count),
            )
            connection.commit()
        return bool(cursor.rowcount)

    def revoke_passkey(self, credential_id: str, *, revoked_at: datetime) -> bool:
        """Revoke a passkey while retaining its credential audit row."""

        timestamp = self._iso_datetime(revoked_at, "revoked_at")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE passkeys SET revoked_at = ? WHERE credential_id = ? AND revoked_at IS NULL",
                (timestamp, credential_id),
            )
            connection.commit()
        return bool(cursor.rowcount)

    def auth_create_passkey(self, fields: Mapping[str, object]) -> dict[str, Any]:
        """Register a WebAuthn credential from the auth manager's durable field mapping."""

        user_id = fields.get("user_id")
        credential_id = fields.get("credential_id")
        public_key = fields.get("public_key")
        sign_count = fields.get("sign_count", 0)
        transports = fields.get("transports")
        if type(user_id) is not int or not isinstance(credential_id, str):
            raise ValueError("passkey identity is invalid")
        if not isinstance(public_key, str) or type(sign_count) is not int:
            raise ValueError("passkey credential is invalid")
        created_at = self._parse_iso_datetime(fields.get("created_at"), "created_at")
        return self.register_passkey(
            user_id=user_id,
            credential_id=credential_id,
            public_key=public_key,
            sign_count=sign_count,
            transports=transports if isinstance(transports, str) else None,
            created_at=created_at,
        )

    def auth_get_passkeys(self, user_id: int) -> list[dict[str, Any]]:
        """List passkeys in the shape required by WebAuthn assertion options."""

        return [
            record
            for record in self.list_user_passkeys(user_id)
            if record.get("revoked_at") is None
        ]

    def auth_get_passkey(
        self, credential_id: str, *, user_id: int | None = None
    ) -> dict[str, Any] | None:
        """Require the expected account when resolving a credential for assertion."""

        if user_id is None:
            return None
        return self.get_passkey(credential_id, user_id=user_id)

    def auth_update_passkey(self, fields: Mapping[str, object]) -> dict[str, Any] | None:
        """Advance a verified credential counter without allowing decreases or reactivation."""

        credential_id = fields.get("credential_id")
        sign_count = fields.get("sign_count")
        if not isinstance(credential_id, str) or type(sign_count) is not int:
            raise ValueError("sign_count must be a non-negative integer")
        used_value = fields.get("last_used_at", datetime.now(UTC))
        used_at = self._parse_iso_datetime(used_value, "last_used_at")
        if not self.update_passkey_sign_count(
            credential_id, sign_count=sign_count, used_at=used_at
        ):
            return None
        with self.connect() as connection:
            row = connection.execute(
                """SELECT id, user_id, credential_id, public_key, sign_count,
                transports, created_at, last_used_at, revoked_at
                FROM passkeys WHERE credential_id = ? AND revoked_at IS NULL""",
                (credential_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    @staticmethod
    def _utc_microseconds(value: datetime) -> int:
        """Return an exact integer UTC key without a float timestamp conversion."""

        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("stored audit timestamps must include a timezone offset")
        utc_value = value.astimezone(UTC)
        epoch_delta = utc_value - datetime(1970, 1, 1, tzinfo=UTC)
        return (
            epoch_delta.days * 86_400 + epoch_delta.seconds
        ) * 1_000_000 + epoch_delta.microseconds

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
        owner_user_id: int,
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
            self._ensure_owner_can_write(connection, owner_user_id)
            resolved_source_event_id = self._resolved_analysis_source(
                connection, owner_user_id, analysis_kind, source_event_id
            )
            repeated = self._has_prior_submission(
                connection, owner_user_id, submitted_symbol, normalized_symbol, asset_type
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
            connection.execute(
                "INSERT INTO search_event_owners(event_id, owner_user_id, assigned_at) "
                "VALUES (?, ?, ?)",
                (event_id, owner_user_id, submitted_at.astimezone(UTC).isoformat()),
            )
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
        owner_user_id: int,
        analysis_kind: str,
        requested_source_event_id: int | None,
    ) -> int | None:
        """Use an FK only for a real successful source while retaining the requested ID."""

        if analysis_kind != "fresh_historical_reconstruction":
            return requested_source_event_id
        if type(requested_source_event_id) is not int or requested_source_event_id < 1:
            return None
        row = connection.execute(
            """SELECT event.id FROM search_events AS event
            JOIN search_event_owners AS owner ON owner.event_id = event.id
            WHERE event.id = ? AND owner.owner_user_id = ? AND event.run_id IS NOT NULL""",
            (requested_source_event_id, owner_user_id),
        ).fetchone()
        return int(row["id"]) if row is not None else None

    @staticmethod
    def _has_prior_submission(
        connection: sqlite3.Connection,
        owner_user_id: int,
        submitted_symbol: str,
        normalized_symbol: str | None,
        asset_type: str,
    ) -> bool:
        """Detect repeats even for invalid symbols that could not be normalized."""

        if normalized_symbol is not None:
            row = connection.execute(
                """SELECT 1 FROM search_events AS event
                JOIN search_event_owners AS owner ON owner.event_id = event.id
                WHERE owner.owner_user_id = ? AND event.normalized_symbol = ?
                  AND event.asset_type = ? LIMIT 1""",
                (owner_user_id, normalized_symbol, asset_type),
            ).fetchone()
        else:
            row = connection.execute(
                """SELECT 1 FROM search_events AS event
                JOIN search_event_owners AS owner ON owner.event_id = event.id
                WHERE owner.owner_user_id = ? AND event.submitted_symbol = ?
                  AND event.asset_type = ? LIMIT 1""",
                (owner_user_id, submitted_symbol[:64], asset_type),
            ).fetchone()
        return row is not None

    def record_success(
        self,
        *,
        owner_user_id: int,
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
        requested_interval = input_snapshot.get("requested_interval")
        if requested_interval is None:
            expected_horizons = {"close_to_close", "completed_5m_to_close"}
        else:
            requested_horizon = FORECAST_INTERVAL_HORIZONS.get(requested_interval)
            if requested_horizon is None:
                raise ValueError("forecast input interval is not supported")
            expected_horizons = {requested_horizon}
        if len(horizons) != len(expected_horizons) or set(horizons) != expected_horizons:
            raise ValueError("forecast result cardinality must match the requested interval")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_owner_can_write(connection, owner_user_id)
            resolved_source_event_id = self._resolved_analysis_source(
                connection, owner_user_id, analysis_kind, source_event_id
            )
            prior = (
                connection.execute(
                    """SELECT run.id FROM forecast_runs AS run
                    JOIN forecast_run_owners AS owner ON owner.run_id = run.id
                    WHERE owner.owner_user_id = ? AND run.symbol = ?
                      AND run.asset_type = ? AND run.content_fingerprint = ?""",
                    (owner_user_id, symbol, asset_type, fingerprint),
                ).fetchone()
                if reuse_exact_input
                else None
            )
            repeated = self._has_prior_submission(
                connection, owner_user_id, submitted_symbol, symbol, asset_type
            )
            reused = prior is not None
            if prior is not None:
                run_id = int(prior["id"])
            else:
                global_run = connection.execute(
                    "SELECT id FROM forecast_runs WHERE symbol = ? AND asset_type = ? "
                    "AND content_fingerprint = ?",
                    (symbol, asset_type, fingerprint),
                ).fetchone()
                if global_run is not None:
                    run_id = int(global_run["id"])
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
                            (
                                input_id,
                                result["horizon"],
                                self._json(result),
                                completed_at.isoformat(),
                            )
                            for result in results
                        ],
                    )
            connection.execute(
                "INSERT OR IGNORE INTO forecast_run_owners(run_id, owner_user_id, assigned_at) "
                "VALUES (?, ?, ?)",
                (run_id, owner_user_id, completed_at.astimezone(UTC).isoformat()),
            )
            result_owner_rows = connection.execute(
                """SELECT result.id FROM forecast_inputs AS input
                JOIN forecast_results AS result ON result.input_id = input.id
                WHERE input.run_id = ?""",
                (run_id,),
            ).fetchall()
            connection.executemany(
                "INSERT OR IGNORE INTO forecast_result_owners"
                "(result_id, owner_user_id, assigned_at) "
                "VALUES (?, ?, ?)",
                [
                    (int(row["id"]), owner_user_id, completed_at.astimezone(UTC).isoformat())
                    for row in result_owner_rows
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
            connection.execute(
                "INSERT INTO search_event_owners(event_id, owner_user_id, assigned_at) "
                "VALUES (?, ?, ?)",
                (event_id, owner_user_id, submitted_at.astimezone(UTC).isoformat()),
            )
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
    def _validate_instrument_provenance(input_snapshot: dict[str, Any], asset_type: str) -> None:
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
            or provenance.get("identity_fingerprint") != input_snapshot.get("identity_fingerprint")
            or input_snapshot.get("identity_fingerprint") != identity_fingerprint
            or provenance.get("content_fingerprint") != input_snapshot.get("content_fingerprint")
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
            # Explicitly unavailable rolling horizons carry fingerprints and a reason instead
            # of a walk-forward evaluation; they are never presented as measured results.
            if (
                result.get("horizon") in _ROLLING_RESULT_HORIZONS
                and result.get("availability") == "unavailable"
            ):
                if (
                    result.get("model_fingerprint") != model_fingerprint
                    or result.get("forecast_contract_version") != contract_version
                    or expected != calculated
                    or not isinstance(result.get("unavailable_reason"), str)
                    or not result["unavailable_reason"]
                ):
                    raise ValueError(
                        "forecast result must match immutable model and evaluation provenance"
                    )
                continue
            if (
                result.get("model_fingerprint") != model_fingerprint
                or result.get("forecast_contract_version") != contract_version
                or expected != calculated
                or not isinstance(evaluation, dict)
                or evaluation.get("method") != "bounded chronological expanding-window walk-forward"
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
        owner_user_id: int,
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

        owner_user_id = self._require_owner_id(owner_user_id)
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
            self._ensure_user_exists(connection, owner_user_id)
            return self._history_page(
                connection,
                owner_user_id,
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
    def _history_where(
        cls,
        filters: HistoryFilters,
        *,
        owner_user_id: int,
        horizon: str | None = None,
    ) -> tuple[str, list[Any]]:
        """Compile only fixed clauses; user values always remain bound parameters."""

        clauses = ["owner.owner_user_id = ?"]
        values: list[Any] = [owner_user_id]
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
            "saved": ("event.analysis_kind = 'submitted_forecast' AND event.run_id IS NOT NULL"),
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
        if horizon is not None:
            clauses.append(
                "event.run_id IS NOT NULL AND EXISTS ("
                "SELECT 1 FROM forecast_inputs AS horizon_input "
                "JOIN forecast_results AS horizon_result "
                "ON horizon_result.input_id = horizon_input.id "
                "WHERE horizon_input.run_id = event.run_id "
                "AND json_extract(horizon_result.result_json, '$.horizon') = ?"
                ")"
            )
            values.append(horizon)
        return " AND ".join(clauses), values

    @classmethod
    def _history_page(
        cls,
        connection: sqlite3.Connection,
        owner_user_id: int,
        filters: HistoryFilters,
        *,
        page: int,
        page_size: int,
        include_analysis: bool,
        include_facets: bool,
        include_summaries: bool = True,
        sort_by: str | None = None,
        sort_order: str = "desc",
        horizon: str | None = None,
    ) -> dict[str, Any]:
        where, values = cls._history_where(filters, owner_user_id=owner_user_id, horizon=horizon)
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
            "ON facet.event_id = event.id JOIN search_event_owners AS owner "
            "ON owner.event_id = event.id"
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
                    "THEN 'close_to_close,completed_5m_to_close,five_min_forward,"
                    "daily_1,weekly_5,monthly_21,quarterly_63' END"
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
        items = [dict(row) for row in rows]
        if include_summaries:
            run_ids = list(
                dict.fromkeys(int(item["run_id"]) for item in items if item["run_id"] is not None)
            )
            summaries: dict[int, dict[str, Any]] = {}
            if run_ids:
                placeholders = ",".join("?" for _ in run_ids)
                summary_rows = connection.execute(
                    f"""SELECT input.run_id, result.horizon,
                    json_extract(result.result_json, '$.evaluation.status') AS evaluation_status,
                    COUNT(outcome_owner.outcome_id) AS outcome_count
                    FROM forecast_inputs AS input
                    JOIN forecast_results AS result ON result.input_id = input.id
                    JOIN forecast_result_owners AS result_owner
                    ON result_owner.result_id = result.id AND result_owner.owner_user_id = ?
                    LEFT JOIN outcomes AS outcome ON outcome.result_id = result.id
                    LEFT JOIN outcome_owners AS outcome_owner
                    ON outcome_owner.outcome_id = outcome.id AND outcome_owner.owner_user_id = ?
                    WHERE input.run_id IN ({placeholders})
                    GROUP BY input.run_id, result.id, result.horizon, evaluation_status
                    ORDER BY input.run_id, result.id""",  # noqa: S608
                    [owner_user_id, owner_user_id, *run_ids],
                ).fetchall()
                for row in summary_rows:
                    summary = summaries.setdefault(
                        int(row["run_id"]),
                        {"horizons": [], "outcome_count": 0, "evaluation_statuses": []},
                    )
                    summary["horizons"].append(row["horizon"])
                    summary["outcome_count"] += int(row["outcome_count"])
                    if row["evaluation_status"] is not None:
                        summary["evaluation_statuses"].append(row["evaluation_status"])
            for item in items:
                event_summary = (
                    summaries.get(int(item["run_id"])) if item["run_id"] is not None else None
                )
                item.update(
                    event_summary or {"horizons": [], "outcome_count": 0, "evaluation_statuses": []}
                )
                item["forecast_available"] = item["run_id"] is not None
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    def reconstruction(self, owner_user_id: int, event_id: int) -> dict[str, Any] | None:
        """Reconstruct immutable display data with a fixed number of bounded queries."""

        owner_user_id = self._require_owner_id(owner_user_id)
        with self.connect() as connection:
            event = connection.execute(
                """SELECT id, request_id, submitted_symbol, normalized_symbol, asset_type,
                status, is_repeat, error_code, error_message, run_id, submitted_at, completed_at,
                analysis_kind, source_event_id, requested_cutoff, requested_source_event_id
                FROM search_events AS event JOIN search_event_owners AS owner
                ON owner.event_id = event.id
                WHERE event.id = ? AND owner.owner_user_id = ?""",
                (event_id, owner_user_id),
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
            details = self._load_run_details(connection, owner_user_id, [int(event["run_id"])])
            detail = details.get(int(event["run_id"]))
            if detail is None:
                return response
            response["input"] = detail["input"]
            response["results"] = detail["results"]
            return response

    @classmethod
    def _load_run_details(
        cls, connection: sqlite3.Connection, owner_user_id: int, run_ids: list[int]
    ) -> dict[int, dict[str, Any]]:
        """Load up to one export page in three queries, independent of event count."""

        if not run_ids:
            return {}
        if len(run_ids) > HISTORY_EXPORT_LIMIT:
            raise ValueError("history detail batch exceeds the export bound")
        placeholders = ",".join("?" for _ in run_ids)
        input_rows = connection.execute(
            f"""SELECT input.id, input.run_id, input.snapshot_json
            FROM forecast_inputs AS input
            JOIN forecast_run_owners AS run_owner ON run_owner.run_id = input.run_id
            WHERE run_owner.owner_user_id = ? AND input.run_id IN ({placeholders})""",  # noqa: S608
            [owner_user_id, *run_ids],
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
            f"""SELECT result.id, result.input_id, result.result_json, result.created_at
            FROM forecast_results AS result
            JOIN forecast_result_owners AS result_owner ON result_owner.result_id = result.id
            WHERE result_owner.owner_user_id = ? AND result.input_id IN ({input_placeholders})
            ORDER BY result.input_id, result.id""",  # noqa: S608
            [owner_user_id, *input_ids],
        ).fetchall()
        result_ids = [int(row["id"]) for row in result_rows]
        outcomes_by_result: dict[int, list[dict[str, Any]]] = {item: [] for item in result_ids}
        if result_ids:
            result_placeholders = ",".join("?" for _ in result_ids)
            # Window ranking bounds returned memory per result while retaining a truncation row.
            outcome_rows = connection.execute(
                f"""WITH ranked AS (
                    SELECT outcome.id, outcome.result_id, outcome.observed_close,
                           outcome.observed_return, outcome.observed_at,
                           outcome.comparison_rule, outcome.state, outcome.note, outcome.created_at,
                           ROW_NUMBER() OVER (PARTITION BY result_id ORDER BY id DESC) AS rank
                    FROM outcomes AS outcome
                    JOIN outcome_owners AS outcome_owner ON outcome_owner.outcome_id = outcome.id
                    WHERE outcome_owner.owner_user_id = ?
                      AND outcome.result_id IN ({result_placeholders})
                )
                SELECT id, result_id, observed_close, observed_return, observed_at,
                       comparison_rule, state, note, created_at, rank
                FROM ranked WHERE rank <= ? ORDER BY result_id, id DESC""",  # noqa: S608
                [owner_user_id, *result_ids, OUTCOME_RECONSTRUCTION_LIMIT + 1],
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
        owner_user_id: int,
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
        horizon: str | None = None,
        max_events: int = HISTORY_EXPORT_LIMIT,
        sort_by: str = "event_id",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        """Return one faithful bounded record stream without per-event detail queries."""

        owner_user_id = self._require_owner_id(owner_user_id)
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
            self._ensure_user_exists(connection, owner_user_id)
            page = self._history_page(
                connection,
                owner_user_id,
                filters,
                page=1,
                page_size=max_events,
                include_analysis=True,
                include_facets=False,
                include_summaries=False,
                sort_by=sort_by,
                sort_order=sort_order,
                horizon=horizon,
            )
            run_ids = list(
                dict.fromkeys(
                    int(event["run_id"]) for event in page["items"] if event["run_id"] is not None
                )
            )
            details = self._load_run_details(connection, owner_user_id, run_ids)
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
                    raise RepositoryDatabaseError("forecast run is missing its immutable input")
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

    def record_history_export(
        self,
        *,
        owner_user_id: int,
        export_format: str,
        filters: dict[str, Any],
        row_count: int,
        created_at: datetime,
    ) -> dict[str, Any]:
        """Append a bounded export audit row owned by the authenticated principal."""

        owner_user_id = self._require_owner_id(owner_user_id)
        if export_format not in {"csv", "json"}:
            raise ValueError("export format is not supported")
        if type(row_count) is not int or not 0 <= row_count <= HISTORY_EXPORT_LIMIT:
            raise ValueError(f"row_count must be 0-{HISTORY_EXPORT_LIMIT}")
        timestamp = self._iso_datetime(created_at, "created_at")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_owner_can_write(connection, owner_user_id)
            cursor = connection.execute(
                """INSERT INTO history_exports
                (owner_user_id, format, filters_json, row_count, created_at)
                VALUES (?, ?, ?, ?, ?)""",
                (owner_user_id, export_format, self._json(filters), row_count, timestamp),
            )
            export_id = self._insert_id(cursor)
            connection.commit()
        return {
            "id": export_id,
            "owner_user_id": owner_user_id,
            "format": export_format,
            "filters": filters,
            "row_count": row_count,
            "created_at": timestamp,
        }

    def list_history_exports(self, owner_user_id: int, *, limit: int = 20) -> list[dict[str, Any]]:
        """Return a bounded export audit list scoped to one authenticated account."""

        owner_user_id = self._require_owner_id(owner_user_id)
        if type(limit) is not int or not 1 <= limit <= HISTORY_EXPORT_LIMIT:
            raise ValueError(f"export history limit must be 1-{HISTORY_EXPORT_LIMIT}")
        with self.connect() as connection:
            self._ensure_user_exists(connection, owner_user_id)
            rows = connection.execute(
                """SELECT id, format, filters_json, row_count, created_at
                FROM history_exports WHERE owner_user_id = ? ORDER BY id DESC LIMIT ?""",
                (owner_user_id, limit),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "format": row["format"],
                "filters": json.loads(row["filters_json"]),
                "row_count": row["row_count"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def historical_series(
        self, owner_user_id: int, event_id: int, *, series: str = "daily", limit: int = 120
    ) -> dict[str, Any] | None:
        """Slice immutable chart and text-equivalent prices to a caller-selected hard limit."""

        owner_user_id = self._require_owner_id(owner_user_id)
        if series not in {"daily", "intraday"}:
            raise ValueError("history price series is not supported")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("history price limit must be 1-500")
        detail = self.reconstruction(owner_user_id, event_id)
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
        owner_user_id: int,
        result_id: int,
        *,
        page: int = 1,
        page_size: int = 20,
        state: str | None = None,
    ) -> dict[str, Any]:
        """Page append-only observations newest-first without loading a result's full ledger."""

        owner_user_id = self._require_owner_id(owner_user_id)
        if type(page) is not int or type(page_size) is not int:
            raise ValueError("outcome page and page_size must be integers")
        if not 1 <= page <= 10_000 or not 1 <= page_size <= 100:
            raise ValueError("outcome page must be 1-10000 and page_size must be 1-100")
        if state not in {None, "observed", "unavailable", "provisional", "corrected"}:
            raise ValueError("outcome state is not supported")
        clause = (
            "outcome.result_id = ? AND outcome_owner.owner_user_id = ? "
            "AND result_owner.owner_user_id = ?" + (" AND outcome.state = ?" if state else "")
        )
        values: list[Any] = [result_id, owner_user_id, owner_user_id, *([state] if state else [])]
        source = (
            "outcomes AS outcome JOIN outcome_owners AS outcome_owner "
            "ON outcome_owner.outcome_id = outcome.id JOIN forecast_result_owners AS result_owner "
            "ON result_owner.result_id = outcome.result_id"
        )
        with self.connect() as connection:
            connection.execute("BEGIN")
            self._ensure_user_exists(connection, owner_user_id)
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {source} WHERE {clause}",  # noqa: S608
                    values,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""SELECT outcome.id, outcome.result_id, outcome.observed_close,
                outcome.observed_return, outcome.observed_at, outcome.comparison_rule,
                outcome.state, outcome.note, outcome.created_at FROM {source}
                WHERE {clause} ORDER BY outcome.id DESC LIMIT ? OFFSET ?""",  # noqa: S608
                [*values, page_size, (page - 1) * page_size],
            ).fetchall()
        return {
            "items": [dict(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    def forecast_result(self, owner_user_id: int, result_id: int) -> dict[str, Any] | None:
        """Return one immutable result for domain-level outcome validation."""

        owner_user_id = self._require_owner_id(owner_user_id)
        with self.connect() as connection:
            row = connection.execute(
                """SELECT result.result_json FROM forecast_results AS result
                JOIN forecast_result_owners AS owner ON owner.result_id = result.id
                WHERE result.id = ? AND owner.owner_user_id = ?""",
                (result_id, owner_user_id),
            ).fetchone()
        return json.loads(row["result_json"]) if row is not None else None

    def append_outcome(
        self,
        owner_user_id: int,
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

        owner_user_id = self._require_owner_id(owner_user_id)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_owner_can_write(connection, owner_user_id)
            exists = connection.execute(
                """SELECT 1 FROM forecast_result_owners
                WHERE result_id = ? AND owner_user_id = ?""",
                (result_id, owner_user_id),
            ).fetchone()
            if exists is None:
                return None
            created_at_text = self._iso_datetime(created_at, "created_at")
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
            outcome_id = self._insert_id(cursor)
            connection.execute(
                "INSERT INTO outcome_owners"
                "(outcome_id, owner_user_id, assigned_at) VALUES (?, ?, ?)",
                (outcome_id, owner_user_id, created_at_text),
            )
            connection.commit()
            return {
                "id": outcome_id,
                "result_id": result_id,
                "observed_close": observed_close,
                "observed_return": observed_return,
                "observed_at": observed_at.isoformat(),
                "state": state,
                "note": note,
                "created_at": created_at_text,
                "comparison_rule": comparison_rule,
            }

    @staticmethod
    def _holding_value(value: float | None, field: str) -> float | None:
        if value is None:
            return None
        if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
            raise ValueError(f"{field} must be null or a non-negative finite number")
        return float(value)

    @staticmethod
    def _instrument_list_kind(value: str) -> str:
        if value not in {"portfolio", "watchlist"}:
            raise ValueError("instrument list kind is not supported")
        return value

    @staticmethod
    def _instrument_list_item(
        connection: sqlite3.Connection,
        owner_user_id: int,
        kind: str,
        provider: str,
        canonical_symbol: str,
        asset_type: str,
    ) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT kind, provider, canonical_symbol, asset_type, exchange, display_name, "
            "quantity, added_at "
            "FROM user_instrument_list_items WHERE owner_user_id = ? AND kind = ? "
            "AND provider = ? AND canonical_symbol = ? AND asset_type = ?",
            (owner_user_id, kind, provider, canonical_symbol, asset_type),
        ).fetchone()
        return dict(row) if row is not None else None

    def instrument_list_items(
        self, owner_user_id: int, kind: str | None = None
    ) -> list[dict[str, Any]]:
        """Return the fixed portfolio, watchlist, or both in deterministic insertion order."""

        owner_user_id = self._require_owner_id(owner_user_id)
        if kind is not None:
            kind = self._instrument_list_kind(kind)
        with self.connect() as connection:
            self._ensure_user_exists(connection, owner_user_id)
            if kind is None:
                rows = connection.execute(
                    "SELECT kind, provider, canonical_symbol, asset_type, exchange, "
                    "display_name, quantity, added_at FROM user_instrument_list_items "
                    "WHERE owner_user_id = ? ORDER BY kind, added_at, canonical_symbol",
                    (owner_user_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT kind, provider, canonical_symbol, asset_type, exchange, "
                    "display_name, quantity, added_at FROM user_instrument_list_items "
                    "WHERE owner_user_id = ? AND kind = ? ORDER BY added_at, canonical_symbol",
                    (owner_user_id, kind),
                ).fetchall()
        return [dict(row) for row in rows]

    def add_instrument_list_item(
        self,
        kind: str,
        *,
        owner_user_id: int,
        provider: str,
        canonical_symbol: str,
        asset_type: str,
        exchange: str,
        display_name: str,
        added_at: datetime,
        quantity: float | None = None,
    ) -> dict[str, Any] | None:
        """Insert an item atomically under the fixed list's one-hundred-item bound."""

        owner_user_id = self._require_owner_id(owner_user_id)
        kind = self._instrument_list_kind(kind)
        if not isinstance(added_at, datetime) or added_at.tzinfo is None:
            raise ValueError("added_at must include a timezone offset")
        timestamp = added_at.astimezone(UTC).isoformat()
        quantity = self._holding_value(quantity, "quantity")
        if kind != "portfolio" and quantity is not None:
            raise ValueError("manual holdings require a portfolio")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_owner_can_write(connection, owner_user_id)
            if (
                self._instrument_list_item(
                    connection, owner_user_id, kind, provider, canonical_symbol, asset_type
                )
                is not None
            ):
                connection.rollback()
                raise ValueError("instrument is already in this list")
            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM user_instrument_list_items "
                    "WHERE owner_user_id = ? AND kind = ?",
                    (owner_user_id, kind),
                ).fetchone()[0]
            )
            if count >= INSTRUMENT_LIST_ITEM_LIMIT:
                connection.rollback()
                raise ValueError(f"instrument list item limit is {INSTRUMENT_LIST_ITEM_LIMIT}")
            connection.execute(
                "INSERT INTO user_instrument_list_items"
                "(owner_user_id, kind, provider, canonical_symbol, asset_type, exchange, "
                "display_name, "
                "quantity, added_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    owner_user_id,
                    kind,
                    provider,
                    canonical_symbol,
                    asset_type,
                    exchange,
                    display_name,
                    quantity,
                    timestamp,
                ),
            )
            connection.commit()
            return self._instrument_list_item(
                connection, owner_user_id, kind, provider, canonical_symbol, asset_type
            )

    def remove_instrument_list_item(
        self,
        kind: str,
        *,
        owner_user_id: int,
        provider: str,
        canonical_symbol: str,
        asset_type: str,
    ) -> bool:
        """Remove one item without affecting the other fixed list."""

        owner_user_id = self._require_owner_id(owner_user_id)
        kind = self._instrument_list_kind(kind)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_user_exists(connection, owner_user_id)
            cursor = connection.execute(
                "DELETE FROM user_instrument_list_items WHERE owner_user_id = ? AND kind = ? "
                "AND provider = ? "
                "AND canonical_symbol = ? AND asset_type = ?",
                (owner_user_id, kind, provider, canonical_symbol, asset_type),
            )
            if not cursor.rowcount:
                connection.rollback()
                return False
            connection.commit()
            return True

    def set_instrument_list_item_holding(
        self,
        kind: str,
        *,
        owner_user_id: int,
        provider: str,
        canonical_symbol: str,
        asset_type: str,
        quantity: float | None,
    ) -> bool:
        """Set nullable quantity while retaining the selected instrument identity."""

        owner_user_id = self._require_owner_id(owner_user_id)
        kind = self._instrument_list_kind(kind)
        quantity = self._holding_value(quantity, "quantity")
        if kind != "portfolio" and quantity is not None:
            raise ValueError("manual holdings require a portfolio")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_owner_can_write(connection, owner_user_id)
            cursor = connection.execute(
                "UPDATE user_instrument_list_items SET quantity = ? "
                "WHERE owner_user_id = ? AND kind = ? AND provider = ? "
                "AND canonical_symbol = ? AND asset_type = ?",
                (
                    quantity,
                    owner_user_id,
                    kind,
                    provider,
                    canonical_symbol,
                    asset_type,
                ),
            )
            if not cursor.rowcount:
                connection.rollback()
                return False
            connection.commit()
            return True

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
