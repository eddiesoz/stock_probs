"""Create or restore one portable backup for the M05 cross-architecture smoke."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
from datetime import UTC, datetime
from pathlib import Path

from stock_probs.backup import BackupManager
from stock_probs.repository import Repository

BACKUP_NAME = "cross-architecture.spbackup"


def _manager(root: Path) -> tuple[Repository, BackupManager]:
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    repository = Repository(root / "stock_probs.sqlite3")
    repository.migrate()
    return repository, BackupManager(repository, root / "backups")


def _report(path: Path, direction: str, counts: object) -> None:
    payload = {
        "task": os.getenv("STOCK_PROBS_TASK_ID", "M05"),
        "direction": direction,
        "machine": platform.machine(),
        "execution_label": os.getenv("STOCK_PROBS_EXECUTION_LABEL", "native x86_64"),
        "physical_arm64_performance": "Unavailable; this is functional restore evidence only",
        "counts": counts,
        "result": "Pass",
    }
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def create(root: Path, request_id: str, report: Path, direction: str) -> None:
    repository, manager = _manager(root)
    now = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)
    repository.record_failure(
        request_id=request_id,
        submitted_symbol="FAIL",
        normalized_symbol="FAIL",
        asset_type="stock",
        error_code="cross_architecture_fixture",
        error_message="Deterministic cross-architecture restore fixture.",
        submitted_at=now,
        completed_at=now,
    )
    manager.create(BACKUP_NAME)
    _report(report, direction, repository.representative_counts())


def restore(
    source: Path, destination: Path, request_id: str, report: Path, direction: str
) -> None:
    repository, manager = _manager(destination)
    manager._ensure_backup_dir()
    shutil.copy2(source / ".backup-auth.key", manager.trust_key_path)
    shutil.copy2(source / "backups" / BACKUP_NAME, manager.backup_dir / BACKUP_NAME)
    restored = manager.restore(BACKUP_NAME, promote=True)
    request_ids = {item["request_id"] for item in repository.history()["items"]}
    if not restored["promoted"] or request_ids != {request_id}:
        raise RuntimeError("cross-architecture restore did not preserve the fixture")
    _report(report, direction, repository.representative_counts())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("create", "restore"))
    parser.add_argument("root", type=Path)
    parser.add_argument("request_id")
    parser.add_argument("report", type=Path)
    parser.add_argument("direction")
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    if args.action == "create":
        create(args.root, args.request_id, args.report, args.direction)
    elif args.source is None:
        parser.error("restore requires --source")
    else:
        restore(args.source, args.root, args.request_id, args.report, args.direction)


if __name__ == "__main__":
    main()
