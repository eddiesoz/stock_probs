"""Host deployment helper tests keep release inputs fixed and responses bounded."""

from __future__ import annotations

import errno
import hashlib
import importlib.util
import json
import os
import re
import secrets
import socket
import sqlite3
import stat
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import nullcontext, suppress
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import stock_probs.cli as cli
from stock_probs.config import Settings
from stock_probs.repository import SCHEMA_VERSION, Repository

ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / "scripts/production-deploy-helper.py"


def test_disposable_schema12_migration_backup_preserves_new_schema13_writes(tmp_path: Path) -> None:
    """Exercise the real migration/backup boundary while preserving writes after v13."""

    data_dir = tmp_path / "data"
    settings = Settings(
        data_dir=data_dir,
        database_path=data_dir / "stock_probs.sqlite3",
        backup_dir=data_dir / "backups",
        provider="fixture",
    )
    settings.ensure_local_dirs()
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        migrations = sorted(
            migration
            for migration in files("stock_probs.migrations").iterdir()
            if migration.name.endswith(".sql") and int(migration.name[:3]) <= 12
        )
        for version, migration in enumerate(migrations, start=1):
            Repository._execute_migration(connection, migration.read_text())
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, "2026-10-04T00:00:00+00:00"),
            )

    repository = Repository(settings.database_path)
    repository.record_failure(
        owner_user_id=1,
        request_id="before-schema13",
        submitted_symbol="FAIL",
        normalized_symbol="FAIL",
        asset_type="stock",
        error_code="fixture_failure",
        error_message="preserve the schema-12 event",
        submitted_at=datetime(2026, 10, 4, tzinfo=UTC),
        completed_at=datetime(2026, 10, 4, tzinfo=UTC),
    )

    manager, receipt = cli._migration_operations(settings)

    assert SCHEMA_VERSION == 13
    assert receipt is not None
    assert receipt["trigger"] == "pre_migration"
    assert receipt["schema_version"] == 12
    assert receipt["verified"] is True
    with repository.connect() as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 13
        assert [
            row[0] for row in connection.execute("SELECT request_id FROM search_events ORDER BY id")
        ] == ["before-schema13"]

    # Inspect the exact old-schema backup through the production archive verifier, then retain
    # a new append-only write on schema 13. This deliberately never promotes/restores old data.
    manifest, staged_database, staging = manager._verify_unlocked(
        receipt["name"], require_active_schema=False
    )
    try:
        assert manifest["schema_version"] == 12
        with sqlite3.connect(staged_database) as connection:
            assert (
                connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 12
            )
            assert [
                row[0]
                for row in connection.execute("SELECT request_id FROM search_events ORDER BY id")
            ] == ["before-schema13"]
    finally:
        staging.cleanup()

    repository.record_failure(
        owner_user_id=1,
        request_id="after-schema13",
        submitted_symbol="FAIL",
        normalized_symbol="FAIL",
        asset_type="stock",
        error_code="fixture_failure",
        error_message="must survive failed-release containment",
        submitted_at=datetime(2026, 10, 4, tzinfo=UTC),
        completed_at=datetime(2026, 10, 4, tzinfo=UTC),
    )
    with repository.connect() as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 13
        assert [
            row[0] for row in connection.execute("SELECT request_id FROM search_events ORDER BY id")
        ] == ["before-schema13", "after-schema13"]


def test_initial_deploy_without_database_needs_no_migration_backup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh empty volume migrates to schema 13 without inventing a source backup."""

    helper = _helper()
    modes: list[str] = []
    monkeypatch.setattr(helper, "_runtime_file", lambda image, mode: modes.append(mode))
    monkeypatch.setattr(
        helper,
        "_compose",
        lambda *args, **kwargs: json.dumps({"status": "migrated", "pre_migration_backup": None}),
    )

    receipt = helper._run_migrations(
        "signal-ledger:test-image",
        "a" * 40,
        source_schema=0,
        target_schema=13,
    )

    assert receipt is None
    assert modes == ["disabled"]


def _helper():
    spec = importlib.util.spec_from_file_location("production_deploy_helper", HELPER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("output", "has_explicit_compose", "expected"),
    [
        ("1", False, True),
        ("0", True, False),
        ("unexpected", False, None),
    ],
)
def test_database_presence_probe_uses_fixed_python_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    output: str,
    has_explicit_compose: bool,
    expected: bool | None,
) -> None:
    """Run the image's read-only file probe directly under Python, not its supervisor."""

    helper = _helper()
    image_ref = "signal-ledger:reviewed-image"
    compose_file = tmp_path / "compose.yaml" if has_explicit_compose else None
    runtime_images: list[str] = []
    compose_calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def fake_compose(*arguments: str, **options: object) -> str:
        compose_calls.append((arguments, options))
        return output

    monkeypatch.setattr(helper, "_runtime_file", lambda image: runtime_images.append(image))
    monkeypatch.setattr(helper, "_compose", fake_compose)

    expected_arguments = (
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "--user",
        "10001:10001",
        "--entrypoint",
        "python",
        "app",
        "-c",
        "from pathlib import Path; "
        "print('1' if Path('/data/stock_probs.sqlite3').is_file() else '0')",
    )
    expected_options = {"timeout": 60, "compose_file": compose_file}

    if expected is None:
        with pytest.raises(helper.HostError, match="database_presence_unavailable"):
            helper._database_present(image_ref, compose_file=compose_file)
    else:
        assert helper._database_present(image_ref, compose_file=compose_file) is expected

    assert runtime_images == [image_ref]
    assert compose_calls == [(expected_arguments, expected_options)]
    assert helper._compose_prefix(compose_file)[-1] == str(
        helper.COMPOSE_FILE if compose_file is None else compose_file
    )


@pytest.mark.parametrize(
    ("output", "has_explicit_compose", "expected"),
    [
        ("12", False, 12),
        ("13", True, 13),
        ("0", False, None),
        ("not-a-schema", True, None),
    ],
)
def test_database_schema_probe_uses_read_only_python_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    output: str,
    has_explicit_compose: bool,
    expected: int | None,
) -> None:
    """Read migration metadata through a read-only SQLite connection as the app UID."""

    helper = _helper()
    image_ref = "signal-ledger:reviewed-image"
    compose_file = tmp_path / "compose.yaml" if has_explicit_compose else None
    runtime_images: list[str] = []
    compose_calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def fake_compose(*arguments: str, **options: object) -> str:
        compose_calls.append((arguments, options))
        return output

    monkeypatch.setattr(helper, "_runtime_file", lambda image: runtime_images.append(image))
    monkeypatch.setattr(helper, "_compose", fake_compose)

    expected_arguments = (
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "--user",
        "10001:10001",
        "--entrypoint",
        "python",
        "app",
        "-c",
        "import sqlite3; c=sqlite3.connect('file:/data/stock_probs.sqlite3?mode=ro', uri=True); "
        "c.execute('PRAGMA query_only=ON'); "
        "r=c.execute('SELECT MAX(version) FROM schema_migrations').fetchone(); "
        "print(r[0] if r and r[0] is not None else 0)",
    )
    expected_options = {"timeout": 60, "compose_file": compose_file}

    if expected is None:
        with pytest.raises(helper.HostError, match="database_schema_unavailable"):
            helper._database_schema(image_ref, compose_file=compose_file)
    else:
        assert helper._database_schema(image_ref, compose_file=compose_file) == expected

    assert runtime_images == [image_ref]
    assert compose_calls == [(expected_arguments, expected_options)]
    assert helper._compose_prefix(compose_file)[-1] == str(
        helper.COMPOSE_FILE if compose_file is None else compose_file
    )


def test_request_parser_accepts_only_fixed_operations_and_exact_payloads() -> None:
    helper = _helper()
    operation, payload = helper._parse_request(b'{"operation":"status","payload":{}}')
    assert operation == "status"
    assert payload == {}

    operation, payload = helper._parse_request(
        b'{"operation":"plan_deploy","payload":{"revision":"'
        + b"a" * 40
        + b'","expected_image_digest":"'
        + b"b" * 64
        + b'"}}'
    )
    assert operation == "plan_deploy"
    assert payload == {"revision": "a" * 40, "expected_image_digest": "b" * 64}
    with pytest.raises(helper.HostError, match="payload_invalid"):
        helper._parse_request(
            b'{"operation":"plan_deploy","payload":{"revision":"' + b"a" * 40 + b'"}}'
        )

    with pytest.raises(helper.HostError, match="payload_invalid"):
        helper._parse_request(b'{"operation":"status","payload":{"path":"/tmp"}}')
    with pytest.raises(helper.HostError, match="operation_invalid"):
        helper._parse_request(b'{"operation":"shell","payload":{}}')


def test_release_pair_request_shape_is_fixed_and_pair_hash_is_required_for_schema13() -> None:
    helper = _helper()
    revision = "a" * 40
    archive_sha256 = "b" * 64
    image_id = "sha256:" + "c" * 64
    pair_sha256 = "d" * 64
    operation, payload = helper._parse_request(
        json.dumps(
            {
                "operation": "plan_deploy",
                "payload": {
                    "revision": revision,
                    "archive_sha256": archive_sha256,
                    "image_id": image_id,
                    "pair_manifest_sha256": pair_sha256,
                },
            }
        ).encode()
    )
    assert operation == "plan_deploy"
    assert payload["pair_manifest_sha256"] == pair_sha256
    with pytest.raises(helper.HostError, match="payload_invalid"):
        helper._parse_request(
            json.dumps(
                {
                    "operation": "plan_deploy",
                    "payload": {
                        "revision": revision,
                        "archive_sha256": archive_sha256,
                        "image_id": image_id,
                        "pair_manifest_sha256": pair_sha256,
                        "recovery_image_id": "sha256:" + "e" * 64,
                    },
                }
            ).encode()
        )


def test_release_pair_migration_pin_matches_packaged_schema13_migration() -> None:
    helper = _helper()
    migration = ROOT / "src/stock_probs/migrations/013_assistant_conversations.sql"

    assert hashlib.sha256(migration.read_bytes()).hexdigest() == helper.PAIR_MIGRATION_SHA256


def test_release_pair_manifest_binds_candidate_recovery_and_reviewed_source() -> None:
    helper = _helper()
    revision = "a" * 40
    source_digest = "1" * 64
    recovery_digest = "2" * 64
    candidate_archive = "3" * 64
    recovery_archive = "4" * 64
    candidate_id = "sha256:" + "5" * 64
    recovery_id = "sha256:" + "6" * 64
    baseline_image_id = "sha256:d3e21ae9de800f0151c1eba74fb3d16423e1171985c33ea03057acbfe2278ec1"
    baseline_archive_sha = "669f840a3141b0fb95ae248b5ea0799733b9e5b5b81e224d4637571c24d8f640"
    migration_path = "src/stock_probs/migrations/013_assistant_conversations.sql"
    facts = {
        "--source-context-manifest": {
            "status": "prepared",
            "source_context_sha256": source_digest,
        },
        "--overlay-manifest": {
            "status": "prepared",
            "observed_deployment_baseline": {
                "source_revision": helper.PAIR_BASE_REVISION,
                "image_id": baseline_image_id,
                "release_archive_sha256": baseline_archive_sha,
            },
            "base_source_context_sha256": "7" * 64,
            "recovery_context_sha256": recovery_digest,
            "recovery_overlay": {
                "base_revision": helper.PAIR_BASE_REVISION,
                "overlay_sha256": "8" * 64,
                "files": {
                    migration_path: helper.PAIR_MIGRATION_SHA256,
                },
            },
        },
    }
    manifest = {
        "format_version": helper.PAIR_MANIFEST_VERSION,
        "repository": helper.PAIR_REPOSITORY,
        "revision": revision,
        "source_context_sha256": source_digest,
        "migration": {
            "from_schema": 12,
            "to_schema": 13,
            "sha256": helper.PAIR_MIGRATION_SHA256,
        },
        "candidate": {
            "asset": helper._release_asset_name(revision, "candidate"),
            "archive_sha256": candidate_archive,
            "archive_size": 1024,
            "image_id": candidate_id,
            "platform": "linux/amd64",
            "revision": revision,
            "schema_version": 13,
            "source_context_sha256": source_digest,
        },
        "recovery": {
            "asset": helper._release_asset_name(revision, "recovery"),
            "archive_sha256": recovery_archive,
            "archive_size": 2048,
            "image_id": recovery_id,
            "platform": "linux/amd64",
            "revision": revision,
            "schema_version": 13,
            "assistant_enabled": False,
            "base_revision": helper.PAIR_BASE_REVISION,
            "base_image_id": baseline_image_id,
            "base_archive_sha256": baseline_archive_sha,
            "base_source_context_sha256": facts["--overlay-manifest"]["base_source_context_sha256"],
            "overlay_sha256": "8" * 64,
            "source_context_sha256": recovery_digest,
            "migration_sha256": helper.PAIR_MIGRATION_SHA256,
        },
    }

    validated = helper._validate_release_pair_manifest(
        manifest,
        revision=revision,
        candidate_archive_sha256=candidate_archive,
        candidate_archive_size=1024,
        candidate_image_id=candidate_id,
        facts=facts,
    )
    assert validated is manifest
    for mutation in (
        {"candidate": {**manifest["candidate"], "archive_size": 1025}},
        {"recovery": {**manifest["recovery"], "assistant_enabled": True}},
        {"recovery": {**manifest["recovery"], "base_revision": "9" * 40}},
        {"migration": {**manifest["migration"], "sha256": "9" * 64}},
    ):
        tampered = {**manifest, **mutation}
        with pytest.raises(helper.HostError, match="release_pair_"):
            helper._validate_release_pair_manifest(
                tampered,
                revision=revision,
                candidate_archive_sha256=candidate_archive,
                candidate_archive_size=1024,
                candidate_image_id=candidate_id,
                facts=facts,
            )


