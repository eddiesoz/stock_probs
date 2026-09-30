"""Runtime settings keep local state server-owned and loopback defaults explicit."""

from __future__ import annotations

import math
import os
import stat
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from stock_probs.auth import AuthSettings
from stock_probs.invitation_mail import InvitationMailSettings

PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
DEVELOPMENT_SESSION_SECRET = "development-only-session-secret-change-me"  # noqa: S105


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


def _environment_bool(name: str, default: str) -> bool:
    value = os.getenv(name, default).strip().lower()
    if value not in {"0", "1", "false", "true", "no", "yes"}:
        raise ValueError(f"{name} must be true or false")
    return value in {"1", "true", "yes"}


def _validate_origin(value: str, *, production: bool) -> str:
    origin = value.strip().rstrip("/")
    parsed = urlparse(origin)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("STOCK_PROBS_PUBLIC_ORIGIN must contain a valid port") from exc
    if (
        parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65_535)
    ):
        raise ValueError("STOCK_PROBS_PUBLIC_ORIGIN must be an exact origin without a path")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("STOCK_PROBS_PUBLIC_ORIGIN must be an HTTP(S) origin")
    if production and parsed.scheme != "https":
        raise ValueError("production authentication requires an HTTPS public origin")
    return origin


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
    backup_interval_seconds: float = 86_400.0
    environment: str = "development"
    auth_mode: str = "disabled"
    auth_session_secret: str = DEVELOPMENT_SESSION_SECRET
    auth_session_idle_seconds: int = 1_800
    auth_session_max_seconds: int = 86_400
    auth_invitation_ttl_seconds: int = 86_400
    auth_public_origin: str | None = None
    auth_cookie_secure: bool = False
    auth_cookie_domain: str | None = None
    github_client_id: str | None = None
    github_client_secret: str | None = None
    github_redirect_uri: str | None = None
    owner_github_id: int | None = None
    invitation_mail: InvitationMailSettings | None = field(default=None, repr=False)
    bootstrap_username: str | None = None
    bootstrap_password: str | None = None
    bootstrap_member_username: str | None = None
    bootstrap_member_password: str | None = None
    trusted_proxy_hosts: tuple[str, ...] = ("127.0.0.1", "::1", "localhost")

    @classmethod
    def from_env(cls) -> Settings:
        # Normalize without resolving symlinks; startup must inspect/reject the configured path
        # rather than silently converting a linked data directory into its target.
        configured_data_dir = Path(os.getenv("STOCK_PROBS_DATA_DIR", "data")).expanduser()
        data_dir = configured_data_dir.absolute()
        timeout = _environment_float("STOCK_PROBS_PROVIDER_TIMEOUT", "8")
        backup_interval = _environment_float("STOCK_PROBS_BACKUP_INTERVAL_SECONDS", "86400")
        port = _environment_int("STOCK_PROBS_PORT", "8000")
        provider = os.getenv("STOCK_PROBS_PROVIDER", "yahoo")
        host = os.getenv("STOCK_PROBS_HOST", "127.0.0.1").strip().lower()
        environment = os.getenv("STOCK_PROBS_ENV", "development").strip().lower()
        if environment not in {"development", "production", "test"}:
            raise ValueError("STOCK_PROBS_ENV must be development, test, or production")
        auth_mode = os.getenv("STOCK_PROBS_AUTH_MODE", "disabled").strip().lower()
        if auth_mode not in {"disabled", "local", "github"}:
            raise ValueError("STOCK_PROBS_AUTH_MODE must be disabled, local, or github")
        if environment == "production" and auth_mode != "github":
            raise ValueError("production must use GitHub authentication")
        public_origin_value = os.getenv("STOCK_PROBS_PUBLIC_ORIGIN")
        if public_origin_value is None and auth_mode == "local":
            public_origin_value = f"http://{host}:{port}"
        public_origin = (
            _validate_origin(public_origin_value, production=environment == "production")
            if public_origin_value
            else None
        )
        session_secret = os.getenv("STOCK_PROBS_AUTH_SESSION_SECRET", DEVELOPMENT_SESSION_SECRET)
        idle_seconds = _environment_int("STOCK_PROBS_AUTH_SESSION_IDLE_SECONDS", "1800")
        max_seconds = _environment_int("STOCK_PROBS_AUTH_SESSION_MAX_SECONDS", "86400")
        invitation_ttl = _environment_int("STOCK_PROBS_AUTH_INVITATION_TTL_SECONDS", "86400")
        cookie_secure = _environment_bool(
            "STOCK_PROBS_AUTH_COOKIE_SECURE", "1" if environment == "production" else "0"
        )
        cookie_domain = os.getenv("STOCK_PROBS_AUTH_COOKIE_DOMAIN")
        github_client_id = os.getenv("STOCK_PROBS_GITHUB_CLIENT_ID")
        github_client_secret = os.getenv("STOCK_PROBS_GITHUB_CLIENT_SECRET")
        github_redirect_uri = os.getenv("STOCK_PROBS_GITHUB_REDIRECT_URI")
        owner_github_id_value = os.getenv("STOCK_PROBS_OWNER_GITHUB_ID")
        try:
            owner_github_id = int(owner_github_id_value) if owner_github_id_value else None
        except ValueError as exc:
            raise ValueError("STOCK_PROBS_OWNER_GITHUB_ID must be an integer") from exc
        if owner_github_id is not None and owner_github_id < 1:
            raise ValueError("STOCK_PROBS_OWNER_GITHUB_ID must be positive")
        if environment == "production" and owner_github_id is None:
            raise ValueError("production requires STOCK_PROBS_OWNER_GITHUB_ID")
        bootstrap_username = os.getenv("STOCK_PROBS_BOOTSTRAP_USERNAME")
        bootstrap_password = os.getenv("STOCK_PROBS_BOOTSTRAP_PASSWORD")
        bootstrap_member_username = os.getenv("STOCK_PROBS_BOOTSTRAP_MEMBER_USERNAME")
        bootstrap_member_password = os.getenv("STOCK_PROBS_BOOTSTRAP_MEMBER_PASSWORD")
        if environment == "production" and (
            bootstrap_username
            or bootstrap_password
            or bootstrap_member_username
            or bootstrap_member_password
        ):
            raise ValueError("development bootstrap credentials cannot be set in production")
        if environment == "production" and session_secret == DEVELOPMENT_SESSION_SECRET:
            raise ValueError("production requires a unique authentication session secret")
        if environment == "production" and not cookie_secure:
            raise ValueError("production authentication cookies must be Secure")
        if environment == "production" and cookie_domain:
            raise ValueError("production authentication cookies must be host-only")
        trusted_proxy_hosts = tuple(
            item.strip().lower()
            for item in os.getenv(
                "STOCK_PROBS_TRUSTED_PROXY_HOSTS", "127.0.0.1,::1,localhost"
            ).split(",")
            if item.strip()
        )
        if not math.isfinite(timeout) or not 1.0 <= timeout <= 20.0:
            raise ValueError("STOCK_PROBS_PROVIDER_TIMEOUT must be between 1 and 20 seconds")
        if not math.isfinite(backup_interval) or not 60.0 <= backup_interval <= 2_678_400.0:
            raise ValueError(
                "STOCK_PROBS_BACKUP_INTERVAL_SECONDS must be between 60 and 2678400 seconds"
            )
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
            backup_interval_seconds=backup_interval,
            environment=environment,
            auth_mode=auth_mode,
            auth_session_secret=session_secret,
            auth_session_idle_seconds=idle_seconds,
            auth_session_max_seconds=max_seconds,
            auth_invitation_ttl_seconds=invitation_ttl,
            auth_public_origin=public_origin,
            auth_cookie_secure=cookie_secure,
            auth_cookie_domain=cookie_domain,
            github_client_id=github_client_id,
            github_client_secret=github_client_secret,
            github_redirect_uri=github_redirect_uri,
            owner_github_id=owner_github_id,
            invitation_mail=InvitationMailSettings.from_env(),
            bootstrap_username=bootstrap_username,
            bootstrap_password=bootstrap_password,
            bootstrap_member_username=bootstrap_member_username,
            bootstrap_member_password=bootstrap_member_password,
            trusted_proxy_hosts=trusted_proxy_hosts,
        )

    @property
    def email_invites_enabled(self) -> bool:
        """Report whether a complete SMTP invitation configuration is available."""

        return self.invitation_mail is not None

    def auth_settings(self) -> AuthSettings:
        """Return validated auth settings without exposing secrets in logs or responses."""

        if self.environment == "production":
            if self.auth_mode != "github":
                raise ValueError("production must use GitHub authentication")
            if self.auth_session_secret == DEVELOPMENT_SESSION_SECRET:
                raise ValueError("production requires a unique authentication session secret")
            if (
                self.bootstrap_username
                or self.bootstrap_password
                or self.bootstrap_member_username
                or self.bootstrap_member_password
            ):
                raise ValueError("development bootstrap credentials cannot be set in production")
            if not self.auth_cookie_secure or not self.auth_public_origin:
                raise ValueError("production authentication requires Secure HTTPS cookies")
            if not self.auth_public_origin.startswith("https://"):
                raise ValueError("production authentication requires an HTTPS public origin")
            if self.auth_cookie_domain:
                raise ValueError("production authentication cookies must be host-only")
            if self.owner_github_id is None or self.owner_github_id < 1:
                raise ValueError("production requires an owner GitHub ID")

        result = AuthSettings(
            mode=self.auth_mode,  # type: ignore[arg-type]
            session_secret=self.auth_session_secret,
            session_idle_seconds=self.auth_session_idle_seconds,
            session_max_seconds=self.auth_session_max_seconds,
            invitation_ttl_seconds=self.auth_invitation_ttl_seconds,
            public_origin=self.auth_public_origin,
            cookie_secure=self.auth_cookie_secure,
            cookie_domain=self.auth_cookie_domain,
            github_client_id=self.github_client_id,
            github_client_secret=self.github_client_secret,
            github_redirect_uri=self.github_redirect_uri,
            owner_github_id=self.owner_github_id,
            bootstrap_username=self.bootstrap_username,
            bootstrap_password=self.bootstrap_password,
        )
        result.validate()
        return result

    def ensure_local_dirs(self) -> None:
        """Create private local directories without accepting paths from requests."""

        ensure_private_directory(self.data_dir)
        ensure_private_directory(self.backup_dir)
