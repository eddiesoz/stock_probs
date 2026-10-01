#!/usr/bin/env python3
"""Install a fixed production SMTP secret and recreate the current immutable app.

The remote entry point accepts only the API-key bytes on standard input. All host paths,
Compose arguments, and the readiness URL are constants so an operator or MCP caller cannot
redirect the operation to another file, image, command, or network destination.
"""

from __future__ import annotations

import fcntl
import hashlib
import http.client
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import time
from contextlib import suppress
from urllib.request import ProxyHandler, Request, build_opener

APP_DIRECTORY = "/etc/signal-ledger"
APP_ENV_NAME = "app.env"
APP_ENV = f"{APP_DIRECTORY}/{APP_ENV_NAME}"
STATE_DIRECTORY = "/var/lib/signal-ledger"
LOCK_FILE_NAME = "deploy.lock"
RUNTIME_ENV = f"{STATE_DIRECTORY}/runtime.env"
COMPOSE_DIRECTORY = "/opt/signal-ledger"
COMPOSE_FILE_NAME = "compose.production.yaml"
COMPOSE_FILE = f"{COMPOSE_DIRECTORY}/{COMPOSE_FILE_NAME}"
PROJECT_NAME = "signal-ledger"
HEALTH_URL = "http://127.0.0.1:8000/api/v1/readiness"
SMTP_PASSWORD_NAME = b"STOCK_PROBS_INVITE_SMTP_PASSWORD"
SMTP_HOST_NAME = b"STOCK_PROBS_INVITE_SMTP_HOST"
SMTP_PORT_NAME = b"STOCK_PROBS_INVITE_SMTP_PORT"
SMTP_USERNAME_NAME = b"STOCK_PROBS_INVITE_SMTP_USERNAME"
SMTP_SECURITY_NAME = b"STOCK_PROBS_INVITE_SMTP_SECURITY"
SMTP_FROM_NAME = b"STOCK_PROBS_INVITE_EMAIL_FROM"
SMTP_TARGET_NAMES = frozenset(
    {
        SMTP_HOST_NAME,
        SMTP_PORT_NAME,
        SMTP_USERNAME_NAME,
        SMTP_PASSWORD_NAME,
        SMTP_SECURITY_NAME,
        SMTP_FROM_NAME,
    }
)
SMTP_ASSIGNMENTS = (
    (SMTP_HOST_NAME, b"smtp.resend.com"),
    (SMTP_PORT_NAME, b"2465"),
    (SMTP_USERNAME_NAME, b"resend"),
    (SMTP_PASSWORD_NAME, None),
    (SMTP_SECURITY_NAME, b"implicit_tls"),
    (SMTP_FROM_NAME, b"invites@mail.jtmb.cc"),
)
MAX_API_KEY_BYTES = 512
MAX_APP_ENV_BYTES = 64 * 1024
MAX_RUNTIME_ENV_BYTES = 4096
API_KEY_PATTERN = re.compile(rb"re_[A-Za-z0-9_-]{8,509}")
RUNTIME_IMAGE_PATTERN = re.compile(rb"STOCK_PROBS_IMAGE=signal-ledger:sha-[0-9a-f]{40}\n?\Z")
ENV_ASSIGNMENT_PATTERN = re.compile(rb"^[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=")
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW
ROOT_UID = 0


class InstallError(Exception):
    """Represent a safe, non-diagnostic installer failure."""


class RollbackRecovered(InstallError):
    """The SMTP update failed, but the previous app configuration recovered."""


class AppEnvPublishError(InstallError):
    """A publish failed after replacement, with an optional exact new-file signature."""

    def __init__(self, installed: os.stat_result | None) -> None:
        super().__init__()
        self.installed = installed


def _directory(path: str, mode: int) -> int:
    try:
        descriptor = os.open(path, DIRECTORY_FLAGS)
        metadata = os.fstat(descriptor)
    except OSError as exc:
        raise InstallError from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != ROOT_UID
        or stat.S_IMODE(metadata.st_mode) != mode
    ):
        os.close(descriptor)
        raise InstallError
    return descriptor


def _regular_bytes(
    path: str, limit: int, *, mode: int, owner: int | None = None
) -> tuple[bytes, os.stat_result]:
    if owner is None:
        owner = ROOT_UID
    descriptor = -1
    try:
        descriptor = os.open(path, FILE_FLAGS)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != owner
            or stat.S_IMODE(metadata.st_mode) != mode
            or metadata.st_nlink != 1
            or metadata.st_size > limit
        ):
            raise InstallError
        value = os.read(descriptor, limit + 1)
        after = os.fstat(descriptor)
        if (
            after.st_dev != metadata.st_dev
            or after.st_ino != metadata.st_ino
            or after.st_size != metadata.st_size
        ):
            raise InstallError
    except (OSError, InstallError) as exc:
        raise InstallError from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(value) != metadata.st_size or len(value) > limit:
        raise InstallError
    return value, metadata


