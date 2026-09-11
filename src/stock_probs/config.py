"""Runtime settings keep local state server-owned and loopback defaults explicit."""

from __future__ import annotations

import math
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


def _environment_float(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def _environment_int(name: str, default: str) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def ensure_private_directory(path: Path) -> None:
    """Create or harden a runtime directory without chmod following its final symlink."""

    path.mkdir(mode=PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise ValueError("Runtime storage path must be a directory.")
        # Descriptor-based chmod closes the check/use gap and never changes a symlink target.
        os.fchmod(descriptor, PRIVATE_DIRECTORY_MODE)
    finally:
        os.close(descriptor)


def ensure_private_file(path: Path, *, create: bool = False) -> None:
    """Harden a regular sensitive file through a no-follow descriptor."""

    flags = os.O_RDWR if create else os.O_RDONLY
    flags |= getattr(os, "O_NOFOLLOW", 0)
    if create:
        flags |= os.O_CREAT
    descriptor = os.open(path, flags, PRIVATE_FILE_MODE)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("Runtime sensitive path must be a regular file.")
        os.fchmod(descriptor, PRIVATE_FILE_MODE)
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class Settings:
    """Small environment-driven configuration suitable for a single local process."""

    data_dir: Path
    database_path: Path
    backup_dir: Path
    provider: str = "yahoo"
    provider_timeout: float = 8.0
    host: str = "127.0.0.1"
    port: int = 8000
    fixture_now: datetime | None = None

    @classmethod
    def from_env(cls) -> Settings:
        # Normalize without resolving symlinks; startup must inspect/reject the configured path
        # rather than silently converting a linked data directory into its target.
        configured_data_dir = Path(os.getenv("STOCK_PROBS_DATA_DIR", "data")).expanduser()
        data_dir = configured_data_dir.absolute()
        timeout = _environment_float("STOCK_PROBS_PROVIDER_TIMEOUT", "8")
        port = _environment_int("STOCK_PROBS_PORT", "8000")
        provider = os.getenv("STOCK_PROBS_PROVIDER", "yahoo")
        host = os.getenv("STOCK_PROBS_HOST", "127.0.0.1").strip().lower()
        if not math.isfinite(timeout) or not 1.0 <= timeout <= 20.0:
            raise ValueError("STOCK_PROBS_PROVIDER_TIMEOUT must be between 1 and 20 seconds")
        if not 1 <= port <= 65535:
            raise ValueError("STOCK_PROBS_PORT must be between 1 and 65535")
        if provider not in {"yahoo", "fixture"}:
            raise ValueError("STOCK_PROBS_PROVIDER must be 'yahoo' or 'fixture'")
        # Environment launch settings fail closed; the CLI has the separate, explicit
        # acknowledgement required for an unsupported broader network bind.
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("STOCK_PROBS_HOST must be a loopback host")
        fixture_value = os.getenv("STOCK_PROBS_FIXTURE_NOW")
        try:
            fixture_now = datetime.fromisoformat(fixture_value) if fixture_value else None
        except ValueError as exc:
            raise ValueError("STOCK_PROBS_FIXTURE_NOW must be an ISO-8601 timestamp") from exc
        if fixture_now is not None and fixture_now.tzinfo is None:
            raise ValueError("STOCK_PROBS_FIXTURE_NOW must include a timezone offset")
        return cls(
            data_dir=data_dir,
            database_path=data_dir / "stock_probs.sqlite3",
            backup_dir=data_dir / "backups",
            provider=provider,
            provider_timeout=timeout,
            host=host,
            port=port,
            fixture_now=fixture_now,
        )

    def ensure_local_dirs(self) -> None:
        """Create private local directories without accepting paths from requests."""

        ensure_private_directory(self.data_dir)
        ensure_private_directory(self.backup_dir)
