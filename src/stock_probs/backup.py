"""Authenticated SQLite backups use bounded staging before atomic promotion."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sqlite3
import stat
import struct
import tempfile
import threading
import time
import zipfile
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from stock_probs.config import ensure_private_directory, ensure_private_file
from stock_probs.repository import (
    SCHEMA_VERSION,
    Repository,
    _is_representative_storage_counts,
    _RepresentativeStorageCounts,
)

ARTIFACT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.spbackup$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
# Archive, extracted database, and manifest limits stop zip bombs on a small ARM64 host.
MAX_BACKUP_BYTES = 64 * 1024 * 1024
MAX_DATABASE_BYTES = MAX_BACKUP_BYTES - 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MAX_MANAGED_BACKUPS = 32
MAX_BACKUP_STORAGE_BYTES = 4 * MAX_BACKUP_BYTES
# Preflight central-directory limits run before ZipFile allocates one object per entry.
MAX_ZIP_ENTRIES = 2
MAX_ZIP_METADATA_BYTES = 16 * 1024
BACKUP_TIMEOUT_SECONDS = 20.0
COPY_CHUNK_BYTES = 1024 * 1024
TRUST_KEY_BYTES = 32
TRUST_KEY_NAME = ".backup-auth.key"
MANIFEST_AUTH_FIELD = "manifest_hmac_sha256"
BACKUP_FAILURE_CATEGORY = "backup_creation_failed"
RESTORE_FAILURE_CATEGORY = "restore_failed"
ZIP_EOCD = struct.Struct("<4s4H2LH")
_BACKUP_DEADLINE: ContextVar[float | None] = ContextVar("backup_deadline", default=None)
_T = TypeVar("_T")


class BackupError(Exception):
    """Keep detailed safe diagnostics separate from the stable public operation category."""

    def __init__(self, message: str):
        # Existing callers retain the one-message interface. The private field prevents generic
        # exception dictionaries from presenting diagnostic state as public response metadata.
        super().__init__(message)
        self._public_category = BACKUP_FAILURE_CATEGORY

    @property
    def public_category(self) -> str:
        """Return the only exception attribute intended for a transport response."""

        return self._public_category

    def _mark_restore_failure(self) -> None:
        """Classify errors only at the public restore boundary, never from artifact input."""

        self._public_category = RESTORE_FAILURE_CATEGORY


def _check_deadline() -> None:
    deadline = _BACKUP_DEADLINE.get()
    if deadline is not None and time.monotonic() >= deadline:
        raise BackupError("Backup operation exceeded its wall-clock time limit.")


def _run_with_deadline(operation: Callable[[], _T]) -> _T:
    """Return at the wall-clock bound while the worker cooperatively refuses late publication."""

    if _BACKUP_DEADLINE.get() is not None:
        _check_deadline()
        return operation()

    deadline = time.monotonic() + BACKUP_TIMEOUT_SECONDS
    results: list[_T] = []
    failures: list[BaseException] = []

    def run() -> None:
        token = _BACKUP_DEADLINE.set(deadline)
        try:
            results.append(operation())
        except BaseException as exc:
            failures.append(exc)
        finally:
            _BACKUP_DEADLINE.reset(token)

    worker = threading.Thread(target=run, name="stock-probs-backup", daemon=True)
    worker.start()
    worker.join(max(0.0, deadline - time.monotonic()))
    if worker.is_alive():
        raise BackupError("Backup operation exceeded its wall-clock time limit.")
    if failures:
        raise failures[0]
    return results[0]


class BackupManager:
    """Create and restore server-rooted artifacts without trusting archive paths."""

    def __init__(self, repository: Repository, backup_dir: Path):
        self.repository = repository
        self.backup_dir = backup_dir
        # The key is deliberately outside the artifact directory so copying an archive alone
        # cannot provide the authority needed to bless attacker-recomputed checksums/counts.
        self.trust_key_path = backup_dir.parent / TRUST_KEY_NAME

    @staticmethod
    def _checksum(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(COPY_CHUNK_BYTES):
                _check_deadline()
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _schema_checksum(connection: sqlite3.Connection) -> str:
        """Fingerprint application DDL, excluding SQLite's generated bookkeeping tables."""

        rows = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        canonical = json.dumps([list(row) for row in rows], separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    @classmethod
    def _integrity(
        cls,
        path: Path,
        expected_schema: str | None = None,
        expected_version: int = SCHEMA_VERSION,
    ) -> str:
        """Check pages, foreign keys, migration identity, and exact application DDL."""

        try:
            connection = sqlite3.connect(
                f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5.0
            )
            try:
                connection.execute("PRAGMA query_only = ON")
                connection.execute("PRAGMA busy_timeout = 5000")
                connection.set_progress_handler(_check_deadline, 1000)
                integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
                foreign_key_error = connection.execute("PRAGMA foreign_key_check").fetchone()
                versions = [
                    int(row[0])
                    for row in connection.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    )
                ]
                schema_checksum = cls._schema_checksum(connection)
            finally:
                connection.close()
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            _check_deadline()
            raise BackupError("Artifact is not a compatible stock-probs database.") from exc
        expected_versions = list(range(1, expected_version + 1))
        if integrity_row is None or integrity_row[0] != "ok" or foreign_key_error is not None:
            raise BackupError("Artifact failed SQLite integrity checks.")
        if versions != expected_versions or (
            expected_schema is not None and schema_checksum != expected_schema
        ):
            raise BackupError("Artifact failed schema compatibility checks.")
        return schema_checksum

    def _ensure_backup_dir(self) -> None:
        try:
            ensure_private_directory(self.backup_dir.parent)
            ensure_private_directory(self.backup_dir)
        except (OSError, ValueError) as exc:
            raise BackupError("Managed backup storage is unavailable.") from exc

    def _managed_backups(self) -> list[tuple[str, int]]:
        """List only managed artifacts and reject linked or irregular entries fail-closed."""

        managed = []
        try:
            with os.scandir(self.backup_dir) as entries:
                for entry in entries:
                    _check_deadline()
                    if not ARTIFACT_PATTERN.fullmatch(entry.name):
                        continue
                    metadata = entry.stat(follow_symlinks=False)
                    if not stat.S_ISREG(metadata.st_mode):
                        raise BackupError("Managed backup storage contains an unsafe artifact.")
                    managed.append((entry.name, metadata.st_size))
        except BackupError:
            raise
        except OSError as exc:
            raise BackupError("Managed backup storage could not be inspected safely.") from exc
        return sorted(managed)

    def _trust_key(self, *, create: bool) -> bytes:
        """Load the installation key, creating it once only while making the first backup."""

        self._ensure_backup_dir()
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        if create:
            try:
                descriptor = os.open(
                    self.trust_key_path,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
            except FileExistsError:
                pass
            except OSError as exc:
                raise BackupError("Local backup trust key could not be created safely.") from exc
            else:
                try:
                    key = secrets.token_bytes(TRUST_KEY_BYTES)
                    written = os.write(descriptor, key)
                    if written != TRUST_KEY_BYTES:
                        raise BackupError("Local backup trust key could not be written completely.")
                    os.fchmod(descriptor, 0o600)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                self._sync_directory(self.trust_key_path.parent)
        try:
            descriptor = os.open(self.trust_key_path, flags)
        except FileNotFoundError as exc:
            # Never generate a replacement during restore: key loss intentionally makes prior
            # artifacts unverifiable rather than silently trusting them under a new identity.
            raise BackupError(
                "Local backup trust key is missing; only this installation's signed backups "
                "can be restored."
            ) from exc
        except OSError as exc:
            raise BackupError("Local backup trust key is unavailable or unsafe.") from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise BackupError("Local backup trust key is not a regular file.")
            os.fchmod(descriptor, 0o600)
            key = os.read(descriptor, TRUST_KEY_BYTES + 1)
        finally:
            os.close(descriptor)
        if len(key) != TRUST_KEY_BYTES:
            raise BackupError(
                "Local backup trust key is invalid; it must not be replaced or regenerated."
            )
        return key

    @staticmethod
    def _manifest_bytes(manifest: dict[str, Any]) -> bytes:
        """Canonicalize every non-signature field for deterministic authentication."""

        authenticated = {
            key: value for key, value in manifest.items() if key != MANIFEST_AUTH_FIELD
        }
        return json.dumps(authenticated, sort_keys=True, separators=(",", ":")).encode()

    @classmethod
    def _sign_manifest(cls, manifest: dict[str, Any], key: bytes) -> str:
        return hmac.new(key, cls._manifest_bytes(manifest), hashlib.sha256).hexdigest()

    def _authenticate_manifest(self, manifest: dict[str, Any]) -> None:
        """Authenticate before extracting or inspecting attacker-controlled database pages."""

        expected = self._sign_manifest(manifest, self._trust_key(create=False))
        if not hmac.compare_digest(expected, manifest[MANIFEST_AUTH_FIELD]):
            raise BackupError(
                "Artifact authenticity check failed; unsigned, forged, or recomputed manifests "
                "cannot be restored."
            )

    def _artifact_path(self, name: str) -> Path:
        if not ARTIFACT_PATTERN.fullmatch(name):
            raise BackupError("Backup name must be a simple .spbackup filename.")
        # A validated filename has no separators; this containment check guards future regex edits.
        try:
            root = self.backup_dir.resolve()
        except (OSError, RuntimeError) as exc:
            raise BackupError("Managed backup storage could not be resolved safely.") from exc
        candidate = root / name
        if candidate.parent != root:
            raise BackupError("Backup path is outside the managed backup directory.")
        return candidate

    @staticmethod
    def _copy_member(source: Any, target: Any, limit: int) -> int:
        """Copy a zip stream while enforcing the real byte count, not only its header."""

        copied = 0
        while chunk := source.read(COPY_CHUNK_BYTES):
            _check_deadline()
            copied += len(chunk)
            if copied > limit:
                raise BackupError("Artifact member exceeds the restore limit.")
            target.write(chunk)
        return copied

    @staticmethod
    def _sync_file(path: Path) -> None:
        """Flush staged bytes before a rename makes them the active database or artifact."""

        with path.open("rb") as file_handle:
            os.fsync(file_handle.fileno())

    @staticmethod
    def _sync_directory(path: Path) -> None:
        # Directory fsync makes rename/link metadata durable on Linux after a sudden power loss.
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _counts(self, path: Path) -> _RepresentativeStorageCounts:
        try:
            return self.repository.representative_counts(path)
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            raise BackupError("Artifact representative-count verification failed.") from exc

    def _online_snapshot(self, snapshot: Path) -> None:
        """Use SQLite's consistent online API with a callback-enforced wall-clock bound."""

        def progress(_: int, __: int, ___: int) -> None:
            _check_deadline()

        try:
            source = sqlite3.connect(self.repository.database_path, timeout=5.0)
            destination = sqlite3.connect(snapshot, timeout=5.0)
            try:
                page_size = int(source.execute("PRAGMA page_size").fetchone()[0])
                page_count = int(source.execute("PRAGMA page_count").fetchone()[0])
                if page_size * page_count > MAX_DATABASE_BYTES:
                    raise BackupError("Database exceeds the bounded backup size.")
                source.backup(destination, pages=256, progress=progress, sleep=0.05)
            finally:
                destination.close()
                source.close()
        except BackupError:
            raise
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            raise BackupError("SQLite could not create a consistent online backup.") from exc
        if snapshot.stat().st_size > MAX_DATABASE_BYTES:
            raise BackupError("Database exceeds the bounded backup size.")

    def _package(
        self, snapshot: Path, manifest: dict[str, Any], trust_key: bytes, target: Path
    ) -> None:
        """Write one bounded signed artifact; callers own its publication semantics."""

        _check_deadline()
        manifest[MANIFEST_AUTH_FIELD] = self._sign_manifest(manifest, trust_key)
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, "database.sqlite3")
            archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True, indent=2))
        _check_deadline()
        if target.stat().st_size > MAX_BACKUP_BYTES:
            raise BackupError("Backup artifact exceeds the 64 MB local limit.")
        target.chmod(0o600)
        self._sync_file(target)

    def create(
        self, name: str | None = None, *, schema_version: int = SCHEMA_VERSION
    ) -> dict[str, Any]:
        """Snapshot through SQLite's online API, then package verified bytes and metadata."""

        return _run_with_deadline(lambda: self._create(name, schema_version=schema_version))

    def _create(
        self, name: str | None = None, *, schema_version: int = SCHEMA_VERSION
    ) -> dict[str, Any]:
        """Create under the current operation deadline, staging until the final hard link."""

        if not 1 <= schema_version <= SCHEMA_VERSION:
            raise BackupError("Backup schema version is invalid.")
        self._ensure_backup_dir()
        artifact_name = name or f"stock-probs-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.spbackup"
        artifact = self._artifact_path(artifact_name)
        if artifact.exists() or artifact.is_symlink():
            raise BackupError("A backup with that name already exists.")
        published = False
        try:
            with (
                self.repository.exclusive(),
                tempfile.TemporaryDirectory(dir=self.backup_dir) as directory,
            ):
                managed = self._managed_backups()
                _check_deadline()
                if len(managed) >= MAX_MANAGED_BACKUPS:
                    raise BackupError(
                        "Managed backup retention limit reached; remove an old backup explicitly."
                    )
                # Never silently replace lost trust state while prior artifacts still exist.
                trust_key = self._trust_key(create=not managed)
                _check_deadline()
                snapshot = Path(directory) / "database.sqlite3"
                self._online_snapshot(snapshot)
                _check_deadline()
                ensure_private_file(snapshot)
                schema_checksum = self._integrity(snapshot, expected_version=schema_version)
                _check_deadline()
                counts = self._counts(snapshot)
                _check_deadline()
                manifest = {
                    "format": "stock-probs-backup",
                    "format_version": 1,
                    "schema_version": schema_version,
                    "schema_sha256": schema_checksum,
                    "created_at": datetime.now(UTC).isoformat(),
                    "database_sha256": self._checksum(snapshot),
                    "database_size": snapshot.stat().st_size,
                    "counts": counts,
                }
                temporary_artifact = Path(directory) / "artifact.zip"
                self._package(snapshot, manifest, trust_key, temporary_artifact)
                _, _, verification = self._verify_unlocked(
                    artifact_name,
                    require_active_schema=False,
                    artifact_path=temporary_artifact,
                )
                verification.cleanup()
                _check_deadline()
                if (
                    sum(size for _, size in managed) + temporary_artifact.stat().st_size
                    > MAX_BACKUP_STORAGE_BYTES
                ):
                    raise BackupError(
                        "Managed backup storage limit reached; remove an old backup explicitly."
                    )
                # Hard-link publication is atomic and cannot overwrite an existing artifact.
                try:
                    _check_deadline()
                    os.link(temporary_artifact, artifact)
                    published = True
                except FileExistsError as exc:
                    raise BackupError("A backup with that name already exists.") from exc
                self._sync_directory(self.backup_dir)
                _check_deadline()
            response = {"name": artifact_name, "sha256": self._checksum(artifact), **manifest}
            _check_deadline()
            return response
        except BackupError:
            if published:
                artifact.unlink(missing_ok=True)
            raise
        except (OSError, sqlite3.Error) as exc:
            artifact.unlink(missing_ok=True)
            raise BackupError("Backup artifact could not be written safely.") from exc

    def create_if_due(
        self, interval_seconds: float, *, now: datetime | None = None
    ) -> dict[str, Any]:
        """Create once the newest managed artifact reaches the configured startup interval."""

        return _run_with_deadline(lambda: self._create_if_due(interval_seconds, now=now))

    def _create_if_due(
        self, interval_seconds: float, *, now: datetime | None = None
    ) -> dict[str, Any]:
        """Inspect and optionally create using the current shared startup deadline."""

        self._ensure_backup_dir()
        _check_deadline()
        checked_at = now or datetime.now(UTC)
        if checked_at.tzinfo is None:
            raise BackupError("Automatic backup time must include a timezone offset.")
        with self.repository.exclusive():
            managed = self._managed_backups()
            if managed:
                manifests = []
                for name, _ in managed:
                    manifests.append((name, self._authenticated_manifest(name)))
                    _check_deadline()
                newest_name, newest_manifest = max(
                    manifests, key=lambda item: datetime.fromisoformat(item[1]["created_at"])
                )
                _, _, staging = self._verify_unlocked(
                    newest_name, require_active_schema=False
                )
                staging.cleanup()
                _check_deadline()
                age_seconds = (
                    checked_at - datetime.fromisoformat(newest_manifest["created_at"])
                ).total_seconds()
                if age_seconds < 0:
                    raise BackupError("Newest managed backup timestamp is in the future.")
                if age_seconds < interval_seconds:
                    _check_deadline()
                    return {
                        "trigger": "due",
                        "status": "not_due",
                        "newest_backup": newest_name,
                        "age_seconds": age_seconds,
                        "interval_seconds": interval_seconds,
                    }
            created = self.create()
            _check_deadline()
            return {
                "trigger": "due",
                "status": "created",
                "interval_seconds": interval_seconds,
                "backup": created,
            }

    def _authenticated_manifest(self, name: str) -> dict[str, Any]:
        """Read bounded signed metadata without expanding every database during a due check."""

        artifact = self._artifact_path(name)
        try:
            if artifact.is_symlink() or not artifact.is_file():
                raise BackupError("Backup does not exist or is not a regular managed artifact.")
            if artifact.stat().st_size > MAX_BACKUP_BYTES:
                raise BackupError("Backup does not exist or exceeds the 64 MB local limit.")
            ensure_private_file(artifact)
            _check_deadline()
            directory_offset = self._preflight_zip(artifact)
            with zipfile.ZipFile(artifact, "r") as archive:
                entries = archive.infolist()
                self._validate_zip_entries(entries, directory_offset)
                manifest_info = next(
                    info for info in entries if info.filename == "manifest.json"
                )
                if not 0 < manifest_info.file_size <= MAX_MANIFEST_BYTES:
                    raise BackupError("Artifact manifest exceeds the restore limit.")
                with archive.open(manifest_info) as source:
                    manifest_bytes = source.read(MAX_MANIFEST_BYTES + 1)
            _check_deadline()
            if len(manifest_bytes) > MAX_MANIFEST_BYTES:
                raise BackupError("Artifact manifest exceeds the restore limit.")
            manifest = self._validate_manifest(json.loads(manifest_bytes))
            self._authenticate_manifest(manifest)
            _check_deadline()
            return manifest
        except BackupError:
            raise
        except (
            EOFError,
            OSError,
            RuntimeError,
            StopIteration,
            UnicodeDecodeError,
            zipfile.BadZipFile,
            zipfile.LargeZipFile,
            json.JSONDecodeError,
        ) as exc:
            raise BackupError("Backup artifact is truncated or invalid.") from exc

    @staticmethod
    def _validate_manifest(manifest: Any) -> dict[str, Any]:
        """Reject loose JSON types such as booleans where exact numeric metadata is required."""

        required = {
            "format",
            "format_version",
            "schema_version",
            "schema_sha256",
            "created_at",
            "database_sha256",
            "database_size",
            "counts",
            MANIFEST_AUTH_FIELD,
        }
        if not isinstance(manifest, dict) or MANIFEST_AUTH_FIELD not in manifest:
            raise BackupError(
                "Artifact manifest is unsigned; only backups signed by this installation "
                "can be restored."
            )
        if not isinstance(manifest, dict) or set(manifest) != required:
            raise BackupError("Artifact manifest fields are invalid.")
        if (
            manifest["format"] != "stock-probs-backup"
            or type(manifest["format_version"]) is not int
            or manifest["format_version"] != 1
            or type(manifest["schema_version"]) is not int
            or not 1 <= manifest["schema_version"] <= SCHEMA_VERSION
        ):
            raise BackupError("Artifact format or schema version is incompatible.")
        if not isinstance(manifest["schema_sha256"], str) or not SHA256_PATTERN.fullmatch(
            manifest["schema_sha256"]
        ):
            raise BackupError("Artifact schema checksum is invalid.")
        if not isinstance(manifest["database_sha256"], str) or not SHA256_PATTERN.fullmatch(
            manifest["database_sha256"]
        ):
            raise BackupError("Artifact database checksum is invalid.")
        if not isinstance(manifest[MANIFEST_AUTH_FIELD], str) or not SHA256_PATTERN.fullmatch(
            manifest[MANIFEST_AUTH_FIELD]
        ):
            raise BackupError("Artifact manifest authenticity value is invalid.")
        if (
            type(manifest["database_size"]) is not int
            or not 0 < manifest["database_size"] <= MAX_DATABASE_BYTES
        ):
            raise BackupError("Artifact database size is invalid.")
        counts = manifest["counts"]
        if not _is_representative_storage_counts(counts):
            raise BackupError("Artifact representative counts are invalid.")
        try:
            created_at = datetime.fromisoformat(manifest["created_at"])
        except (TypeError, ValueError) as exc:
            raise BackupError("Artifact creation timestamp is invalid.") from exc
        if created_at.tzinfo is None:
            raise BackupError("Artifact creation timestamp must include a timezone offset.")
        return manifest

    @staticmethod
    def _preflight_zip(artifact: Path) -> int:
        """Bound entry count/metadata from EOCD bytes before ZipFile parses the directory."""

        size = artifact.stat().st_size
        trailer_size = min(size, 65_535 + ZIP_EOCD.size)
        with artifact.open("rb") as source:
            source.seek(size - trailer_size)
            trailer = source.read(trailer_size)
        marker = trailer.rfind(b"PK\x05\x06")
        if marker < 0 or len(trailer) - marker < ZIP_EOCD.size:
            raise BackupError("Backup artifact is truncated or invalid.")
        (
            _,
            disk_number,
            directory_disk,
            disk_entries,
            total_entries,
            directory_size,
            directory_offset,
            comment_size,
        ) = ZIP_EOCD.unpack_from(trailer, marker)
        eocd_offset = size - trailer_size + marker
        if comment_size != len(trailer) - marker - ZIP_EOCD.size:
            raise BackupError("Backup artifact has invalid trailing metadata.")
        if disk_number or directory_disk or disk_entries != total_entries:
            raise BackupError("Multi-disk backup artifacts are unsupported.")
        if total_entries > MAX_ZIP_ENTRIES:
            raise BackupError("Artifact contains too many entries.")
        if total_entries != MAX_ZIP_ENTRIES:
            raise BackupError("Artifact contains unexpected or unsafe members.")
        if directory_size > MAX_ZIP_METADATA_BYTES:
            raise BackupError("Artifact ZIP metadata exceeds the restore limit.")
        if directory_offset + directory_size != eocd_offset:
            raise BackupError("Artifact ZIP metadata offsets are invalid.")
        return int(directory_offset)

    @staticmethod
    def _validate_zip_entries(entries: list[zipfile.ZipInfo], directory_offset: int) -> None:
        """Reject unsafe member metadata before opening either compressed stream."""

        expected = {"database.sqlite3", "manifest.json"}
        if len(entries) != MAX_ZIP_ENTRIES or {info.filename for info in entries} != expected:
            raise BackupError("Artifact contains unexpected or unsafe members.")
        for info in entries:
            unix_mode = info.external_attr >> 16
            if (
                info.is_dir()
                or stat.S_ISLNK(unix_mode)
                or info.flag_bits & ~0x800
                or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                or len(info.filename.encode()) > 64
                or len(info.extra) + len(info.comment) > MAX_ZIP_METADATA_BYTES
                or info.header_offset < 0
                or info.header_offset >= directory_offset
                or info.compress_size < 0
                or info.compress_size > MAX_BACKUP_BYTES
            ):
                raise BackupError("Artifact contains unsafe ZIP member metadata.")

    def verify(self, name: str) -> tuple[dict[str, Any], Path, tempfile.TemporaryDirectory[str]]:
        """Coordinate active-schema inspection with writes and restore promotion."""

        try:
            return _run_with_deadline(lambda: self._verify_coordinated(name))
        except sqlite3.Error as exc:
            raise BackupError("Database operation did not acquire the bounded local lock.") from exc

    def _verify_coordinated(
        self, name: str
    ) -> tuple[dict[str, Any], Path, tempfile.TemporaryDirectory[str]]:
        with self.repository.exclusive():
            result = self._verify_unlocked(name)
            try:
                # A delayed verifier can finish after its caller timed out; discard its staging.
                _check_deadline()
            except BackupError:
                result[2].cleanup()
                raise
            return result

    def _verify_unlocked(
        self,
        name: str,
        *,
        require_active_schema: bool = True,
        artifact_path: Path | None = None,
    ) -> tuple[dict[str, Any], Path, tempfile.TemporaryDirectory[str]]:
        """Extract only exact expected members and retain staging until caller finishes."""

        self._ensure_backup_dir()
        artifact = artifact_path or self._artifact_path(name)
        if artifact.is_symlink() or not artifact.is_file():
            raise BackupError("Backup does not exist or is not a regular managed artifact.")
        try:
            if artifact.stat().st_size > MAX_BACKUP_BYTES:
                raise BackupError("Backup does not exist or exceeds the 64 MB local limit.")
            ensure_private_file(artifact)
        except (OSError, ValueError) as exc:
            raise BackupError("Backup artifact is unavailable.") from exc
        staging = tempfile.TemporaryDirectory(dir=self.backup_dir)
        try:
            directory_offset = self._preflight_zip(artifact)
            _check_deadline()
            with zipfile.ZipFile(artifact, "r") as archive:
                entries = archive.infolist()
                self._validate_zip_entries(entries, directory_offset)
                sizes = {info.filename: info.file_size for info in entries}
                if not 0 < sizes["database.sqlite3"] <= MAX_DATABASE_BYTES:
                    raise BackupError("Artifact database exceeds the restore limit.")
                if not 0 < sizes["manifest.json"] <= MAX_MANIFEST_BYTES:
                    raise BackupError("Artifact manifest exceeds the restore limit.")
                with archive.open("manifest.json") as source:
                    manifest_bytes = source.read(MAX_MANIFEST_BYTES + 1)
                if len(manifest_bytes) > MAX_MANIFEST_BYTES:
                    raise BackupError("Artifact manifest exceeds the restore limit.")
                manifest = self._validate_manifest(json.loads(manifest_bytes))
                self._authenticate_manifest(manifest)
                _check_deadline()
                database = Path(staging.name) / "database.sqlite3"
                with archive.open("database.sqlite3") as source, database.open("xb") as target:
                    copied = self._copy_member(source, target, MAX_DATABASE_BYTES)
                ensure_private_file(database)
            if copied != manifest["database_size"] or database.stat().st_size != copied:
                raise BackupError("Artifact database size does not match its manifest.")
            if self._checksum(database) != manifest["database_sha256"]:
                raise BackupError("Artifact database checksum does not match its manifest.")
            schema_version = manifest["schema_version"]
            schema = self._integrity(
                database,
                expected_schema=manifest["schema_sha256"],
                expected_version=schema_version,
            )
            if schema != manifest["schema_sha256"]:
                raise BackupError("Artifact schema checksum does not match its manifest.")
            if require_active_schema:
                active_schema = self._integrity(
                    self.repository.database_path, expected_version=schema_version
                )
                if active_schema != schema:
                    raise BackupError("Artifact failed schema compatibility checks.")
            if self._counts(database) != manifest["counts"]:
                raise BackupError("Artifact representative counts do not match its manifest.")
            _check_deadline()
            return manifest, database, staging
        except BackupError:
            staging.cleanup()
            raise
        except (
            EOFError,
            OSError,
            RuntimeError,
            UnicodeDecodeError,
            zipfile.BadZipFile,
            zipfile.LargeZipFile,
            json.JSONDecodeError,
            KeyError,
        ) as exc:
            staging.cleanup()
            raise BackupError("Backup artifact is truncated or invalid.") from exc
        except Exception:
            staging.cleanup()
            raise

    @staticmethod
    def _write_key(path: Path, key: bytes) -> None:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            if os.write(descriptor, key) != len(key):
                raise BackupError("Replacement trust key could not be written completely.")
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def rotate_key(self) -> dict[str, Any]:
        """Verify every artifact, then replace its signature and the installation key together."""

        self._ensure_backup_dir()
        self._trust_key(create=False)
        managed = self._managed_backups()
        new_key = secrets.token_bytes(TRUST_KEY_BYTES)
        try:
            with self.repository.exclusive(), tempfile.TemporaryDirectory(
                dir=self.backup_dir
            ) as directory:
                staging_root = Path(directory)
                replacements = staging_root / "replacements"
                originals = staging_root / "originals"
                replacements.mkdir(mode=0o700)
                originals.mkdir(mode=0o700)
                for name, _ in managed:
                    manifest, database, staging = self._verify_unlocked(
                        name, require_active_schema=False
                    )
                    try:
                        self._package(database, manifest, new_key, replacements / name)
                    finally:
                        staging.cleanup()
                    os.link(self._artifact_path(name), originals / name)
                os.link(self.trust_key_path, originals / TRUST_KEY_NAME)
                replacement_key = staging_root / TRUST_KEY_NAME
                self._write_key(replacement_key, new_key)

                swapped: list[str] = []
                key_swapped = False
                try:
                    for name, _ in managed:
                        os.replace(replacements / name, self._artifact_path(name))
                        swapped.append(name)
                    os.replace(replacement_key, self.trust_key_path)
                    key_swapped = True
                    self._sync_directory(self.backup_dir)
                    self._sync_directory(self.trust_key_path.parent)
                except OSError as exc:
                    try:
                        for name in reversed(swapped):
                            os.replace(originals / name, self._artifact_path(name))
                        if key_swapped:
                            os.replace(originals / TRUST_KEY_NAME, self.trust_key_path)
                        self._sync_directory(self.backup_dir)
                        self._sync_directory(self.trust_key_path.parent)
                    except OSError as rollback_error:
                        raise BackupError(
                            "Trust-key rotation failed and could not restore every prior file."
                        ) from rollback_error
                    raise BackupError(
                        "Trust-key rotation failed; prior trust was restored."
                    ) from exc
            return {"status": "rotated", "artifacts_resigned": len(managed)}
        except BackupError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise BackupError("Trust-key rotation could not be completed safely.") from exc

    def retire_key(self) -> dict[str, Any]:
        """Remove trust only after the operator has explicitly moved or removed every artifact."""

        self._ensure_backup_dir()
        managed = self._managed_backups()
        with self.repository.exclusive():
            self._trust_key(create=False)
            if managed:
                raise BackupError(
                    "Trust key cannot be retired while managed backups remain; transfer or "
                    "remove them explicitly first."
                )
            try:
                self.trust_key_path.unlink()
                self._sync_directory(self.trust_key_path.parent)
            except OSError as exc:
                raise BackupError("Trust key could not be retired safely.") from exc
        return {"status": "retired", "artifacts_remaining": 0}

    def _stage_promotion(
        self, staged_database: Path, current: Path, manifest: dict[str, Any]
    ) -> Path:
        """Copy into the database filesystem and reverify before touching the active name."""

        descriptor, candidate_name = tempfile.mkstemp(
            prefix=".stock-probs-restore-", suffix=".sqlite3", dir=current.parent
        )
        os.close(descriptor)
        candidate = Path(candidate_name)
        try:
            shutil.copyfile(staged_database, candidate)
            candidate.chmod(0o600)
            self._sync_file(candidate)
            self._integrity(candidate, expected_schema=manifest["schema_sha256"])
            if self._counts(candidate) != manifest["counts"]:
                raise BackupError("Staged database failed representative-count verification.")
            return candidate
        except Exception:
            candidate.unlink(missing_ok=True)
            raise

    def restore(self, name: str, *, promote: bool = False) -> dict[str, Any]:
        """Return one safe error if bounded database coordination cannot be acquired."""

        try:
            return _run_with_deadline(
                lambda: self._restore_coordinated(name, promote=promote)
            )
        except BackupError as exc:
            exc._mark_restore_failure()
            raise
        except sqlite3.Error as exc:
            error = BackupError("Database operation did not acquire the bounded local lock.")
            error._mark_restore_failure()
            raise error from exc

    def _restore_coordinated(self, name: str, *, promote: bool = False) -> dict[str, Any]:
        """Verify first; promotion keeps a rollback copy until the active recheck passes."""

        with self.repository.exclusive():
            manifest, staged_database, staging = self._verify_unlocked(name)
            candidate: Path | None = None
            rollback_temporary: Path | None = None
            try:
                # Refuse a late verification result before returning it or starting promotion.
                _check_deadline()
                response = {
                    "name": name,
                    "verified": True,
                    "promoted": False,
                    "counts": manifest["counts"],
                }
                if not promote:
                    return response
                current = self.repository.database_path
                rollback = current.with_suffix(".pre-restore.sqlite3")
                if rollback.exists() or rollback.is_symlink():
                    raise BackupError(
                        "A prior restore rollback file exists; resolve it before promotion."
                    )
                candidate = self._stage_promotion(staged_database, current, manifest)
                # Checkpoint while the old active file still owns its name and remains usable.
                with self.repository.connect() as connection:
                    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                for suffix in ("-wal", "-shm"):
                    Path(f"{current}{suffix}").unlink(missing_ok=True)

                descriptor, rollback_name = tempfile.mkstemp(
                    prefix=".stock-probs-rollback-", suffix=".sqlite3", dir=current.parent
                )
                os.close(descriptor)
                rollback_temporary = Path(rollback_name)
                shutil.copyfile(current, rollback_temporary)
                rollback_temporary.chmod(0o600)
                self._sync_file(rollback_temporary)
                # A rollback is useful only after proving its copied pages and rows match active.
                active_counts = self._counts(current)
                self._integrity(
                    rollback_temporary, expected_schema=manifest["schema_sha256"]
                )
                if self._counts(rollback_temporary) != active_counts:
                    raise BackupError("Restore rollback staging failed verification.")
                os.replace(rollback_temporary, rollback)
                rollback_temporary = None
                self._sync_directory(current.parent)

                try:
                    os.replace(candidate, current)
                    candidate = None
                    self._sync_directory(current.parent)
                    self._integrity(current, expected_schema=manifest["schema_sha256"])
                    if self._counts(current) != manifest["counts"]:
                        raise BackupError(
                            "Promoted database failed representative-count verification."
                        )
                except Exception as promotion_error:
                    # Atomic rollback restores the prior active bytes after any post-swap failure.
                    try:
                        os.replace(rollback, current)
                        self._sync_directory(current.parent)
                    except OSError as rollback_error:
                        raise BackupError(
                            "Restore promotion failed; preserved rollback could not be promoted."
                        ) from rollback_error
                    if isinstance(promotion_error, BackupError):
                        raise promotion_error
                    raise BackupError(
                        "Restore promotion failed; active data was restored."
                    ) from promotion_error
                response["promoted"] = True
                try:
                    rollback.unlink()
                    self._sync_directory(current.parent)
                except OSError:
                    # The promoted database is valid; retain/report cleanup state rather than lie.
                    response["rollback_cleanup_required"] = rollback.exists()
                return response
            except BackupError:
                raise
            except (OSError, sqlite3.Error) as exc:
                raise BackupError("Restore could not be promoted safely.") from exc
            finally:
                if candidate is not None:
                    candidate.unlink(missing_ok=True)
                if rollback_temporary is not None:
                    rollback_temporary.unlink(missing_ok=True)
                staging.cleanup()