def _signature(metadata: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_uid,
        metadata.st_gid,
        stat.S_IMODE(metadata.st_mode),
        metadata.st_nlink,
        metadata.st_size,
    )


def _write_all(descriptor: int, value: bytes) -> None:
    remaining = memoryview(value)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise InstallError
        remaining = remaining[written:]


def _validate_fixed_files() -> tuple[bytes, os.stat_result]:
    app_directory_fd = _directory(APP_DIRECTORY, 0o750)
    try:
        app_value, app_metadata = _regular_bytes(
            APP_ENV,
            MAX_APP_ENV_BYTES,
            mode=0o600,
        )
    finally:
        os.close(app_directory_fd)

    runtime_value, _ = _regular_bytes(RUNTIME_ENV, MAX_RUNTIME_ENV_BYTES, mode=0o640)
    if RUNTIME_IMAGE_PATTERN.fullmatch(runtime_value) is None:
        raise InstallError

    compose_directory_fd = _directory(COMPOSE_DIRECTORY, 0o750)
    try:
        _, compose_metadata = _regular_bytes(
            COMPOSE_FILE,
            512 * 1024,
            mode=0o644,
        )
    finally:
        os.close(compose_directory_fd)
    if compose_metadata.st_uid != ROOT_UID:
        raise InstallError
    return app_value, app_metadata


def _validate_api_key(value: bytes) -> bytes:
    if value.endswith(b"\n"):
        value = value[:-1]
    if len(value) > MAX_API_KEY_BYTES or API_KEY_PATTERN.fullmatch(value) is None:
        raise InstallError
    return value


def _updated_app_env(existing: bytes, api_key: bytes) -> bytes:
    if b"\x00" in existing:
        raise InstallError
    retained: list[bytes] = []
    for line in existing.splitlines(keepends=True):
        content = line[:-1] if line.endswith(b"\n") else line
        if content.endswith(b"\r"):
            content = content[:-1]
        if content.lstrip(b" \t").startswith(b"#") or not content.strip():
            retained.append(line)
            continue
        assignment = ENV_ASSIGNMENT_PATTERN.match(content)
        if assignment is None:
            raise InstallError
        if assignment.group(1) not in SMTP_TARGET_NAMES:
            retained.append(line)

    result = b"".join(retained)
    if result and not result.endswith(b"\n"):
        result += b"\n"
    for name, fixed_value in SMTP_ASSIGNMENTS:
        value = api_key if name == SMTP_PASSWORD_NAME else fixed_value
        if value is None:
            raise InstallError
        result += name + b"=" + value + b"\n"
    if len(result) > MAX_APP_ENV_BYTES:
        raise InstallError
    return result


def _create_rollback_artifact(original: bytes) -> str:
    parent_fd = _directory(STATE_DIRECTORY, 0o750)
    name = f".smtp-rollback.{secrets.token_hex(16)}.env"
    descriptor = -1
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        _write_all(descriptor, original)
        os.fchown(descriptor, ROOT_UID, 0)
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != ROOT_UID
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
            or metadata.st_size != len(original)
        ):
            raise InstallError
        os.close(descriptor)
        descriptor = -1
        os.fsync(parent_fd)
        return name
    except (OSError, InstallError) as exc:
        raise InstallError from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if descriptor >= 0 or "metadata" not in locals():
            with suppress(FileNotFoundError, OSError):
                os.unlink(name, dir_fd=parent_fd)
        os.close(parent_fd)