def test_legacy_registry_image_cannot_plan_schema13_without_pair(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    helper = _helper()
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr(helper, "COMPOSE_FILE", compose_file)
    monkeypatch.setattr(helper, "_exclusive_lock", nullcontext)
    monkeypatch.setattr(helper, "_ensure_layout", lambda: None)
    monkeypatch.setattr(helper, "_ensure_source", lambda: None)
    monkeypatch.setattr(helper, "_assert_main_revision", lambda _: None)
    monkeypatch.setattr(helper, "_read_json", lambda _: None)
    monkeypatch.setattr(helper, "_checkout_revision", lambda _: None)
    monkeypatch.setattr(helper, "_assert_compose_revision", lambda: None)
    monkeypatch.setattr(helper, "_compose_digest", lambda: "a" * 64)
    monkeypatch.setattr(helper, "_write_compose_snapshot", lambda *args: None)
    monkeypatch.setattr(
        helper,
        "_pull_image",
        lambda revision, digest: ("ghcr.io/jtmb/signal-ledger@sha256:" + "b" * 64, digest, 13),
    )
    with pytest.raises(helper.HostError, match="release_pair_required"):
        helper._plan_deploy("c" * 40, "d" * 64)


def test_request_parser_rejects_oversized_input_and_untrusted_revision() -> None:
    helper = _helper()
    with pytest.raises(helper.HostError, match="request_too_large"):
        helper._parse_request(b"x" * (helper.REQUEST_LIMIT + 1))
    with pytest.raises(helper.HostError, match="revision_invalid"):
        helper._validate_revision("main;touch /tmp/pwned")


def test_request_parser_accepts_release_archive_identity_without_url_or_path() -> None:
    helper = _helper()
    operation, payload = helper._parse_request(
        json.dumps(
            {
                "operation": "plan_deploy",
                "payload": {
                    "revision": "a" * 40,
                    "archive_sha256": "b" * 64,
                    "image_id": "sha256:" + "c" * 64,
                },
            }
        ).encode()
    )
    assert operation == "plan_deploy"
    assert payload["archive_sha256"] == "b" * 64
    assert payload["image_id"] == "sha256:" + "c" * 64
    with pytest.raises(helper.HostError, match="payload_invalid"):
        helper._parse_request(
            json.dumps(
                {
                    "operation": "plan_deploy",
                    "payload": {
                        "revision": "a" * 40,
                        "archive_sha256": "b" * 64,
                        "image_id": "sha256:" + "c" * 64,
                        "url": "https://attacker.invalid/image.tar.gz",
                    },
                }
            ).encode()
        )


def test_request_parser_limits_assistant_rollout_to_mode_and_exact_release_identity() -> None:
    helper = _helper()
    payload = {
        "mode": "owner_canary",
        "revision": "a" * 40,
        "archive_sha256": "b" * 64,
        "image_id": "sha256:" + "c" * 64,
    }
    operation, parsed = helper._parse_request(
        json.dumps({"operation": "set_assistant_rollout", "payload": payload}).encode()
    )
    assert operation == "set_assistant_rollout"
    assert parsed == payload
    with pytest.raises(helper.HostError, match="payload_invalid"):
        helper._parse_request(
            json.dumps(
                {
                    "operation": "set_assistant_rollout",
                    "payload": {**payload, "runtime_env": "/absolute/override"},
                }
            ).encode()
        )


def test_assistant_rollout_is_bound_to_current_schema13_release_and_ordered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    revision = "a" * 40
    archive_sha256 = "b" * 64
    image_id = "sha256:" + "c" * 64
    current = {
        "revision": revision,
        "transport": helper.GITHUB_RELEASE_TRANSPORT,
        "image_ref": helper._local_image_ref(revision),
        "image_digest": archive_sha256,
        "archive_sha256": archive_sha256,
        "image_id": image_id,
        "platform": "linux/amd64",
        "archive_size": 1234,
        "schema_version": 13,
        "compose_digest": "d" * 64,
        "assistant_rollout_mode": "disabled",
    }
    writes: list[dict[str, object]] = []
    runtime_modes: list[str] = []
    compose_calls: list[dict[str, object]] = []
    kill_calls: list[str] = []
    snapshot = tmp_path / "reviewed.compose.yaml"

    def read_json(path: Path):
        return current if path == helper.CURRENT_RECORD else None

    def write_json(path: Path, value: dict[str, object], **_: object) -> None:
        if path == helper.CURRENT_RECORD:
            current.update(value)
            writes.append(dict(value))

    def health_check() -> dict[str, object]:
        enabled = runtime_modes[-1] != "disabled"
        return {
            "status": "ready",
            "schema_version": 13,
            "assistant": {
                "enabled": enabled,
                "status": "ready" if enabled else "disabled",
            },
        }

    monkeypatch.setattr(helper, "_exclusive_lock", nullcontext)
    monkeypatch.setattr(helper, "_ensure_layout", lambda: None)
    monkeypatch.setattr(helper, "_read_json", read_json)
    monkeypatch.setattr(helper, "_write_json", write_json)
    monkeypatch.setattr(helper, "_image_schema", lambda _: 13)
    monkeypatch.setattr(helper, "_assert_loaded_image", lambda _: None)
    monkeypatch.setattr(helper, "_assert_record_compose_digest", lambda _: snapshot)
    monkeypatch.setattr(helper, "_compose_digest", lambda: current["compose_digest"])
    monkeypatch.setattr(helper, "_runtime_file", lambda _image, mode: runtime_modes.append(mode))
    monkeypatch.setattr(helper, "_app_container_identity", lambda _snapshot: ("1" * 64, 123))
    monkeypatch.setattr(helper, "_request_in_place_assistant_kill", kill_calls.append)
    monkeypatch.setattr(
        helper,
        "_compose_up",
        lambda record, **kwargs: compose_calls.append({"record": record, **kwargs}) or "",
    )
    monkeypatch.setattr(helper, "_health_check", health_check)
    monkeypatch.setattr(helper, "_audit", lambda *args, **kwargs: None)

    with pytest.raises(helper.HostError, match="assistant_release_identity_mismatch"):
        helper._set_assistant_rollout(
            "owner_canary",
            revision="e" * 40,
            archive_sha256=archive_sha256,
            image_id=image_id,
        )
    with pytest.raises(helper.HostError, match="assistant_rollout_transition_invalid"):
        helper._set_assistant_rollout(
            "invited",
            revision=revision,
            archive_sha256=archive_sha256,
            image_id=image_id,
        )
    assert runtime_modes == []

    owner = helper._set_assistant_rollout(
        "owner_canary",
        revision=revision,
        archive_sha256=archive_sha256,
        image_id=image_id,
    )
    invited = helper._set_assistant_rollout(
        "invited",
        revision=revision,
        archive_sha256=archive_sha256,
        image_id=image_id,
    )
    killed = helper._set_assistant_rollout(
        "disabled",
        revision=revision,
        archive_sha256=archive_sha256,
        image_id=image_id,
    )
    assert [owner["assistant_rollout_mode"], invited["assistant_rollout_mode"]] == [
        "owner_canary",
        "invited",
    ]
    assert killed["assistant_rollout_mode"] == "disabled"
    assert current["assistant_rollout_mode"] == "disabled"
    assert runtime_modes == ["owner_canary", "invited", "disabled"]
    assert len(writes) == 3
    assert len(compose_calls) == 2
    assert all(call["force_recreate"] is True for call in compose_calls)
    assert all(call["compose_file"] == snapshot for call in compose_calls)
    assert kill_calls == ["1" * 64]


def test_in_place_kill_uses_only_the_fixed_nonroot_cli_vector(monkeypatch) -> None:
    helper = _helper()
    container_id = "a" * 64
    calls: list[tuple[list[str], float]] = []

    def run(command: list[str], *, timeout: float, cwd=None):
        calls.append((command, timeout))
        return SimpleNamespace(stdout='{"status":"assistant_disabled"}')

    monkeypatch.setattr(helper, "_run", run)

    helper._request_in_place_assistant_kill(container_id)

    assert calls == [
        (
            [
                "docker",
                "exec",
                "--user",
                "10001:10001",
                container_id,
                "python",
                "-m",
                "stock_probs.cli",
                "assistant-kill",
            ],
            30,
        )
    ]


@pytest.mark.parametrize("container_id", ("bad", "sha256:" + "a" * 64, "A" * 64))
def test_in_place_kill_rejects_noncanonical_container_identity(
    monkeypatch, container_id: str
) -> None:
    helper = _helper()
    monkeypatch.setattr(
        helper,
        "_run",
        lambda *_args, **_kwargs: pytest.fail("invalid identity reached docker"),
    )

    with pytest.raises(helper.HostError, match="assistant_app_identity_unavailable"):
        helper._request_in_place_assistant_kill(container_id)


def test_assistant_rollout_readiness_failure_reverts_to_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    revision = "a" * 40
    archive_sha256 = "b" * 64
    image_id = "sha256:" + "c" * 64
    current = {
        "revision": revision,
        "transport": helper.GITHUB_RELEASE_TRANSPORT,
        "image_ref": helper._local_image_ref(revision),
        "image_digest": archive_sha256,
        "archive_sha256": archive_sha256,
        "image_id": image_id,
        "platform": "linux/amd64",
        "archive_size": 1234,
        "schema_version": 13,
        "compose_digest": "d" * 64,
        "assistant_rollout_mode": "disabled",
    }
    modes: list[str] = []
    writes: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []

    def write_json(path: Path, value: dict[str, object], **_: object) -> None:
        if path == helper.CURRENT_RECORD:
            current.update(value)
            writes.append(dict(value))
        elif path == helper.FAILED_RECORD:
            failures.append(dict(value))

    def health_check() -> dict[str, object]:
        enabled = modes[-1] != "disabled"
        return {
            "status": "ready",
            "schema_version": 13,
            "assistant": {
                "enabled": enabled,
                "status": "unavailable" if enabled else "disabled",
            },
        }

    monkeypatch.setattr(helper, "_exclusive_lock", nullcontext)
    monkeypatch.setattr(helper, "_ensure_layout", lambda: None)
    monkeypatch.setattr(
        helper,
        "_read_json",
        lambda path: current if path == helper.CURRENT_RECORD else None,
    )
    monkeypatch.setattr(helper, "_write_json", write_json)
    monkeypatch.setattr(helper, "_image_schema", lambda _: 13)
    monkeypatch.setattr(helper, "_assert_loaded_image", lambda _: None)
    monkeypatch.setattr(helper, "_assert_record_compose_digest", lambda _: tmp_path / "compose")
    monkeypatch.setattr(helper, "_compose_digest", lambda: current["compose_digest"])
    monkeypatch.setattr(helper, "_runtime_file", lambda _image, mode: modes.append(mode))
    monkeypatch.setattr(helper, "_app_container_identity", lambda _snapshot: ("1" * 64, 123))
    monkeypatch.setattr(helper, "_request_in_place_assistant_kill", lambda _container: None)
    monkeypatch.setattr(helper, "_compose_up", lambda *args, **kwargs: "")
    monkeypatch.setattr(helper, "_health_check", health_check)
    monkeypatch.setattr(helper, "_audit", lambda *args, **kwargs: None)

    with pytest.raises(helper.HostError, match="assistant_not_ready"):
        helper._set_assistant_rollout(
            "owner_canary",
            revision=revision,
            archive_sha256=archive_sha256,
            image_id=image_id,
        )
    assert modes == ["owner_canary", "disabled"]
    assert current["assistant_rollout_mode"] == "disabled"
    assert writes[-1]["assistant_rollout_mode"] == "disabled"
    assert failures[-1]["assistant_disabled_verified"] is True
    assert failures[-1]["app_stopped"] is False
    assert failures[-1]["containment_status"] == "assistant_disabled"


def test_disable_rollout_stops_app_when_kill_switch_cannot_be_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    revision = "a" * 40
    archive_sha256 = "b" * 64
    image_id = "sha256:" + "c" * 64
    current = {
        "revision": revision,
        "transport": helper.GITHUB_RELEASE_TRANSPORT,
        "image_ref": helper._local_image_ref(revision),
        "image_digest": archive_sha256,
        "archive_sha256": archive_sha256,
        "image_id": image_id,
        "platform": "linux/amd64",
        "archive_size": 1234,
        "schema_version": 13,
        "compose_digest": "d" * 64,
        "assistant_rollout_mode": "invited",
    }
    writes: list[tuple[Path, dict[str, object]]] = []
    modes: list[str] = []
    stopped: list[Path | None] = []

    def write_json(path: Path, value: dict[str, object], **_: object) -> None:
        writes.append((path, dict(value)))
        if path == helper.CURRENT_RECORD:
            current.update(value)

    monkeypatch.setattr(helper, "_exclusive_lock", nullcontext)
    monkeypatch.setattr(helper, "_ensure_layout", lambda: None)
    monkeypatch.setattr(
        helper,
        "_read_json",
        lambda path: current if path == helper.CURRENT_RECORD else None,
    )
    monkeypatch.setattr(helper, "_write_json", write_json)
    monkeypatch.setattr(helper, "_image_schema", lambda _: 13)
    monkeypatch.setattr(helper, "_assert_loaded_image", lambda _: None)
    monkeypatch.setattr(helper, "_assert_record_compose_digest", lambda _: tmp_path / "compose")
    monkeypatch.setattr(helper, "_compose_digest", lambda: current["compose_digest"])
    monkeypatch.setattr(helper, "_runtime_file", lambda _image, mode: modes.append(mode))
    monkeypatch.setattr(helper, "_app_container_identity", lambda _snapshot: ("1" * 64, 123))
    monkeypatch.setattr(helper, "_request_in_place_assistant_kill", lambda _container: None)
    monkeypatch.setattr(helper, "_compose_up", lambda *args, **kwargs: "")
    # The recreated process remains enabled despite the fixed disabled runtime environment.
    monkeypatch.setattr(
        helper,
        "_health_check",
        lambda: {
            "status": "ready",
            "schema_version": 13,
            "assistant": {"enabled": True, "status": "ready"},
        },
    )
    monkeypatch.setattr(helper, "_stop_app", lambda path=None: stopped.append(path))
    monkeypatch.setattr(helper, "_audit", lambda *args, **kwargs: None)

    with pytest.raises(helper.HostError, match="assistant_disable_unverified"):
        helper._set_assistant_rollout(
            "disabled",
            revision=revision,
            archive_sha256=archive_sha256,
            image_id=image_id,
        )

    failed = next(value for path, value in writes if path == helper.FAILED_RECORD)
    assert modes == ["disabled", "disabled"]
    assert stopped == [tmp_path / "compose"]
    assert current["assistant_rollout_mode"] == "disabled"
    assert failed["requested_mode"] == "disabled"
    assert failed["assistant_disabled_verified"] is False
    assert failed["app_stopped"] is True
    assert failed["containment_status"] == "app_stopped"


def test_in_place_disable_rejects_container_replacement_and_stops_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    revision = "a" * 40
    archive_sha256 = "b" * 64
    image_id = "sha256:" + "c" * 64
    current = {
        "revision": revision,
        "transport": helper.GITHUB_RELEASE_TRANSPORT,
        "image_ref": helper._local_image_ref(revision),
        "image_digest": archive_sha256,
        "archive_sha256": archive_sha256,
        "image_id": image_id,
        "platform": "linux/amd64",
        "archive_size": 1234,
        "schema_version": 13,
        "compose_digest": "d" * 64,
        "assistant_rollout_mode": "invited",
    }
    stopped: list[Path | None] = []
    identities = iter((("1" * 64, 123), ("2" * 64, 456)))

    monkeypatch.setattr(helper, "_exclusive_lock", nullcontext)
    monkeypatch.setattr(helper, "_ensure_layout", lambda: None)
    monkeypatch.setattr(
        helper,
        "_read_json",
        lambda path: current if path == helper.CURRENT_RECORD else None,
    )
    monkeypatch.setattr(helper, "_write_json", lambda path, value, **_: current.update(value))
    monkeypatch.setattr(helper, "_image_schema", lambda _: 13)
    monkeypatch.setattr(helper, "_assert_loaded_image", lambda _: None)
    monkeypatch.setattr(helper, "_assert_record_compose_digest", lambda _: tmp_path / "compose")
    monkeypatch.setattr(helper, "_compose_digest", lambda: current["compose_digest"])
    monkeypatch.setattr(helper, "_runtime_file", lambda *_: None)
    monkeypatch.setattr(helper, "_app_container_identity", lambda _snapshot: next(identities))
    monkeypatch.setattr(helper, "_request_in_place_assistant_kill", lambda _container: None)
    monkeypatch.setattr(
        helper,
        "_health_check",
        lambda: {
            "status": "ready",
            "schema_version": 13,
            "assistant": {"enabled": False, "status": "disabled"},
        },
    )
    monkeypatch.setattr(helper, "_stop_app", lambda path=None: stopped.append(path))
    monkeypatch.setattr(helper, "_audit", lambda *args, **kwargs: None)

    with pytest.raises(helper.HostError, match="assistant_app_identity_changed"):
        helper._set_assistant_rollout(
            "disabled",
            revision=revision,
            archive_sha256=archive_sha256,
            image_id=image_id,
        )
    assert stopped == [tmp_path / "compose"]
    assert current["assistant_rollout_mode"] == "disabled"


def test_disabled_readiness_requires_explicit_worker_disabled_projection() -> None:
    helper = _helper()
    helper._require_assistant_ready(
        {"assistant": {"enabled": False, "status": "disabled"}}, "disabled"
    )
    with pytest.raises(helper.HostError, match="assistant_disable_unverified"):
        helper._require_assistant_ready({"status": "ready"}, "disabled")
    with pytest.raises(helper.HostError, match="assistant_disable_unverified"):
        helper._require_assistant_ready(
            {"assistant": {"enabled": False, "status": "unavailable"}}, "disabled"
        )


def test_release_asset_location_is_derived_from_revision() -> None:
    helper = _helper()
    revision = "a" * 40
    assert helper._release_archive_url(revision) == (
        "https://github.com/eddiesoz/stock_probs/releases/download/"
        f"signal-ledger-{revision}/signal-ledger-image-{revision}.tar.gz"
    )
    with pytest.raises(helper.HostError, match="revision_invalid"):
        helper._release_archive_url("main")


def test_release_archive_hashes_before_loading_and_records_image_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    revision = "a" * 40
    image_id = "sha256:" + "c" * 64
    archive = tmp_path / "image.tar.gz"
    archive.write_bytes(b"verified archive bytes")
    archive_digest = helper._archive_sha256(archive)[0]
    commands: list[list[str]] = []

    monkeypatch.setattr(helper, "_download_release_archive", lambda _: archive)

    def fake_run(command: list[str], **_: object) -> SimpleNamespace:
        commands.append(command)
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(helper, "_run", fake_run)
    monkeypatch.setattr(helper, "_image_id", lambda _: image_id)
    monkeypatch.setattr(helper, "_image_revision", lambda _: revision)
    monkeypatch.setattr(helper, "_image_platform", lambda _: "linux/amd64")
    monkeypatch.setattr(helper, "_image_schema", lambda _: 8)

    result = helper._load_release_archive(revision, archive_digest, image_id)

    assert result == (
        helper._local_image_ref(revision),
        archive_digest,
        image_id,
        "linux/amd64",
        8,
        len(b"verified archive bytes"),
    )
    assert commands == [
        ["docker", "load", "--input", str(archive)],
        ["docker", "tag", image_id, helper._local_image_ref(revision)],
    ]
    assert not archive.exists()


def test_release_archive_digest_mismatch_never_loads_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    archive = tmp_path / "image.tar.gz"
    archive.write_bytes(b"tampered archive")
    commands: list[list[str]] = []
    monkeypatch.setattr(helper, "_download_release_archive", lambda _: archive)
    monkeypatch.setattr(
        helper,
        "_run",
        lambda command, **_: commands.append(command) or SimpleNamespace(stdout=""),
    )
    with pytest.raises(helper.HostError, match="archive_digest_mismatch"):
        helper._load_release_archive("a" * 40, "b" * 64, "sha256:" + "c" * 64)
    assert commands == []
    assert not archive.exists()


def test_release_download_is_fixed_https_bounded_and_timed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    commands: list[list[str]] = []
    monkeypatch.setattr(helper, "RELEASE_ROOT", tmp_path)
    monkeypatch.setattr(helper.secrets, "token_hex", lambda _: "fixed")

    def fake_run(command: list[str], **_: object) -> SimpleNamespace:
        commands.append(command)
        Path(command[command.index("--output") + 1]).write_bytes(b"archive")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(helper, "_run", fake_run)
    revision = "a" * 40
    archive = helper._download_release_archive(revision)
    try:
        assert archive.read_bytes() == b"archive"
        assert commands == [
            [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--location",
                "--proto",
                "=https",
                "--proto-redir",
                "=https",
                "--max-redirs",
                "3",
                "--connect-timeout",
                "10",
                "--max-time",
                "600",
                "--max-filesize",
                str(helper.MAX_RELEASE_ARCHIVE_BYTES),
                "--output",
                str(archive),
                helper._release_archive_url(revision),
            ]
        ]
    finally:
        archive.unlink(missing_ok=True)


def test_release_plan_record_requires_image_id_platform_and_archive_size() -> None:
    helper = _helper()
    revision = "a" * 40
    archive_digest = "b" * 64
    record = {
        "revision": revision,
        "transport": helper.GITHUB_RELEASE_TRANSPORT,
        "image_ref": helper._local_image_ref(revision),
        "image_digest": archive_digest,
        "archive_sha256": archive_digest,
        "image_id": "sha256:" + "c" * 64,
        "platform": "linux/amd64",
        "archive_size": 1234,
    }
    helper._assert_image_record(record)
    record["image_ref"] = "signal-ledger:latest"
    with pytest.raises(helper.HostError, match="release_invalid"):
        helper._assert_image_record(record)


def test_release_start_disables_compose_pull_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _helper()
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        helper,
        "_compose",
        lambda *arguments, **_: calls.append(arguments) or "",
    )
    helper._compose_up(
        {"transport": helper.GITHUB_RELEASE_TRANSPORT},
    )
    assert calls == [("up", "--detach", "--no-build", "--pull", "never", "app")]


def test_release_rollback_request_requires_full_image_id() -> None:
    helper = _helper()
    operation, payload = helper._parse_request(
        json.dumps(
            {
                "operation": "rollback",
                "payload": {
                    "revision": "a" * 40,
                    "image_id": "sha256:" + "c" * 64,
                },
            }
        ).encode()
    )
    assert operation == "rollback"
    assert payload["image_id"] == "sha256:" + "c" * 64


def test_schema_probe_runs_pulled_image_with_bounded_permissions(monkeypatch) -> None:
    helper = _helper()
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, timeout: int) -> SimpleNamespace:
        assert timeout == 60
        commands.append(command)
        return SimpleNamespace(stdout="8\n")

    monkeypatch.setattr(helper, "_run", fake_run)
    image_ref = helper._image_ref("a" * 40, "b" * 64)
    assert helper._image_schema(image_ref) == 8
    command = commands[0]
    assert command[:2] == ["docker", "run"]
    assert command[-4:] == ["python", image_ref, "-c", command[-1]]
    for flag, value in (
        ("--pull", "never"),
        ("--network", "none"),
        ("--cap-drop", "ALL"),
        ("--security-opt", "no-new-privileges"),
        ("--pids-limit", "64"),
        ("--memory", "256m"),
        ("--cpus", "0.5"),
        ("--user", "10001:10001"),
    ):
        assert command[command.index(flag) + 1] == value
    assert "--read-only" in command
    assert "--tmpfs" in command


def test_run_applies_deadline_after_child_closes_both_pipes() -> None:
    """A child that closes output streams must not bypass the host command deadline."""

    helper = _helper()
    started = time.monotonic()
    with pytest.raises(helper.HostError, match="host_command_timeout"):
        helper._run(
            [
                sys.executable,
                "-c",
                "import os, time; os.close(1); os.close(2); time.sleep(30)",
            ],
            timeout=0.05,
        )
    assert time.monotonic() - started < 2.0


def test_compose_and_source_paths_are_fixed_and_loopback(tmp_path: Path) -> None:
    helper = _helper()
    compose = (ROOT / "compose.production.yaml").read_text()
    optional_invite_settings = (
        "STOCK_PROBS_INVITE_SMTP_HOST",
        "STOCK_PROBS_INVITE_SMTP_PORT",
        "STOCK_PROBS_INVITE_SMTP_USERNAME",
        "STOCK_PROBS_INVITE_SMTP_PASSWORD",
        "STOCK_PROBS_INVITE_SMTP_SECURITY",
        "STOCK_PROBS_INVITE_EMAIL_FROM",
    )
    assert '"127.0.0.1:8000:8000"' in compose
    assert "STOCK_PROBS_HOST: 127.0.0.1" in compose
    assert 'STOCK_PROBS_TRUSTED_PROXY_HOSTS: "127.0.0.1,::1,localhost,172.30.219.1"' in compose
    assert "signal-ledger-data:/data" in compose
    assert "name: signal-ledger-production-ingress" in compose
    assert "subnet: 172.30.219.0/28" in compose
    assert "gateway: 172.30.219.1" in compose
    assert "STOCK_PROBS_AUTH_MODE: github" in compose
    assert "STOCK_PROBS_AUTH_SESSION_SECRET" in compose
    assert "STOCK_PROBS_GITHUB_CLIENT_SECRET" in compose
    for setting in optional_invite_settings:
        assert f'{setting}: "${{{setting}:-}}"' in compose

    compose_arguments = helper._compose_prefix()
    app_env_option = compose_arguments.index("--env-file")
    assert compose_arguments[app_env_option + 1] == str(helper.APP_ENV_FILE)
    assert "cap_drop:" in compose and "no-new-privileges:true" in compose
    assert helper.REPOSITORY_URL == "https://github.com/eddiesoz/stock_probs.git"
    assert helper.MAIN_BRANCH == "main"
    assert Path("/opt/signal-ledger/compose.production.yaml") == helper.COMPOSE_FILE
    assert Path("/var/lib/signal-ledger") == helper.STATE_ROOT
    assert tmp_path != helper.STATE_ROOT


def test_plan_requires_installed_compose_to_match_reviewed_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    source = tmp_path / "source"
    source.mkdir()
    installed = tmp_path / "installed-compose.yaml"
    (source / "compose.production.yaml").write_text("services: {app: {}}\n")
    installed.write_text("services: {app: {}}\n")
    monkeypatch.setattr(helper, "SOURCE_ROOT", source)
    monkeypatch.setattr(helper, "COMPOSE_FILE", installed)
    helper._assert_compose_revision()

    installed.write_text("services: {app: {ports: [8080]}}\n")
    with pytest.raises(helper.HostError, match="compose_revision_mismatch"):
        helper._assert_compose_revision()

    installed.unlink()
    installed.symlink_to(source / "compose.production.yaml")
    with pytest.raises(helper.HostError, match="compose_revision_mismatch"):
        helper._assert_compose_revision()


def test_deploy_rechecks_compose_after_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _helper()
    revision = "a" * 40
    digest = "b" * 64
    compose_digest = "d" * 64
    plan_id = "c" * 32

    monkeypatch.setattr(helper, "_exclusive_lock", nullcontext)
    monkeypatch.setattr(helper, "_ensure_layout", lambda: None)
    monkeypatch.setattr(
        helper,
        "_load_plan",
        lambda _: {
            "revision": revision,
            "image_digest": digest,
            "compose_digest": compose_digest,
        },
    )
    monkeypatch.setattr(
        helper,
        "_compose_digest",
        lambda: "e" * 64,
    )
    monkeypatch.setattr(
        helper,
        "_apply_release",
        lambda _: pytest.fail("mismatched Compose must not be deployed"),
    )
    with pytest.raises(helper.HostError, match="compose_revision_mismatch"):
        helper._deploy(plan_id, revision, digest)


def test_plan_requires_compose_digest_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    plan_id = "c" * 32
    revision = "a" * 40
    plan_path = tmp_path / f"{plan_id}.json"
    monkeypatch.setattr(helper, "PLAN_ROOT", tmp_path)
    plan = {
        "plan_id": plan_id,
        "revision": revision,
        "image_digest": "b" * 64,
        "image_ref": helper._image_ref(revision, "b" * 64),
        "schema_version": 8,
    }
    helper._write_json(plan_path, plan)
    with pytest.raises(helper.HostError, match="plan_invalid"):
        helper._load_plan(plan_id)

    plan["compose_digest"] = "d" * 64
    helper._write_json(plan_path, plan)
    assert helper._load_plan(plan_id)["compose_digest"] == "d" * 64


def test_published_image_is_pulled_and_bound_to_registry_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _helper()
    revision = "a" * 40
    digest = "b" * 64
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> object:
        commands.append(command)
        return type("Result", (), {"stdout": ""})()

    monkeypatch.setattr(helper, "_run", fake_run)
    monkeypatch.setattr(helper, "_image_digest", lambda _: digest)
    monkeypatch.setattr(helper, "_image_revision", lambda _: revision)
    monkeypatch.setattr(helper, "_image_schema", lambda _: 8)

    image_ref, image_digest, schema_version = helper._pull_image(revision, digest)

    assert commands == [["docker", "pull", "--quiet", helper._image_ref(revision, digest)]]
    assert image_ref == helper._image_ref(revision, digest)
    assert image_digest == digest
    assert schema_version == 8


def test_published_image_digest_mismatch_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _helper()
    revision = "a" * 40
    expected_digest = "b" * 64
    monkeypatch.setattr(
        helper,
        "_run",
        lambda *args, **kwargs: type("Result", (), {"stdout": ""})(),
    )
    monkeypatch.setattr(helper, "_image_digest", lambda _: "c" * 64)
    with pytest.raises(helper.HostError, match="image_digest_mismatch"):
        helper._pull_image(revision, expected_digest)


def test_plan_rejects_mutable_registry_tag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _helper()
    plan_id = "c" * 32
    revision = "a" * 40
    plan = {
        "plan_id": plan_id,
        "revision": revision,
        "image_ref": f"ghcr.io/jtmb/signal-ledger:{revision}",
        "image_digest": "b" * 64,
        "schema_version": 8,
        "compose_digest": "d" * 64,
    }
    monkeypatch.setattr(helper, "PLAN_ROOT", tmp_path)
    helper._write_json(tmp_path / f"{plan_id}.json", plan)
    with pytest.raises(helper.HostError, match="plan_invalid"):
        helper._load_plan(plan_id)


