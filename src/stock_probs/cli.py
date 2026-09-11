"""Operational CLI provides explicit loopback launch, migration, backup, and restore paths."""

from __future__ import annotations

import argparse
import json
import sys

import uvicorn

from stock_probs.api import create_app
from stock_probs.backup import BackupError, BackupManager
from stock_probs.config import Settings
from stock_probs.repository import Repository


def _port(value: str) -> int:
    """Reject invalid listener ports before uvicorn performs any network operation."""

    parsed = int(value)
    if not 1 <= parsed <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return parsed


def _is_loopback(host: str) -> bool:
    """Match the listener to the API Host allowlist instead of accepting DNS aliases."""

    return host in {"127.0.0.1", "localhost", "::1"}


def _operations() -> tuple[Settings, Repository, BackupManager]:
    settings = Settings.from_env()
    settings.ensure_local_dirs()
    repository = Repository(settings.database_path)
    repository.migrate()
    return settings, repository, BackupManager(repository, settings.backup_dir)


def main() -> None:
    """Dispatch bounded local operations; broader network binds require an explicit flag."""

    parser = argparse.ArgumentParser(prog="stock-probs")
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
                create_app(),
                host=host,
                port=port,
                workers=1,
                limit_concurrency=32,
                backlog=64,
                timeout_keep_alive=5,
                timeout_graceful_shutdown=10,
            )
        elif args.command == "migrate":
            _operations()
            print(json.dumps({"status": "migrated"}))
        elif args.command == "backup":
            print(json.dumps(_operations()[2].create(args.name), indent=2))
        elif args.command == "restore":
            print(json.dumps(_operations()[2].restore(args.name, promote=args.promote), indent=2))
    except BackupError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
