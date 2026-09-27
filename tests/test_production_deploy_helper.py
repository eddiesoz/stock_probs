"""Host deployment helper tests keep release inputs fixed and responses bounded."""

from __future__ import annotations

import importlib.util
import json
import re
import stat
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / "scripts/production-deploy-helper.py"


def _helper():
    spec = importlib.util.spec_from_file_location("production_deploy_helper", HELPER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
            b'{"operation":"plan_deploy","payload":{"revision":"'
            + b"a" * 40
            + b'"}}'
        )

    with pytest.raises(helper.HostError, match="payload_invalid"):
        helper._parse_request(b'{"operation":"status","payload":{"path":"/tmp"}}')
    with pytest.raises(helper.HostError, match="operation_invalid"):
        helper._parse_request(b'{"operation":"shell","payload":{}}')


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
    assert '"127.0.0.1:8000:8000"' in compose
    assert "STOCK_PROBS_HOST: 127.0.0.1" in compose
    assert "signal-ledger-data:/data" in compose
    assert "STOCK_PROBS_AUTH_MODE: github" in compose
    assert "STOCK_PROBS_AUTH_SESSION_SECRET" in compose
    assert "STOCK_PROBS_GITHUB_CLIENT_SECRET" in compose
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
    assert "--token-file /etc/cloudflared/tunnel.token" in script
    assert "systemctl disable --now signal-ledger-cloudflared.service" in script
    assert "--shell /bin/sh" in script
    assert "systemctl reload ssh" in script
    assert "127.0.0.1:8000:8000" in (ROOT / "compose.production.yaml").read_text()
    assert "docker.sock" not in script