def test_write_json_is_atomic_and_private(tmp_path: Path) -> None:
    helper = _helper()
    target = tmp_path / "state" / "record.json"
    helper._write_json(target, {"status": "ok", "revision": "a" * 40})
    assert json.loads(target.read_text()) == {"revision": "a" * 40, "status": "ok"}
    assert stat.S_IMODE(target.stat().st_mode) & 0o077 == 0
    assert not list(target.parent.glob("*.tmp"))


def test_setup_script_uses_forced_command_and_no_public_app_port() -> None:
    script = (ROOT / "scripts/setup-production-host.sh").read_text()
    assert "SIGNAL_LEDGER_DEPLOY_PUBLIC_KEY_FILE" in script
    assert "ssh-keygen -lf" in script
    assert 'install -o "$DEPLOY_USER" -g "$DEPLOY_GROUP" -m 0600' in script
    assert 'restrict,command="$WRAPPER"' in script
    assert "publish_restricted_authorized_key" in script
    assert script.index("sshd -t") < script.rindex("publish_restricted_authorized_key")
    assert '"$DEPLOY_PUBLIC_KEY_FILE" "$AUTHORIZED_KEYS"' not in script
    assert "AuthorizedKeysFile $AUTHORIZED_KEYS" in script
    assert "AuthenticationMethods publickey" in script
    assert "NOPASSWD:" in script
    assert "signal-ledger-deploy-helper" in script
    assert "cloudflared tunnel" in script
    assert "/usr/bin/cloudflared tunnel --no-autoupdate run --help" in script
    assert "cloudflared tunnel run --no-autoupdate" not in script
    unit_path = ROOT / "infra" / "cloudflare" / "signal-ledger-cloudflared.service"
    unit = unit_path.read_text()
    assert (
        'SYSTEMD_UNIT_SOURCE="$ROOT/infra/cloudflare/signal-ledger-cloudflared.service"' in script
    )
    assert 'install -o root -g root -m 0644 "$SYSTEMD_UNIT_SOURCE" "$SYSTEMD_UNIT"' in script
    assert (
        "ExecStart=/usr/bin/cloudflared tunnel --no-autoupdate run "
        "--token-file /etc/cloudflared/tunnel.token"
    ) in unit
    assert "cloudflared tunnel run --no-autoupdate" not in unit
    assert "systemctl daemon-reload" in script
    assert "systemctl disable --now signal-ledger-cloudflared.service" in script
    assert "--shell /bin/sh" in script
    assert "systemctl reload ssh" in script
    assert "127.0.0.1:8000:8000" in (ROOT / "compose.production.yaml").read_text()
    assert "docker.sock" not in script


def test_local_release_publisher_uses_revision_bound_archive_and_digest() -> None:
    script = (ROOT / "scripts/publish-production-image.sh").read_text()
    verifier = (ROOT / "scripts/verify-release-archive.py").read_text()
    assert 'PUBLISH_MODE="${SIGNAL_LEDGER_IMAGE_PUBLISH_MODE:-release}"' in script
    assert 'RELEASE_REPOSITORY="eddiesoz/stock_probs"' in script
    assert 'docker save "$IMAGE_TAG" | gzip -n -9' in script
    assert 'sha256sum "$ARCHIVE_PATH"' in script
    assert (
        'gh release create "$RELEASE_TAG" "$ARCHIVE_PATH" '
        '"$RECOVERY_ARCHIVE_PATH" "$PAIR_MANIFEST_PATH"' in script
    )
    assert 'gh release download "$RELEASE_TAG"' in script
    assert 'docker load --input "$DOWNLOADED_ARCHIVE"' in script
    assert "DOWNLOADED_IMAGE_ID" in script
    assert '--target "$REVISION"' in script
    assert '--candidate-image-id "$IMAGE_ID"' in script
    assert '--release-artifact-directory "$PAIR_ROOT"' in script
    assert "verify-release-archive.py" in script
    assert 'tarfile.open(path, mode="r:gz")' in verifier
    assert 'tarfile.open(fileobj=layer_stream, mode="r|*")' in verifier
    assert "SIGNAL_LEDGER_IMAGE_PUBLISH_MODE must be release, prebuilt-release, or ghcr." in script


def test_local_release_publisher_allows_public_ca_bundle_but_scans_private_keys() -> None:
    script = (ROOT / "scripts/publish-production-image.sh").read_text()
    assert ".*\\.pem$" not in script
    assert "id_(rsa|dsa|ecdsa|ed25519)" in script
    assert "PRIVATE KEY" in script


def test_local_release_publisher_rejects_database_backup_and_sqlite_sidecar_paths() -> None:
    script = (ROOT / "scripts/publish-production-image.sh").read_text()
    pattern_match = re.search(r"DATA_PATH_PATTERN='([^']+)'", script)
    assert pattern_match is not None
    data_path_pattern = re.compile(pattern_match.group(1), re.IGNORECASE)

    for path in (
        "var/lib/signal-ledger/stock_probs.sqlite3",
        "var/lib/signal-ledger/stock_probs.sqlite3-wal",
        "var/lib/signal-ledger/stock_probs.sqlite3-shm",
        "var/lib/signal-ledger/stock_probs.sqlite3-journal",
        "var/lib/signal-ledger/legacy.spbackup",
        "tmp/cache.db/metadata.json",
    ):
        assert data_path_pattern.search(path), path

    for path in (
        "usr/lib/python3.12/sqlite3/__init__.py",
        "usr/share/ca-certificates/mozilla/ISRG_Root_X1.crt",
        "app/src/stock_probs/static/dashboard.js",
    ):
        assert not data_path_pattern.search(path), path

    assert "data_path_pattern = re.compile(data_path_expression, re.IGNORECASE)" in script
    assert "13) printf 'The image archive contains a database or backup path." in script


def test_existing_release_is_backed_up_with_old_image_before_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _helper()
    old_revision = "a" * 40
    new_revision = "b" * 40
    old_digest = "1" * 64
    new_digest = "2" * 64
    old_image = helper._image_ref(old_revision, old_digest)
    new_image = helper._image_ref(new_revision, new_digest)
    current = {
        "revision": old_revision,
        "image_ref": old_image,
        "image_digest": old_digest,
        "schema_version": 7,
    }
    target = {
        "revision": new_revision,
        "image_ref": new_image,
        "image_digest": new_digest,
        "schema_version": 8,
    }
    events: list[tuple[str, object]] = []
    old_compose = Path("/verified/old-compose.yaml")
    health_results = iter(
        ({"status": "ready", "schema_version": 7}, {"status": "ready", "schema_version": 8})
    )

    monkeypatch.setattr(
        helper,
        "_read_json",
        lambda path: current if path == helper.CURRENT_RECORD else None,
    )
    monkeypatch.setattr(
        helper,
        "_image_digest",
        lambda image: old_digest if image == old_image else new_digest,
    )
    monkeypatch.setattr(helper, "_image_schema", lambda image: 7 if image == old_image else 8)
    monkeypatch.setattr(helper, "_assert_record_compose_digest", lambda _: old_compose)
    monkeypatch.setattr(helper, "_health_check", lambda: next(health_results))
    monkeypatch.setattr(
        helper,
        "_runtime_file",
        lambda image, mode="disabled": events.append(("runtime", (image, mode))),
    )
    monkeypatch.setattr(
        helper,
        "_verified_backup",
        lambda image, revision, **kwargs: events.append(("backup", (image, kwargs)))
        or {
            "trigger": "pre_deploy",
            "name": "pre-deploy-safe.spbackup",
            "sha256": "3" * 64,
            "schema_version": 7,
            "verified": True,
        },
    )
    monkeypatch.setattr(
        helper,
        "_run_migrations",
        lambda image, revision, **kwargs: events.append(("migrate", kwargs))
        or {
            "trigger": "pre_migration",
            "name": "pre-migration-safe.spbackup",
            "sha256": "4" * 64,
            "schema_version": 7,
            "verified": True,
        },
    )
    monkeypatch.setattr(
        helper,
        "_database_schema",
        lambda image, **kwargs: events.append(("schema", (image, kwargs)))
        or (7 if image == old_image else 8),
    )
    monkeypatch.setattr(
        helper,
        "_compose",
        lambda *arguments, **_: events.append(("compose", str(arguments))) or "",
    )
    monkeypatch.setattr(
        helper,
        "_compose_up",
        lambda record, **kwargs: events.append(("up", kwargs)) or "",
    )
    monkeypatch.setattr(helper, "_write_json", lambda *arguments, **_: None)
    monkeypatch.setattr(helper, "_audit", lambda *arguments, **_: None)

    result = helper._apply_release(target)

    assert result["status"] == "ok"
    stop_index = next(
        index for index, event in enumerate(events) if event[0] == "compose" and "stop" in event[1]
    )
    backup_index = next(index for index, event in enumerate(events) if event[0] == "backup")
    migrate_index = next(index for index, event in enumerate(events) if event[0] == "migrate")
    start_index = next(index for index, event in enumerate(events) if event[0] == "up")
    assert stop_index < backup_index < migrate_index < start_index
    assert events[backup_index][1][0] == old_image
    assert events[backup_index][1][1]["compose_file"] == old_compose


def test_apply_release_rejects_drifted_active_image_before_schema_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _helper()
    old_revision = "a" * 40
    new_revision = "b" * 40
    old_archive = "1" * 64
    new_archive = "2" * 64
    old_image_id = "sha256:" + "3" * 64
    new_image_id = "sha256:" + "4" * 64
    old_image = helper._local_image_ref(old_revision)
    new_image = helper._local_image_ref(new_revision)
    current = {
        "revision": old_revision,
        "transport": helper.GITHUB_RELEASE_TRANSPORT,
        "image_ref": old_image,
        "image_digest": old_archive,
        "archive_sha256": old_archive,
        "image_id": old_image_id,
        "platform": "linux/amd64",
        "archive_size": 1234,
        "schema_version": 8,
    }
    target = {
        "revision": new_revision,
        "transport": helper.GITHUB_RELEASE_TRANSPORT,
        "image_ref": new_image,
        "image_digest": new_archive,
        "archive_sha256": new_archive,
        "image_id": new_image_id,
        "platform": "linux/amd64",
        "archive_size": 1234,
        "schema_version": 8,
    }
    schema_calls: list[str] = []
    health_calls: list[object] = []

    monkeypatch.setattr(
        helper,
        "_read_json",
        lambda path: current if path == helper.CURRENT_RECORD else None,
    )
    monkeypatch.setattr(
        helper,
        "_image_id",
        lambda image: new_image_id if image == new_image else "sha256:" + "5" * 64,
    )
    monkeypatch.setattr(helper, "_image_revision", lambda image: target["revision"])
    monkeypatch.setattr(helper, "_image_platform", lambda _: "linux/amd64")
    monkeypatch.setattr(helper, "_health_check", lambda: health_calls.append(True))
    monkeypatch.setattr(
        helper,
        "_image_schema",
        lambda image: schema_calls.append(image) or 8,
    )

    with pytest.raises(helper.HostError, match="image_id_mismatch"):
        helper._apply_release(target)

    assert schema_calls == []
    assert health_calls == []


def test_migration_success_readiness_failure_stops_candidate_and_records_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _helper()
    old_revision = "a" * 40
    new_revision = "b" * 40
    old_digest = "1" * 64
    new_digest = "2" * 64
    old_image = helper._image_ref(old_revision, old_digest)
    new_image = helper._image_ref(new_revision, new_digest)
    current = {
        "revision": old_revision,
        "image_ref": old_image,
        "image_digest": old_digest,
        "schema_version": 12,
    }
    target = {
        "revision": new_revision,
        "image_ref": new_image,
        "image_digest": new_digest,
        "schema_version": 13,
        "pair_manifest_sha256": "5" * 64,
        "recovery_image_ref": helper._local_recovery_image_ref(new_revision),
        "recovery_image_id": "sha256:" + "6" * 64,
        "recovery_archive_sha256": "7" * 64,
        "recovery_archive_size": 2048,
        "recovery_platform": "linux/amd64",
        "recovery_schema_version": 13,
        "recovery_base_revision": helper.PAIR_BASE_REVISION,
        "recovery_overlay_sha256": "8" * 64,
    }
    events: list[tuple[str, object]] = []
    writes: list[tuple[Path, dict[str, object]]] = []
    health_calls = 0
    schema_results = iter((12, 13, 13))
    old_compose = Path("/verified/old-compose.yaml")

    def health_check() -> dict[str, object]:
        nonlocal health_calls
        health_calls += 1
        if health_calls == 1:
            return {"status": "ready", "schema_version": 12}
        raise helper.HostError("readiness_failed")

    monkeypatch.setattr(
        helper,
        "_read_json",
        lambda path: current if path == helper.CURRENT_RECORD else None,
    )
    monkeypatch.setattr(
        helper,
        "_image_digest",
        lambda image: old_digest if image == old_image else new_digest,
    )
    monkeypatch.setattr(helper, "_image_schema", lambda image: 12 if image == old_image else 13)
    monkeypatch.setattr(helper, "_assert_loaded_recovery_image", lambda _: None)
    monkeypatch.setattr(helper, "_health_check", health_check)
    monkeypatch.setattr(helper, "_assert_record_compose_digest", lambda _: old_compose)
    monkeypatch.setattr(
        helper,
        "_activate_same_schema_recovery",
        lambda record, **kwargs: events.append(("forward_recovery", kwargs)) or False,
    )
    monkeypatch.setattr(
        helper,
        "_runtime_file",
        lambda image, mode="disabled": events.append(("runtime", (image, mode))),
    )
    monkeypatch.setattr(
        helper,
        "_verified_backup",
        lambda image, revision, **kwargs: events.append(("backup", (image, kwargs)))
        or {
            "trigger": "pre_deploy",
            "name": "pre-deploy-safe.spbackup",
            "sha256": "3" * 64,
            "schema_version": 12,
            "verified": True,
        },
    )
    monkeypatch.setattr(
        helper,
        "_run_migrations",
        lambda image, revision, **kwargs: {
            "trigger": "pre_migration",
            "name": "pre-migration-safe.spbackup",
            "sha256": "4" * 64,
            "schema_version": 12,
            "verified": True,
        },
    )
    monkeypatch.setattr(
        helper,
        "_compose",
        lambda *arguments, **_: events.append(("compose", arguments)) or "",
    )
    monkeypatch.setattr(
        helper,
        "_database_schema",
        lambda image, **kwargs: events.append(("schema", image)) or next(schema_results),
    )
    monkeypatch.setattr(
        helper,
        "_write_json",
        lambda path, value, **_: writes.append((path, value)),
    )
    monkeypatch.setattr(helper, "_audit", lambda *arguments, **_: None)

    with pytest.raises(helper.HostError, match="readiness_failed"):
        helper._apply_release(target)

    stop_events = [
        index
        for index, event in enumerate(events)
        if event[0] == "compose" and event[1] == ("stop", "app")
    ]
    schema_indices = [index for index, event in enumerate(events) if event[0] == "schema"]
    assert len(stop_events) == 2
    assert stop_events[-1] < schema_indices[-1]
    failed_writes = [value for path, value in writes if path == helper.FAILED_RECORD]
    assert len(failed_writes) == 1
    failed = failed_writes[0]
    assert failed["status"] == "failed_migrated"
    assert failed["actual_schema_version"] == 13
    assert failed["failure_code"] == "readiness_failed"
    assert failed["rollback_attempted"] is False
    assert failed["pre_deploy_backup"]["schema_version"] == 12
    assert failed["pre_migration_backup"]["trigger"] == "pre_migration"
    assert failed["pre_migration_backup"]["schema_version"] == 12
    assert failed["pre_migration_backup"]["name"] == "pre-migration-safe.spbackup"


def test_schema13_forward_recovery_requires_exact_verified_schema12_boundary() -> None:
    helper = _helper()
    old_revision = "a" * 40
    current = {"revision": old_revision, "schema_version": 12}
    target = {"revision": "b" * 40, "schema_version": 13}
    pre_deploy = {
        "trigger": "pre_deploy",
        "name": "pre-deploy-aaaaaaaaaaaaaaaa-1234abcd.spbackup",
        "sha256": "c" * 64,
        "schema_version": 12,
        "verified": True,
    }
    failed = {
        "status": "failed_migrated",
        "revision": target["revision"],
        "schema_version": 13,
        "actual_schema_version": 13,
        "previous_revision": old_revision,
        "previous_schema_version": 12,
        "pre_deploy_backup": pre_deploy,
    }
    assert helper._forward_recovery_backup(failed, current, target) == pre_deploy
    assert (
        helper._forward_recovery_backup({**failed, "actual_schema_version": 12}, current, target)
        is None
    )
    assert (
        helper._forward_recovery_backup(
            {**failed, "pre_deploy_backup": {**pre_deploy, "schema_version": 13}},
            current,
            target,
        )
        is None
    )
    assert (
        helper._forward_recovery_backup({**failed, "previous_revision": "d" * 40}, current, target)
        is None
    )


def test_schema13_forward_recovery_starts_app_only_code_without_restoring_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _helper()
    revision = "a" * 40
    recovery_id = "sha256:" + "b" * 64
    recovery_archive_sha = "c" * 64
    recovery_ref = helper._local_recovery_image_ref(revision)
    snapshot = Path("/verified/schema13-compose.yaml")
    record = {
        "revision": revision,
        "schema_version": 13,
        "image_ref": helper._local_image_ref(revision),
        "image_digest": "d" * 64,
        "image_id": "sha256:" + "e" * 64,
        "archive_sha256": "d" * 64,
        "archive_size": 1024,
        "platform": "linux/amd64",
        "release_role": "candidate",
        "pair_manifest_sha256": "f" * 64,
        "recovery_image_ref": recovery_ref,
        "recovery_image_id": recovery_id,
        "recovery_archive_sha256": recovery_archive_sha,
        "recovery_archive_size": 2048,
        "recovery_platform": "linux/amd64",
        "recovery_schema_version": 13,
        "recovery_base_revision": helper.PAIR_BASE_REVISION,
        "recovery_overlay_sha256": "1" * 64,
    }
    events: list[tuple[str, object]] = []
    monkeypatch.setattr(
        helper, "_assert_loaded_recovery_image", lambda _: events.append(("verify", True))
    )
    monkeypatch.setattr(
        helper, "_assert_image_record", lambda row: events.append(("record", row["release_role"]))
    )
    monkeypatch.setattr(
        helper,
        "_runtime_file",
        lambda image, mode: events.append(("runtime", (image, mode))),
    )
    monkeypatch.setattr(
        helper,
        "_compose_up",
        lambda row, **kwargs: events.append(("up", (row["image_ref"], kwargs["compose_file"]))),
    )
    monkeypatch.setattr(
        helper,
        "_health_check",
        lambda: {
            "status": "ready",
            "schema_version": 13,
            "assistant": {"enabled": False, "status": "disabled"},
        },
    )
    monkeypatch.setattr(
        helper,
        "_write_json",
        lambda path, value: events.append(("persist", (path, value["release_role"]))),
    )
    monkeypatch.setattr(
        helper,
        "_stop_app",
        lambda *_args, **_kwargs: events.append(("stop", True)),
    )

    assert helper._activate_same_schema_recovery(record, compose_snapshot=snapshot) is True
    assert ("runtime", (recovery_ref, "disabled")) in events
    assert ("up", (recovery_ref, snapshot)) in events
    assert ("persist", (helper.CURRENT_RECORD, "recovery")) in events
    assert not any("restore" in str(event).casefold() for event in events)


def test_rollback_rejects_actual_schema_before_starting_old_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    revision = "a" * 40
    image_ref = helper._image_ref(revision, "1" * 64)
    release = {
        "revision": revision,
        "image_ref": image_ref,
        "image_digest": "1" * 64,
        "schema_version": 7,
        "compose_digest": "c" * 64,
    }
    compose_calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(helper, "RELEASE_ROOT", tmp_path)
    monkeypatch.setattr(helper, "_exclusive_lock", nullcontext)
    monkeypatch.setattr(helper, "_ensure_layout", lambda: None)
    monkeypatch.setattr(helper, "_read_json", lambda _: release)
    monkeypatch.setattr(helper, "_assert_record_compose_digest", lambda _: tmp_path / "compose")
    monkeypatch.setattr(helper, "_database_schema", lambda _: 8)
    monkeypatch.setattr(helper, "_compose_digest", lambda: release["compose_digest"])
    monkeypatch.setattr(helper, "_image_digest", lambda _: release["image_digest"])
    monkeypatch.setattr(
        helper,
        "_compose",
        lambda *arguments, **_: compose_calls.append(arguments) or "",
    )

    with pytest.raises(helper.HostError, match="rollback_schema_incompatible"):
        helper._rollback(revision)

    assert compose_calls == []


def test_readiness_schema_mismatch_stops_candidate_and_records_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _helper()
    revision = "b" * 40
    target = {
        "revision": revision,
        "image_digest": "2" * 64,
        "image_ref": helper._image_ref(revision, "2" * 64),
        "schema_version": 8,
    }
    events: list[tuple[str, object]] = []
    writes: list[tuple[Path, dict[str, object]]] = []

    monkeypatch.setattr(helper, "_read_json", lambda _: None)
    monkeypatch.setattr(helper, "_image_digest", lambda _: target["image_digest"])
    monkeypatch.setattr(helper, "_database_present", lambda _: False)
    monkeypatch.setattr(
        helper,
        "_runtime_file",
        lambda image, mode="disabled": events.append(("runtime", (image, mode))),
    )
    monkeypatch.setattr(helper, "_run_migrations", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        helper,
        "_compose",
        lambda *arguments, **_: events.append(("compose", arguments)) or "",
    )
    monkeypatch.setattr(
        helper,
        "_health_check",
        lambda: {"status": "ready", "schema_version": 7},
    )
    monkeypatch.setattr(helper, "_database_schema", lambda _: 8)
    monkeypatch.setattr(
        helper,
        "_write_json",
        lambda path, value, **_: writes.append((path, value)),
    )
    monkeypatch.setattr(helper, "_audit", lambda *arguments, **_: None)

    with pytest.raises(helper.HostError, match="readiness_schema_mismatch"):
        helper._apply_release(target)

    assert any(event == ("compose", ("stop", "app")) for event in events)
    failed_writes = [value for path, value in writes if path == helper.FAILED_RECORD]
    assert len(failed_writes) == 1
    assert failed_writes[0]["failure_code"] == "readiness_schema_mismatch"
    assert failed_writes[0]["actual_schema_version"] == 8


