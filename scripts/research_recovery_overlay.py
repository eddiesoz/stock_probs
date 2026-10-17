"""Prepare a pinned schema-14 recovery source overlay and inspect schema-14 databases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

BASELINE_REVISION = "5ad2c3fddfce5a5a631b72cd832a53f24757c44a"
BASELINE_REPOSITORY_PATH = "src/stock_probs/repository.py"
BASELINE_REPOSITORY_BLOB_SHA1 = "86994c12f8694ef882f7f4eaa76d4d420c8ec1f6"
BASELINE_REPOSITORY_SHA256 = "435cae9ef43e7c4b4596238b03a5acdea747625c79554f1816e96af732cc0f86"
MIGRATION_PATH = "src/stock_probs/migrations/014_research_workspaces.sql"
MIGRATION_SHA256 = "0229c7713bd8d0fe5dfc2cc57d52052f71af4b4f417761175753287f3bf453ae"
OVERLAY_REPOSITORY_SHA256 = "10f5553d5d1e46e3d62899d79501d59ad08cbfaf1a2ac1755464f287680759ec"
OVERLAY_SHA256 = "8305782c24de6ad539b15e3dda4bfd3982010052013cac9b2d29086d31019520"
GIT_EXECUTABLE = "/usr/bin/git"
SCHEMA_VERSION = 14
RECOVERY_SNAPSHOT_MAX_ROWS_PER_TABLE = 250_000
RECOVERY_SNAPSHOT_MAX_CANONICAL_BYTES = 128 * 1024 * 1024
RESEARCH_TABLES = frozenset(
    {"research_theses", "research_thesis_revisions", "research_comparisons"}
)
# This is a compatibility floor for the pinned 5ad schema-13 baseline plus migration 014.
# Existing migration receipts store only versions and timestamps, so the reader cannot prove
# per-migration digests or arbitrary SQL constraints; it checks the known table set and the
# critical columns needed to read retained core, owner, assistant, and research records.
RECOVERY_REQUIRED_TABLES = frozenset(
    {
        "assistant_action_receipts",
        "assistant_conversation_deletions",
        "assistant_conversations",
        "assistant_events",
        "assistant_execution_leases",
        "assistant_messages",
        "assistant_model_consents",
        "assistant_proposed_actions",
        "assistant_search_previews",
        "assistant_sources",
        "assistant_turns",
        "forecast_inputs",
        "forecast_result_owners",
        "forecast_results",
        "forecast_run_owners",
        "forecast_runs",
        "history_exports",
        "history_facets",
        "instrument_list_items",
        "invitations",
        "oauth_states",
        "outcome_owners",
        "outcomes",
        "passkeys",
        "recovery_codes",
        "research_comparisons",
        "research_theses",
        "research_thesis_revisions",
        "schema_migrations",
        "search_event_owners",
        "search_events",
        "sessions",
        "totp_attempt_throttles",
        "totp_enrollments",
        "totp_factors",
        "user_instrument_list_items",
        "users",
    }
)
RECOVERY_REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "schema_migrations": frozenset({"version", "applied_at"}),
    "forecast_runs": frozenset({"id", "symbol", "asset_type", "content_fingerprint", "created_at"}),
    "search_events": frozenset(
        {
            "id",
            "request_id",
            "submitted_symbol",
            "normalized_symbol",
            "asset_type",
            "status",
            "run_id",
            "submitted_at",
            "completed_at",
        }
    ),
    "forecast_inputs": frozenset({"id", "run_id", "snapshot_json", "created_at"}),
    "forecast_results": frozenset({"id", "input_id", "horizon", "result_json", "created_at"}),
    "outcomes": frozenset(
        {
            "id",
            "result_id",
            "observed_close",
            "observed_return",
            "observed_at",
            "comparison_rule",
            "state",
            "note",
            "created_at",
        }
    ),
    "users": frozenset(
        {"id", "github_user_id", "login", "display_name", "role", "status", "created_at"}
    ),
    "sessions": frozenset(
        {
            "id",
            "user_id",
            "session_id",
            "token_hash",
            "csrf_token_hash",
            "issued_at",
            "idle_expires_at",
            "absolute_expires_at",
        }
    ),
    "oauth_states": frozenset({"id", "state_hash", "code_verifier", "redirect_uri"}),
    "forecast_run_owners": frozenset({"run_id", "owner_user_id", "assigned_at"}),
    "forecast_result_owners": frozenset({"result_id", "owner_user_id", "assigned_at"}),
    "outcome_owners": frozenset({"outcome_id", "owner_user_id", "assigned_at"}),
    "search_event_owners": frozenset({"event_id", "owner_user_id", "assigned_at"}),
    "user_instrument_list_items": frozenset(
        {"owner_user_id", "kind", "provider", "canonical_symbol", "asset_type", "added_at"}
    ),
    "assistant_conversations": frozenset(
        {"id", "user_id", "context_json", "context_version", "revision", "created_at"}
    ),
    "assistant_turns": frozenset(
        {"id", "conversation_id", "user_id", "status", "model_id", "context_json"}
    ),
    "assistant_messages": frozenset(
        {"id", "conversation_id", "turn_id", "user_id", "sequence", "role", "content"}
    ),
    "research_theses": frozenset(
        {
            "id",
            "owner_user_id",
            "idempotency_key",
            "request_sha256",
            "revision",
            "payload_json",
            "created_at",
            "updated_at",
        }
    ),
    "research_thesis_revisions": frozenset(
        {"thesis_id", "owner_user_id", "revision", "payload_json", "recorded_at"}
    ),
    "research_comparisons": frozenset(
        {"id", "owner_user_id", "idempotency_key", "payload_json", "created_at"}
    ),
}
MANIFEST_PATH = Path(__file__).resolve().parents[1] / "tools/research-recovery/manifest.json"


class RecoveryOverlayError(ValueError):
    """Report a fixed safe category for invalid overlay or recovery database input."""


def _expected_manifest() -> dict[str, object]:
    """Return the immutable source and disabled-feature contract for this overlay."""

    return {
        "format_version": 1,
        "baseline": {
            "revision": BASELINE_REVISION,
            "schema_version": 13,
            "repository_path": BASELINE_REPOSITORY_PATH,
            "repository_git_blob_sha1": BASELINE_REPOSITORY_BLOB_SHA1,
            "repository_sha256": BASELINE_REPOSITORY_SHA256,
        },
        "migration": {
            "from_schema": 13,
            "to_schema": SCHEMA_VERSION,
            "source_path": MIGRATION_PATH,
            "target_path": MIGRATION_PATH,
            "sha256": MIGRATION_SHA256,
        },
        "overlay": {
            "source_paths": [BASELINE_REPOSITORY_PATH, MIGRATION_PATH],
            "repository_sha256": OVERLAY_REPOSITORY_SHA256,
            "sha256": OVERLAY_SHA256,
        },
        "controls": {
            "assistant_enabled": False,
            "research_features_enabled": False,
            "automatic_pair_rollout_enabled": False,
            "schema13_backup_promotion_enabled": False,
        },
    }


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON object keys instead of accepting last-key-wins input."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RecoveryOverlayError("overlay_manifest_invalid")
        result[key] = value
    return result


def _validate_manifest(value: object) -> dict[str, object]:
    """Require the complete exact manifest, including literal disabled controls."""

    expected = _expected_manifest()
    if not isinstance(value, dict) or set(value) != set(expected):
        raise RecoveryOverlayError("overlay_manifest_invalid")
    if type(value.get("format_version")) is not int or value["format_version"] != 1:
        raise RecoveryOverlayError("overlay_manifest_invalid")
    baseline = value.get("baseline")
    migration = value.get("migration")
    overlay = value.get("overlay")
    controls = value.get("controls")
    if not all(isinstance(item, dict) for item in (baseline, migration, overlay, controls)):
        raise RecoveryOverlayError("overlay_manifest_invalid")
    if any(
        type(section.get(field)) is not int
        for section, field in (
            (baseline, "schema_version"),
            (migration, "from_schema"),
            (migration, "to_schema"),
        )
    ):
        raise RecoveryOverlayError("overlay_manifest_invalid")
    if any(controls.get(field) is not False for field in expected["controls"]):
        raise RecoveryOverlayError("overlay_manifest_invalid")
    if value != expected:
        raise RecoveryOverlayError("overlay_manifest_invalid")
    return value


def load_manifest(path: Path = MANIFEST_PATH) -> tuple[dict[str, object], bytes]:
    """Read and authenticate the one checked-in schema-14 source manifest."""

    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 16_384:
            raise RecoveryOverlayError("overlay_manifest_invalid")
        raw = path.read_bytes()
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except RecoveryOverlayError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryOverlayError("overlay_manifest_invalid") from exc
    return _validate_manifest(value), raw


def _sha256(value: bytes) -> str:
    """Return a lowercase SHA-256 digest for exact file bytes."""

    return hashlib.sha256(value).hexdigest()


def _overlay_digest(files: Mapping[str, bytes]) -> str:
    """Bind sorted relative paths and exact bytes into one deterministic digest."""

    digest = hashlib.sha256()
    for path, contents in sorted(files.items()):
        encoded_path = path.encode("utf-8")
        digest.update(len(encoded_path).to_bytes(4, "big"))
        digest.update(encoded_path)
        digest.update(len(contents).to_bytes(8, "big"))
        digest.update(contents)
    return digest.hexdigest()


def build_overlay_files(
    baseline_repository: bytes,
    migration: bytes,
    manifest: object,
) -> dict[str, bytes]:
    """Apply only the pinned schema-version and migration-registry additions."""

    validated = _validate_manifest(manifest)
    if _sha256(baseline_repository) != BASELINE_REPOSITORY_SHA256:
        raise RecoveryOverlayError("overlay_baseline_mismatch")
    if _sha256(migration) != MIGRATION_SHA256:
        raise RecoveryOverlayError("overlay_migration_mismatch")

    old_version = b"SCHEMA_VERSION = 13"
    new_version = b"SCHEMA_VERSION = 14"
    old_pin = b'    13: "41e7d0ef5e5267ab50a67666862bf01e4c6cfd8986b6096bd8b92deed70ff31b",\n'
    new_pin = old_pin + f'    14: "{MIGRATION_SHA256}",\n'.encode("ascii")
    if baseline_repository.count(old_version) != 1 or baseline_repository.count(old_pin) != 1:
        raise RecoveryOverlayError("overlay_patch_anchor_invalid")
    patched_repository = baseline_repository.replace(old_version, new_version, 1).replace(
        old_pin, new_pin, 1
    )
    if _sha256(patched_repository) != OVERLAY_REPOSITORY_SHA256:
        raise RecoveryOverlayError("overlay_output_mismatch")
    files = {
        BASELINE_REPOSITORY_PATH: patched_repository,
        MIGRATION_PATH: migration,
    }
    overlay = validated["overlay"]
    if not isinstance(overlay, dict) or _overlay_digest(files) != OVERLAY_SHA256:
        raise RecoveryOverlayError("overlay_output_mismatch")
    if overlay.get("sha256") != _overlay_digest(files):
        raise RecoveryOverlayError("overlay_output_mismatch")
    return files


def _read_reviewed_baseline(repository_root: Path) -> bytes:
    """Read the fixed reviewed repository blob without consulting the worktree copy."""

    object_spec = f"{BASELINE_REVISION}:{BASELINE_REPOSITORY_PATH}"
    try:
        blob = subprocess.run(  # noqa: S603 - fixed Git executable, revision, and literal path
            [GIT_EXECUTABLE, "rev-parse", object_spec],
            cwd=repository_root,
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
        if blob.returncode != 0 or blob.stdout.strip() != BASELINE_REPOSITORY_BLOB_SHA1:
            raise RecoveryOverlayError("overlay_baseline_mismatch")
        source = subprocess.run(  # noqa: S603 - fixed Git executable, revision, and literal path
            [GIT_EXECUTABLE, "show", object_spec],
            cwd=repository_root,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RecoveryOverlayError("overlay_baseline_unavailable") from exc
    if source.returncode != 0 or _sha256(source.stdout) != BASELINE_REPOSITORY_SHA256:
        raise RecoveryOverlayError("overlay_baseline_mismatch")
    return source.stdout


def _write_private_file(path: Path, contents: bytes) -> None:
    """Create one new overlay artifact with restrictive permissions and no overwrite."""

    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(contents)
    path.chmod(0o600)


def prepare_overlay(repository_root: Path, destination: Path) -> dict[str, object]:
    """Materialize the verified overlay into a new private directory."""

    manifest, manifest_bytes = load_manifest()
    baseline_repository = _read_reviewed_baseline(repository_root)
    migration_path = repository_root / MIGRATION_PATH
    try:
        migration_metadata = migration_path.lstat()
        if not stat.S_ISREG(migration_metadata.st_mode):
            raise RecoveryOverlayError("overlay_migration_unavailable")
        migration = migration_path.read_bytes()
    except RecoveryOverlayError:
        raise
    except OSError as exc:
        raise RecoveryOverlayError("overlay_migration_unavailable") from exc
    files = build_overlay_files(baseline_repository, migration, manifest)

    parent = destination.parent.resolve(strict=True)
    target = parent / destination.name
    if not target.name or os.path.lexists(target):
        raise RecoveryOverlayError("overlay_destination_unavailable")
    staging = Path(tempfile.mkdtemp(prefix=".schema14-recovery-overlay-", dir=parent))
    staging.chmod(0o700)
    try:
        for relative_path, contents in files.items():
            pure_path = PurePosixPath(relative_path)
            if pure_path.is_absolute() or ".." in pure_path.parts:
                raise RecoveryOverlayError("overlay_path_invalid")
            private_parent = staging
            for part in pure_path.parts[:-1]:
                private_parent = private_parent / part
                private_parent.mkdir(mode=0o700, exist_ok=True)
                private_parent.chmod(0o700)
            file_path = private_parent / pure_path.name
            _write_private_file(file_path, contents)
        _write_private_file(staging / "manifest.json", manifest_bytes)
        os.rename(staging, target)
    except (OSError, RecoveryOverlayError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        if isinstance(exc, RecoveryOverlayError):
            raise
        raise RecoveryOverlayError("overlay_write_failed") from exc

    return {
        "status": "prepared",
        "baseline_revision": BASELINE_REVISION,
        "baseline_repository_sha256": BASELINE_REPOSITORY_SHA256,
        "migration_sha256": MIGRATION_SHA256,
        "overlay_sha256": OVERLAY_SHA256,
        "source_paths": [BASELINE_REPOSITORY_PATH, MIGRATION_PATH],
        "destination": str(target),
        "assistant_enabled": False,
        "research_features_enabled": False,
        "automatic_pair_rollout_enabled": False,
        "schema13_backup_promotion_enabled": False,
        "built_or_published": False,
    }


def open_schema14_recovery_reader(database_path: Path) -> sqlite3.Connection:
    """Open a compatible schema-14 database read-only without migration or restore behavior."""

    connection: sqlite3.Connection | None = None
    try:
        metadata = database_path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise RecoveryOverlayError("recovery_database_invalid")
        uri = database_path.resolve(strict=True).as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=3)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA foreign_keys = ON")
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        if not RECOVERY_REQUIRED_TABLES.issubset(tables):
            raise RecoveryOverlayError("recovery_database_tables_missing")
        for table, required_columns in RECOVERY_REQUIRED_COLUMNS.items():
            columns = {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')}
            if not required_columns.issubset(columns):
                raise RecoveryOverlayError("recovery_database_columns_missing")
        versions = [
            int(row[0])
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
        if versions != list(range(1, SCHEMA_VERSION + 1)):
            raise RecoveryOverlayError("recovery_database_schema_invalid")
        return connection
    except RecoveryOverlayError:
        if connection is not None:
            connection.close()
        raise
    except (OSError, sqlite3.Error, ValueError) as exc:
        if connection is not None:
            connection.close()
        raise RecoveryOverlayError("recovery_database_invalid") from exc


def recovery_database_snapshot(connection: sqlite3.Connection) -> dict[str, object]:
    """Fingerprint retained application rows through the already-validated read-only handle.

    The snapshot reports counts and digests only. It streams every fixed recovery table, including
    assistant history, owner mappings, research rows, and migration timestamps, without returning
    row contents to the caller.
    """

    if connection.execute("PRAGMA query_only").fetchone()[0] != 1:
        raise RecoveryOverlayError("recovery_reader_not_read_only")
    versions = [
        int(row[0])
        for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
    ]
    expected_versions = list(range(1, SCHEMA_VERSION + 1))
    if versions != expected_versions:
        raise RecoveryOverlayError("recovery_database_schema_invalid")
    actual_tables = {
        name
        for name in (
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        )
        if not name.startswith("sqlite_")
    }
    if actual_tables != RECOVERY_REQUIRED_TABLES:
        raise RecoveryOverlayError("recovery_database_tables_unexpected")

    total_canonical_bytes = 0
    table_summaries: dict[str, dict[str, object]] = {}
    for table in sorted(RECOVERY_REQUIRED_TABLES):
        quoted_table = '"' + table.replace('"', '""') + '"'
        columns = [str(row[1]) for row in connection.execute(f"PRAGMA table_info({quoted_table})")]
        if (
            not columns
            or len(columns) > 128
            or any(not name or len(name) > 128 for name in columns)
        ):
            raise RecoveryOverlayError("recovery_database_columns_invalid")
        quoted_columns = ['"' + name.replace('"', '""') + '"' for name in columns]
        order_by = ", ".join(quoted_columns)
        # The table is allowlisted and schema-derived identifiers are quoted above.
        cursor = connection.execute(
            f"SELECT {order_by} FROM {quoted_table} ORDER BY {order_by}"  # noqa: S608 - fixed identifiers
        )
        row_digest = hashlib.sha256()
        column_bytes = json.dumps(
            columns, ensure_ascii=True, separators=(",", ":"), allow_nan=False
        ).encode("ascii")
        row_digest.update(len(column_bytes).to_bytes(4, "big"))
        row_digest.update(column_bytes)
        row_count = 0
        for row in cursor:
            row_values: list[list[object]] = []
            for value in row:
                if value is None:
                    row_values.append(["null", None])
                elif type(value) is int:
                    row_values.append(["integer", value])
                elif type(value) is float:
                    row_values.append(["real", value.hex()])
                elif isinstance(value, str):
                    row_values.append(["text", value])
                elif isinstance(value, bytes):
                    row_values.append(["blob", value.hex()])
                else:
                    raise RecoveryOverlayError("recovery_database_value_invalid")
            try:
                encoded_row = json.dumps(
                    row_values,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("ascii")
            except (TypeError, ValueError) as exc:
                raise RecoveryOverlayError("recovery_database_value_invalid") from exc
            row_count += 1
            total_canonical_bytes += len(encoded_row)
            if (
                row_count > RECOVERY_SNAPSHOT_MAX_ROWS_PER_TABLE
                or len(encoded_row) > 4 * 1024 * 1024
                or total_canonical_bytes > RECOVERY_SNAPSHOT_MAX_CANONICAL_BYTES
            ):
                raise RecoveryOverlayError("recovery_snapshot_limit")
            row_digest.update(len(encoded_row).to_bytes(8, "big"))
            row_digest.update(encoded_row)
        table_summaries[table] = {
            "columns_sha256": hashlib.sha256(column_bytes).hexdigest(),
            "rows": row_count,
            "sha256": row_digest.hexdigest(),
        }

    canonical_summary = {
        "schema_versions": versions,
        "tables": table_summaries,
    }
    summary_bytes = json.dumps(
        canonical_summary, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("ascii")
    return {
        "schema_version": SCHEMA_VERSION,
        **canonical_summary,
        "sha256": hashlib.sha256(summary_bytes).hexdigest(),
    }


def main() -> int:
    """Expose the pinned overlay preparation as a bounded, no-build CLI operation."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[1]
    try:
        receipt = prepare_overlay(repository_root, args.output_dir)
    except RecoveryOverlayError as exc:
        parser.exit(2, f"schema14_recovery_overlay_failed:{exc}\n")
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