def test_local_release_publisher_uses_revision_bound_archive_and_digest() -> None:
    script = (ROOT / "scripts/publish-production-image.sh").read_text()
    assert 'PUBLISH_MODE="${SIGNAL_LEDGER_IMAGE_PUBLISH_MODE:-release}"' in script
    assert 'RELEASE_REPOSITORY="eddiesoz/stock_probs"' in script
    assert 'RELEASE_TAG_PREFIX="signal-ledger-"' in script
    assert 'RELEASE_ARCHIVE_PREFIX="signal-ledger-image-"' in script
    assert 'docker save "$IMAGE_TAG" | gzip -n -9' in script
    assert 'sha256sum "$ARCHIVE_PATH"' in script
    assert 'gh release create "$RELEASE_TAG" "$ARCHIVE_PATH"' in script
    assert 'gh release download "$RELEASE_TAG"' in script
    assert 'docker load --input "$DOWNLOADED_ARCHIVE"' in script
    assert 'DOWNLOADED_IMAGE_ID' in script
    assert '--target "$REVISION"' in script
    assert 'manifest.json' in script
    assert 'tarfile.open(layer_path, mode="r:*")' in script
    assert 'SIGNAL_LEDGER_IMAGE_PUBLISH_MODE must be release or ghcr.' in script


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
    events: list[tuple[str, str]] = []
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
    monkeypatch.setattr(helper, "_health_check", lambda: next(health_results))
    monkeypatch.setattr(helper, "_runtime_file", lambda image: events.append(("runtime", image)))
    monkeypatch.setattr(
        helper,
        "_verified_backup",
        lambda image, revision: events.append(("backup", image)) or {"name": "backup"},
    )
    monkeypatch.setattr(
        helper,
        "_compose",
        lambda *arguments, **_: events.append(("compose", str(arguments))) or "",
    )
    monkeypatch.setattr(helper, "_write_json", lambda *arguments, **_: None)
    monkeypatch.setattr(helper, "_audit", lambda *arguments, **_: None)

    result = helper._apply_release(target)

    assert result["status"] == "ok"
    backup_index = events.index(("backup", old_image))
    new_runtime_index = events.index(("runtime", new_image))
    stop_index = next(
        index for index, event in enumerate(events) if event[0] == "compose" and "stop" in event[1]
    )
    migrate_index = next(
        index
        for index, event in enumerate(events)
        if event[0] == "compose" and "migrate" in event[1]
    )
    assert backup_index < new_runtime_index < stop_index < migrate_index


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
        "schema_version": 7,
    }
    target = {
        "revision": new_revision,
        "image_ref": new_image,
        "image_digest": new_digest,
        "schema_version": 8,
    }
    events: list[tuple[str, object]] = []
    writes: list[tuple[Path, dict[str, object]]] = []
    health_calls = 0

    def health_check() -> dict[str, object]:
        nonlocal health_calls
        health_calls += 1
        if health_calls == 1:
            return {"status": "ready", "schema_version": 7}
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
    monkeypatch.setattr(helper, "_image_schema", lambda _: 7)
    monkeypatch.setattr(helper, "_health_check", health_check)
    monkeypatch.setattr(helper, "_runtime_file", lambda image: events.append(("runtime", image)))
    monkeypatch.setattr(
        helper,
        "_verified_backup",
        lambda image, revision: events.append(("backup", image)) or {"name": "backup"},
    )
    monkeypatch.setattr(
        helper,
        "_compose",
        lambda *arguments, **_: events.append(("compose", arguments)) or "",
    )
    monkeypatch.setattr(
        helper,
        "_database_schema",
        lambda image: events.append(("schema", image)) or 8,
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
    schema_index = next(index for index, event in enumerate(events) if event[0] == "schema")
    assert len(stop_events) == 2
    assert stop_events[-1] < schema_index
    failed_writes = [value for path, value in writes if path == helper.FAILED_RECORD]
    assert len(failed_writes) == 1
    failed = failed_writes[0]
    assert failed["status"] == "failed_migrated"
    assert failed["actual_schema_version"] == 8
    assert failed["failure_code"] == "readiness_failed"
    assert failed["rollback_attempted"] is False


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
    monkeypatch.setattr(helper, "_runtime_file", lambda image: events.append(("runtime", image)))
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
    monkeypatch.setattr(helper, "_compose_digest", lambda: "d" * 64)
    monkeypatch.setattr(
        helper,
        "_database_schema",
        lambda image: schema_calls.append(image) or 7,
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


@pytest.mark.parametrize("compose_digest_match", [True, False])
def test_failed_code_only_release_rolls_back_after_schema_probe(
    compose_digest_match: bool,
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
    monkeypatch.setattr(
        helper,
        "_compose_digest",
        lambda: "c" * 64 if compose_digest_match else "d" * 64,
    )
    monkeypatch.setattr(helper, "_runtime_file", lambda image: events.append(("runtime", image)))
    monkeypatch.setattr(
        helper,
        "_verified_backup",
        lambda image, revision: {"name": "backup"},
    )
    monkeypatch.setattr(
        helper,
        "_compose",
        lambda *arguments, **_: events.append(("compose", arguments)) or "",
    )
    monkeypatch.setattr(
        helper,
        "_database_schema",
        lambda image: events.append(("schema", image)) or 7,
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
    assert failed_writes[0]["rollback_attempted"] is compose_digest_match
    assert failed_writes[0]["rollback_succeeded"] is compose_digest_match
    schema_index = next(index for index, event in enumerate(events) if event[0] == "schema")
    up_indices = [
        index
        for index, event in enumerate(events)
        if event[0] == "compose" and event[1] == ("up", "--detach", "--no-build", "app")
    ]
    expected_up_count = 2 if compose_digest_match else 1
    assert len(up_indices) == expected_up_count
    if compose_digest_match:
        assert schema_index < up_indices[-1]


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
    monkeypatch.setattr(helper, "_runtime_file", lambda _: None)
    monkeypatch.setattr(
        helper,
        "_compose",
        lambda *arguments, **_: compose_calls.append(arguments) or "",
    )
    monkeypatch.setattr(helper, "_write_failed_record", lambda *arguments, **_: None)

    with pytest.raises(helper.HostError, match="database_schema_unavailable"):
        helper._apply_release(target)
    assert compose_calls == [("stop", "app")]


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

    monkeypatch.setattr(helper, "_runtime_file", lambda _: None)
    monkeypatch.setattr(
        helper,
        "_compose",
        lambda *arguments, **_: calls.append(arguments) or json.dumps(migrate_receipt),
    )
    monkeypatch.setattr(
        helper,
        "_verified_backup",
        lambda image, selected_revision: {
            "name": "pre-deploy-post-migration.spbackup",
            "verified": True,
        },
    )
    monkeypatch.setattr(helper, "_audit", lambda *arguments, **_: None)

    result = helper._verified_first_release_backup(image_ref, revision, 6, 8)

    assert calls == [
        ("run", "--rm", "--no-deps", "-T", "app", "stock-probs", "migrate")
    ]
    assert result == {
        "name": "pre-deploy-post-migration.spbackup",
        "verified": True,
        "pre_migration_backup": "pre-migration-v6-to-v8-20260927T120000Z.spbackup",
        "schema_version": 8,
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
    monkeypatch.setattr(helper, "_runtime_file", lambda _: None)
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
    monkeypatch.setattr(
        helper,
        "_database_schema",
        lambda _: events.append(("database_schema", 6)) or 6,
    )
    monkeypatch.setattr(
        helper,
        "_verified_first_release_backup",
        lambda *arguments: events.append(("legacy_backup", arguments))
        or {"name": "post-migration.spbackup", "verified": True},
    )
    monkeypatch.setattr(helper, "_runtime_file", lambda image: events.append(("runtime", image)))
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