def test_rollback_rejects_compose_drift_before_schema_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    revision = "a" * 40
    release = {
        "revision": revision,
        "image_digest": "1" * 64,
        "image_ref": helper._image_ref(revision, "1" * 64),
        "schema_version": 7,
        "compose_digest": "c" * 64,
    }
    schema_calls: list[str] = []
    compose_calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(helper, "RELEASE_ROOT", tmp_path)
    monkeypatch.setattr(helper, "_exclusive_lock", nullcontext)
    monkeypatch.setattr(helper, "_ensure_layout", lambda: None)
    monkeypatch.setattr(helper, "_read_json", lambda _: release)
    snapshot = helper._compose_snapshot_path(revision)
    snapshot.write_bytes(b"services: {app: {image: drifted}}\n")
    snapshot.chmod(0o600)
    monkeypatch.setattr(
        helper,
        "_database_schema",
        lambda image, **kwargs: schema_calls.append(image) or 7,
    )
    monkeypatch.setattr(
        helper,
        "_compose",
        lambda *arguments, **_: compose_calls.append(arguments) or "",
    )

    with pytest.raises(helper.HostError, match="compose_revision_mismatch"):
        helper._rollback(revision)

    assert schema_calls == []
    assert compose_calls == []


def test_rollback_rejects_loaded_image_before_schema_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    revision = "a" * 40
    archive_digest = "1" * 64
    expected_image_id = "sha256:" + "2" * 64
    release = {
        "revision": revision,
        "transport": helper.GITHUB_RELEASE_TRANSPORT,
        "image_ref": helper._local_image_ref(revision),
        "image_digest": archive_digest,
        "archive_sha256": archive_digest,
        "image_id": expected_image_id,
        "platform": "linux/amd64",
        "archive_size": 1234,
        "schema_version": 8,
        "compose_digest": "c" * 64,
    }
    schema_calls: list[str] = []

    monkeypatch.setattr(helper, "RELEASE_ROOT", tmp_path)
    monkeypatch.setattr(helper, "_exclusive_lock", nullcontext)
    monkeypatch.setattr(helper, "_ensure_layout", lambda: None)
    monkeypatch.setattr(helper, "_read_json", lambda _: release)
    monkeypatch.setattr(helper, "_assert_record_compose_digest", lambda _: None)
    monkeypatch.setattr(helper, "_image_id", lambda _: "sha256:" + "3" * 64)
    monkeypatch.setattr(
        helper,
        "_database_schema",
        lambda image: schema_calls.append(image) or 8,
    )

    with pytest.raises(helper.HostError, match="image_id_mismatch"):
        helper._rollback(revision, expected_image_id)

    assert schema_calls == []


def test_failed_code_only_release_rolls_back_after_schema_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _helper()
    old_revision = "a" * 40
    new_revision = "b" * 40
    old_digest = "1" * 64
    new_digest = "2" * 64
    old_image = helper._image_ref(old_revision, old_digest)
    new_image = helper._image_ref(new_revision, new_digest)
    current = {
        "revision": old_revision,
        "image_ref": old_image,
        "image_digest": old_digest,
        "schema_version": 7,
        "compose_digest": "c" * 64,
    }
    target = {
        "revision": new_revision,
        "image_ref": new_image,
        "image_digest": new_digest,
        "schema_version": 7,
        "compose_digest": "c" * 64,
    }
    events: list[tuple[str, object]] = []
    health_calls = 0
    writes: list[tuple[Path, dict[str, object]]] = []
    compose_snapshot = tmp_path / "previous-compose.yaml"

    def health_check() -> dict[str, object]:
        nonlocal health_calls
        health_calls += 1
        if health_calls == 2:
            raise helper.HostError("readiness_failed")
        return {"status": "ready", "schema_version": 7}

    monkeypatch.setattr(
        helper,
        "_read_json",
        lambda path: current if path == helper.CURRENT_RECORD else None,
    )
    monkeypatch.setattr(
        helper,
        "_image_digest",
        lambda image: old_digest if image == old_image else new_digest,
    )
    monkeypatch.setattr(helper, "_image_schema", lambda _: 7)
    monkeypatch.setattr(helper, "_health_check", health_check)
    monkeypatch.setattr(helper, "_assert_record_compose_digest", lambda _: compose_snapshot)
    monkeypatch.setattr(
        helper,
        "_runtime_file",
        lambda image, mode="disabled": events.append(("runtime", (image, mode))),
    )
    monkeypatch.setattr(
        helper,
        "_verified_backup",
        lambda image, revision, **kwargs: {
            "trigger": "pre_deploy",
            "name": "pre-deploy-safe.spbackup",
            "sha256": "3" * 64,
            "schema_version": 7,
            "verified": True,
        },
    )
    monkeypatch.setattr(helper, "_run_migrations", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        helper,
        "_compose",
        lambda *arguments, **_: events.append(("compose", arguments)) or "",
    )
    monkeypatch.setattr(
        helper,
        "_database_schema",
        lambda image, **kwargs: events.append(("schema", image)) or 7,
    )
    monkeypatch.setattr(
        helper,
        "_compose_up",
        lambda record, **kwargs: events.append(("up", kwargs)) or "",
    )
    monkeypatch.setattr(
        helper,
        "_write_json",
        lambda path, value, **_: writes.append((path, value)),
    )
    monkeypatch.setattr(helper, "_audit", lambda *arguments, **_: None)

    with pytest.raises(helper.HostError, match="readiness_failed"):
        helper._apply_release(target)

    failed_writes = [value for path, value in writes if path == helper.FAILED_RECORD]
    assert len(failed_writes) == 1
    assert failed_writes[0]["rollback_attempted"] is True
    assert failed_writes[0]["rollback_succeeded"] is True
    schema_index = next(index for index, event in enumerate(events) if event[0] == "schema")
    up_indices = [index for index, event in enumerate(events) if event[0] == "up"]
    assert len(up_indices) == 2
    assert schema_index < up_indices[-1]
    assert events[up_indices[-1]][1]["compose_file"] == compose_snapshot
    assert events[up_indices[-1]][1]["force_recreate"] is True


def test_first_deploy_refuses_an_unowned_existing_database(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _helper()
    target = {
        "revision": "b" * 40,
        "image_digest": "2" * 64,
        "image_ref": helper._image_ref("b" * 40, "2" * 64),
        "schema_version": 8,
    }
    compose_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(helper, "_read_json", lambda _: None)
    monkeypatch.setattr(helper, "_image_digest", lambda _: target["image_digest"])
    monkeypatch.setattr(helper, "_database_present", lambda _: True)
    monkeypatch.setattr(
        helper,
        "_database_schema",
        lambda _: (_ for _ in ()).throw(helper.HostError("database_schema_unavailable")),
    )
    monkeypatch.setattr(helper, "_runtime_file", lambda *_args: None)
    monkeypatch.setattr(
        helper,
        "_compose",
        lambda *arguments, **_: compose_calls.append(arguments) or "",
    )
    monkeypatch.setattr(helper, "_write_failed_record", lambda *arguments, **_: None)

    with pytest.raises(helper.HostError, match="database_schema_unavailable"):
        helper._apply_release(target)
    assert compose_calls == [
        ("stop", "app"),
        ("ps", "--status", "running", "--services"),
        ("stop", "app"),
        ("ps", "--status", "running", "--services"),
    ]


def test_first_release_backup_requires_verified_pre_migration_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _helper()
    revision = "b" * 40
    image_ref = helper._image_ref(revision, "2" * 64)
    migrate_receipt = {
        "status": "migrated",
        "pre_migration_backup": {
            "trigger": "pre_migration",
            "verified": True,
            "name": "pre-migration-v6-to-v8-20260927T120000Z.spbackup",
            "sha256": "3" * 64,
            "schema_version": 6,
        },
    }
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(helper, "_runtime_file", lambda *_args: None)
    monkeypatch.setattr(helper, "_image_schema", lambda _: 8)
    monkeypatch.setattr(helper.secrets, "token_hex", lambda _: "cafebabe")

    def compose(*arguments: str, **_: object) -> str:
        calls.append(arguments)
        if "migrate" in arguments:
            return json.dumps(migrate_receipt)
        if "backup" in arguments:
            name = arguments[arguments.index("--name") + 1]
            return json.dumps(
                {"name": name, "verified": True, "schema_version": 8, "sha256": "4" * 64}
            )
        if "restore" in arguments:
            return json.dumps({"name": arguments[-1], "verified": True})
        return "8"

    monkeypatch.setattr(helper, "_compose", compose)
    monkeypatch.setattr(helper, "_audit", lambda *arguments, **_: None)

    result = helper._verified_first_release_backup(image_ref, revision, 6, 8)

    assert calls[0][-1] == "migrate"
    assert calls[1][-1].startswith("import sqlite3; c=sqlite3.connect(")
    assert calls[2][-1] == "pre-deploy-" + revision[:16] + "-cafebabe.spbackup"
    assert calls[3][-1] == "pre-deploy-" + revision[:16] + "-cafebabe.spbackup"
    assert result == {
        "trigger": "pre_deploy",
        "name": f"pre-deploy-{revision[:16]}-cafebabe.spbackup",
        "sha256": "4" * 64,
        "schema_version": 8,
        "verified": True,
        "pre_migration_backup": {
            "trigger": "pre_migration",
            "name": "pre-migration-v6-to-v8-20260927T120000Z.spbackup",
            "sha256": "3" * 64,
            "schema_version": 6,
            "verified": True,
        },
    }


def test_first_release_backup_fails_closed_on_unverified_pre_migration_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _helper()
    revision = "b" * 40
    image_ref = helper._image_ref(revision, "2" * 64)
    invalid_receipt = {
        "status": "migrated",
        "pre_migration_backup": {
            "trigger": "pre_migration",
            "verified": False,
            "name": "pre-migration-v6-to-v8.spbackup",
            "sha256": "3" * 64,
            "schema_version": 6,
        },
    }
    monkeypatch.setattr(helper, "_runtime_file", lambda *_args: None)
    monkeypatch.setattr(
        helper,
        "_compose",
        lambda *arguments, **_: json.dumps(invalid_receipt),
    )
    monkeypatch.setattr(
        helper,
        "_verified_backup",
        lambda *arguments: pytest.fail("post-migration backup must wait for the receipt"),
    )

    with pytest.raises(helper.HostError, match="pre_migration_backup_unverified"):
        helper._verified_first_release_backup(image_ref, revision, 6, 8)


def test_first_deploy_checks_existing_schema_before_legacy_backup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _helper()
    target = {
        "revision": "b" * 40,
        "image_digest": "2" * 64,
        "image_ref": helper._image_ref("b" * 40, "2" * 64),
        "schema_version": 8,
    }
    events: list[tuple[str, object]] = []
    monkeypatch.setattr(helper, "_read_json", lambda _: None)
    monkeypatch.setattr(helper, "_image_digest", lambda _: target["image_digest"])
    monkeypatch.setattr(
        helper,
        "_database_present",
        lambda _: events.append(("database_present", None)) or True,
    )
    schema_results = iter((6, 8))
    monkeypatch.setattr(
        helper,
        "_database_schema",
        lambda *_args, **_kwargs: events.append(("database_schema", next(schema_results)))
        or events[-1][1],
    )
    monkeypatch.setattr(
        helper,
        "_verified_first_release_backup",
        lambda *arguments: events.append(("legacy_backup", arguments))
        or {"name": "post-migration.spbackup", "verified": True},
    )
    monkeypatch.setattr(
        helper,
        "_runtime_file",
        lambda image, mode="disabled": events.append(("runtime", (image, mode))),
    )
    monkeypatch.setattr(
        helper,
        "_compose",
        lambda *arguments, **_: events.append(("compose", arguments)) or "",
    )
    monkeypatch.setattr(
        helper,
        "_health_check",
        lambda: {"status": "ready", "schema_version": 8},
    )
    monkeypatch.setattr(helper, "_write_json", lambda *arguments, **_: None)
    monkeypatch.setattr(helper, "_audit", lambda *arguments, **_: None)

    result = helper._apply_release(target)

    assert result["status"] == "ok"
    assert events.index(("database_schema", 6)) < next(
        index for index, event in enumerate(events) if event[0] == "legacy_backup"
    )


def test_first_deploy_rejects_newer_existing_schema_before_backup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _helper()
    target = {
        "revision": "b" * 40,
        "image_digest": "2" * 64,
        "image_ref": helper._image_ref("b" * 40, "2" * 64),
        "schema_version": 8,
    }
    backups: list[object] = []
    monkeypatch.setattr(helper, "_read_json", lambda _: None)
    monkeypatch.setattr(helper, "_image_digest", lambda _: target["image_digest"])
    monkeypatch.setattr(helper, "_database_present", lambda _: True)
    monkeypatch.setattr(helper, "_runtime_file", lambda *_args: None)
    monkeypatch.setattr(helper, "_database_schema", lambda _: 9)
    monkeypatch.setattr(
        helper,
        "_verified_first_release_backup",
        lambda *arguments: backups.append(arguments) or {"name": "unsafe"},
    )
    monkeypatch.setattr(helper, "_compose", lambda *arguments, **_: "")
    monkeypatch.setattr(helper, "_write_failed_record", lambda *arguments, **_: None)

    with pytest.raises(helper.HostError, match="schema_incompatible"):
        helper._apply_release(target)
    assert backups == []


RECOVERY_DISPATCH_ARTIFACTS = (
    ROOT / "test-results/assistant-r120/coordination/recovery-dispatch-preparation-20261006"
)
RECOVERY_DISPATCH_SOURCE_ROOTS = (ROOT / "src/stock_probs",)


class _DispatchCleanupOwnership:
    """Record only resources observed as new during a clean, phase-bound run."""

    _CONTAINER_PHASES = frozenset({"seed_run", "candidate_up", "recovery_up", "database_probe"})
    _COMPOSE_PHASES = frozenset({"candidate_up", "recovery_up", "database_probe"})
    _NETWORK_PHASES = frozenset({"candidate_up", "recovery_up", "database_probe"})
    _VOLUME_PHASES = frozenset({"explicit_volume_create"})

    def __init__(self, *, task_id: str, run_id: str, project: str, volume: str) -> None:
        self.task_id = task_id
        self.run_id = run_id
        self.project = project
        self.volume = volume
        self.preflight_passed = False
        self.baseline_container_ids: set[str] = set()
        self.baseline_network_ids: set[str] = set()
        self.baseline_volume_names: set[str] = set()
        self.created_container_phases: dict[str, set[str]] = {}
        self.created_network_phases: dict[str, set[str]] = {}
        self.created_volume_phases: dict[str, set[str]] = {}

    def establish_preflight(
        self,
        *,
        project_container_ids: set[str],
        project_network_ids: set[str],
        run_volume_names: set[str],
        volume_names: set[str],
        all_container_ids: set[str],
        all_network_ids: set[str],
    ) -> bool:
        """Enable cleanup ownership only after every fixed-name collision check is clear."""

        if (
            self.preflight_passed
            or project_container_ids
            or project_network_ids
            or run_volume_names
            or self.volume in volume_names
        ):
            return False
        self.baseline_container_ids = set(all_container_ids)
        self.baseline_network_ids = set(all_network_ids)
        self.baseline_volume_names = set(volume_names)
        self.preflight_passed = True
        return True

    def _expected_labels(self, *, compose: bool) -> dict[str, str]:
        expected = {
            "com.stock-probs.task": self.task_id,
            "com.stock-probs.run": self.run_id,
        }
        if compose:
            expected["com.docker.compose.project"] = self.project
        return expected

    @staticmethod
    def _matches_labels(labels: object, expected: dict[str, str]) -> bool:
        return isinstance(labels, dict) and all(
            labels.get(key) == value for key, value in expected.items()
        )

    @staticmethod
    def _valid_full_id(resource_id: str) -> bool:
        return re.fullmatch(r"[0-9a-f]{64}", resource_id) is not None

    def record_container(
        self,
        resource_id: str,
        *,
        phase: str,
        labels: object,
        before_ids: set[str],
        after_ids: set[str],
    ) -> bool:
        """Record a newly observed container only for an allowed creation phase."""

        if (
            not self.preflight_passed
            or phase not in self._CONTAINER_PHASES
            or not self._valid_full_id(resource_id)
            or resource_id in self.baseline_container_ids
            or resource_id in before_ids
            or resource_id not in after_ids
        ):
            return False
        compose = phase in self._COMPOSE_PHASES
        expected = self._expected_labels(compose=compose)
        if not self._matches_labels(labels, expected):
            return False
        if not compose and isinstance(labels, dict) and "com.docker.compose.project" in labels:
            return False
        self.created_container_phases.setdefault(resource_id, set()).add(phase)
        return True

    def record_network(
        self,
        resource_id: str,
        *,
        phase: str,
        labels: object,
        before_ids: set[str],
        after_ids: set[str],
    ) -> bool:
        """Record only a new Compose network observed during an up phase."""

        if (
            not self.preflight_passed
            or phase not in self._NETWORK_PHASES
            or not self._valid_full_id(resource_id)
            or resource_id in self.baseline_network_ids
            or resource_id in before_ids
            or resource_id not in after_ids
            or not self._matches_labels(labels, self._expected_labels(compose=True))
        ):
            return False
        self.created_network_phases.setdefault(resource_id, set()).add(phase)
        return True

    def record_volume(self, volume_name: str, *, phase: str, labels: object) -> bool:
        """Record the fixed volume after its preflight absence and run labels are verified."""

        if (
            not self.preflight_passed
            or phase not in self._VOLUME_PHASES
            or volume_name != self.volume
            or volume_name in self.baseline_volume_names
            or not self._matches_labels(labels, self._expected_labels(compose=False))
        ):
            return False
        self.created_volume_phases.setdefault(volume_name, set()).add(phase)
        return True

    def permits_container_removal(self, resource_id: str, labels: object) -> bool:
        """Require a known created ID and its task/run labels immediately before removal."""

        phases = self.created_container_phases.get(resource_id, set())
        return bool(
            self.preflight_passed
            and phases
            and phases <= self._CONTAINER_PHASES
            and self._matches_labels(
                labels,
                self._expected_labels(compose=bool(phases & self._COMPOSE_PHASES)),
            )
        )

    def permits_network_removal(self, resource_id: str, labels: object) -> bool:
        """Require a known created network ID and exact task/run/project labels."""

        phases = self.created_network_phases.get(resource_id, set())
        return bool(
            self.preflight_passed
            and phases
            and phases <= self._NETWORK_PHASES
            and self._matches_labels(labels, self._expected_labels(compose=True))
        )

    def permits_volume_removal(self, volume_name: str, labels: object) -> bool:
        """Require the exact volume name created after clean preflight and matching labels."""

        phases = self.created_volume_phases.get(volume_name, set())
        return bool(
            self.preflight_passed
            and volume_name == self.volume
            and volume_name not in self.baseline_volume_names
            and phases
            and phases <= self._VOLUME_PHASES
            and self._matches_labels(labels, self._expected_labels(compose=False))
        )


def _dispatch_cleanup_owned_resources(
    ownership: _DispatchCleanupOwnership | None,
    *,
    inspect_container: Callable[[str], tuple[str, object]],
    remove_container: Callable[[str], None],
    container_absent: Callable[[str], bool],
    inspect_network: Callable[[str], tuple[str, object]],
    remove_network: Callable[[str], None],
    network_absent: Callable[[str], bool],
    inspect_volume: Callable[[str], tuple[str, object]],
    volume_attached: Callable[[str], bool],
    remove_volume: Callable[[str], None],
    volume_absent: Callable[[str], bool],
    cleanup_errors: list[str],
    removed_container_ids: list[str],
    removed_volume_names: list[str],
    already_absent_container_ids: list[str],
    already_absent_network_ids: list[str],
    already_absent_volume_names: list[str],
) -> None:
    """Revalidate tracked resources and skip IDs already removed by recovery."""

    if ownership is None or not ownership.preflight_passed:
        return
    for resource_id in sorted(ownership.created_container_phases):
        try:
            if container_absent(resource_id):
                already_absent_container_ids.append(resource_id)
                continue
            observed_id, labels = inspect_container(resource_id)
            if observed_id != resource_id or not ownership.permits_container_removal(
                resource_id, labels
            ):
                cleanup_errors.append("known_container_identity_changed")
                continue
            remove_container(resource_id)
            if container_absent(resource_id):
                removed_container_ids.append(resource_id)
            else:
                cleanup_errors.append("known_container_remains")
        except Exception:
            cleanup_errors.append("known_container_cleanup_unverified")
    for resource_id in sorted(ownership.created_network_phases):
        try:
            if network_absent(resource_id):
                already_absent_network_ids.append(resource_id)
                continue
            observed_id, labels = inspect_network(resource_id)
            if observed_id != resource_id or not ownership.permits_network_removal(
                resource_id, labels
            ):
                cleanup_errors.append("known_network_identity_changed")
                continue
            remove_network(resource_id)
            if not network_absent(resource_id):
                cleanup_errors.append("known_network_remains")
        except Exception:
            cleanup_errors.append("known_network_cleanup_unverified")
    for volume_name in sorted(ownership.created_volume_phases):
        try:
            if volume_absent(volume_name):
                already_absent_volume_names.append(volume_name)
                continue
            observed_name, labels = inspect_volume(volume_name)
            if observed_name != volume_name or not ownership.permits_volume_removal(
                volume_name, labels
            ):
                cleanup_errors.append("known_volume_identity_changed")
                continue
            if volume_attached(volume_name):
                cleanup_errors.append("known_volume_still_mounted")
                continue
            remove_volume(volume_name)
            if volume_absent(volume_name):
                removed_volume_names.append(volume_name)
            else:
                cleanup_errors.append("known_volume_remains")
        except Exception:
            cleanup_errors.append("known_volume_cleanup_unverified")


def _dispatch_full_id_absent(helper: Any, kind: str, resource_id: str) -> bool:
    """Check absence through a filtered, no-truncation full-ID lookup."""

    if re.fullmatch(r"[0-9a-f]{64}", resource_id) is None:
        raise ValueError("resource_id_invalid")
    if kind == "container":
        command = [
            "docker",
            "ps",
            "--all",
            "--quiet",
            "--no-trunc",
            "--filter",
            f"id={resource_id}",
        ]
    elif kind == "network":
        command = [
            "docker",
            "network",
            "ls",
            "--quiet",
            "--no-trunc",
            "--filter",
            f"id={resource_id}",
        ]
    else:
        raise ValueError("resource_kind_invalid")
    matches = _dispatch_docker(helper, command).split()
    if len(matches) > 1 or any(
        re.fullmatch(r"[0-9a-f]{64}", match) is None or match != resource_id for match in matches
    ):
        raise ValueError("resource_absence_lookup_invalid")
    return not matches


def _dispatch_volume_absent(helper: Any, volume_name: str) -> bool:
    """Check the fixed volume name through a bounded name-filtered lookup."""

    if re.fullmatch(r"r120-recovery-data-[0-9a-f]{16}", volume_name) is None:
        raise ValueError("volume_name_invalid")
    matches = _dispatch_docker(
        helper,
        ["docker", "volume", "ls", "--quiet", "--filter", f"name={volume_name}"],
    ).split()
    if len(matches) > 1 or any(match != volume_name for match in matches):
        raise ValueError("volume_absence_lookup_invalid")
    return not matches


def _dispatch_all_resource_ids(helper: Any, kind: str) -> set[str]:
    """Read a full-ID Docker resource snapshot for one fixed resource kind."""

    commands = {
        "container": ["docker", "ps", "--all", "--quiet", "--no-trunc"],
        "network": ["docker", "network", "ls", "--quiet", "--no-trunc"],
        "volume": ["docker", "volume", "ls", "--quiet"],
    }
    if kind not in commands:
        raise ValueError("resource_kind_invalid")
    values = set(_dispatch_docker(helper, commands[kind]).split())
    if kind != "volume" and any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in values):
        raise ValueError("resource_id_snapshot_invalid")
    return values