def _remove_rollback_artifact(name: str) -> None:
    try:
        parent_fd = _directory(STATE_DIRECTORY, 0o750)
    except InstallError:
        return
    try:
        with suppress(FileNotFoundError, OSError):
            os.unlink(name, dir_fd=parent_fd)
        with suppress(OSError):
            os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _publish_app_env(
    updated: bytes, before: os.stat_result, before_digest: bytes
) -> os.stat_result:
    parent_fd = _directory(APP_DIRECTORY, 0o750)
    temporary_name = f".app.env.smtp.{secrets.token_hex(16)}.tmp"
    temporary_fd = -1
    replaced = False
    installed_metadata: os.stat_result | None = None
    try:
        temporary_fd = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        _write_all(temporary_fd, updated)
        os.fchown(temporary_fd, ROOT_UID, 0)
        os.fchmod(temporary_fd, 0o600)
        os.fsync(temporary_fd)
        os.close(temporary_fd)
        temporary_fd = -1

        current = os.stat(APP_ENV_NAME, dir_fd=parent_fd, follow_symlinks=False)
        current_value, _ = _regular_bytes(APP_ENV, MAX_APP_ENV_BYTES, mode=0o600)
        if (
            _signature(current) != _signature(before)
            or hashlib.sha256(current_value).digest() != before_digest
        ):
            raise InstallError
        os.replace(
            temporary_name,
            APP_ENV_NAME,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        replaced = True
        installed, metadata = _regular_bytes(APP_ENV, MAX_APP_ENV_BYTES, mode=0o600)
        if (
            metadata.st_uid == ROOT_UID
            and installed == updated
            and _signature(metadata) != _signature(before)
        ):
            installed_metadata = metadata
        if _signature(metadata) == _signature(before) or installed != updated:
            raise InstallError
        os.fsync(parent_fd)
        return metadata
    except (OSError, InstallError) as exc:
        if replaced:
            raise AppEnvPublishError(installed_metadata) from exc
        raise InstallError from exc
    finally:
        if temporary_fd >= 0:
            os.close(temporary_fd)
        with suppress(FileNotFoundError, OSError):
            os.unlink(temporary_name, dir_fd=parent_fd)
        os.close(parent_fd)


def _compose_recreate() -> None:
    environment = {
        "HOME": "/root",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    }
    command = [
        "/usr/bin/docker",
        "compose",
        "--ansi",
        "never",
        "--project-name",
        PROJECT_NAME,
        "--env-file",
        APP_ENV,
        "--env-file",
        RUNTIME_ENV,
        "--file",
        COMPOSE_FILE,
        "up",
        "--detach",
        "--no-build",
        "--pull",
        "never",
        "--force-recreate",
        "app",
    ]
    try:
        subprocess.run(  # noqa: S603 - command and environment are fixed above.
            command,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment,
            timeout=180,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise InstallError from exc


def _wait_ready() -> None:
    opener = build_opener(ProxyHandler({}))
    request = Request(  # noqa: S310 - HEALTH_URL is a fixed loopback HTTP constant.
        HEALTH_URL, headers={"Accept": "application/json"}
    )
    for _ in range(30):
        try:
            with opener.open(request, timeout=3) as response:
                if response.status != 200:
                    raise InstallError
                value = json.loads(response.read(8193))
                if (
                    isinstance(value, dict)
                    and value.get("status") == "ready"
                    and type(value.get("schema_version")) is int
                    and 1 <= value["schema_version"] <= 100
                ):
                    return
        except (
            OSError,
            http.client.HTTPException,
            http.client.IncompleteRead,
            ValueError,
            TypeError,
            InstallError,
        ):
            pass
        time.sleep(1)
    raise InstallError


def install(api_key: bytes) -> None:
    lock_parent_fd = _directory(STATE_DIRECTORY, 0o750)
    lock_fd = -1
    rollback_name: str | None = None
    try:
        lock_fd = os.open(
            LOCK_FILE_NAME,
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o640,
            dir_fd=lock_parent_fd,
        )
        lock_metadata = os.fstat(lock_fd)
        if (
            not stat.S_ISREG(lock_metadata.st_mode)
            or lock_metadata.st_uid != ROOT_UID
            or stat.S_IMODE(lock_metadata.st_mode) not in (0o600, 0o640)
            or lock_metadata.st_nlink != 1
        ):
            raise InstallError
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise InstallError from exc

        app_value, before = _validate_fixed_files()
        api_key = _validate_api_key(api_key)
        updated = _updated_app_env(app_value, api_key)
        rollback_name = _create_rollback_artifact(app_value)
        published: os.stat_result | None = None
        try:
            published = _publish_app_env(updated, before, hashlib.sha256(app_value).digest())
            _compose_recreate()
            _wait_ready()
        except (OSError, InstallError) as exc:
            if isinstance(exc, AppEnvPublishError):
                published = exc.installed
            if published is None:
                raise InstallError from None
            try:
                _publish_app_env(
                    app_value,
                    published,
                    hashlib.sha256(updated).digest(),
                )
                _compose_recreate()
                _wait_ready()
            except (OSError, InstallError):
                raise InstallError from None
            _remove_rollback_artifact(rollback_name)
            raise RollbackRecovered from None
        _remove_rollback_artifact(rollback_name)
    except RollbackRecovered:
        raise
    except (OSError, InstallError):
        raise InstallError from None
    finally:
        if lock_fd >= 0:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        os.close(lock_parent_fd)


def validate_key_file(path: str) -> None:
    descriptor = -1
    try:
        descriptor = os.open(path, FILE_FLAGS)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_mode & 0o077
            or metadata.st_size <= 0
            or metadata.st_size > MAX_API_KEY_BYTES + 1
        ):
            raise InstallError
        value = os.read(descriptor, MAX_API_KEY_BYTES + 2)
        after = os.fstat(descriptor)
        if (
            after.st_dev != metadata.st_dev
            or after.st_ino != metadata.st_ino
            or after.st_size != metadata.st_size
        ):
            raise InstallError
    except (OSError, InstallError):
        raise SystemExit(2) from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    try:
        value = _validate_api_key(value)
    except InstallError:
        raise SystemExit(2) from None


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--validate-file":
        validate_key_file(sys.argv[2])
        return 0
    if len(sys.argv) != 1:
        raise SystemExit(2)
    try:
        api_key = sys.stdin.buffer.read(MAX_API_KEY_BYTES + 2)
        install(api_key)
    except RollbackRecovered:
        return 3
    except InstallError:
        raise SystemExit(2) from None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
