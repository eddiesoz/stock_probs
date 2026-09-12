"""Operational CLI provides explicit loopback launch, migration, backup, and restore paths."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from typing import Any

import uvicorn
from starlette.types import ASGIApp, Receive, Scope, Send

from stock_probs.api import create_app
from stock_probs.backup import BackupError, BackupManager, _check_deadline, _run_with_deadline
from stock_probs.config import Settings
from stock_probs.repository import SCHEMA_VERSION, Repository

TRUST_KEY_TRANSFER_HELP = (
    "Trust-key transfer: copy .backup-auth.key with managed .spbackup files over a protected "
    "channel, retain mode 0600, verify at the destination, then retire the source key only "
    "after its artifacts are explicitly transferred or removed."
)


def _port(value: str) -> int:
    """Reject invalid listener ports before uvicorn performs any network operation."""

    parsed = int(value)
    if not 1 <= parsed <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return parsed


def _is_loopback(host: str) -> bool:
    """Match the listener to the API Host allowlist instead of accepting DNS aliases."""

    return host in {"127.0.0.1", "localhost", "::1"}


def _migrate_with_backup(
    repository: Repository, manager: BackupManager
) -> dict[str, Any] | None:
    """Create and re-open one old-schema artifact immediately before an upgrade."""

    def migrate() -> dict[str, Any] | None:
        # Migration and its callback stay on one worker so the repository lock remains reentrant.
        receipt: dict[str, Any] | None = None

        def backup_before_migration(schema_version: int) -> None:
            nonlocal receipt
            name = (
                f"pre-migration-v{schema_version}-to-v{SCHEMA_VERSION}-"
                f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.spbackup"
            )
            created: dict[str, Any] | None = None
            try:
                created = manager.create(name, schema_version=schema_version)
                _check_deadline()
            except Exception:
                if created is not None:
                    try:
                        (manager.backup_dir / name).unlink(missing_ok=True)
                        manager._sync_directory(manager.backup_dir)
                    except OSError as cleanup_error:
                        raise BackupError(
                            "Refused pre-migration backup could not be removed safely."
                        ) from cleanup_error
                raise
            receipt = {
                "trigger": "pre_migration",
                "verified": True,
                "name": created["name"],
                "sha256": created["sha256"],
                "schema_version": schema_version,
            }

        repository.migrate(before_migration=backup_before_migration)
        _check_deadline()
        return receipt

    return _run_with_deadline(migrate)


def _migration_operations(settings: Settings) -> tuple[BackupManager, dict[str, Any] | None]:
    settings.ensure_local_dirs()
    repository = Repository(settings.database_path)
    manager = BackupManager(repository, settings.backup_dir)
    return manager, _migrate_with_backup(repository, manager)


def _serve_app(settings: Settings) -> ASGIApp:
    """Delay automatic persistence work until Uvicorn actually starts the ASGI lifespan."""

    application = create_app()

    async def automatic_backup(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            try:
                def startup_backups() -> dict[str, Any]:
                    manager, migration_backup = _migration_operations(settings)
                    due_backup = manager.create_if_due(settings.backup_interval_seconds)
                    _check_deadline()
                    return {
                        "status": "automatic_backup_checked",
                        "pre_migration_backup": migration_backup,
                        "due_backup": due_backup,
                    }

                print(json.dumps(_run_with_deadline(startup_backups)))
            except BackupError as exc:
                print(
                    json.dumps({"error": str(exc), "trigger": "automatic_backup"}),
                    file=sys.stderr,
                )
                raise
        await application(scope, receive, send)

    return automatic_backup


def main() -> None:
    """Dispatch bounded local operations; broader network binds require an explicit flag."""

    parser = argparse.ArgumentParser(
        prog="stock-probs",
        epilog=TRUST_KEY_TRANSFER_HELP,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve", help="run the local dashboard and API")
    serve.add_argument("--host", help="listener host (defaults to STOCK_PROBS_HOST or loopback)")
    serve.add_argument("--port", type=_port, help="listener port (defaults to STOCK_PROBS_PORT)")
    serve.add_argument(
        "--allow-non-loopback",
        action="store_true",
        help="acknowledge that non-loopback binding is unsupported and security-sensitive",
    )
    subparsers.add_parser("migrate", help="apply packaged SQLite migrations")
    backup = subparsers.add_parser("backup", help="create a verified managed backup")
    backup.add_argument("--name")
    restore = subparsers.add_parser("restore", help="verify or promote a managed backup")
    restore.add_argument("name")
    restore.add_argument("--promote", action="store_true")
    backup_key = subparsers.add_parser(
        "backup-key",
        help="rotate or retire the managed-backup trust key",
        epilog=TRUST_KEY_TRANSFER_HELP,
    )
    key_commands = backup_key.add_subparsers(dest="key_command", required=True)
    key_commands.add_parser("rotate", help="verify and re-sign every backup with a new key")
    key_commands.add_parser(
        "retire", help="remove the key only after every managed backup is transferred or removed"
    )
    args = parser.parse_args()

    try:
        if args.command == "serve":
            settings = Settings.from_env()
            host = args.host or settings.host
            port = args.port or settings.port
            if not _is_loopback(host) and not args.allow_non_loopback:
                parser.error("non-loopback binding requires --allow-non-loopback")
            # One worker and bounded queues/timeouts keep malformed or idle clients inexpensive.
            uvicorn.run(
                _serve_app(settings),
                host=host,
                port=port,
                workers=1,
                limit_concurrency=32,
                backlog=64,
                timeout_keep_alive=5,
                timeout_graceful_shutdown=10,
            )
        elif args.command == "migrate":
            _, migration_backup = _migration_operations(Settings.from_env())
            print(
                json.dumps(
                    {"status": "migrated", "pre_migration_backup": migration_backup}, indent=2
                )
            )
        elif args.command == "backup":
            manager, _ = _migration_operations(Settings.from_env())
            print(json.dumps(manager.create(args.name), indent=2))
        elif args.command == "restore":
            manager, _ = _migration_operations(Settings.from_env())
            print(json.dumps(manager.restore(args.name, promote=args.promote), indent=2))
        elif args.command == "backup-key":
            manager, _ = _migration_operations(Settings.from_env())
            result = manager.rotate_key() if args.key_command == "rotate" else manager.retire_key()
            print(json.dumps(result, indent=2))
    except BackupError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