def _dispatch_capture_created_resources(
    helper: Any,
    ownership: _DispatchCleanupOwnership,
    *,
    phase: str,
    before_containers: set[str],
    before_networks: set[str],
    cleanup_errors: list[str],
) -> None:
    """Record newly observed IDs from one creation phase after validating labels."""

    try:
        after_containers = _dispatch_all_resource_ids(helper, "container")
        for resource_id in sorted(after_containers - before_containers):
            raw = _dispatch_docker(
                helper,
                ["docker", "inspect", "--format", "{{.Id}}|{{json .Config.Labels}}", resource_id],
            ).split("|", 1)
            if len(raw) != 2 or raw[0] != resource_id:
                cleanup_errors.append("created_container_identity_unverified")
                continue
            labels = json.loads(raw[1])
            if not ownership.record_container(
                resource_id,
                phase=phase,
                labels=labels,
                before_ids=before_containers,
                after_ids=after_containers,
            ):
                cleanup_errors.append("created_container_ownership_unverified")
    except Exception:
        cleanup_errors.append("created_container_snapshot_unverified")
    if phase not in ownership._COMPOSE_PHASES:
        return
    try:
        after_networks = _dispatch_all_resource_ids(helper, "network")
        for resource_id in sorted(after_networks - before_networks):
            raw = _dispatch_docker(
                helper,
                [
                    "docker",
                    "network",
                    "inspect",
                    "--format",
                    "{{.Id}}|{{json .Labels}}",
                    resource_id,
                ],
            ).split("|", 1)
            if len(raw) != 2 or raw[0] != resource_id:
                cleanup_errors.append("created_network_identity_unverified")
                continue
            labels = json.loads(raw[1])
            if not ownership.record_network(
                resource_id,
                phase=phase,
                labels=labels,
                before_ids=before_networks,
                after_ids=after_networks,
            ):
                cleanup_errors.append("created_network_ownership_unverified")
    except Exception:
        cleanup_errors.append("created_network_snapshot_unverified")


def _seed_schema12_failure(settings: Settings) -> Repository:
    """Create the schema-12 failure event fixture shared with the migration rehearsal."""

    settings.ensure_local_dirs()
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        migrations = sorted(
            migration
            for migration in files("stock_probs.migrations").iterdir()
            if migration.name.endswith(".sql") and int(migration.name[:3]) <= 12
        )
        for version, migration in enumerate(migrations, start=1):
            Repository._execute_migration(connection, migration.read_text())
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, "2026-10-04T00:00:00+00:00"),
            )
    repository = Repository(settings.database_path)
    repository.record_failure(
        owner_user_id=1,
        request_id="before-schema13",
        submitted_symbol="FAIL",
        normalized_symbol="FAIL",
        asset_type="stock",
        error_code="fixture_failure",
        error_message="preserve the schema-12 event",
        submitted_at=datetime(2026, 10, 4, tzinfo=UTC),
        completed_at=datetime(2026, 10, 4, tzinfo=UTC),
    )
    return repository


def _sha256_file(path: Path) -> str:
    """Hash a regular file through a no-follow descriptor for a fail-closed baseline."""

    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    digest = hashlib.sha256()
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("source_binding_unsafe")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def _recovery_dispatch_inputs() -> dict[str, str]:
    """Bind the maintained test, helper, conftest, package sources, and migrations."""

    paths = {
        ROOT / "pyproject.toml",
        ROOT / "Dockerfile",
        ROOT / "tests/conftest.py",
        ROOT / "tests/test_production_deploy_helper.py",
        HELPER_PATH,
    }
    for source_root in RECOVERY_DISPATCH_SOURCE_ROOTS:
        paths.update(source_root.rglob("*.py"))
        paths.update(source_root.joinpath("migrations").glob("*.sql"))
    return {path.relative_to(ROOT).as_posix(): _sha256_file(path) for path in sorted(paths)}


def _safe_artifact_directory() -> Path:
    """Create only the fixed task-owned ignored directory without following symlinks."""

    descriptor = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    root_descriptor = descriptor
    try:
        for component in RECOVERY_DISPATCH_ARTIFACTS.relative_to(ROOT).parts:
            with suppress(FileExistsError):
                os.mkdir(component, mode=0o700, dir_fd=descriptor)
            child = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=descriptor,
            )
            if descriptor != root_descriptor:
                os.close(descriptor)
            descriptor = child
    finally:
        if descriptor != root_descriptor:
            os.close(descriptor)
        os.close(root_descriptor)
    return RECOVERY_DISPATCH_ARTIFACTS


def _read_bounded_regular(path: Path, limit: int, code: str) -> bytes:
    """Read one bounded regular file without following a replaced final path."""

    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"{code}_unsafe")
        if metadata.st_size > limit:
            raise ValueError(f"{code}_too_large")
        output = bytearray()
        while len(output) <= limit:
            chunk = os.read(descriptor, min(16_384, limit + 1 - len(output)))
            if not chunk:
                break
            output.extend(chunk)
        if len(output) > limit or len(output) != metadata.st_size:
            raise ValueError(f"{code}_size_invalid")
        return bytes(output)
    finally:
        os.close(descriptor)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate keys in the pair manifest and pre-run receipt."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("release_pair_duplicate_property")
        result[key] = value
    return result


def _read_pair_source_facts(
    helper: Any, source_specs: object, *, pair_directory: Path
) -> tuple[dict[str, object], dict[str, tuple[Path, str]]]:
    """Read the public source/overlay manifests bound by the prepared pre-run receipt."""

    fact_names = {"--source-context-manifest", "--overlay-manifest"}
    if not isinstance(source_specs, dict) or set(source_specs) != fact_names:
        raise ValueError("pair_source_fact_bindings_invalid")
    facts: dict[str, object] = {}
    files_by_name: dict[str, tuple[Path, str]] = {}
    for name in sorted(fact_names):
        spec = source_specs[name]
        if not isinstance(spec, dict) or set(spec) != {"path", "sha256"}:
            raise ValueError("pair_source_fact_binding_invalid")
        path_value = spec.get("path")
        expected_sha = spec.get("sha256")
        if (
            not isinstance(path_value, str)
            or not isinstance(expected_sha, str)
            or helper.DIGEST_PATTERN.fullmatch(expected_sha) is None
        ):
            raise ValueError("pair_source_fact_binding_invalid")
        fact_path = Path(path_value)
        if (
            not fact_path.is_absolute()
            or ".." in fact_path.parts
            or fact_path.parent != pair_directory
        ):
            raise ValueError("pair_source_fact_path_invalid")
        raw = _read_bounded_regular(fact_path, 65_536, "pair_source_fact")
        actual_sha = hashlib.sha256(raw).hexdigest()
        if actual_sha != expected_sha:
            raise ValueError("pair_source_fact_digest_mismatch")
        value = json.loads(raw, object_pairs_hook=_unique_json_object)
        if not isinstance(value, dict):
            raise ValueError("pair_source_fact_invalid")
        facts[name] = value
        files_by_name[name] = (fact_path, actual_sha)
    return facts, files_by_name


def _read_recovery_pair(
    helper: Any,
    path: Path,
    expected_sha256: str,
    *,
    expected_candidate_image_id: str,
    expected_recovery_image_id: str,
    facts: dict[str, object],
) -> tuple[dict[str, object], str]:
    """Bind the reviewed pair digest and exact image identities through helper validation."""

    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("release_pair_path_invalid")
    if (
        helper.DIGEST_PATTERN.fullmatch(expected_sha256) is None
        or helper.IMAGE_ID_PATTERN.fullmatch(expected_candidate_image_id) is None
        or helper.IMAGE_ID_PATTERN.fullmatch(expected_recovery_image_id) is None
    ):
        raise ValueError("release_pair_binding_invalid")
    raw = _read_bounded_regular(path, 65_536, "release_pair_manifest")
    if not raw:
        raise ValueError("release_pair_manifest_size_invalid")
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise ValueError("release_pair_manifest_digest_mismatch")
    parsed = json.loads(raw, object_pairs_hook=_unique_json_object)
    if not isinstance(parsed, dict):
        raise ValueError("release_pair_manifest_invalid")
    revision = parsed.get("revision")
    candidate = parsed.get("candidate")
    recovery = parsed.get("recovery")
    if (
        not isinstance(revision, str)
        or helper.REVISION_PATTERN.fullmatch(revision) is None
        or not isinstance(candidate, dict)
        or not isinstance(recovery, dict)
        or candidate.get("image_id") != expected_candidate_image_id
        or recovery.get("image_id") != expected_recovery_image_id
    ):
        raise ValueError("release_pair_identity_invalid")
    helper._validate_release_pair_manifest(
        parsed,
        revision=revision,
        candidate_archive_sha256=candidate.get("archive_sha256"),
        candidate_archive_size=candidate.get("archive_size"),
        candidate_image_id=expected_candidate_image_id,
        facts=facts,
    )
    return parsed, actual


def _write_dispatch_receipt(path: Path, value: dict[str, object]) -> None:
    """Create one private, non-overwriting receipt in the ignored task directory."""

    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
    )
    try:
        view = memoryview(raw)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                raise OSError("receipt_write_incomplete")
            view = view[count:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _dispatch_docker(helper: Any, args: list[str], timeout: float = 60.0) -> str:
    """Use only the helper's bounded argv runner for local Docker operations."""

    return helper._run(args, timeout=timeout).stdout.strip()


def _dispatch_container_facts(helper: Any, container_id: str) -> dict[str, object]:
    """Read exact container, volume, network, isolation, and host-port facts."""

    template = "|".join(
        (
            "{{.Id}}",
            "{{.Image}}",
            "{{json .Mounts}}",
            "{{json .HostConfig}}",
            "{{json .NetworkSettings.Ports}}",
            "{{json .NetworkSettings.Networks}}",
            "{{json .Config.Labels}}",
            "{{.Config.User}}",
        )
    )
    output = _dispatch_docker(helper, ["docker", "inspect", "--format", template, container_id])
    fields = output.split("|", 7)
    if len(fields) != 8 or fields[0] != container_id:
        raise ValueError("container_inspection_invalid")
    return {
        "container_id": fields[0],
        "image_id": fields[1],
        "mounts": json.loads(fields[2]),
        "host_config": json.loads(fields[3]),
        "published_ports": json.loads(fields[4]),
        "networks": json.loads(fields[5]),
        "labels": json.loads(fields[6]),
        "config_user": fields[7],
    }


def _dispatch_database_facts(
    helper: Any,
    ownership: _DispatchCleanupOwnership,
    cleanup_errors: list[str],
) -> tuple[int, int, int, str]:
    """Read the task volume through the exact Compose service as its application UID."""

    script = """
import hashlib
import json
import sqlite3

connection = sqlite3.connect("file:/data/stock_probs.sqlite3?mode=ro", uri=True)
connection.execute("PRAGMA query_only=ON")
schema = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
request_id = "before-schema13"
rows = connection.execute(
    "SELECT COUNT(*) FROM search_events WHERE request_id = ?", (request_id,)
).fetchone()[0]
event = connection.execute(
    "SELECT id, request_id, submitted_symbol, normalized_symbol, asset_type, status, "
    "is_repeat, error_code, error_message, run_id, submitted_at, completed_at "
    "FROM search_events WHERE request_id = ?",
    (request_id,),
).fetchone()
owner = connection.execute(
    "SELECT owner_user_id, assigned_at FROM search_event_owners "
    "WHERE event_id = (SELECT id FROM search_events WHERE request_id = ?)",
    (request_id,),
).fetchone()
owner_count = connection.execute(
    "SELECT COUNT(*) FROM search_event_owners "
    "WHERE event_id = (SELECT id FROM search_events WHERE request_id = ?)",
    (request_id,),
).fetchone()[0]
fixture = "missing"
if event is not None and owner is not None:
    fixture = hashlib.sha256(
        json.dumps([event, owner], separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
print(f"{schema}|{rows}|{owner_count}|{fixture}")
"""
    before_containers = _dispatch_all_resource_ids(helper, "container")
    before_networks = _dispatch_all_resource_ids(helper, "network")
    try:
        output = _dispatch_docker(
            helper,
            [
                *helper._compose_prefix(),
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "--user",
                "10001:10001",
                "--entrypoint",
                "python",
                "app",
                "-c",
                script,
            ],
        )
    finally:
        _dispatch_capture_created_resources(
            helper,
            ownership,
            phase="database_probe",
            before_containers=before_containers,
            before_networks=before_networks,
            cleanup_errors=cleanup_errors,
        )
    values = output.split("|")
    if (
        len(values) != 4
        or any(not value.isdigit() for value in values[:3])
        or re.fullmatch(r"[0-9a-f]{64}", values[3]) is None
    ):
        raise ValueError("database_fixture_probe_invalid")
    return int(values[0]), int(values[1]), int(values[2]), values[3]


def _dispatch_compose_yaml(volume_name: str, run_id: str) -> bytes:
    """Build a disposable production-shaped profile with no external network."""

    return f"""services:
  app:
    user: "0:0"
    image: ${{STOCK_PROBS_IMAGE:?}}
    pull_policy: never
    environment:
      STOCK_PROBS_ASSISTANT_ENABLED: "${{STOCK_PROBS_ASSISTANT_ENABLED:-0}}"
      STOCK_PROBS_ASSISTANT_ROLLOUT: "${{STOCK_PROBS_ASSISTANT_ROLLOUT:-disabled}}"
      STOCK_PROBS_ASSISTANT_CANARY_GITHUB_IDS: ""
      STOCK_PROBS_DATA_DIR: /data
      STOCK_PROBS_ENV: production
      STOCK_PROBS_HOST: 127.0.0.1
      STOCK_PROBS_PORT: "8000"
      STOCK_PROBS_PROVIDER: fixture
      STOCK_PROBS_AUTH_MODE: github
      STOCK_PROBS_PUBLIC_ORIGIN: ${{STOCK_PROBS_PUBLIC_ORIGIN:?}}
      STOCK_PROBS_AUTH_SESSION_SECRET: ${{STOCK_PROBS_AUTH_SESSION_SECRET:?}}
      STOCK_PROBS_AUTH_COOKIE_SECURE: "1"
      STOCK_PROBS_GITHUB_CLIENT_ID: ${{STOCK_PROBS_GITHUB_CLIENT_ID:?}}
      STOCK_PROBS_GITHUB_CLIENT_SECRET: ${{STOCK_PROBS_GITHUB_CLIENT_SECRET:?}}
      STOCK_PROBS_GITHUB_REDIRECT_URI: ${{STOCK_PROBS_GITHUB_REDIRECT_URI:?}}
      STOCK_PROBS_OWNER_GITHUB_ID: "1"
    ports:
      - "127.0.0.1::8000"
    volumes:
      - dispatch-data:/data
    read_only: true
    tmpfs:
      - /tmp:rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001,mode=0700
      - /run/assistant:rw,nosuid,nodev,noexec,size=16m,mode=0711
      - /run/assistant-worker-home:rw,nosuid,nodev,noexec,size=64m,uid=10002,gid=10002,mode=0700
    cap_drop:
      - ALL
    cap_add:
      - SETUID
      - SETGID
    security_opt:
      - no-new-privileges:true
    pids_limit: 128
    mem_limit: 768m
    cpus: 1.0
    restart: "no"
    labels:
      com.stock-probs.task: R-ASTRA-120
      com.stock-probs.run: {run_id}
    networks:
      - isolated
volumes:
  dispatch-data:
    external: true
    name: {volume_name}
networks:
  isolated:
    internal: true
    labels:
      com.stock-probs.task: R-ASTRA-120
      com.stock-probs.run: {run_id}
""".encode()


def _write_dispatch_file(path: Path, raw: bytes) -> None:
    """Write one new private task file without following or replacing paths."""

    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
    )
    try:
        view = memoryview(raw)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                raise OSError("temporary_file_write_incomplete")
            view = view[count:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _dispatch_profile(
    facts: dict[str, object], *, project: str, run_id: str, volume: str
) -> dict[str, object]:
    """Require same task volume and fixed no-egress, resource-bounded container profile."""

    host = facts["host_config"]
    mounts = facts["mounts"]
    ports = facts["published_ports"]
    networks = facts["networks"]
    labels = facts["labels"]
    expected_network = f"{project}_isolated"
    if not all(isinstance(item, dict) for item in (host, ports, networks, labels)):
        raise ValueError("container_profile_invalid")
    # This fixed /tmp is a container tmpfs; the exact profile check pins owner and mode.
    expected_tmpfs = {
        "/tmp": "rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001,mode=0700",  # noqa: S108
        "/run/assistant": "rw,nosuid,nodev,noexec,size=16m,mode=0711",
        "/run/assistant-worker-home": (
            "rw,nosuid,nodev,noexec,size=64m,uid=10002,gid=10002,mode=0700"
        ),
    }
    if (
        host.get("ReadonlyRootfs") is not True
        or host.get("Memory") != 768 * 1024 * 1024
        or host.get("NanoCpus") != 1_000_000_000
        or host.get("PidsLimit") != 128
        or host.get("CapDrop") != ["ALL"]
        or set(host.get("CapAdd", [])) != {"SETGID", "SETUID"}
        or host.get("SecurityOpt") != ["no-new-privileges:true"]
        or host.get("Tmpfs") != expected_tmpfs
        or host.get("RestartPolicy", {}).get("Name") != "no"
        or host.get("Privileged") is not False
        or host.get("NetworkMode") != expected_network
        or facts.get("config_user") != "0:0"
        or labels.get("com.stock-probs.task") != "R-ASTRA-120"
        or labels.get("com.stock-probs.run") != run_id
        or set(networks) != {expected_network}
        or not isinstance(ports.get("8000/tcp"), list)
        or len(ports["8000/tcp"]) != 1
    ):
        raise ValueError("container_profile_invalid")
    if not isinstance(mounts, list) or len(mounts) != 1:
        raise ValueError("container_mounts_invalid")
    data_mounts = [
        entry for entry in mounts if isinstance(entry, dict) and entry.get("Destination") == "/data"
    ]
    if (
        len(data_mounts) != 1
        or data_mounts[0].get("Type") != "volume"
        or data_mounts[0].get("Name") != volume
        or data_mounts[0].get("RW") is not True
    ):
        raise ValueError("container_mounts_invalid")
    port = ports["8000/tcp"][0]
    if (
        not isinstance(port, dict)
        or port.get("HostIp") != "127.0.0.1"
        or not isinstance(port.get("HostPort"), str)
        or not port["HostPort"].isdigit()
    ):
        raise ValueError("container_port_binding_invalid")
    return {
        "network_name": expected_network,
        "published_host": port["HostIp"],
        "published_port": int(port["HostPort"]),
        "volume_name": data_mounts[0]["Name"],
        "volume_source_sha256": hashlib.sha256(
            str(data_mounts[0].get("Source", "")).encode()
        ).hexdigest(),
        "volume_destination": data_mounts[0]["Destination"],
        "volume_rw": data_mounts[0]["RW"],
        "profile": {
            "read_only_root": host["ReadonlyRootfs"],
            "memory_bytes": host["Memory"],
            "nano_cpus": host["NanoCpus"],
            "pids_limit": host["PidsLimit"],
            "cap_drop": host["CapDrop"],
            "cap_add": sorted(host.get("CapAdd", [])),
            "no_new_privileges": "no-new-privileges:true" in host.get("SecurityOpt", []),
            "tmpfs": dict(sorted(host["Tmpfs"].items())),
        },
    }


def test_opt_in_schema13_recovery_dispatch_on_disposable_data(tmp_path: Path) -> None:
    """Exercise first-deploy recovery and its public rollback selector on pinned local images."""

    if os.environ.get("R120_RECOVERY_DISPATCH_DOCKER") != "1":
        pytest.skip("opt in only after parent review of the local Docker contract")

    raw_run_id = os.environ.get("R120_RECOVERY_DISPATCH_RUN_ID", "")
    if re.fullmatch(r"[0-9a-f]{16}", raw_run_id) is None:
        raise ValueError("run_id_invalid")
    run_id = raw_run_id
    artifact_dir = RECOVERY_DISPATCH_ARTIFACTS
    receipt_path = artifact_dir / f"receipt-{run_id}.json"
    manifest_value = os.environ.get("R120_RECOVERY_DISPATCH_PAIR_MANIFEST", "")
    expected_pair_sha = os.environ.get("R120_RECOVERY_DISPATCH_PAIR_SHA256", "")
    bindings_value = os.environ.get("R120_RECOVERY_DISPATCH_PRE_RUN_BINDINGS", "")
    manifest_path = Path(manifest_value)
    bindings_path = Path(bindings_value)

    start = datetime.now(UTC).isoformat()
    receipt: dict[str, object] = {
        "schema_version": 1,
        "task_id": "R-ASTRA-120",
        "scope": "candidate failure, forward recovery, and explicit same-schema rollback",
        "result": "Fail",
        "phase": "preflight",
        "started_at": start,
        "ended_at": None,
        "source_bindings": {},
        "release_pair_manifest": None,
        "reviewed_image_ids": None,
        "pair_source_facts": {},
        "candidate_image_id": None,
        "recovery_image_id": None,
        "compose_project": None,
        "volume": None,
        "up_containers": [],
        "candidate_failure_injected_once": False,
        "schema_version_before_candidate": None,
        "preserved_fixture_row_count_before_candidate": None,
        "preserved_fixture_owner_count_before_candidate": None,
        "schema_version_after_recovery": None,
        "preserved_fixture_row_count": None,
        "preserved_fixture_owner_count": None,
        "preserved_fixture_sha256_before_candidate": None,
        "preserved_fixture_sha256_after_recovery": None,
        "explicit_recovery_rollback_result": None,
        "schema_version_after_explicit_rollback": None,
        "preserved_fixture_row_count_after_explicit_rollback": None,
        "preserved_fixture_owner_count_after_explicit_rollback": None,
        "preserved_fixture_sha256_after_explicit_rollback": None,
        "explicit_rollback_health": None,
        "explicit_rollback_profile_matches_forward_recovery": None,
        "typed_rollback_request_parsed_dispatched": False,
        "current_release_role": None,
        "current_rollout_mode": None,
        "failed_status": None,
        "failed_forward_recovery_succeeded": None,
        "owned_cleanup": {
            "result": "pending",
            "removed_container_ids": [],
            "removed_volume_names": [],
            "already_absent_container_ids": [],
            "already_absent_network_ids": [],
            "already_absent_volume_names": [],
            "project_containers_absent": False,
            "project_networks_absent": False,
            "volume_absent": False,
            "removed_volume": False,
            "loopback_ports_released": [],
            "temporary_workspace_removed": False,
            "images_retained": True,
        },
        "failure_code": None,
    }
    failure: BaseException | None = None
    cleanup_errors: list[str] = []
    helper: Any | None = None
    target: dict[str, Any] | None = None
    project: str | None = None
    volume: str | None = None
    project_candidate: str | None = None
    volume_candidate: str | None = None
    ownership: _DispatchCleanupOwnership | None = None
    volume_labels: dict[str, str] = {}
    compose_file: Path | None = None
    temporary: tempfile.TemporaryDirectory[str] | None = None
    temporary_root: Path | None = None
    original_cwd = Path.cwd()
    original_docker_config = os.environ.get("DOCKER_CONFIG")
    docker_config_changed = False
    ports_seen: list[int] = []
    up_ids: list[str] = []
    seed_id: str | None = None
    health_failure_count = 0
    source_bindings: dict[str, str] = {}
    pre_run_bindings_sha256: str | None = None
    reviewed_image_ids: dict[str, str] = {}
    pair_source_facts: dict[str, object] = {}
    pair_source_fact_files: dict[str, tuple[Path, str]] = {}

    artifact_ready = False
    try:
        artifact_dir = _safe_artifact_directory()
        receipt_path = artifact_dir / f"receipt-{run_id}.json"
        artifact_ready = True
        if any(name.startswith("STOCK_PROBS_") for name in os.environ):
            raise ValueError("host_application_environment_present")
        if (
            os.environ.get("DOCKER_CONTEXT")
            or os.environ.get("DOCKER_TLS_VERIFY")
            or os.environ.get("DOCKER_CERT_PATH")
        ):
            raise ValueError("local_docker_context_required")
        docker_host = os.environ.get("DOCKER_HOST", "")
        if not docker_host.startswith("unix://"):
            raise ValueError("local_docker_socket_required")
        if not manifest_value or not expected_pair_sha or not bindings_value:
            raise ValueError("opt_in_inputs_missing")
        binding_raw = _read_bounded_regular(bindings_path, 65_536, "pre_run_bindings")
        pre_run_bindings_sha256 = hashlib.sha256(binding_raw).hexdigest()
        receipt["pre_run_bindings_sha256"] = pre_run_bindings_sha256
        bindings = json.loads(binding_raw, object_pairs_hook=_unique_json_object)
        source_bindings = _recovery_dispatch_inputs()
        if (
            not isinstance(bindings, dict)
            or frozenset(bindings)
            not in {
                frozenset(
                    {
                        "schema_version",
                        "run_id",
                        "pair_manifest_sha256",
                        "inputs",
                        "reviewed_image_ids",
                        "source_facts",
                    }
                ),
                frozenset(
                    {
                        "schema_version",
                        "run_id",
                        "pair_manifest_sha256",
                        "inputs",
                        "reviewed_image_ids",
                        "source_facts",
                        "driver_sha256",
                    }
                ),
            }
            or type(bindings.get("schema_version")) is not int
            or bindings.get("schema_version") != 1
            or bindings.get("run_id") != run_id
            or bindings.get("pair_manifest_sha256") != expected_pair_sha
            or bindings.get("inputs") != source_bindings
        ):
            raise ValueError("pre_run_source_binding_mismatch")
        receipt["source_bindings"] = source_bindings
        if "driver_sha256" in bindings:
            driver_sha = bindings["driver_sha256"]
            if not isinstance(driver_sha, str) or re.fullmatch(r"[0-9a-f]{64}", driver_sha) is None:
                raise ValueError("pre_run_driver_binding_invalid")
            receipt["driver_sha256"] = driver_sha
        helper = _helper()
        reviewed = bindings.get("reviewed_image_ids")
        if (
            not isinstance(reviewed, dict)
            or set(reviewed) != {"candidate", "recovery"}
            or not isinstance(reviewed.get("candidate"), str)
            or not isinstance(reviewed.get("recovery"), str)
            or helper.IMAGE_ID_PATTERN.fullmatch(reviewed["candidate"]) is None
            or helper.IMAGE_ID_PATTERN.fullmatch(reviewed["recovery"]) is None
        ):
            raise ValueError("pre_run_reviewed_images_invalid")
        reviewed_image_ids = {
            "candidate": reviewed["candidate"],
            "recovery": reviewed["recovery"],
        }
        pair_source_facts, pair_source_fact_files = _read_pair_source_facts(
            helper, bindings.get("source_facts"), pair_directory=manifest_path.parent
        )
        receipt["reviewed_image_ids"] = dict(reviewed_image_ids)
        receipt["pair_source_facts"] = {
            name: {"name": source_path.name, "sha256": digest}
            for name, (source_path, digest) in sorted(pair_source_fact_files.items())
        }
        manifest, pair_sha = _read_recovery_pair(
            helper,
            manifest_path,
            expected_pair_sha,
            expected_candidate_image_id=reviewed_image_ids["candidate"],
            expected_recovery_image_id=reviewed_image_ids["recovery"],
            facts=pair_source_facts,
        )
        receipt["release_pair_manifest"] = {
            "name": manifest_path.name,
            "sha256": pair_sha,
            "revision": manifest["revision"],
        }
        candidate = manifest["candidate"]
        recovery = manifest["recovery"]
        revision = manifest["revision"]
        assert isinstance(candidate, dict) and isinstance(recovery, dict)
        assert isinstance(revision, str)
        candidate_ref = helper._local_image_ref(revision)
        recovery_ref = helper._local_recovery_image_ref(revision)
        target = {
            "transport": helper.GITHUB_RELEASE_TRANSPORT,
            "revision": revision,
            "image_ref": candidate_ref,
            "image_digest": candidate["archive_sha256"],
            "archive_sha256": candidate["archive_sha256"],
            "archive_size": candidate["archive_size"],
            "image_id": candidate["image_id"],
            "platform": candidate["platform"],
            "schema_version": candidate["schema_version"],
            "pair_manifest_sha256": pair_sha,
            "source_context_sha256": manifest["source_context_sha256"],
            "migration_sha256": manifest["migration"]["sha256"],
            "recovery_image_ref": recovery_ref,
            "recovery_image_id": recovery["image_id"],
            "recovery_archive_sha256": recovery["archive_sha256"],
            "recovery_archive_size": recovery["archive_size"],
            "recovery_platform": recovery["platform"],
            "recovery_schema_version": recovery["schema_version"],
            "recovery_base_revision": recovery["base_revision"],
            "recovery_overlay_sha256": recovery["overlay_sha256"],
        }
        receipt["candidate_image_id"] = target["image_id"]
        receipt["recovery_image_id"] = target["recovery_image_id"]
        temporary = tempfile.TemporaryDirectory(prefix="r120-recovery-dispatch-", dir=tmp_path)
        temporary_root = Path(temporary.name)
        os.chdir(temporary_root)
        empty_docker_config = temporary_root / "docker-config"
        empty_docker_config.mkdir(mode=0o700)
        os.environ["DOCKER_CONFIG"] = str(empty_docker_config)
        docker_config_changed = True

        for ref, expected in (
            (candidate_ref, target["image_id"]),
            (recovery_ref, target["recovery_image_id"]),
        ):
            if (
                helper._image_id(ref) != expected
                or helper._image_revision(ref) != revision
                or helper._image_platform(ref) != "linux/amd64"
                or helper._image_schema(ref) != helper.ASSISTANT_MINIMUM_SCHEMA
            ):
                raise ValueError("local_image_identity_mismatch")

        state = temporary_root / "state"
        release_root = state / "releases"
        release_root.mkdir(parents=True, mode=0o700)
        project_candidate = f"r120-recovery-dispatch-{run_id}"
        volume_candidate = f"r120-recovery-data-{run_id}"
        volume_labels = {
            "com.stock-probs.task": "R-ASTRA-120",
            "com.stock-probs.run": run_id,
        }
        compose_file = temporary_root / "compose.integration.yaml"
        app_env = temporary_root / "synthetic-compose.env"
        runtime_file = state / "runtime.env"
        for name, value in {
            "STATE_ROOT": state,
            "SOURCE_ROOT": state / "source",
            "RELEASE_ROOT": release_root,
            "PLAN_ROOT": state / "plans",
            "CURRENT_RECORD": state / "current.json",
            "FAILED_RECORD": state / "failed.json",
            "COMPOSE_FILE": compose_file,
            "APP_ENV_FILE": app_env,
            "RUNTIME_ENV_FILE": runtime_file,
            "AUDIT_LOG": state / "deploy.jsonl",
            "LOCK_FILE": state / "deploy.lock",
            "PROJECT_NAME": project_candidate,
        }.items():
            setattr(helper, name, value)
        helper.HEALTH_URL = "http://127.0.0.1:1/api/v1/readiness"
        if helper.CURRENT_RECORD.exists() or helper.FAILED_RECORD.exists():
            raise ValueError("temporary_release_state_not_empty")
        receipt["current_record_initially_absent"] = True

        compose_bytes = _dispatch_compose_yaml(volume_candidate, run_id)
        _write_dispatch_file(compose_file, compose_bytes)
        secret = secrets.token_hex(32)
        app_env_bytes = (
            f"STOCK_PROBS_PROVIDER=fixture\n"
            f"STOCK_PROBS_PUBLIC_ORIGIN=https://signal-ledger.invalid\n"
            f"STOCK_PROBS_AUTH_MODE=github\n"
            f"STOCK_PROBS_AUTH_SESSION_SECRET={secret}\n"
            f"STOCK_PROBS_GITHUB_CLIENT_ID=synthetic-client-id\n"
            f"STOCK_PROBS_GITHUB_CLIENT_SECRET=synthetic-client-secret\n"
            f"STOCK_PROBS_GITHUB_REDIRECT_URI=https://signal-ledger.invalid/auth/github/callback\n"
            f"STOCK_PROBS_OWNER_GITHUB_ID=1\n"
        ).encode()
        _write_dispatch_file(app_env, app_env_bytes)
        receipt["compose_project"] = project_candidate
        receipt["compose_sha256"] = hashlib.sha256(compose_bytes).hexdigest()

        existing_project_containers = set(
            _dispatch_docker(
                helper,
                [
                    "docker",
                    "ps",
                    "--all",
                    "--quiet",
                    "--no-trunc",
                    "--filter",
                    f"label=com.docker.compose.project={project_candidate}",
                ],
            ).split()
        )
        existing_project_networks = set(
            _dispatch_docker(
                helper,
                [
                    "docker",
                    "network",
                    "ls",
                    "--quiet",
                    "--no-trunc",
                    "--filter",
                    f"label=com.docker.compose.project={project_candidate}",
                ],
            ).split()
        )
        existing_run_volumes = set(
            _dispatch_docker(
                helper,
                [
                    "docker",
                    "volume",
                    "ls",
                    "--quiet",
                    "--filter",
                    f"label=com.stock-probs.run={run_id}",
                ],
            ).split()
        )
        existing_volume_names = _dispatch_all_resource_ids(helper, "volume")
        baseline_container_ids = _dispatch_all_resource_ids(helper, "container")
        baseline_network_ids = _dispatch_all_resource_ids(helper, "network")
        ownership = _DispatchCleanupOwnership(
            task_id="R-ASTRA-120",
            run_id=run_id,
            project=project_candidate,
            volume=volume_candidate,
        )
        if not ownership.establish_preflight(
            project_container_ids=existing_project_containers,
            project_network_ids=existing_project_networks,
            run_volume_names=existing_run_volumes,
            volume_names=existing_volume_names,
            all_container_ids=baseline_container_ids,
            all_network_ids=baseline_network_ids,
        ):
            raise ValueError("task_docker_identity_already_exists")
        project = project_candidate
        volume = volume_candidate

        seed_root = temporary_root / "seed"
        seed_settings = Settings(
            data_dir=seed_root,
            database_path=seed_root / "stock_probs.sqlite3",
            backup_dir=seed_root / "backups",
            provider="fixture",
        )
        _seed_schema12_failure(seed_settings)
        seed_database = temporary_root / "schema12.sqlite3"
        with (
            sqlite3.connect(seed_settings.database_path) as source,
            sqlite3.connect(seed_database) as destination,
        ):
            source.backup(destination)
        _dispatch_docker(
            helper,
            [
                "docker",
                "volume",
                "create",
                "--label",
                "com.stock-probs.task=R-ASTRA-120",
                "--label",
                f"com.stock-probs.run={run_id}",
                volume,
            ],
        )
        volume_result = _dispatch_docker(
            helper,
            ["docker", "volume", "inspect", "--format", "{{.Name}}|{{json .Labels}}", volume],
        )
        volume_parts = volume_result.split("|", 1)
        if (
            len(volume_parts) != 2
            or volume_parts[0] != volume
            or json.loads(volume_parts[1]) != volume_labels
            or not ownership.record_volume(
                volume,
                phase="explicit_volume_create",
                labels=json.loads(volume_parts[1]) if len(volume_parts) == 2 else None,
            )
        ):
            raise ValueError("temporary_volume_identity_invalid")
        receipt["volume"] = {"name": volume, "labels": volume_labels}

        seed_cid = temporary_root / "seed-container.cid"
        # The candidate image creates /data as UID/GID 10001 mode 0700; Docker volume copy-up
        # preserves that ownership because this seed mount does not request volume-nocopy.
        seed_script = (
            "from pathlib import Path; import shutil; "
            "shutil.copyfile('/seed.sqlite3', '/data/stock_probs.sqlite3'); "
            "Path('/data/stock_probs.sqlite3').chmod(0o600)"
        )
        seed_containers_before = _dispatch_all_resource_ids(helper, "container")
        seed_networks_before = _dispatch_all_resource_ids(helper, "network")
        try:
            _dispatch_docker(
                helper,
                [
                    "docker",
                    "run",
                    "--rm",
                    "--pull",
                    "never",
                    "--network",
                    "none",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--pids-limit",
                    "64",
                    "--memory",
                    "256m",
                    "--cpus",
                    "0.5",
                    "--user",
                    "10001:10001",
                    "--tmpfs",
                    # The --rm seed container owns this private, non-executable tmpfs.
                    (
                        "/tmp:rw,nosuid,nodev,noexec,size=16m,"  # noqa: S108
                        "uid=10001,gid=10001,mode=0700"
                    ),
                    "--label",
                    "com.stock-probs.task=R-ASTRA-120",
                    "--label",
                    f"com.stock-probs.run={run_id}",
                    "--mount",
                    f"type=volume,src={volume},dst=/data",
                    "--mount",
                    f"type=bind,src={seed_database},dst=/seed.sqlite3,readonly",
                    "--cidfile",
                    str(seed_cid),
                    "--entrypoint",
                    "python",
                    candidate_ref,
                    "-c",
                    seed_script,
                ],
                timeout=180,
            )
        finally:
            _dispatch_capture_created_resources(
                helper,
                ownership,
                phase="seed_run",
                before_containers=seed_containers_before,
                before_networks=seed_networks_before,
                cleanup_errors=cleanup_errors,
            )
            if seed_cid.is_file() and not seed_cid.is_symlink():
                seed_id = seed_cid.read_text(encoding="ascii").strip()
                if helper.CONTAINER_ID_PATTERN.fullmatch(seed_id) is None:
                    raise ValueError("seed_container_id_invalid")

        helper._runtime_file(candidate_ref, "disabled")
        (
            schema_before,
            fixture_rows_before,
            fixture_owners_before,
            fixture_sha_before,
        ) = _dispatch_database_facts(helper, ownership, cleanup_errors)
        if (
            schema_before != helper.ASSISTANT_MINIMUM_SCHEMA - 1
            or fixture_rows_before != 1
            or fixture_owners_before != 1
        ):
            raise AssertionError("schema12_fixture_not_seeded")
        receipt["schema_version_before_candidate"] = schema_before
        receipt["preserved_fixture_row_count_before_candidate"] = fixture_rows_before
        receipt["preserved_fixture_owner_count_before_candidate"] = fixture_owners_before
        receipt["preserved_fixture_sha256_before_candidate"] = fixture_sha_before
        compose_digest = helper._compose_digest()
        target["compose_digest"] = compose_digest
        snapshot = helper._compose_snapshot_path(revision)
        _write_dispatch_file(snapshot, compose_bytes)

        original_up = helper._compose_up
        original_health = helper._health_check

        def observe_up(
            record: dict[str, Any],
            *,
            timeout: float = 180,
            compose_file: Path | None = None,
            force_recreate: bool = False,
        ) -> str:
            """Start the real service and record live image, mount, profile and port facts."""

            phase = "recovery_up" if record.get("release_role") == "recovery" else "candidate_up"
            containers_before = _dispatch_all_resource_ids(helper, "container")
            networks_before = _dispatch_all_resource_ids(helper, "network")
            try:
                result = original_up(
                    record,
                    timeout=timeout,
                    compose_file=compose_file,
                    force_recreate=force_recreate,
                )
            finally:
                _dispatch_capture_created_resources(
                    helper,
                    ownership,
                    phase=phase,
                    before_containers=containers_before,
                    before_networks=networks_before,
                    cleanup_errors=cleanup_errors,
                )
            active = _dispatch_docker(
                helper,
                [
                    "docker",
                    "compose",
                    "--ansi",
                    "never",
                    "--project-name",
                    project,
                    "--env-file",
                    str(app_env),
                    "--env-file",
                    str(runtime_file),
                    "--file",
                    str(helper.COMPOSE_FILE if compose_file is None else compose_file),
                    "ps",
                    "--quiet",
                    "app",
                ],
            )
            if helper.CONTAINER_ID_PATTERN.fullmatch(active) is None:
                raise ValueError("active_container_identity_invalid")
            facts = _dispatch_container_facts(helper, active)
            if not ownership.permits_container_removal(active, facts["labels"]):
                raise ValueError("active_container_ownership_unverified")
            expected_image = record.get("image_id")
            if facts["image_id"] != expected_image:
                raise ValueError("active_container_image_mismatch")
            mount_facts = _dispatch_profile(facts, project=project, run_id=run_id, volume=volume)
            internal = _dispatch_docker(
                helper,
                [
                    "docker",
                    "network",
                    "inspect",
                    "--format",
                    "{{.Internal}}",
                    mount_facts["network_name"],
                ],
            )
            if internal != "true":
                raise ValueError("container_network_not_internal")
            port = mount_facts["published_port"]
            assert isinstance(port, int)
            ports_seen.append(port)
            helper.HEALTH_URL = f"http://{mount_facts['published_host']}:{port}/api/v1/readiness"
            if active not in up_ids:
                up_ids.append(active)
            receipt["up_containers"].append(
                {
                    "container_id": active,
                    "image_id": expected_image,
                    "release_role": record.get("release_role", "candidate"),
                    **mount_facts,
                    "network_internal": True,
                }
            )
            return result

        def inject_candidate_failure() -> dict[str, Any]:
            """Inject exactly one candidate health failure and use real recovery health."""

            nonlocal health_failure_count
            if health_failure_count == 0:
                last = receipt["up_containers"][-1]
                if last["release_role"] != "candidate":
                    raise ValueError("candidate_failure_injection_order_invalid")
                health_failure_count += 1
                raise helper.HostError("readiness_failed")
            return original_health()

        helper._compose_up = observe_up
        helper._health_check = inject_candidate_failure
        receipt["phase"] = "apply_release"
        try:
            helper._apply_release(target)
        except helper.HostError as error:
            if error.code != "readiness_failed":
                raise
        else:
            raise AssertionError("candidate_health_failure_did_not_escape_apply_release")
        if health_failure_count != 1:
            raise AssertionError("candidate_health_failure_not_injected_exactly_once")

        ups = receipt["up_containers"]
        assert isinstance(ups, list) and len(ups) == 2
        candidate_up, recovery_up = ups
        assert candidate_up["release_role"] == "candidate"
        assert recovery_up["release_role"] == "recovery"
        assert recovery_up["image_id"] == target["recovery_image_id"]
        assert candidate_up["volume_name"] == recovery_up["volume_name"] == volume
        assert candidate_up["profile"] == recovery_up["profile"]
        assert candidate_up["network_internal"] is recovery_up["network_internal"] is True

        schema_after, row_count, owner_count, fixture_sha_after = _dispatch_database_facts(
            helper, ownership, cleanup_errors
        )
        if (
            schema_after != helper.ASSISTANT_MINIMUM_SCHEMA
            or row_count != 1
            or owner_count != 1
            or fixture_sha_after != fixture_sha_before
        ):
            raise AssertionError("schema13_fixture_data_not_preserved")
        current = json.loads(helper.CURRENT_RECORD.read_text(encoding="utf-8"))
        failed = json.loads(helper.FAILED_RECORD.read_text(encoding="utf-8"))
        if (
            current.get("release_role") != "recovery"
            or current.get("assistant_rollout_mode") != "disabled"
            or failed.get("status") != "failed_migrated"
            or failed.get("forward_recovery_succeeded") is not True
        ):
            raise AssertionError("release_recovery_records_invalid")

        # Exercise the public recovery selector after the candidate's automatic recovery has
        # already completed, using the same reviewed image pair and disposable data volume.
        rollback_request = json.dumps(
            {
                "operation": "rollback",
                "payload": {
                    "revision": revision,
                    "image_id": target["recovery_image_id"],
                },
            },
            separators=(",", ":"),
        ).encode("utf-8")
        rollback_operation, rollback_payload = helper._parse_request(rollback_request)
        if rollback_operation != "rollback":
            raise AssertionError("explicit_rollback_operation_not_parsed")
        rollback_result = helper._dispatch(rollback_operation, rollback_payload)
        receipt["typed_rollback_request_parsed_dispatched"] = True
        (
            schema_after_rollback,
            rows_after_rollback,
            owners_after_rollback,
            fixture_sha_after_rollback,
        ) = _dispatch_database_facts(helper, ownership, cleanup_errors)
        rollback_up = receipt["up_containers"][-1]
        current_after_rollback = json.loads(helper.CURRENT_RECORD.read_text(encoding="utf-8"))
        failed_after_rollback = json.loads(helper.FAILED_RECORD.read_text(encoding="utf-8"))
        rollback_health = rollback_result.get("health", {})
        rollback_assistant_health = rollback_health.get("assistant", {})
        if (
            len(receipt["up_containers"]) != 3
            or rollback_up["release_role"] != "recovery"
            or rollback_up["image_id"] != target["recovery_image_id"]
            or rollback_up["volume_name"] != volume
            or recovery_up["volume_name"] != volume
            or rollback_up["volume_source_sha256"] != recovery_up["volume_source_sha256"]
            or rollback_up["profile"] != recovery_up["profile"]
            or rollback_up["network_name"] != recovery_up["network_name"]
            or rollback_up["network_internal"] is not True
            or schema_after_rollback != helper.ASSISTANT_MINIMUM_SCHEMA
            or rows_after_rollback != 1
            or owners_after_rollback != 1
            or fixture_sha_after_rollback != fixture_sha_before
            or rollback_result.get("status") != "ok"
            or rollback_result.get("result") != "rolled_back"
            or rollback_result.get("revision") != revision
            or rollback_result.get("image_id") != target["recovery_image_id"]
            or rollback_result.get("archive_sha256") != target["recovery_archive_sha256"]
            or rollback_result.get("release_role") != "recovery"
            or rollback_result.get("pair_manifest_sha256") != pair_sha
            or rollback_result.get("schema_version") != helper.ASSISTANT_MINIMUM_SCHEMA
            or rollback_health.get("status") != "ready"
            or rollback_health.get("schema_version") != helper.ASSISTANT_MINIMUM_SCHEMA
            or rollback_assistant_health.get("enabled") is not False
            or rollback_assistant_health.get("status") != "disabled"
            or current_after_rollback.get("release_role") != "recovery"
            or current_after_rollback.get("image_id") != target["recovery_image_id"]
            or current_after_rollback.get("image_ref") != target["recovery_image_ref"]
            or current_after_rollback.get("image_digest") != target["recovery_archive_sha256"]
            or current_after_rollback.get("pair_manifest_sha256") != pair_sha
            or current_after_rollback.get("assistant_rollout_mode") != "disabled"
            or current_after_rollback.get("schema_version") != helper.ASSISTANT_MINIMUM_SCHEMA
            or failed_after_rollback != failed
        ):
            raise AssertionError("explicit_recorded_recovery_rollback_invalid")
        receipt.update(
            {
                "candidate_failure_injected_once": True,
                "schema_version_after_recovery": schema_after,
                "preserved_fixture_row_count": row_count,
                "preserved_fixture_owner_count": owner_count,
                "preserved_fixture_sha256_before_candidate": fixture_sha_before,
                "preserved_fixture_sha256_after_recovery": fixture_sha_after,
                "explicit_recovery_rollback_result": rollback_result,
                "typed_rollback_request_parsed_dispatched": receipt[
                    "typed_rollback_request_parsed_dispatched"
                ],
                "schema_version_after_explicit_rollback": schema_after_rollback,
                "preserved_fixture_row_count_after_explicit_rollback": rows_after_rollback,
                "preserved_fixture_owner_count_after_explicit_rollback": owners_after_rollback,
                "preserved_fixture_sha256_after_explicit_rollback": fixture_sha_after_rollback,
                "explicit_rollback_health": rollback_health,
                "explicit_rollback_profile_matches_forward_recovery": (
                    rollback_up["profile"] == recovery_up["profile"]
                    and rollback_up["volume_name"] == recovery_up["volume_name"]
                ),
                "current_release_role": current.get("release_role"),
                "current_rollout_mode": current.get("assistant_rollout_mode"),
                "failed_status": failed.get("status"),
                "failed_forward_recovery_succeeded": failed.get("forward_recovery_succeeded"),
                "phase": "assertions_passed",
                "result": "Pass",
            }
        )
    except BaseException as error:
        failure = error
        receipt["result"] = "Fail"
        receipt["failure_code"] = (
            error.code
            if helper is not None and isinstance(error, helper.HostError)
            else type(error).__name__
        )
    finally:
        if helper is not None and ownership is not None and ownership.preflight_passed:

            def inspect_container(resource_id: str) -> tuple[str, object]:
                parts = _dispatch_docker(
                    helper,
                    [
                        "docker",
                        "inspect",
                        "--format",
                        "{{.Id}}|{{json .Config.Labels}}",
                        resource_id,
                    ],
                ).split("|", 1)
                if len(parts) != 2:
                    raise ValueError("known_container_inspection_invalid")
                return parts[0], json.loads(parts[1])

            def remove_container(resource_id: str) -> None:
                _dispatch_docker(helper, ["docker", "rm", "--force", resource_id])

            def container_absent(resource_id: str) -> bool:
                return _dispatch_full_id_absent(helper, "container", resource_id)

            def inspect_network(resource_id: str) -> tuple[str, object]:
                parts = _dispatch_docker(
                    helper,
                    [
                        "docker",
                        "network",
                        "inspect",
                        "--format",
                        "{{.Id}}|{{json .Labels}}",
                        resource_id,
                    ],
                ).split("|", 1)
                if len(parts) != 2:
                    raise ValueError("known_network_inspection_invalid")
                return parts[0], json.loads(parts[1])

            def remove_network(resource_id: str) -> None:
                _dispatch_docker(helper, ["docker", "network", "rm", resource_id])

            def network_absent(resource_id: str) -> bool:
                return _dispatch_full_id_absent(helper, "network", resource_id)

            def inspect_volume(volume_name: str) -> tuple[str, object]:
                parts = _dispatch_docker(
                    helper,
                    [
                        "docker",
                        "volume",
                        "inspect",
                        "--format",
                        "{{.Name}}|{{json .Labels}}",
                        volume_name,
                    ],
                ).split("|", 1)
                if len(parts) != 2:
                    raise ValueError("known_volume_inspection_invalid")
                return parts[0], json.loads(parts[1])

            def volume_attached(volume_name: str) -> bool:
                return bool(
                    _dispatch_docker(
                        helper,
                        [
                            "docker",
                            "ps",
                            "--all",
                            "--quiet",
                            "--no-trunc",
                            "--filter",
                            f"volume={volume_name}",
                        ],
                    )
                )

            def remove_volume(volume_name: str) -> None:
                _dispatch_docker(helper, ["docker", "volume", "rm", volume_name])

            def volume_absent(volume_name: str) -> bool:
                return _dispatch_volume_absent(helper, volume_name)

            _dispatch_cleanup_owned_resources(
                ownership,
                inspect_container=inspect_container,
                remove_container=remove_container,
                container_absent=container_absent,
                inspect_network=inspect_network,
                remove_network=remove_network,
                network_absent=network_absent,
                inspect_volume=inspect_volume,
                volume_attached=volume_attached,
                remove_volume=remove_volume,
                volume_absent=volume_absent,
                cleanup_errors=cleanup_errors,
                removed_container_ids=receipt["owned_cleanup"]["removed_container_ids"],
                removed_volume_names=receipt["owned_cleanup"]["removed_volume_names"],
                already_absent_container_ids=receipt["owned_cleanup"][
                    "already_absent_container_ids"
                ],
                already_absent_network_ids=receipt["owned_cleanup"]["already_absent_network_ids"],
                already_absent_volume_names=receipt["owned_cleanup"]["already_absent_volume_names"],
            )
            try:
                remaining_project_containers = set(
                    _dispatch_docker(
                        helper,
                        [
                            "docker",
                            "ps",
                            "--all",
                            "--quiet",
                            "--no-trunc",
                            "--filter",
                            f"label=com.docker.compose.project={ownership.project}",
                        ],
                    ).split()
                )
                receipt["owned_cleanup"][
                    "project_containers_absent"
                ] = not remaining_project_containers
                if remaining_project_containers:
                    cleanup_errors.append("project_containers_remain_unmodified")
            except Exception:
                cleanup_errors.append("project_container_cleanup_unverified")
            try:
                remaining_project_networks = set(
                    _dispatch_docker(
                        helper,
                        [
                            "docker",
                            "network",
                            "ls",
                            "--quiet",
                            "--no-trunc",
                            "--filter",
                            f"label=com.docker.compose.project={ownership.project}",
                        ],
                    ).split()
                )
                receipt["owned_cleanup"]["project_networks_absent"] = not remaining_project_networks
                if remaining_project_networks:
                    cleanup_errors.append("project_networks_remain_unmodified")
            except Exception:
                cleanup_errors.append("project_network_cleanup_unverified")
            if volume is not None:
                try:
                    volume_is_absent = volume_absent(volume)
                    receipt["owned_cleanup"]["volume_absent"] = volume_is_absent
                    receipt["owned_cleanup"]["removed_volume"] = (
                        volume in receipt["owned_cleanup"]["removed_volume_names"]
                    )
                    if not volume_is_absent:
                        cleanup_errors.append("temporary_volume_remains_unmodified")
                except Exception:
                    cleanup_errors.append("temporary_volume_cleanup_unverified")
        for port in sorted(set(ports_seen)):
            try:
                with socket.socket() as probe:
                    probe.settimeout(1.0)
                    result = probe.connect_ex(("127.0.0.1", port))
                if result == 0:
                    cleanup_errors.append("loopback_listener_remains")
                elif result not in {errno.ECONNREFUSED, errno.EHOSTUNREACH, errno.ENETUNREACH}:
                    cleanup_errors.append("loopback_listener_cleanup_unverified")
                else:
                    receipt["owned_cleanup"]["loopback_ports_released"].append(port)
            except Exception:
                cleanup_errors.append("loopback_listener_cleanup_unverified")
        if helper is not None and source_bindings:
            try:
                receipt["source_bindings_unchanged_at_end"] = (
                    _recovery_dispatch_inputs() == source_bindings
                )
                if receipt["source_bindings_unchanged_at_end"] is not True:
                    cleanup_errors.append("source_binding_changed_during_run")
            except Exception:
                cleanup_errors.append("source_binding_end_check_failed")
        if helper is not None and manifest_value and expected_pair_sha and reviewed_image_ids:
            try:
                final_facts, final_fact_files = _read_pair_source_facts(
                    helper,
                    bindings.get("source_facts"),
                    pair_directory=manifest_path.parent,
                )
                receipt["pair_source_facts_unchanged_at_end"] = (
                    final_fact_files == pair_source_fact_files
                )
                if receipt["pair_source_facts_unchanged_at_end"] is not True:
                    cleanup_errors.append("pair_source_fact_changed_during_run")
                _final_manifest, final_pair_sha = _read_recovery_pair(
                    helper,
                    manifest_path,
                    expected_pair_sha,
                    expected_candidate_image_id=reviewed_image_ids["candidate"],
                    expected_recovery_image_id=reviewed_image_ids["recovery"],
                    facts=final_facts,
                )
                receipt["pair_manifest_unchanged_at_end"] = final_pair_sha == expected_pair_sha
                if receipt["pair_manifest_unchanged_at_end"] is not True:
                    cleanup_errors.append("pair_manifest_changed_during_run")
            except Exception:
                cleanup_errors.append("pair_manifest_or_source_fact_end_check_failed")
        if bindings_value and pre_run_bindings_sha256 is not None:
            try:
                final_binding_raw = _read_bounded_regular(bindings_path, 65_536, "pre_run_bindings")
                receipt["pre_run_bindings_unchanged_at_end"] = (
                    hashlib.sha256(final_binding_raw).hexdigest() == pre_run_bindings_sha256
                )
                if receipt["pre_run_bindings_unchanged_at_end"] is not True:
                    cleanup_errors.append("pre_run_bindings_changed_during_run")
            except Exception:
                cleanup_errors.append("pre_run_bindings_end_check_failed")
        if helper is not None and target is not None:
            try:
                receipt["owned_cleanup"]["images_retained"] = (
                    helper._image_id(target["image_ref"]) == target["image_id"]
                    and helper._image_id(target["recovery_image_ref"])
                    == target["recovery_image_id"]
                )
                if receipt["owned_cleanup"]["images_retained"] is not True:
                    cleanup_errors.append("reviewed_image_identity_changed")
            except Exception:
                receipt["owned_cleanup"]["images_retained"] = False
                cleanup_errors.append("reviewed_image_retention_unverified")
        try:
            if os.getcwd() != str(original_cwd):
                os.chdir(original_cwd)
        except Exception:
            cleanup_errors.append("working_directory_restore_failed")
        try:
            if temporary is not None:
                temporary.cleanup()
            if temporary_root is not None:
                receipt["owned_cleanup"][
                    "temporary_workspace_removed"
                ] = not temporary_root.exists()
                if temporary_root.exists():
                    cleanup_errors.append("temporary_workspace_remains")
        except Exception:
            cleanup_errors.append("temporary_workspace_cleanup_unverified")
        if docker_config_changed:
            if original_docker_config is None:
                os.environ.pop("DOCKER_CONFIG", None)
            else:
                os.environ["DOCKER_CONFIG"] = original_docker_config
        for field in (
            "removed_container_ids",
            "removed_volume_names",
            "already_absent_container_ids",
            "already_absent_network_ids",
            "already_absent_volume_names",
        ):
            receipt["owned_cleanup"][field] = sorted(set(receipt["owned_cleanup"][field]))
        receipt["owned_cleanup"]["created_resource_phases"] = {
            "containers": {
                resource_id: sorted(phases)
                for resource_id, phases in sorted(
                    (ownership.created_container_phases if ownership is not None else {}).items()
                )
            },
            "networks": {
                resource_id: sorted(phases)
                for resource_id, phases in sorted(
                    (ownership.created_network_phases if ownership is not None else {}).items()
                )
            },
            "volumes": {
                name: sorted(phases)
                for name, phases in sorted(
                    (ownership.created_volume_phases if ownership is not None else {}).items()
                )
            },
        }
        if cleanup_errors:
            receipt["result"] = "Fail"
            receipt["failure_code"] = receipt["failure_code"] or "owned_cleanup_failed"
        cleanup_started = bool(
            ownership is not None
            and (
                ownership.created_container_phases
                or ownership.created_network_phases
                or ownership.created_volume_phases
            )
        )
        receipt["owned_cleanup"]["result"] = (
            "Fail" if cleanup_errors else "Pass" if cleanup_started else "not_required"
        )
        receipt["cleanup_errors"] = sorted(set(cleanup_errors))
        receipt["ended_at"] = datetime.now(UTC).isoformat()
        receipt["candidate_failure_injected_once"] = health_failure_count == 1
        if artifact_ready:
            try:
                if receipt_path.exists() or receipt_path.is_symlink():
                    failure = failure or FileExistsError("run_receipt_already_exists")
                else:
                    _write_dispatch_receipt(receipt_path, receipt)
            except Exception as error:
                failure = failure or error

    if failure is not None:
        raise failure
    if cleanup_errors or receipt.get("result") != "Pass":
        pytest.fail("disposable recovery dispatch or its exact cleanup did not pass")


def _dispatch_mock_cleanup_callbacks(
    operations: list[tuple[str, str]],
    *,
    container_labels: dict[str, object] | None = None,
    network_labels: dict[str, object] | None = None,
    volume_labels: dict[str, object] | None = None,
    attached_volumes: set[str] | None = None,
    absent_volumes: set[str] | None = None,
    absent_container_ids: set[str] | None = None,
    absent_network_ids: set[str] | None = None,
    absent_volume_names: set[str] | None = None,
    absence_lookup_errors: set[str] | None = None,
) -> dict[str, Callable[..., object]]:
    """Return Docker-free callbacks that record each inspection and mutation."""

    removed_containers: set[str] = set()
    removed_networks: set[str] = set()
    removed_volumes: set[str] = set()

    def _lookup_failed(resource_id: str) -> None:
        if resource_id in (absence_lookup_errors or set()):
            raise OSError("mock_absence_lookup_failed")

    def inspect_container(resource_id: str) -> tuple[str, object]:
        operations.append(("inspect_container", resource_id))
        return resource_id, (container_labels or {}).get(resource_id, {})

    def remove_container(resource_id: str) -> None:
        operations.append(("remove_container", resource_id))
        removed_containers.add(resource_id)

    def container_absent(resource_id: str) -> bool:
        operations.append(("container_absent", resource_id))
        _lookup_failed(resource_id)
        return resource_id in (absent_container_ids or set()) or resource_id in removed_containers

    def inspect_network(resource_id: str) -> tuple[str, object]:
        operations.append(("inspect_network", resource_id))
        return resource_id, (network_labels or {}).get(resource_id, {})

    def remove_network(resource_id: str) -> None:
        operations.append(("remove_network", resource_id))
        removed_networks.add(resource_id)

    def network_absent(resource_id: str) -> bool:
        operations.append(("network_absent", resource_id))
        _lookup_failed(resource_id)
        return resource_id in (absent_network_ids or set()) or resource_id in removed_networks

    def inspect_volume(volume_name: str) -> tuple[str, object]:
        operations.append(("inspect_volume", volume_name))
        return volume_name, (volume_labels or {}).get(volume_name, {})

    def volume_attached(volume_name: str) -> bool:
        operations.append(("volume_attached", volume_name))
        return volume_name in (attached_volumes or set())

    def remove_volume(volume_name: str) -> None:
        operations.append(("remove_volume", volume_name))
        removed_volumes.add(volume_name)

    def volume_absent(volume_name: str) -> bool:
        operations.append(("volume_absent", volume_name))
        _lookup_failed(volume_name)
        if volume_name in (absent_volume_names or set()):
            return True
        if volume_name not in removed_volumes:
            return False
        absent_after_remove = absent_volumes if absent_volumes is not None else {volume_name}
        return volume_name in absent_after_remove

    return {
        "inspect_container": inspect_container,
        "remove_container": remove_container,
        "container_absent": container_absent,
        "inspect_network": inspect_network,
        "remove_network": remove_network,
        "network_absent": network_absent,
        "inspect_volume": inspect_volume,
        "volume_attached": volume_attached,
        "remove_volume": remove_volume,
        "volume_absent": volume_absent,
    }


def _dispatch_test_ownership(
    *,
    baseline_container_ids: set[str] | None = None,
    baseline_network_ids: set[str] | None = None,
    baseline_volume_names: set[str] | None = None,
) -> _DispatchCleanupOwnership:
    """Build a clean-preflight tracker for one mock-only ownership test."""

    ownership = _DispatchCleanupOwnership(
        task_id="R-ASTRA-120",
        run_id="0123456789abcdef",
        project="r120-recovery-dispatch-0123456789abcdef",
        volume="r120-recovery-data-0123456789abcdef",
    )
    assert ownership.establish_preflight(
        project_container_ids=set(),
        project_network_ids=set(),
        run_volume_names=set(),
        volume_names=baseline_volume_names or set(),
        all_container_ids=baseline_container_ids or set(),
        all_network_ids=baseline_network_ids or set(),
    )
    return ownership


def _dispatch_run_mock_cleanup(
    ownership: _DispatchCleanupOwnership | None,
    operations: list[tuple[str, str]],
    *,
    container_labels: dict[str, object] | None = None,
    network_labels: dict[str, object] | None = None,
    volume_labels: dict[str, object] | None = None,
    attached_volumes: set[str] | None = None,
    absent_volumes: set[str] | None = None,
    absent_container_ids: set[str] | None = None,
    absent_network_ids: set[str] | None = None,
    absent_volume_names: set[str] | None = None,
    absence_lookup_errors: set[str] | None = None,
    recorded_absences: dict[str, list[str]] | None = None,
    recorded_volume_removals: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Call the exact proposal cleanup policy with mock-only resource operations."""

    errors: list[str] = []
    removed_container_ids: list[str] = []
    removed_volume_names: list[str] = []
    recorded_absences = recorded_absences if recorded_absences is not None else {}
    absent_containers: list[str] = []
    absent_networks: list[str] = []
    already_absent_volumes: list[str] = []
    _dispatch_cleanup_owned_resources(
        ownership,
        **_dispatch_mock_cleanup_callbacks(
            operations,
            container_labels=container_labels,
            network_labels=network_labels,
            volume_labels=volume_labels,
            attached_volumes=attached_volumes,
            absent_volumes=absent_volumes,
            absent_container_ids=absent_container_ids,
            absent_network_ids=absent_network_ids,
            absent_volume_names=absent_volume_names,
            absence_lookup_errors=absence_lookup_errors,
        ),
        cleanup_errors=errors,
        removed_container_ids=removed_container_ids,
        removed_volume_names=removed_volume_names,
        already_absent_container_ids=absent_containers,
        already_absent_network_ids=absent_networks,
        already_absent_volume_names=already_absent_volumes,
    )
    recorded_absences.update(
        {
            "containers": absent_containers,
            "networks": absent_networks,
            "volumes": already_absent_volumes,
        }
    )
    if recorded_volume_removals is not None:
        recorded_volume_removals.extend(removed_volume_names)
    return errors, removed_container_ids


def test_dispatch_cleanup_skips_absent_candidate_and_removes_surviving_recovery() -> None:
    """A Compose-replaced candidate is recorded absent while the surviving recovery is cleaned."""

    candidate_id = "a" * 64
    recovery_id = "b" * 64
    network_id = "c" * 64
    volume_name = "r120-recovery-data-0123456789abcdef"
    labels = {
        "com.stock-probs.task": "R-ASTRA-120",
        "com.stock-probs.run": "0123456789abcdef",
        "com.docker.compose.project": "r120-recovery-dispatch-0123456789abcdef",
    }
    ownership = _dispatch_test_ownership()
    assert ownership.record_container(
        candidate_id,
        phase="candidate_up",
        labels=labels,
        before_ids=set(),
        after_ids={candidate_id},
    )
    assert ownership.record_container(
        recovery_id, phase="recovery_up", labels=labels, before_ids=set(), after_ids={recovery_id}
    )
    assert ownership.record_network(
        network_id, phase="candidate_up", labels=labels, before_ids=set(), after_ids={network_id}
    )
    assert ownership.record_volume(
        volume_name,
        phase="explicit_volume_create",
        labels={"com.stock-probs.task": "R-ASTRA-120", "com.stock-probs.run": "0123456789abcdef"},
    )
    operations: list[tuple[str, str]] = []
    recorded_absences: dict[str, list[str]] = {}
    recorded_volume_removals: list[str] = []
    errors, removed = _dispatch_run_mock_cleanup(
        ownership,
        operations,
        container_labels={candidate_id: labels, recovery_id: labels},
        network_labels={network_id: labels},
        volume_labels={
            volume_name: {
                "com.stock-probs.task": "R-ASTRA-120",
                "com.stock-probs.run": "0123456789abcdef",
            }
        },
        absent_container_ids={candidate_id},
        absent_network_ids={network_id},
        absent_volume_names={volume_name},
        recorded_absences=recorded_absences,
        recorded_volume_removals=recorded_volume_removals,
    )
    assert errors == []
    assert removed == [recovery_id]
    assert recorded_absences == {
        "containers": [candidate_id],
        "networks": [network_id],
        "volumes": [volume_name],
    }
    assert recorded_volume_removals == []
    assert operations == [
        ("container_absent", candidate_id),
        ("container_absent", recovery_id),
        ("inspect_container", recovery_id),
        ("remove_container", recovery_id),
        ("container_absent", recovery_id),
        ("network_absent", network_id),
        ("volume_absent", volume_name),
    ]


def test_dispatch_cleanup_absence_lookup_failure_fails_closed() -> None:
    """A failed exact-ID absence lookup never falls through to inspect or removal."""

    resource_id = "e" * 64
    labels = {
        "com.stock-probs.task": "R-ASTRA-120",
        "com.stock-probs.run": "0123456789abcdef",
        "com.docker.compose.project": "r120-recovery-dispatch-0123456789abcdef",
    }
    ownership = _dispatch_test_ownership()
    assert ownership.record_container(
        resource_id,
        phase="candidate_up",
        labels=labels,
        before_ids=set(),
        after_ids={resource_id},
    )
    operations: list[tuple[str, str]] = []
    recorded_absences: dict[str, list[str]] = {}
    errors, removed = _dispatch_run_mock_cleanup(
        ownership,
        operations,
        container_labels={resource_id: labels},
        absence_lookup_errors={resource_id},
        recorded_absences=recorded_absences,
    )
    assert errors == ["known_container_cleanup_unverified"]
    assert removed == []
    assert recorded_absences == {"containers": [], "networks": [], "volumes": []}
    assert operations == [("container_absent", resource_id)]


@pytest.mark.parametrize(
    ("project_containers", "project_networks", "run_volumes", "volume_names"),
    [
        ({"a" * 64}, set(), set(), set()),
        (set(), {"b" * 64}, set(), set()),
        (set(), set(), {"foreign-volume"}, set()),
        (set(), set(), set(), {"r120-recovery-data-0123456789abcdef"}),
    ],
)
def test_dispatch_cleanup_collision_preflight_performs_no_mutation(
    project_containers: set[str],
    project_networks: set[str],
    run_volumes: set[str],
    volume_names: set[str],
) -> None:
    """A colliding project prevents ownership and makes cleanup a no-op."""

    ownership = _DispatchCleanupOwnership(
        task_id="R-ASTRA-120",
        run_id="0123456789abcdef",
        project="r120-recovery-dispatch-0123456789abcdef",
        volume="r120-recovery-data-0123456789abcdef",
    )
    assert not ownership.establish_preflight(
        project_container_ids=project_containers,
        project_network_ids=project_networks,
        run_volume_names=run_volumes,
        volume_names=volume_names,
        all_container_ids=project_containers,
        all_network_ids=project_networks,
    )
    operations: list[tuple[str, str]] = []
    errors, removed = _dispatch_run_mock_cleanup(ownership, operations)
    assert operations == []
    assert errors == []
    assert removed == []


def test_dispatch_cleanup_clean_preflight_without_creation_is_noop() -> None:
    """Passing preflight alone does not grant cleanup authority over resources."""

    ownership = _dispatch_test_ownership()
    operations: list[tuple[str, str]] = []
    errors, removed = _dispatch_run_mock_cleanup(ownership, operations)
    assert operations == []
    assert errors == []
    assert removed == []


def test_dispatch_cleanup_rejects_baseline_and_foreign_resources() -> None:
    """Existing IDs and mismatched labels are never added to cleanup ownership."""

    existing_id = "a" * 64
    foreign_id = "b" * 64
    untracked_id = "d" * 64
    ownership = _dispatch_test_ownership(baseline_container_ids={existing_id})
    expected_labels = {
        "com.stock-probs.task": "R-ASTRA-120",
        "com.stock-probs.run": "0123456789abcdef",
        "com.docker.compose.project": "r120-recovery-dispatch-0123456789abcdef",
    }
    foreign_labels = {**expected_labels, "com.stock-probs.run": "ffffffffffffffff"}
    assert not ownership.record_container(
        existing_id,
        phase="candidate_up",
        labels=expected_labels,
        before_ids=set(),
        after_ids={existing_id},
    )
    assert not ownership.record_container(
        foreign_id,
        phase="candidate_up",
        labels=foreign_labels,
        before_ids=set(),
        after_ids={foreign_id},
    )
    operations: list[tuple[str, str]] = []
    errors, removed = _dispatch_run_mock_cleanup(
        ownership,
        operations,
        container_labels={
            existing_id: expected_labels,
            foreign_id: foreign_labels,
            untracked_id: expected_labels,
        },
    )
    assert operations == []
    assert errors == []
    assert removed == []


def test_dispatch_cleanup_removes_only_a_tracked_owned_full_id() -> None:
    """A new ID is removed only after exact-ID and task/run/project revalidation."""

    resource_id = "a" * 64
    labels = {
        "com.stock-probs.task": "R-ASTRA-120",
        "com.stock-probs.run": "0123456789abcdef",
        "com.docker.compose.project": "r120-recovery-dispatch-0123456789abcdef",
    }
    ownership = _dispatch_test_ownership()
    assert ownership.record_container(
        resource_id,
        phase="candidate_up",
        labels=labels,
        before_ids=set(),
        after_ids={resource_id},
    )
    operations: list[tuple[str, str]] = []
    errors, removed = _dispatch_run_mock_cleanup(
        ownership,
        operations,
        container_labels={resource_id: labels},
    )
    assert errors == []
    assert removed == [resource_id]
    assert operations == [
        ("container_absent", resource_id),
        ("inspect_container", resource_id),
        ("remove_container", resource_id),
        ("container_absent", resource_id),
    ]


def test_dispatch_cleanup_does_not_remove_known_id_after_label_change() -> None:
    """Removal fails closed when a tracked ID no longer carries its task/run labels."""

    resource_id = "c" * 64
    original_labels = {
        "com.stock-probs.task": "R-ASTRA-120",
        "com.stock-probs.run": "0123456789abcdef",
        "com.docker.compose.project": "r120-recovery-dispatch-0123456789abcdef",
    }
    changed_labels = {**original_labels, "com.stock-probs.task": "other-task"}
    ownership = _dispatch_test_ownership()
    assert ownership.record_container(
        resource_id,
        phase="recovery_up",
        labels=original_labels,
        before_ids=set(),
        after_ids={resource_id},
    )
    operations: list[tuple[str, str]] = []
    errors, removed = _dispatch_run_mock_cleanup(
        ownership,
        operations,
        container_labels={resource_id: changed_labels},
    )
    assert errors == ["known_container_identity_changed"]
    assert removed == []
    assert operations == [
        ("container_absent", resource_id),
        ("inspect_container", resource_id),
    ]


def test_dispatch_cleanup_revalidates_owned_network_and_volume() -> None:
    """Network IDs and the fixed volume are removed only with current matching labels."""

    network_id = "d" * 64
    network_labels = {
        "com.stock-probs.task": "R-ASTRA-120",
        "com.stock-probs.run": "0123456789abcdef",
        "com.docker.compose.project": "r120-recovery-dispatch-0123456789abcdef",
    }
    volume_name = "r120-recovery-data-0123456789abcdef"
    volume_labels = {
        "com.stock-probs.task": "R-ASTRA-120",
        "com.stock-probs.run": "0123456789abcdef",
    }
    ownership = _dispatch_test_ownership()
    assert ownership.record_network(
        network_id,
        phase="candidate_up",
        labels=network_labels,
        before_ids=set(),
        after_ids={network_id},
    )
    assert ownership.record_volume(
        volume_name,
        phase="explicit_volume_create",
        labels=volume_labels,
    )
    operations: list[tuple[str, str]] = []
    errors, removed = _dispatch_run_mock_cleanup(
        ownership,
        operations,
        network_labels={network_id: network_labels},
        volume_labels={volume_name: volume_labels},
    )
    assert errors == []
    assert removed == []
    assert operations == [
        ("network_absent", network_id),
        ("inspect_network", network_id),
        ("remove_network", network_id),
        ("network_absent", network_id),
        ("volume_absent", volume_name),
        ("inspect_volume", volume_name),
        ("volume_attached", volume_name),
        ("remove_volume", volume_name),
        ("volume_absent", volume_name),
    ]


def _schema13_release_record(helper: Any) -> dict[str, Any]:
    """Return the pinned candidate/recovery metadata stored during schema-13 staging."""
    revision = "a" * 40
    candidate_digest = "d" * 64
    return {
        "revision": revision,
        "transport": helper.GITHUB_RELEASE_TRANSPORT,
        "image_ref": helper._local_image_ref(revision),
        "image_digest": candidate_digest,
        "archive_sha256": candidate_digest,
        "image_id": "sha256:" + "e" * 64,
        "platform": "linux/amd64",
        "archive_size": 1024,
        "schema_version": 13,
        "compose_digest": "c" * 64,
        "pair_manifest_sha256": "f" * 64,
        "source_context_sha256": "1" * 64,
        "migration_sha256": helper.PAIR_MIGRATION_SHA256,
        "recovery_image_ref": helper._local_recovery_image_ref(revision),
        "recovery_image_id": "sha256:" + "2" * 64,
        "recovery_archive_sha256": "3" * 64,
        "recovery_archive_size": 2048,
        "recovery_platform": "linux/amd64",
        "recovery_schema_version": 13,
        "recovery_base_revision": helper.PAIR_BASE_REVISION,
        "recovery_overlay_sha256": "4" * 64,
    }


def _install_schema13_rollback_mocks(
    helper: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    record: dict[str, Any],
    *,
    database_schema: int | tuple[int, ...] = 13,
    readiness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Install deterministic host-operation seams for recovery rollback tests."""
    events: list[tuple[str, Any]] = []
    schema_results = iter(
        database_schema if isinstance(database_schema, tuple) else (database_schema,)
    )
    persisted: dict[Path, dict[str, Any]] = {}
    compose_snapshot = tmp_path / "compose.yaml"
    release_path = tmp_path / f"{record['revision']}.json"
    monkeypatch.setattr(helper, "RELEASE_ROOT", tmp_path)
    monkeypatch.setattr(helper, "CURRENT_RECORD", tmp_path / "current.json")
    monkeypatch.setattr(helper, "_exclusive_lock", nullcontext)
    monkeypatch.setattr(helper, "_ensure_layout", lambda: None)
    monkeypatch.setattr(
        helper,
        "_read_json",
        lambda path: record if path == release_path else persisted.get(path),
    )
    monkeypatch.setattr(
        helper,
        "_write_json",
        lambda path, value: persisted.__setitem__(path, dict(value)),
    )
    monkeypatch.setattr(helper, "_assert_record_compose_digest", lambda _: compose_snapshot)
    monkeypatch.setattr(
        helper,
        "_assert_loaded_image",
        lambda row: events.append(("loaded_candidate", row["image_id"])),
    )
    monkeypatch.setattr(
        helper,
        "_assert_loaded_recovery_image",
        lambda row: events.append(("loaded_recovery", row["recovery_image_id"])),
    )

    def database_schema_probe(image: str, **kwargs: Any) -> int:
        events.append(("schema", (image, kwargs.get("compose_file"))))
        fallback = database_schema[-1] if isinstance(database_schema, tuple) else database_schema
        return next(schema_results, fallback)

    monkeypatch.setattr(helper, "_database_schema", database_schema_probe)
    monkeypatch.setattr(helper, "_stop_app", lambda *args, **kwargs: events.append(("stop", args)))
    monkeypatch.setattr(
        helper,
        "_runtime_file",
        lambda image, mode="disabled": events.append(("runtime", (image, mode))),
    )
    monkeypatch.setattr(
        helper,
        "_compose_up",
        lambda row, **kwargs: events.append(("up", (row["image_ref"], kwargs.get("compose_file")))),
    )
    health = readiness or {
        "status": "ready",
        "schema_version": 13,
        "assistant": {"enabled": False, "status": "disabled"},
    }
    monkeypatch.setattr(helper, "_health_check", lambda: events.append(("health", None)) or health)
    monkeypatch.setattr(
        helper,
        "_audit",
        lambda *args, **kwargs: events.append(("audit", (args, kwargs))),
    )
    return {"events": events, "persisted": persisted, "compose_snapshot": compose_snapshot}


def test_rollback_selects_exact_recorded_schema13_recovery_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Select only the staged recovery image and persist the verified disabled state."""
    helper = _helper()
    record = _schema13_release_record(helper)
    observed = _install_schema13_rollback_mocks(helper, monkeypatch, tmp_path, record)
    monkeypatch.setattr(
        helper,
        "_assert_loaded_image",
        lambda _: pytest.fail("recovery must not require the candidate image to remain loaded"),
    )

    result = helper._rollback(record["revision"], record["recovery_image_id"])

    current = observed["persisted"][helper.CURRENT_RECORD]
    assert result["result"] == "rolled_back"
    assert result["image_id"] == record["recovery_image_id"]
    assert result["archive_sha256"] == record["recovery_archive_sha256"]
    assert result["pair_manifest_sha256"] == record["pair_manifest_sha256"]
    assert result["release_role"] == "recovery"
    assert current["release_role"] == "recovery"
    assert current["image_id"] == record["recovery_image_id"]
    assert current["assistant_rollout_mode"] == "disabled"
    assert current["schema_version"] == 13
    events = observed["events"]
    assert events.count(("stop", ())) == 1
    assert events.count(("health", None)) == 1
    assert result["health"] == {
        "status": "ready",
        "schema_version": 13,
        "assistant": {"enabled": False, "status": "disabled"},
    }
    assert all(
        event[1][0] == record["recovery_image_ref"] for event in events if event[0] == "schema"
    )
    assert ("runtime", (record["recovery_image_ref"], "disabled")) in events
    assert ("up", (record["recovery_image_ref"], observed["compose_snapshot"])) in events
    assert (
        "audit",
        (
            ("rollback", "applied"),
            {
                "revision": record["revision"],
                "image_digest": record["recovery_archive_sha256"],
                "image_id": record["recovery_image_id"],
                "release_role": "recovery",
                "pair_manifest_sha256": record["pair_manifest_sha256"],
                "compose_digest": record["compose_digest"],
                "schema_version": 13,
            },
        ),
    ) in events
    assert not any("restore" in str(event).casefold() for event in events)


@pytest.mark.parametrize(
    ("field", "value"),
    [("source_context_sha256", "bad"), ("migration_sha256", "5" * 64)],
)
def test_rollback_rejects_unbound_recovery_pair_before_stopping_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    """Reject malformed source or migration bindings before stopping the app."""
    helper = _helper()
    record = _schema13_release_record(helper)
    record[field] = value
    observed = _install_schema13_rollback_mocks(helper, monkeypatch, tmp_path, record)

    with pytest.raises(helper.HostError, match="recovery_image_record_invalid"):
        helper._rollback(record["revision"], record["recovery_image_id"])

    assert not any(event[0] in {"stop", "runtime", "up"} for event in observed["events"])
    assert helper.CURRENT_RECORD not in observed["persisted"]


def test_rollback_rejects_incompatible_actual_schema_for_recovery_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a schema mismatch before stopping or starting an application container."""
    helper = _helper()
    record = _schema13_release_record(helper)
    observed = _install_schema13_rollback_mocks(
        helper, monkeypatch, tmp_path, record, database_schema=12
    )

    with pytest.raises(helper.HostError, match="rollback_schema_incompatible"):
        helper._rollback(record["revision"], record["recovery_image_id"])

    assert not any(event[0] in {"stop", "runtime", "up"} for event in observed["events"])
    assert helper.CURRENT_RECORD not in observed["persisted"]


def test_rollback_rejects_unrecorded_image_id_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    record = _schema13_release_record(helper)
    observed = _install_schema13_rollback_mocks(helper, monkeypatch, tmp_path, record)

    with pytest.raises(helper.HostError, match="rollback_identity_mismatch"):
        helper._rollback(record["revision"], "sha256:" + "9" * 64)

    assert not any(
        event[0] in {"stop", "runtime", "up", "loaded_recovery"} for event in observed["events"]
    )
    assert helper.CURRENT_RECORD not in observed["persisted"]


def test_rollback_rechecks_schema_after_stopping_candidate_before_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stop the candidate and recheck the volume schema before activating recovery."""
    helper = _helper()
    record = _schema13_release_record(helper)
    observed = _install_schema13_rollback_mocks(
        helper, monkeypatch, tmp_path, record, database_schema=(13, 12)
    )

    with pytest.raises(helper.HostError, match="rollback_schema_incompatible"):
        helper._rollback(record["revision"], record["recovery_image_id"])

    events = observed["events"]
    schema_events = [index for index, event in enumerate(events) if event[0] == "schema"]
    stop_events = [index for index, event in enumerate(events) if event[0] == "stop"]
    assert len(schema_events) == 2
    assert schema_events[0] < stop_events[0] < schema_events[1] < stop_events[-1]
    assert not any(event[0] in {"runtime", "up", "health"} for event in events)
    assert helper.CURRENT_RECORD not in observed["persisted"]


@pytest.mark.parametrize(
    "readiness",
    [
        {"status": "ready", "schema_version": 12},
        {
            "status": "ready",
            "schema_version": 13,
            "assistant": {"enabled": False, "status": "unavailable"},
        },
    ],
)
def test_rollback_does_not_record_recovery_when_readiness_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    readiness: dict[str, Any],
) -> None:
    """Leave current release state untouched when recovery readiness is not verified."""
    helper = _helper()
    record = _schema13_release_record(helper)
    observed = _install_schema13_rollback_mocks(
        helper, monkeypatch, tmp_path, record, readiness=readiness
    )

    with pytest.raises(helper.HostError, match="recovery_activation_failed"):
        helper._rollback(record["revision"], record["recovery_image_id"])

    events = observed["events"]
    assert any(event[0] == "up" and event[1][0] == record["recovery_image_ref"] for event in events)
    assert events.count(("health", None)) == 1
    assert events.count(("stop", ())) == 1
    assert events.count(("stop", (observed["compose_snapshot"],))) >= 1
    assert helper.CURRENT_RECORD not in observed["persisted"]


def test_rollback_repeating_exact_recovery_selector_preserves_recovery_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated selection of the recorded recovery image preserves the same state."""
    helper = _helper()
    record = _schema13_release_record(helper)
    observed = _install_schema13_rollback_mocks(helper, monkeypatch, tmp_path, record)

    first = helper._rollback(record["revision"], record["recovery_image_id"])
    first_current = dict(observed["persisted"][helper.CURRENT_RECORD])
    second = helper._rollback(record["revision"], record["recovery_image_id"])

    current = observed["persisted"][helper.CURRENT_RECORD]
    assert first["image_id"] == second["image_id"] == record["recovery_image_id"]
    assert first_current == current
    assert current["release_role"] == "recovery"
    assert current["image_ref"] == record["recovery_image_ref"]
    assert current["pair_manifest_sha256"] == record["pair_manifest_sha256"]
    assert sum(event[0] == "up" for event in observed["events"]) == 2
    assert sum(event[0] == "health" for event in observed["events"]) == 2
    assert not any("restore" in str(event).casefold() for event in observed["events"])


def test_rollback_keeps_candidate_image_path_for_exact_candidate_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preserve the existing candidate-image rollback selector and behavior."""
    helper = _helper()
    record = _schema13_release_record(helper)
    observed = _install_schema13_rollback_mocks(helper, monkeypatch, tmp_path, record)

    result = helper._rollback(record["revision"], record["image_id"])

    current = observed["persisted"][helper.CURRENT_RECORD]
    assert result["result"] == "rolled_back"
    assert result["image_id"] == record["image_id"]
    assert current["image_ref"] == record["image_ref"]
    assert current["assistant_rollout_mode"] == "disabled"
    assert ("up", (record["image_ref"], observed["compose_snapshot"])) in observed["events"]
    assert not any(event[0] == "loaded_recovery" for event in observed["events"])
