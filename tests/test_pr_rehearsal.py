from __future__ import annotations

import ast
import gzip
import hashlib
import io
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tarfile
from pathlib import Path
from subprocess import CompletedProcess
from types import SimpleNamespace

import pytest

from scripts import pin_pr_rehearsal_review
from scripts import pr_rehearsal_bootstrap as bootstrap
from scripts import pr_rehearsal_host_helper as host_helper
from scripts import rehearse_schema13 as schema13
from stock_probs.repository import Repository
from tools.deploy_mcp import pr_rehearsal as controller


def _review_pin_test_environment(monkeypatch, tmp_path: Path) -> Path:
    config_home = tmp_path / "config-home"
    config_home.mkdir(mode=0o700)
    identity = tmp_path / "test-identity"
    known_hosts = tmp_path / "test-known-hosts"
    identity.write_text("test-only identity metadata", encoding="utf-8")
    known_hosts.write_text("test-only known-hosts metadata", encoding="utf-8")
    identity.chmod(0o600)
    known_hosts.chmod(0o600)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("SIGNAL_LEDGER_OPERATOR_IDENTITY_FILE", str(identity))
    monkeypatch.setenv("SIGNAL_LEDGER_KNOWN_HOSTS_FILE", str(known_hosts))
    monkeypatch.delenv(controller.REVIEW_HEAD_ENV, raising=False)
    monkeypatch.delenv(controller.REVIEW_PAIR_ENV, raising=False)
    return config_home


def _owned_network_inspect_output(
    name: str,
    identifier: str,
    volume: str,
    revision: str,
    pair: str,
    *,
    endpoints: dict[str, object] | None = None,
    driver: str = "bridge",
    scope: str = "local",
    internal: str = "false",
    ipam_driver: str = "default",
    task: str = host_helper.TASK_ID,
    run_id: str | None = None,
) -> bytes:
    labels = ["true", task, revision, pair, volume, run_id or volume.rsplit("-", 1)[1]]
    fields = [identifier, name, driver, scope, internal, ipam_driver, *labels]
    return ("|".join(fields) + "|" + json.dumps(endpoints or {}) + "\n").encode()


def _app_profile_inspect_output(
    container: str,
    name: str,
    volume: str,
    revision: str,
    pair: str,
    role: str,
    network: str,
    network_id: str | None,
    memory: int,
    *,
    networks_override: dict[str, object] | None = None,
    port_bindings: object = None,
) -> bytes:
    run_id = volume.rsplit("-", 1)[1]
    labels = ["true", host_helper.TASK_ID, run_id, revision, pair, role, volume]
    networks = networks_override or (
        {network: {"NetworkID": network_id}} if role == "candidate" else {"none": {}}
    )
    fields = [
        container,
        f"/{name}",
        *labels,
        str(memory),
        str(memory),
        "100000",
        "100000",
        "0",
        "128",
        "true",
        network,
        '["ALL"]',
        '["SETUID","SETGID"]',
        json.dumps(port_bindings or {}),
        "0:0",
        '["no-new-privileges:true"]',
        json.dumps(networks),
    ]
    return ("|".join(fields) + "\n").encode()


def test_installed_helper_path_matches_bootstrap_asset_name() -> None:
    installed = bootstrap.ASSETS["host_helper"][1]
    assert Path(controller.HELPER_PATH).name == installed
    assert controller.SOURCE_ASSETS["host_helper"][1] == installed
    assert bootstrap.ASSETS["driver"][1] == controller.SOURCE_ASSETS["driver"][1]
    assert host_helper.INSTALL_ROOT / installed == Path(controller.HELPER_PATH)
    assert set(host_helper.INSTALLED_FILES) == {"host_helper.py", "seed.py", "native_driver.py"}


def test_pair_migration_pins_match_the_unreleased_migration_file() -> None:
    migration_path = (
        Path(host_helper.__file__).resolve().parents[1]
        / "src/stock_probs/migrations/013_assistant_conversations.sql"
    )
    source_digest = hashlib.sha256(migration_path.read_bytes()).hexdigest()
    assert source_digest == schema13.MIGRATION_013_SHA256
    assert source_digest == host_helper.MIGRATION_SHA256
    assert source_digest == controller.MIGRATION_SHA256


def test_forged_pair_manifest_digest_is_rejected_before_any_remote_call(
    monkeypatch,
) -> None:
    revision = "a" * 40
    approved = "b" * 64
    config = controller.RehearsalConfig(
        Path("/unused/operator-key"),
        Path("/unused/known-hosts"),
        revision,
        approved,
    )
    monkeypatch.setattr(controller.RehearsalConfig, "from_env", classmethod(lambda _cls: config))
    monkeypatch.setattr(
        controller,
        "verify_pull_request",
        lambda _revision: (_ for _ in ()).throw(AssertionError("remote request was reached")),
    )
    with pytest.raises(controller.RehearsalError, match="reviewed_pair_manifest_mismatch"):
        controller.rehearse_pr_pair(
            reviewed_head_sha=revision,
            candidate_image_id="sha256:" + "c" * 64,
            candidate_source_context_sha256="d" * 64,
            recovery_image_id="sha256:" + "e" * 64,
            recovery_source_context_sha256="f" * 64,
            recovery_overlay_sha256="1" * 64,
            pair_manifest_sha256="2" * 64,
        )


@pytest.mark.parametrize("pin_source", ["environment", "metadata"])
def test_review_pins_load_from_paired_environment_or_private_metadata(
    monkeypatch,
    tmp_path: Path,
    pin_source: str,
) -> None:
    config_home = _review_pin_test_environment(monkeypatch, tmp_path)
    head = "a" * 40
    pair = "b" * 64
    if pin_source == "environment":
        monkeypatch.setenv(controller.REVIEW_HEAD_ENV, head)
        monkeypatch.setenv(controller.REVIEW_PAIR_ENV, pair)
    else:
        controller._write_review_metadata(head, pair)

    config = controller.RehearsalConfig.from_env()

    assert config.reviewed_head_sha == head
    assert config.reviewed_pair_manifest_sha256 == pair
    metadata_file = (
        config_home / controller.REVIEW_METADATA_DIRECTORY / (controller.REVIEW_METADATA_FILENAME)
    )
    assert metadata_file.exists() is (pin_source == "metadata")


def test_review_pins_reject_partial_environment_even_when_metadata_exists(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _review_pin_test_environment(monkeypatch, tmp_path)
    controller._write_review_metadata("a" * 40, "b" * 64)
    monkeypatch.setenv(controller.REVIEW_HEAD_ENV, "a" * 40)

    with pytest.raises(controller.RehearsalError, match="review_pins_partial_environment"):
        controller.RehearsalConfig.from_env()


def test_review_pins_reject_environment_and_metadata_disagreement(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _review_pin_test_environment(monkeypatch, tmp_path)
    controller._write_review_metadata("a" * 40, "b" * 64)
    monkeypatch.setenv(controller.REVIEW_HEAD_ENV, "c" * 40)
    monkeypatch.setenv(controller.REVIEW_PAIR_ENV, "d" * 64)

    with pytest.raises(controller.RehearsalError, match="review_pins_disagree"):
        controller.RehearsalConfig.from_env()


def test_review_pin_directory_and_file_are_created_private(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_home = _review_pin_test_environment(monkeypatch, tmp_path)
    head = "a" * 40
    pair = "b" * 64

    controller._write_review_metadata(head, pair)

    directory = config_home / controller.REVIEW_METADATA_DIRECTORY
    metadata_file = directory / controller.REVIEW_METADATA_FILENAME
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(metadata_file.stat().st_mode) == 0o600
    assert metadata_file.stat().st_nlink == 1
    assert json.loads(metadata_file.read_text(encoding="ascii")) == {
        "format_version": controller.REVIEW_METADATA_VERSION,
        "reviewed_pair_manifest_sha256": pair,
        "reviewed_pr_head_sha": head,
    }


@pytest.mark.parametrize("mode", [0o640, 0o666])
def test_review_metadata_rejects_non_private_file_modes(
    monkeypatch,
    tmp_path: Path,
    mode: int,
) -> None:
    config_home = _review_pin_test_environment(monkeypatch, tmp_path)
    directory = config_home / controller.REVIEW_METADATA_DIRECTORY
    directory.mkdir(mode=0o700)
    metadata_file = directory / controller.REVIEW_METADATA_FILENAME
    metadata_file.write_text(
        json.dumps(
            {
                "format_version": 1,
                "reviewed_pr_head_sha": "a" * 40,
                "reviewed_pair_manifest_sha256": "b" * 64,
            }
        ),
        encoding="ascii",
    )
    metadata_file.chmod(mode)

    with pytest.raises(controller.RehearsalError, match="review_metadata_permissions"):
        controller._read_review_metadata()


def test_review_metadata_rejects_a_symlink_without_reading_its_target(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_home = _review_pin_test_environment(monkeypatch, tmp_path)
    directory = config_home / controller.REVIEW_METADATA_DIRECTORY
    directory.mkdir(mode=0o700)
    target = tmp_path / "target.json"
    target.write_text(
        json.dumps(
            {
                "format_version": 1,
                "reviewed_pr_head_sha": "a" * 40,
                "reviewed_pair_manifest_sha256": "b" * 64,
            }
        ),
        encoding="ascii",
    )
    target.chmod(0o600)
    (directory / controller.REVIEW_METADATA_FILENAME).symlink_to(target)

    with pytest.raises(controller.RehearsalError, match="review_metadata_permissions"):
        controller._read_review_metadata()


def test_review_metadata_rejects_linked_parent_directory(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_home = _review_pin_test_environment(monkeypatch, tmp_path)
    target = tmp_path / "outside"
    target.mkdir(mode=0o700)
    (target / controller.REVIEW_METADATA_FILENAME).write_text(
        json.dumps(
            {
                "format_version": 1,
                "reviewed_pr_head_sha": "a" * 40,
                "reviewed_pair_manifest_sha256": "b" * 64,
            }
        ),
        encoding="ascii",
    )
    (target / controller.REVIEW_METADATA_FILENAME).chmod(0o600)
    (config_home / controller.REVIEW_METADATA_DIRECTORY).symlink_to(
        target,
        target_is_directory=True,
    )

    with pytest.raises(controller.RehearsalError, match="review_metadata_directory_unsafe"):
        controller._read_review_metadata()


def test_review_metadata_rejects_hardlinks_duplicate_keys_and_oversize(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_home = _review_pin_test_environment(monkeypatch, tmp_path)
    directory = config_home / controller.REVIEW_METADATA_DIRECTORY
    directory.mkdir(mode=0o700)
    metadata_file = directory / controller.REVIEW_METADATA_FILENAME
    valid = json.dumps(
        {
            "format_version": 1,
            "reviewed_pr_head_sha": "a" * 40,
            "reviewed_pair_manifest_sha256": "b" * 64,
        },
        separators=(",", ":"),
    )
    metadata_file.write_text(valid, encoding="ascii")
    metadata_file.chmod(0o600)
    os.link(metadata_file, directory / "second-link")
    with pytest.raises(controller.RehearsalError, match="review_metadata_permissions"):
        controller._read_review_metadata()

    (directory / "second-link").unlink()
    metadata_file.write_text(
        '{"format_version":1,"format_version":1,'
        f'"reviewed_pr_head_sha":"{"a" * 40}",'
        f'"reviewed_pair_manifest_sha256":"{"b" * 64}"}}',
        encoding="ascii",
    )
    with pytest.raises(controller.RehearsalError, match="review_metadata_invalid"):
        controller._read_review_metadata()

    metadata_file.write_bytes(b"x" * (controller.MAX_REVIEW_METADATA_BYTES + 1))
    metadata_file.chmod(0o600)
    with pytest.raises(controller.RehearsalError, match="review_metadata_permissions"):
        controller._read_review_metadata()


def test_review_metadata_rejects_owner_mismatch() -> None:
    metadata = SimpleNamespace(
        st_mode=stat.S_IFREG | 0o600,
        st_uid=os.geteuid() + 1,
        st_nlink=1,
        st_size=128,
    )

    with pytest.raises(controller.RehearsalError, match="review_metadata_permissions"):
        controller._validate_review_file_metadata(metadata)


def test_review_metadata_rejects_changes_during_bounded_read(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_home = _review_pin_test_environment(monkeypatch, tmp_path)
    controller._write_review_metadata("a" * 40, "b" * 64)
    metadata_file = (
        config_home / controller.REVIEW_METADATA_DIRECTORY / controller.REVIEW_METADATA_FILENAME
    )
    original_read = os.read
    changed = False

    def race_read(descriptor: int, size: int) -> bytes:
        nonlocal changed
        contents = original_read(descriptor, size)
        if contents and not changed:
            changed = True
            metadata = metadata_file.stat()
            metadata_file.write_bytes(contents)
            os.utime(
                metadata_file,
                ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 1_000_000_000),
            )
        return contents

    monkeypatch.setattr(controller.os, "read", race_read)
    with pytest.raises(controller.RehearsalError, match="review_metadata_changed"):
        controller._read_review_metadata()


def test_review_pin_cli_verifies_current_pair_before_writing_metadata(
    monkeypatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_home = _review_pin_test_environment(monkeypatch, tmp_path)
    revision = "a" * 40
    candidate_id = "sha256:" + "b" * 64
    recovery_id = "sha256:" + "c" * 64
    candidate_context = "d" * 64
    recovery_context = "e" * 64
    overlay = "f" * 64
    manifest = {
        "format_version": 1,
        "repository": controller.REPOSITORY,
        "revision": revision,
        "source_context_sha256": candidate_context,
        "migration": {"from_schema": 12, "to_schema": 13, "sha256": controller.MIGRATION_SHA256},
        "candidate": {
            "image_id": candidate_id,
            "source_context_sha256": candidate_context,
        },
        "recovery": {
            "image_id": recovery_id,
            "source_context_sha256": recovery_context,
            "overlay_sha256": overlay,
        },
    }
    manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode("ascii")
    monkeypatch.setattr(controller, "ARTIFACT_DIRECTORY", tmp_path / "fixed-pair")
    monkeypatch.setattr(
        controller, "_run_fixed", lambda *_args, **_kwargs: (revision + "\n").encode()
    )
    monkeypatch.setattr(
        controller,
        "_read_regular_file",
        lambda *_args, **_kwargs: manifest_bytes,
    )
    calls: list[str] = []
    monkeypatch.setattr(
        controller,
        "_verify_local_reviewed_source",
        lambda _revision, **_kwargs: calls.append("source"),
    )
    monkeypatch.setattr(
        controller,
        "verify_pull_request",
        lambda _revision: calls.append("pull_request"),
    )
    monkeypatch.setattr(
        controller,
        "_artifact_pair",
        lambda _revision, **_kwargs: calls.append("pair"),
    )
    monkeypatch.setattr(
        controller,
        "_private_file_metadata",
        lambda *_args: pytest.fail("the pin CLI must not inspect SSH file metadata"),
    )

    assert pin_pr_rehearsal_review.main(["--write"]) == 0

    metadata_file = (
        config_home / controller.REVIEW_METADATA_DIRECTORY / controller.REVIEW_METADATA_FILENAME
    )
    assert calls == ["source", "pull_request", "pair"]
    assert controller._read_review_metadata() == (
        revision,
        hashlib.sha256(manifest_bytes).hexdigest(),
    )
    assert stat.S_IMODE(metadata_file.stat().st_mode) == 0o600
    assert json.loads(capsys.readouterr().out) == {
        "reviewed_pair_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "reviewed_pr_head_sha": revision,
        "status": "written",
    }


def test_review_pin_cli_rejects_path_arguments(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        pin_pr_rehearsal_review.pr_rehearsal,
        "write_review_pins_from_current_pair",
        lambda: pytest.fail("unexpected pin write"),
    )

    with pytest.raises(SystemExit) as failure:
        pin_pr_rehearsal_review.main(["--write", "--config", "ignored-path"])
    assert failure.value.code == 2


def test_bootstrap_accepts_bounded_realistic_open_pr_payload_over_16k(
    monkeypatch,
) -> None:
    revision = "a" * 40
    payload = {
        "state": "open",
        "draft": True,
        "base": {"ref": "main"},
        "head": {"sha": revision, "repo": {"full_name": bootstrap.REPOSITORY}},
        "body": "x" * 21_000,
    }
    encoded = json.dumps(payload, separators=(",", ":")).encode()
    assert len(encoded) > 16 * 1024
    assert len(encoded) <= bootstrap.RESPONSE_LIMIT

    class Response:
        status = 200

        def read(self, size: int) -> bytes:
            assert size == bootstrap.RESPONSE_LIMIT + 1
            return encoded

    class Connection:
        def __init__(self, host: str, *, timeout: float) -> None:
            assert host == "api.github.com"
            assert timeout == 10

        def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
            assert method == "GET"
            assert path == "/repos/eddiesoz/stock_probs/pulls/1"
            assert headers["Accept"] == "application/vnd.github+json"

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            pass

    monkeypatch.setattr(bootstrap.http.client, "HTTPSConnection", Connection)
    bootstrap._verify_pull_request(revision)


def test_bootstrap_install_requires_fixed_reviewed_manifest_digest() -> None:
    try:
        bootstrap.install(
            {
                "reviewed_head_sha": "a" * 40,
                "asset_sha256": {name: "b" * 64 for name in bootstrap.ASSETS},
            }
        )
    except bootstrap.InstallError as exc:
        assert exc.code == "payload_invalid"
    else:
        raise AssertionError("bootstrap accepted an unbound reviewed manifest")


def test_attached_native_driver_does_not_require_checkout_test_modules() -> None:
    driver = Path(__file__).with_name("native_assistant_probe.py")
    module = ast.parse(driver.read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in module.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    attached = functions["run_attached_existing_app_probe"]
    attached_source = ast.get_source_segment(driver.read_text(encoding="utf-8"), attached)
    assert attached_source is not None
    assert "test_assistant_api" not in attached_source
    assert "sys.path.insert" not in attached_source
    main_source = ast.get_source_segment(driver.read_text(encoding="utf-8"), functions["main"])
    assert main_source is not None
    assert main_source.index("if arguments.attach_existing_app") < main_source.index(
        "if arguments.app_integration"
    )


def test_pr_rehearsal_bundle_installs_driver_that_uses_image_package() -> None:
    assets, hashes = controller._source_bundle()
    assert set(assets) == {"bootstrap", "host_helper", "seed", "driver"}
    assert hashes == {name: hashlib.sha256(content).hexdigest() for name, content in assets.items()}
    assert assets["driver"] == Path(__file__).with_name("native_assistant_probe.py").read_bytes()


def test_source_upload_and_reviewed_bootstrap_share_the_sha_prefixed_names(
    monkeypatch,
) -> None:
    revision = "a" * 40
    pair_digest = "b" * 64
    config = controller.RehearsalConfig(
        Path("/unused/operator-key"), Path("/unused/known-hosts"), revision, pair_digest
    )
    names = controller._source_stage_names(revision)
    assert set(names) == set(bootstrap.ASSETS)
    for role, name in names.items():
        assert name == f"signal-ledger-pr1-{revision}-{bootstrap.ASSETS[role][1]}"
        assert bootstrap._staged_asset_path(revision, role) == bootstrap.INCOMING / name

    staged: list[dict[str, str]] = []
    monkeypatch.setattr(
        controller,
        "_stage_named_assets",
        lambda _config, staged_names, _assets: staged.append(dict(staged_names)),
    )
    captured: list[tuple[list[str], bytes]] = []

    def fake_run_fixed(
        command: list[str], *, timeout: float, input_bytes: bytes | None = None
    ) -> bytes:
        assert timeout == 120
        assert input_bytes is not None
        captured.append((command, input_bytes))
        request = json.loads(input_bytes)
        payload = request["payload"]
        return json.dumps(
            {
                "status": "installed",
                "reviewed_head_sha": payload["reviewed_head_sha"],
                "reviewed_pair_manifest_sha256": payload["reviewed_pair_manifest_sha256"],
                "asset_sha256": payload["asset_sha256"],
            }
        ).encode()

    monkeypatch.setattr(controller, "_run_fixed", fake_run_fixed)
    assets = {role: f"{role} source".encode() for role in names}
    hashes = {role: hashlib.sha256(data).hexdigest() for role, data in assets.items()}
    controller._stage_source_bundle(config, revision, pair_digest, assets, hashes)

    assert staged == [names]
    command, input_bytes = captured[0]
    assert command[-1] == (
        f"sudo -n /usr/bin/python3 {controller.INCOMING_DIRECTORY}/{names['bootstrap']}"
    )
    request = json.loads(input_bytes)
    assert request["payload"]["reviewed_head_sha"] == revision
    assert request["payload"]["asset_sha256"] == hashes
    with pytest.raises(controller.RehearsalError, match="reviewed_pr_head_invalid"):
        controller._source_stage_names("../bootstrap.py")
    with pytest.raises(bootstrap.InstallError, match="bootstrap_asset_name_invalid"):
        bootstrap._staged_asset_path(revision, "../../bootstrap.py")


def test_bootstrap_installs_from_and_cleans_only_sha_prefixed_source_files(
    monkeypatch, tmp_path: Path
) -> None:
    revision = "c" * 40
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    install_root = tmp_path / "installed"
    sources = {
        relative: f"reviewed source for {role}".encode()
        for role, (relative, _name, _maximum) in bootstrap.ASSETS.items()
    }
    hashes: dict[str, str] = {}
    for role, (relative, staged_name, _maximum) in bootstrap.ASSETS.items():
        content = sources[relative]
        hashes[role] = hashlib.sha256(content).hexdigest()
        (incoming / f"signal-ledger-pr1-{revision}-{staged_name}").write_bytes(content)
        # Bare legacy names must not be read or removed by this SHA-bound installation.
        (incoming / staged_name).write_bytes(b"legacy name must remain untouched")

    installed: list[tuple[Path, bytes, int]] = []
    monkeypatch.setattr(bootstrap, "INCOMING", incoming)
    monkeypatch.setattr(bootstrap, "INSTALL_ROOT", install_root)
    monkeypatch.setattr(bootstrap, "INSTALLED_MANIFEST", install_root / "installed.json")
    monkeypatch.setattr(bootstrap, "_safe_directory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bootstrap, "_safe_incoming_directory", lambda: None)
    monkeypatch.setattr(bootstrap, "_check_root_directory", lambda *_args: None)
    monkeypatch.setattr(bootstrap, "_verify_pull_request", lambda _revision: None)
    monkeypatch.setattr(
        bootstrap,
        "_fetch_reviewed_source",
        lambda _revision, relative, _maximum: sources[relative],
    )
    monkeypatch.setattr(
        bootstrap,
        "_atomic_root_file",
        lambda path, content, mode: installed.append((path, content, mode)),
    )

    result = bootstrap.install(
        {
            "reviewed_head_sha": revision,
            "reviewed_pair_manifest_sha256": "d" * 64,
            "asset_sha256": hashes,
        }
    )

    assert result["status"] == "installed"
    assert result["asset_sha256"] == hashes
    assert {path.name for path, _content, _mode in installed} == {
        "host_helper.py",
        "seed.py",
        "native_driver.py",
        "installed.json",
    }
    for _role, (_relative, staged_name, _maximum) in bootstrap.ASSETS.items():
        assert not (incoming / f"signal-ledger-pr1-{revision}-{staged_name}").exists()
        assert (incoming / staged_name).read_bytes() == b"legacy name must remain untouched"


def test_host_cleanup_removes_only_the_exact_reviewed_sha_asset_namespace(
    monkeypatch, tmp_path: Path
) -> None:
    revision = "e" * 40
    other_revision = "f" * 40
    incoming = tmp_path / "incoming"
    temporary = tmp_path / "temporary"
    incoming.mkdir()
    temporary.mkdir()
    monkeypatch.setattr(host_helper, "INCOMING", incoming)
    monkeypatch.setattr(host_helper, "TEMP_ROOT", temporary)
    monkeypatch.setattr(
        host_helper.pwd,
        "getpwnam",
        lambda name: SimpleNamespace(pw_uid=os.geteuid()) if name == "signalops" else None,
    )
    expected = [
        "candidate.tar.gz",
        "recovery.tar.gz",
        "pair.json",
        "bootstrap.py",
        "host_helper.py",
        "seed.py",
        "native_driver.py",
    ]
    for suffix in expected:
        (incoming / f"signal-ledger-pr1-{revision}-{suffix}").write_bytes(b"owned asset")
    (incoming / f"signal-ledger-pr1-{other_revision}-bootstrap.py").write_bytes(b"other sha")
    (incoming / "bootstrap.py").write_bytes(b"bare legacy asset")

    result = host_helper._cleanup_assets(revision)

    assert result == {
        "status": "cleaned",
        "reviewed_head_sha": revision,
        "removed_assets": len(expected),
    }
    assert not any(
        (incoming / f"signal-ledger-pr1-{revision}-{suffix}").exists() for suffix in expected
    )
    assert (
        incoming / f"signal-ledger-pr1-{other_revision}-bootstrap.py"
    ).read_bytes() == b"other sha"
    assert (incoming / "bootstrap.py").read_bytes() == b"bare legacy asset"


def test_mock_container_transfer_uses_bounded_stdin_and_safe_fixed_names(monkeypatch) -> None:
    content = b"print('synthetic fixture')\n"
    captured: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> CompletedProcess[bytes]:
        captured.append((command, kwargs))
        return CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(host_helper, "_run", fake_run)
    host_helper._transfer_container_asset("a" * 64, "seed.py", content)
    command, kwargs = captured[0]
    assert command[:6] == [
        "/usr/bin/docker",
        "exec",
        "-i",
        "--user",
        "0:0",
        "a" * 64,
    ]
    assert command[6:9] == ["python", "-c", host_helper.CONTAINER_ASSET_INSTALLER]
    assert command[9:] == ["seed.py", str(len(content)), hashlib.sha256(content).hexdigest()]
    assert kwargs == {"timeout": 30, "input_bytes": content, "maximum": 4_096}
    assert command[1:3] == ["exec", "-i"]
    assert "chown" not in host_helper.CONTAINER_ASSET_INSTALLER
    assert "os.chmod(" not in host_helper.CONTAINER_ASSET_INSTALLER
    assert "os.fchmod(file_fd, 0o444)" in host_helper.CONTAINER_ASSET_INSTALLER

    for invalid_container, invalid_name, invalid_content in (
        ("not-a-container", "seed.py", content),
        ("a" * 64, "../seed.py", content),
        (
            "a" * 64,
            "native_driver.py",
            b"x" * (host_helper.INSTALLED_FILES["native_driver.py"] + 1),
        ),
    ):
        with pytest.raises(host_helper.RehearsalError, match="container_asset_invalid"):
            host_helper._transfer_container_asset(invalid_container, invalid_name, invalid_content)
    assert len(captured) == 1


def test_fixed_helper_run_streams_and_bounds_stdin_bytes() -> None:
    content = b"x" * (2 * 1024 * 1024)
    result = host_helper._run(
        [sys.executable, "-c", "import sys; print(len(sys.stdin.buffer.read()))"],
        timeout=5,
        input_bytes=content,
        maximum=128,
    )
    assert result.stdout == f"{len(content)}\n".encode()

    with pytest.raises(host_helper.RehearsalError, match="fixed_command_timeout"):
        host_helper._run(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            timeout=0.1,
            input_bytes=content,
            maximum=128,
        )


def test_both_probe_and_fixture_paths_use_the_same_reviewed_stdin_installer(monkeypatch) -> None:
    source_digests = {"native_driver.py": "c" * 64, "seed.py": "d" * 64}
    installed: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        host_helper,
        "_install_container_asset",
        lambda container, name, digest: installed.append((container, name, digest)),
    )
    host_helper._copy_probe_files("a" * 64, source_digests)
    host_helper._copy_fixture_files("b" * 64, source_digests)
    assert installed == [
        ("a" * 64, "native_driver.py", source_digests["native_driver.py"]),
        ("a" * 64, "seed.py", source_digests["seed.py"]),
        ("b" * 64, "native_driver.py", source_digests["native_driver.py"]),
        ("b" * 64, "seed.py", source_digests["seed.py"]),
    ]


def test_container_transfer_rechecks_reviewed_digest_before_upload(monkeypatch) -> None:
    content = b"reviewed immutable source"
    digest = hashlib.sha256(content).hexdigest()
    uploaded: list[tuple[str, str, bytes]] = []
    monkeypatch.setattr(host_helper, "_read_root_file", lambda _path, _maximum: content)
    monkeypatch.setattr(
        host_helper,
        "_transfer_container_asset",
        lambda container, name, data: uploaded.append((container, name, data)),
    )

    host_helper._install_container_asset("a" * 64, "seed.py", digest)
    assert uploaded == [("a" * 64, "seed.py", content)]
    with pytest.raises(host_helper.RehearsalError, match="installed_source_digest_mismatch"):
        host_helper._install_container_asset("a" * 64, "seed.py", "e" * 64)
    with pytest.raises(host_helper.RehearsalError, match="container_asset_invalid"):
        host_helper._install_container_asset("a" * 64, "../seed.py", digest)
    assert len(uploaded) == 1


def test_local_docker_integration_transfers_into_exact_restricted_tmpfs_profile(
    monkeypatch, tmp_path: Path
) -> None:
    """Use only the already-cached fixed image; skip if local Docker lacks it."""

    for path in (tmp_path / "docker-config", tmp_path / "docker-home"):
        path.mkdir()
    monkeypatch.setattr(host_helper, "DOCKER_CONFIG", tmp_path / "docker-config")
    monkeypatch.setattr(host_helper, "DOCKER_HOME", tmp_path / "docker-home")
    image = host_helper.BASE_IMAGE_ID
    inspected = host_helper._run(
        ["/usr/bin/docker", "image", "inspect", "--format", "{{.Id}}", image],
        timeout=10,
        allow_failure=True,
    )
    if inspected.returncode != 0 or inspected.stdout.decode().strip() != image:
        pytest.skip("fixed baseline image is not already available in local Docker")

    container_name = f"signal-ledger-pr1-stdin-fixture-{secrets.token_hex(6)}"
    run = host_helper._run(
        [
            "/usr/bin/docker",
            "run",
            "--detach",
            "--name",
            container_name,
            "--network=none",
            "--restart=no",
            "--read-only",
            "--user",
            "0:0",
            "--memory",
            str(host_helper.RECOVERY_MEMORY_LIMIT),
            "--memory-swap",
            str(host_helper.RECOVERY_MEMORY_LIMIT),
            "--cpu-period",
            "100000",
            "--cpu-quota",
            "100000",
            "--pids-limit",
            "128",
            "--cap-drop",
            "ALL",
            "--cap-add",
            "SETUID",
            "--cap-add",
            "SETGID",
            "--security-opt",
            "no-new-privileges:true",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001,mode=0700",  # noqa: S108 - match the app's private tmpfs profile.
            "--tmpfs",
            "/run/assistant:rw,nosuid,nodev,noexec,size=16m,mode=0711",
            "--tmpfs",
            "/run/assistant-worker-home:rw,nosuid,nodev,noexec,size=64m,uid=10002,gid=10002,mode=0700",
            "--entrypoint",
            "python",
            image,
            "-c",
            "import time; time.sleep(60)",
        ],
        timeout=20,
    )
    container_id = run.stdout.decode("ascii").strip()
    assert re.fullmatch(r"[0-9a-f]{64}", container_id)
    try:
        host_helper._verify_container_profile(
            container_id, expected_network="none", expected_role="recovery"
        )
        content = b"print('local tmpfs transfer fixture')\n"
        host_helper._transfer_container_asset(container_id, "seed.py", content)
        probe = (
            "import hashlib,json,os,stat; p='/run/assistant/seed.py'; "
            "s=os.stat(p,follow_symlinks=False); "
            "print(json.dumps({'uid':os.getuid(),'gid':os.getgid(),'file_uid':s.st_uid,"
            "'mode':stat.S_IMODE(s.st_mode),'sha256':hashlib.sha256(open(p,'rb').read()).hexdigest()}))"
        )
        result = host_helper._run(
            [
                "/usr/bin/docker",
                "exec",
                "--user",
                "10001:10001",
                container_id,
                "python",
                "-c",
                probe,
            ],
            timeout=10,
            maximum=4_096,
        )
        evidence = json.loads(result.stdout)
        assert evidence == {
            "uid": 10001,
            "gid": 10001,
            "file_uid": 0,
            "mode": 0o444,
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        with pytest.raises(host_helper.RehearsalError, match="fixed_command_failed"):
            host_helper._transfer_container_asset(container_id, "seed.py", b"replacement")
        invalid_digest = host_helper._run(
            [
                "/usr/bin/docker",
                "exec",
                "-i",
                "--user",
                "0:0",
                container_id,
                "python",
                "-c",
                host_helper.CONTAINER_ASSET_INSTALLER,
                "native_driver.py",
                str(len(content)),
                "0" * 64,
            ],
            timeout=10,
            input_bytes=content,
            maximum=4_096,
            allow_failure=True,
        )
        assert invalid_digest.returncode != 0
    finally:
        cleanup = host_helper._run(
            ["/usr/bin/docker", "rm", "--force", container_id],
            timeout=15,
            allow_failure=True,
            maximum=4_096,
        )
        assert cleanup.returncode == 0


def test_host_schema_probe_is_read_only_and_matches_repository_migration_history(
    tmp_path: Path,
) -> None:
    database = tmp_path / "schema.sqlite3"
    Repository(database).migrate()
    probe = subprocess.run(  # noqa: S603 - fixed interpreter and generated fixed-query probe.
        [sys.executable, "-c", host_helper._schema_probe_source(str(database))],
        env={"PATH": os.defpath},
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert probe.returncode == 0
    assert json.loads(probe.stdout) == {"versions": list(range(1, 14)), "max": 13}

    missing = tmp_path / "missing.sqlite3"
    absent_probe = subprocess.run(  # noqa: S603 - fixed interpreter and generated fixed-query probe.
        [sys.executable, "-c", host_helper._schema_probe_source(str(missing))],
        env={"PATH": os.defpath},
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert absent_probe.returncode != 0
    assert not missing.exists()


def test_archive_copy_uses_bounded_chunks_without_materializing_source(
    tmp_path: Path, monkeypatch
) -> None:
    payload = bytes(range(256)) * (host_helper.COPY_CHUNK // 256 * 41) + b"tail"
    source_path = tmp_path / "incoming.tar.gz"
    target_path = tmp_path / "snapshot.tar.gz"
    source_path.write_bytes(payload)
    source_fd = os.open(source_path, os.O_RDONLY)
    target_fd = os.open(target_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    read_sizes: list[int] = []
    actual_read = os.read

    def tracked_read(descriptor: int, size: int) -> bytes:
        read_sizes.append(size)
        return actual_read(descriptor, size)

    monkeypatch.setattr(host_helper.os, "read", tracked_read)
    try:
        copied, digest = host_helper._copy_stream(source_fd, target_fd, maximum=len(payload))
    finally:
        os.close(source_fd)
        os.close(target_fd)

    assert copied == len(payload)
    assert digest == hashlib.sha256(payload).hexdigest()
    assert target_path.read_bytes() == payload
    assert len(read_sizes) > 40
    assert set(read_sizes) == {host_helper.COPY_CHUNK}


def test_host_failure_projection_keeps_stage_and_owner_outcomes_without_content() -> None:
    raw = {
        "failure_stage": "owner_evidence_and_isolation",
        "missing_conditions": ["owner1_answer_empty", "unknown-private-condition"],
        "answer": "synthetic provider output",
        "prompt": "synthetic private input",
        "owners": [
            {
                "terminal_status": "completed",
                "workspace_summary_receipt_count": 1,
                "workspace_summary_digest_matches": True,
                "answer": "synthetic secret answer",
                "cookie": "synthetic cookie",
            },
            {"terminal_status": "failed", "native_search_source_count": 2},
        ],
        "native_api_token": "synthetic token",
    }

    host = host_helper._native_failure_projection(raw)
    public = controller._safe_native_failure(raw)

    assert host == {
        "failure_stage": "owner_evidence_and_isolation",
        "missing_conditions": ["owner1_answer_empty"],
        "owners": [
            {
                "terminal_status": "completed",
                "workspace_summary_receipt_count": 1,
                "workspace_summary_digest_matches": True,
            },
            {"terminal_status": "failed", "native_search_source_count": 2},
        ],
    }
    assert public is None  # Unknown fields reject the whole host-originated detail object.
    assert "synthetic" not in json.dumps(host)


def test_controller_native_failure_allowlist_keeps_only_bounded_status_fields() -> None:
    safe = controller._safe_native_failure(
        {
            "failure_stage": "owner_evidence_and_isolation",
            "missing_conditions": ["owner1_answer_empty"],
            "owners": [
                {
                    "terminal_status": "failed",
                    "model_id_matches": False,
                    "workspace_summary_receipt_count": 0,
                    "answer": "private model output",
                }
            ],
            "turn_requests_issued_concurrently": True,
            "cross_owner_conversation_status": 404,
            "private_transcript": "do not return",
        }
    )
    assert safe is None
    projected = controller._safe_native_failure(
        {
            "failure_stage": "owner_evidence_and_isolation",
            "missing_conditions": ["owner1_answer_empty"],
            "owners": [
                {
                    "terminal_status": "failed",
                    "model_id_matches": False,
                    "workspace_summary_receipt_count": 0,
                }
            ],
            "turn_requests_issued_concurrently": True,
            "cross_owner_conversation_status": 404,
        }
    )
    assert projected == {
        "failure_stage": "owner_evidence_and_isolation",
        "missing_conditions": ["owner1_answer_empty"],
        "owners": [
            {
                "terminal_status": "failed",
                "model_id_matches": False,
                "workspace_summary_receipt_count": 0,
            }
        ],
        "turn_requests_issued_concurrently": True,
        "cross_owner_conversation_status": 404,
    }


def test_migration_cli_backup_result_is_checked_against_schema12_shape() -> None:
    valid = host_helper._validate_pre_migration_backup(
        {
            "status": "migrated",
            "pre_migration_backup": {
                "name": "pre-migration-v12-test.spbackup",
                "sha256": "a" * 64,
                "schema_version": 12,
                "verified": True,
            },
        }
    )
    assert valid == {
        "name": "pre-migration-v12-test.spbackup",
        "sha256": "a" * 64,
        "schema_version": 12,
        "verified": True,
    }
    with pytest.raises(host_helper.RehearsalError, match="pre_migration_backup_invalid"):
        host_helper._validate_pre_migration_backup(
            {
                "status": "migrated",
                "pre_migration_backup": {
                    "name": "pre-migration-v12-test.spbackup",
                    "sha256": "a" * 64,
                    "schema_version": 13,
                    "verified": True,
                },
            }
        )


@pytest.mark.parametrize(
    ("role", "memory", "network"),
    [
        ("candidate", 768 * 1024 * 1024, "bridge"),
        ("recovery", 384 * 1024 * 1024, "none"),
    ],
)
def test_candidate_and_recovery_keep_distinct_bounded_profiles(
    monkeypatch, role: str, memory: int, network: str
) -> None:
    output = (
        f"{memory}|{memory}|100000|100000|0|128|true|{network}|"
        '["ALL"]|["SETUID","SETGID"]|'
        '{}|0:0|["no-new-privileges:true"]\n'
    ).encode()
    monkeypatch.setattr(
        host_helper,
        "_run",
        lambda *_args, **_kwargs: CompletedProcess([], 0, output, b""),
    )
    assert host_helper._memory_limit_for_role(role) == memory
    host_helper._verify_container_profile("a" * 64, expected_network=network, expected_role=role)

    wrong_memory = (
        host_helper.RECOVERY_MEMORY_LIMIT
        if role == "candidate"
        else host_helper.CANDIDATE_MEMORY_LIMIT
    )
    wrong_output = (
        f"{wrong_memory}|{wrong_memory}|100000|100000|0|128|true|{network}|"
        '["ALL"]|["SETUID","SETGID"]|{}|0:0|["no-new-privileges:true"]\n'
    ).encode()
    monkeypatch.setattr(
        host_helper,
        "_run",
        lambda *_args, **_kwargs: CompletedProcess([], 0, wrong_output, b""),
    )
    with pytest.raises(host_helper.RehearsalError, match="container_profile_mismatch"):
        host_helper._verify_container_profile(
            "a" * 64, expected_network=network, expected_role=role
        )


@pytest.mark.parametrize(
    ("period", "quota", "nano_cpus"),
    (
        (50_000, 100_000, 0),  # A 50ms period with a 100ms quota permits two CPUs.
        (100_000, 200_000, 0),
        (100_000, 100_000, 1_000_000_000),  # Reject mixed/alternative CPU representations.
        (100_000, 50_000, 0),
    ),
)
def test_container_profile_rejects_non_exact_single_cpu_limits(
    monkeypatch, period: int, quota: int, nano_cpus: int
) -> None:
    output = (
        f"805306368|805306368|{period}|{quota}|{nano_cpus}|128|true|bridge|"
        '["ALL"]|["SETUID","SETGID"]|{}|0:0|["no-new-privileges:true"]\n'
    ).encode()
    monkeypatch.setattr(
        host_helper,
        "_run",
        lambda *_args, **_kwargs: CompletedProcess([], 0, output, b""),
    )

    with pytest.raises(host_helper.RehearsalError, match="container_profile_mismatch"):
        host_helper._verify_container_profile(
            "a" * 64, expected_network="bridge", expected_role="candidate"
        )


@pytest.mark.parametrize(
    "capabilities",
    (
        ["CAP_SETGID", "CAP_SETUID"],
        ["SETGID", "CAP_SETUID"],
        ["CAP_SETUID", "SETGID"],
    ),
)
def test_container_profile_accepts_only_docker_canonical_setuid_setgid_pair(
    monkeypatch, capabilities: list[str]
) -> None:
    output = (
        f"805306368|805306368|100000|100000|0|128|true|bridge|"
        f'["ALL"]|{json.dumps(capabilities)}|'
        '{}|0:0|["no-new-privileges:true"]\n'
    ).encode()
    monkeypatch.setattr(
        host_helper,
        "_run",
        lambda *_args, **_kwargs: CompletedProcess([], 0, output, b""),
    )

    host_helper._verify_container_profile(
        "a" * 64, expected_network="bridge", expected_role="candidate"
    )


@pytest.mark.parametrize(
    "capabilities",
    (
        ["CAP_SETUID"],
        ["CAP_SETUID", "CAP_SETGID", "CAP_NET_ADMIN"],
        ["CAP_SETUID", "SETUID"],
        ["CAP_SETUID", "CAP_SETGID", "CAP_SETGID"],
        ["CAP_CAP_SETUID", "CAP_SETGID"],
        ["CAP_SETUID", 17],
    ),
)
def test_container_profile_rejects_extra_missing_duplicate_or_invalid_capabilities(
    monkeypatch, capabilities: list[object]
) -> None:
    output = (
        f"805306368|805306368|100000|100000|0|128|true|bridge|"
        f'["ALL"]|{json.dumps(capabilities)}|'
        '{}|0:0|["no-new-privileges:true"]\n'
    ).encode()
    monkeypatch.setattr(
        host_helper,
        "_run",
        lambda *_args, **_kwargs: CompletedProcess([], 0, output, b""),
    )

    with pytest.raises(host_helper.RehearsalError, match="container_profile_mismatch"):
        host_helper._verify_container_profile(
            "a" * 64, expected_network="bridge", expected_role="candidate"
        )


@pytest.mark.parametrize(
    "security_options",
    (
        "null",
        '["no-new-privileges:false"]',
        '["no-new-privileges:true","seccomp=unconfined"]',
        '{"no-new-privileges":true}',
        "not-json",
    ),
)
def test_container_profile_rejects_missing_changed_extra_or_malformed_security_options(
    monkeypatch, security_options: str
) -> None:
    output = (
        "805306368|805306368|100000|100000|0|128|true|bridge|"
        '["ALL"]|["SETUID","SETGID"]|'
        f"{{}}|0:0|{security_options}\n"
    ).encode()
    monkeypatch.setattr(
        host_helper,
        "_run",
        lambda *_args, **_kwargs: CompletedProcess([], 0, output, b""),
    )

    with pytest.raises(host_helper.RehearsalError, match="container_profile_mismatch"):
        host_helper._verify_container_profile(
            "a" * 64, expected_network="bridge", expected_role="candidate"
        )


def test_container_profile_rejects_legacy_inspect_without_security_options(monkeypatch) -> None:
    output = (
        b'805306368|805306368|100000|100000|0|128|true|bridge|["ALL"]|["SETUID","SETGID"]|{}|0:0\n'
    )
    monkeypatch.setattr(
        host_helper,
        "_run",
        lambda *_args, **_kwargs: CompletedProcess([], 0, output, b""),
    )

    with pytest.raises(host_helper.RehearsalError, match="container_profile_mismatch"):
        host_helper._verify_container_profile(
            "a" * 64, expected_network="bridge", expected_role="candidate"
        )


def test_candidate_network_creation_uses_bounded_default_bridge_and_run_labels(monkeypatch) -> None:
    revision = "a" * 40
    pair = "b" * 64
    volume = f"signal-ledger-pr1-{revision[:8]}-{'c' * 16}"
    name = host_helper._candidate_network_name(volume)
    network_id = "d" * 64
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> CompletedProcess[bytes]:
        calls.append((command, kwargs))
        if command[1:3] == ["network", "create"]:
            return CompletedProcess(command, 0, f"{network_id}\n".encode(), b"")
        if command[1:3] == ["network", "inspect"]:
            return CompletedProcess(
                command,
                0,
                _owned_network_inspect_output(name, network_id, volume, revision, pair),
                b"",
            )
        raise AssertionError("network creation must not remove resources")

    monkeypatch.setattr(host_helper, "_run", fake_run)
    assert host_helper._create_candidate_network(name, revision, pair, volume) == network_id
    command, kwargs = calls[0]
    assert command[:5] == ["/usr/bin/docker", "network", "create", "--driver", "bridge"]
    assert command[-1] == name
    assert "--internal" not in command
    assert not {"--subnet", "--gateway", "--ipam-driver", "--publish"}.intersection(command)
    labels = {
        command[index + 1].split("=", 1)[0]: command[index + 1].split("=", 1)[1]
        for index, value in enumerate(command[:-1])
        if value == "--label"
    }
    assert labels == host_helper._network_labels(revision, pair, volume)
    assert kwargs == {"timeout": 15, "allow_failure": True, "maximum": 4_096}
    assert calls[1][1] == {"timeout": 10, "allow_failure": True, "maximum": 4_096}


def test_malformed_network_create_output_recovers_only_from_exact_inspect(monkeypatch) -> None:
    revision = "a" * 40
    pair = "b" * 64
    volume = f"signal-ledger-pr1-{revision[:8]}-{'c' * 16}"
    name = host_helper._candidate_network_name(volume)
    network_id = "d" * 64
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> CompletedProcess[bytes]:
        commands.append(command)
        if command[1:3] == ["network", "create"]:
            return CompletedProcess(command, 0, b"unrecognized create output\n", b"")
        if command[1:3] == ["network", "inspect"]:
            return CompletedProcess(
                command,
                0,
                _owned_network_inspect_output(name, network_id, volume, revision, pair),
                b"",
            )
        raise AssertionError("unverified output must never trigger removal")

    monkeypatch.setattr(host_helper, "_run", fake_run)
    assert host_helper._create_candidate_network(name, revision, pair, volume) == network_id
    assert [command[1:3] for command in commands] == [["network", "create"], ["network", "inspect"]]


def test_failed_network_creation_confirms_exact_name_absence_without_removal(monkeypatch) -> None:
    revision = "a" * 40
    pair = "b" * 64
    volume = f"signal-ledger-pr1-{revision[:8]}-{'c' * 16}"
    name = host_helper._candidate_network_name(volume)
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> CompletedProcess[bytes]:
        commands.append(command)
        if command[1:3] == ["network", "create"]:
            return CompletedProcess(command, 1, b"", b"fixed create failure")
        if command[1:3] == ["network", "inspect"]:
            return CompletedProcess(command, 1, b"", b"not found")
        if command[1:3] == ["network", "ls"]:
            return CompletedProcess(command, 0, b"", b"")
        raise AssertionError("failed creation must not remove an unverified network")

    monkeypatch.setattr(host_helper, "_run", fake_run)
    with pytest.raises(host_helper.RehearsalError, match="candidate_network_creation_invalid"):
        host_helper._create_candidate_network(name, revision, pair, volume)
    assert [command[1:3] for command in commands] == [
        ["network", "create"],
        ["network", "inspect"],
        ["network", "ls"],
    ]
    assert commands[2] == [
        "/usr/bin/docker",
        "network",
        "ls",
        "--no-trunc",
        "--filter",
        f"name={name}",
        "--format",
        "{{.ID}}|{{.Name}}",
    ]


def test_failed_inspect_rejects_an_exact_network_name_in_bounded_listing(monkeypatch) -> None:
    revision = "a" * 40
    pair = "b" * 64
    volume = f"signal-ledger-pr1-{revision[:8]}-{'c' * 16}"
    name = host_helper._candidate_network_name(volume)
    network_id = "d" * 64
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> CompletedProcess[bytes]:
        calls.append(command)
        if command[1:3] == ["network", "inspect"]:
            return CompletedProcess(command, 1, b"", b"inspect unavailable")
        if command[1:3] == ["network", "ls"]:
            return CompletedProcess(command, 0, f"{network_id}|{name}\n".encode(), b"")
        raise AssertionError("an unverified network must never be removed")

    monkeypatch.setattr(host_helper, "_run", fake_run)
    with pytest.raises(host_helper.RehearsalError, match="candidate_network_inspect_unverified"):
        host_helper._inspect_owned_network(
            name, revision, pair, volume, require_empty=True, allow_absent=True
        )
    assert [command[1:3] for command in calls] == [["network", "inspect"], ["network", "ls"]]
    assert not any(command[1:3] == ["network", "rm"] for command in calls)


def test_failed_inspect_allows_only_valid_substring_siblings_as_absence(monkeypatch) -> None:
    revision = "a" * 40
    pair = "b" * 64
    volume = f"signal-ledger-pr1-{revision[:8]}-{'c' * 16}"
    name = host_helper._candidate_network_name(volume)
    sibling_id = "e" * 64
    sibling_name = f"{name}-sibling"
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> CompletedProcess[bytes]:
        calls.append(command)
        if command[1:3] == ["network", "inspect"]:
            return CompletedProcess(command, 1, b"", b"inspect unavailable")
        if command[1:3] == ["network", "ls"]:
            return CompletedProcess(command, 0, f"{sibling_id}|{sibling_name}\n".encode(), b"")
        raise AssertionError("absence verification must not remove a sibling")

    monkeypatch.setattr(host_helper, "_run", fake_run)
    assert (
        host_helper._inspect_owned_network(
            name, revision, pair, volume, require_empty=True, allow_absent=True
        )
        is None
    )
    listing = calls[1]
    assert listing == [
        "/usr/bin/docker",
        "network",
        "ls",
        "--no-trunc",
        "--filter",
        f"name={name}",
        "--format",
        "{{.ID}}|{{.Name}}",
    ]


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr"),
    [
        (0, b"not-a-full-id|valid-sibling\n", b""),
        (0, b"f" * 64 + b"|invalid/name\n", b""),
        (0, b"f" * 64 + b"|valid-sibling\nmalformed-row\n", b""),
        (0, b"x" * 4_097, b""),
        (0, b"f" * 64 + b"|valid-sibling\n", b"unexpected warning"),
        (1, b"", b"network listing failed"),
    ],
)
def test_failed_inspect_rejects_invalid_network_listing(
    monkeypatch, returncode: int, stdout: bytes, stderr: bytes
) -> None:
    revision = "a" * 40
    pair = "b" * 64
    volume = f"signal-ledger-pr1-{revision[:8]}-{'c' * 16}"
    name = host_helper._candidate_network_name(volume)

    def fake_run(command: list[str], **_kwargs: object) -> CompletedProcess[bytes]:
        if command[1:3] == ["network", "inspect"]:
            return CompletedProcess(command, 1, b"", b"inspect unavailable")
        if command[1:3] == ["network", "ls"]:
            return CompletedProcess(command, returncode, stdout, stderr)
        raise AssertionError("invalid listing must never trigger cleanup")

    monkeypatch.setattr(host_helper, "_run", fake_run)
    with pytest.raises(host_helper.RehearsalError, match="candidate_network_inspect_unverified"):
        host_helper._inspect_owned_network(
            name, revision, pair, volume, require_empty=True, allow_absent=True
        )


def test_network_creation_rejects_owner_mismatch_without_removal(monkeypatch) -> None:
    revision = "a" * 40
    pair = "b" * 64
    volume = f"signal-ledger-pr1-{revision[:8]}-{'c' * 16}"
    name = host_helper._candidate_network_name(volume)
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> CompletedProcess[bytes]:
        commands.append(command)
        if command[1:3] == ["network", "create"]:
            return CompletedProcess(command, 0, b"malformed\n", b"")
        if command[1:3] == ["network", "inspect"]:
            return CompletedProcess(
                command,
                0,
                _owned_network_inspect_output(
                    name, "d" * 64, volume, revision, pair, task="R-ASTRA-119"
                ),
                b"",
            )
        raise AssertionError("an unowned network must not be removed")

    monkeypatch.setattr(host_helper, "_run", fake_run)
    with pytest.raises(host_helper.RehearsalError, match="candidate_network_identity_mismatch"):
        host_helper._create_candidate_network(name, revision, pair, volume)
    assert [command[1:3] for command in commands] == [["network", "create"], ["network", "inspect"]]


@pytest.mark.parametrize(
    ("identifier", "inspect_name", "driver", "scope", "internal", "ipam_driver"),
    (
        ("invalid-id", "exact", "bridge", "local", "false", "default"),
        ("d" * 64, "other", "bridge", "local", "false", "default"),
        ("d" * 64, "exact", "overlay", "local", "false", "default"),
        ("d" * 64, "exact", "bridge", "global", "false", "default"),
        ("d" * 64, "exact", "bridge", "local", "true", "default"),
        ("d" * 64, "exact", "bridge", "local", "false", "custom"),
    ),
)
def test_candidate_network_rejects_wrong_id_name_or_bridge_properties(
    monkeypatch,
    identifier: str,
    inspect_name: str,
    driver: str,
    scope: str,
    internal: str,
    ipam_driver: str,
) -> None:
    revision = "a" * 40
    pair = "b" * 64
    volume = f"signal-ledger-pr1-{revision[:8]}-{'c' * 16}"
    name = host_helper._candidate_network_name(volume)
    observed_name = name if inspect_name == "exact" else name + "-other"
    output = _owned_network_inspect_output(
        observed_name,
        identifier,
        volume,
        revision,
        pair,
        driver=driver,
        scope=scope,
        internal=internal,
        ipam_driver=ipam_driver,
    )
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> CompletedProcess[bytes]:
        calls.append(command)
        return CompletedProcess(command, 0, output, b"")

    monkeypatch.setattr(host_helper, "_run", fake_run)
    with pytest.raises(host_helper.RehearsalError, match="candidate_network_identity_mismatch"):
        host_helper._inspect_owned_network(name, revision, pair, volume, require_empty=True)
    assert [command[1:3] for command in calls] == [["network", "inspect"]]


def test_candidate_profile_requires_exact_owned_network_and_no_ports(monkeypatch) -> None:
    revision = "a" * 40
    pair = "b" * 64
    run_id = "c" * 16
    volume = f"signal-ledger-pr1-{revision[:8]}-{run_id}"
    name = f"{volume}-candidate"
    network = host_helper._candidate_network_name(volume)
    network_id = "d" * 64
    expected = {
        "expected_network": network,
        "expected_role": "candidate",
        "expected_name": name,
        "expected_network_id": network_id,
        "expected_task": host_helper.TASK_ID,
        "expected_run_id": run_id,
        "expected_revision": revision,
        "expected_pair": pair,
        "expected_volume": volume,
    }
    output = _app_profile_inspect_output(
        "e" * 64,
        name,
        volume,
        revision,
        pair,
        "candidate",
        network,
        network_id,
        host_helper.CANDIDATE_MEMORY_LIMIT,
    )
    monkeypatch.setattr(
        host_helper,
        "_run",
        lambda *_args, **_kwargs: CompletedProcess([], 0, output, b""),
    )
    host_helper._verify_container_profile("e" * 64, **expected)

    wrong_profiles = (
        _app_profile_inspect_output(
            "e" * 64,
            name,
            volume,
            revision,
            pair,
            "candidate",
            network,
            network_id,
            host_helper.CANDIDATE_MEMORY_LIMIT,
            networks_override={network: {"NetworkID": "f" * 64}},
        ),
        _app_profile_inspect_output(
            "e" * 64,
            name,
            volume,
            revision,
            pair,
            "candidate",
            network,
            network_id,
            host_helper.CANDIDATE_MEMORY_LIMIT,
            networks_override={network: {"NetworkID": network_id}, "bridge": {}},
        ),
        _app_profile_inspect_output(
            "e" * 64,
            name,
            volume,
            revision,
            pair,
            "candidate",
            network,
            network_id,
            host_helper.CANDIDATE_MEMORY_LIMIT,
            port_bindings={"8000/tcp": [{"HostPort": "8000"}]},
        ),
    )
    for invalid_output in wrong_profiles:
        monkeypatch.setattr(
            host_helper,
            "_run",
            lambda *_args, _output=invalid_output, **_kwargs: CompletedProcess([], 0, _output, b""),
        )
        with pytest.raises(host_helper.RehearsalError, match="container_profile_mismatch"):
            host_helper._verify_container_profile("e" * 64, **expected)


def test_app_container_command_uses_role_bound_memory_and_keeps_security_limits(
    monkeypatch, tmp_path
) -> None:
    revision = "a" * 40
    pair = "b" * 64
    run_id = "d" * 16
    volume = f"signal-ledger-pr1-{revision[:8]}-{run_id}"
    candidate_network = host_helper._candidate_network_name(volume)
    network_id = "e" * 64
    cases = (
        ("candidate", candidate_network, network_id, 768 * 1024 * 1024),
        ("recovery", "none", None, 384 * 1024 * 1024),
    )
    monkeypatch.setattr(
        host_helper,
        "_write_environment",
        lambda **_kwargs: tmp_path / "synthetic.env",
    )

    for role, network, expected_network_id, memory in cases:
        captured: list[list[str]] = []

        def fake_run(
            command: list[str],
            _captured: list[list[str]] = captured,
            _memory: int = memory,
            _network: str = network,
            _network_id: str | None = expected_network_id,
            _role: str = role,
            **_kwargs: object,
        ) -> CompletedProcess[bytes]:
            _captured.append(command)
            if command[1:3] == ["network", "inspect"]:
                return CompletedProcess(
                    command,
                    0,
                    _owned_network_inspect_output(
                        _network,
                        _network_id or "f" * 64,
                        volume,
                        revision,
                        pair,
                    ),
                    b"",
                )
            if command[1] == "run":
                return CompletedProcess(command, 0, ("a" * 64 + "\n").encode(), b"")
            if command[1] == "inspect":
                output = _app_profile_inspect_output(
                    "a" * 64,
                    f"{volume}-{_role}",
                    volume,
                    revision,
                    pair,
                    _role,
                    _network,
                    _network_id,
                    _memory,
                )
                return CompletedProcess(command, 0, output, b"")
            raise AssertionError("unexpected Docker command")

        monkeypatch.setattr(host_helper, "_run", fake_run)
        host_helper._start_app(
            "sha256:" + "c" * 64,
            volume,
            f"{volume}-{role}",
            assistant_enabled=role == "candidate",
            network=network,
            network_id=expected_network_id,
            run_id=run_id,
            reviewed_head_sha=revision,
            pair_manifest_sha256=pair,
            role=role,
        )
        run_index = next(index for index, command in enumerate(captured) if command[1] == "run")
        run_command = captured[run_index]
        if role == "candidate":
            assert captured[0][1:3] == ["network", "inspect"]
            assert run_index == 1
        assert captured[run_index + 1][1] == "inspect"
        assert run_command[run_command.index("--memory") + 1] == str(memory)
        assert run_command[run_command.index("--memory-swap") + 1] == str(memory)
        assert run_command[run_command.index("--cpu-period") + 1] == "100000"
        assert run_command[run_command.index("--cpu-quota") + 1] == "100000"
        assert "--cpus" not in run_command
        assert run_command[run_command.index("--pids-limit") + 1] == "128"
        assert "--network=" + network in run_command
        assert "--publish" not in run_command
        assert "--internal" not in run_command
        assert "--subnet" not in run_command
        assert "--gateway" not in run_command
        assert run_command[run_command.index("--read-only") - 1] == "--restart=no"
        assert run_command[run_command.index("--cap-drop") + 1] == "ALL"


def test_schema_cli_keeps_the_lower_memory_profile(monkeypatch) -> None:
    captured: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> CompletedProcess[bytes]:
        captured.append(command)
        return CompletedProcess(command, 0, b"{}\n", b"")

    monkeypatch.setattr(host_helper, "_run", fake_run)
    result = host_helper._volume_cli(
        "sha256:" + "c" * 64,
        "signal-ledger-pr1-aaaaaaaa-" + "d" * 16,
        ["migrate"],
        revision="a" * 40,
        pair_manifest_sha256="b" * 64,
    )
    assert result == {}
    command = captured[0]
    assert command[command.index("--memory") + 1] == str(384 * 1024 * 1024)
    assert command[command.index("--memory-swap") + 1] == str(384 * 1024 * 1024)


def test_schema_query_command_has_the_bounded_private_cli_profile(monkeypatch) -> None:
    captured: list[list[str]] = []
    schema = {"max": 13, "versions": list(range(1, 14))}

    def fake_run(command: list[str], **_kwargs: object) -> CompletedProcess[bytes]:
        captured.append(command)
        return CompletedProcess(command, 0, json.dumps(schema).encode(), b"")

    monkeypatch.setattr(host_helper, "_run", fake_run)
    result = host_helper._schema_version(
        "sha256:" + "c" * 64,
        "signal-ledger-pr1-aaaaaaaa-" + "d" * 16,
        revision="a" * 40,
        pair_manifest_sha256="b" * 64,
    )
    assert result == 13
    command = captured[0]
    assert command[command.index("--network=none")] == "--network=none"
    assert "--read-only" in command
    assert command[command.index("--user") + 1] == "10001:10001"
    assert command[command.index("--volume") + 1].endswith(":/data")
    assert command[command.index("--memory") + 1] == str(384 * 1024 * 1024)
    assert command[command.index("--memory-swap") + 1] == str(384 * 1024 * 1024)
    assert command[command.index("--cpus") + 1] == "1.0"
    assert command[command.index("--pids-limit") + 1] == "128"
    assert command[-2] == "-c"
    assert "/data/stock_probs.sqlite3" in command[-1]
    assert not host_helper.OPERATION_CONTAINERS


def _controller_resource_evidence() -> dict[str, object]:
    zero_events = {name: 0 for name in host_helper.OOM_EVENT_COUNTERS}
    candidate_cpu = {
        "complete": True,
        "resource_role": "candidate",
        "baseline": {
            "usage_usec": 100,
            "nr_periods": 5,
            "nr_throttled": 2,
            "throttled_usec": 40,
        },
        "final": {
            "usage_usec": 240,
            "nr_periods": 12,
            "nr_throttled": 4,
            "throttled_usec": 90,
        },
        "delta": {
            "usage_usec": 140,
            "nr_periods": 7,
            "nr_throttled": 2,
            "throttled_usec": 50,
        },
    }
    recovery_cpu = {
        **candidate_cpu,
        "resource_role": "recovery",
        "baseline": candidate_cpu["baseline"].copy(),
        "final": candidate_cpu["final"].copy(),
        "delta": candidate_cpu["delta"].copy(),
    }
    return {
        "host_memavailable_before_kib": 600_000,
        "host_memavailable_after_kib": 550_000,
        "host_memory_capacity_evidence": {
            "complete": True,
            "unit": "kib",
            "memtotal_before": 1_500_000,
            "memtotal_after": 1_500_000,
            "stable": True,
        },
        "candidate_memory_peak_bytes": 500 * 1024 * 1024,
        "candidate_memory_limit_bytes": 768 * 1024 * 1024,
        "candidate_oom_event_evidence": {
            "complete": True,
            "baseline": zero_events.copy(),
            "final": zero_events.copy(),
            "delta": zero_events.copy(),
            "zero_oom_events": True,
        },
        "candidate_cpu_stat_evidence": candidate_cpu,
        "recovery_memory_peak_bytes": 250 * 1024 * 1024,
        "recovery_memory_limit_bytes": 384 * 1024 * 1024,
        "recovery_oom_event_evidence": {
            "complete": True,
            "baseline": zero_events.copy(),
            "final": zero_events.copy(),
            "delta": zero_events.copy(),
            "zero_oom_events": True,
        },
        "recovery_cpu_stat_evidence": recovery_cpu,
        "oom_event_evidence_complete": True,
        "zero_oom_events_verified": True,
    }


def test_controller_projects_only_complete_resource_observations() -> None:
    response = _controller_resource_evidence()
    response["raw_host_data"] = "must not be forwarded"

    evidence = controller._validated_resource_evidence(response)

    assert evidence == _controller_resource_evidence()
    assert "raw_host_data" not in evidence


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("missing_capacity", "host_response_invalid"),
        ("incomplete_capacity", "host_response_invalid"),
        ("unbounded_capacity", "host_response_invalid"),
        ("missing_oom_counter", "host_response_invalid"),
        ("nonzero_oom_counter", "host_response_invalid"),
        ("missing_cpu_counter", "host_response_invalid"),
    ],
)
def test_controller_rejects_unavailable_or_nonzero_resource_claims(
    mutation: str, expected_code: str
) -> None:
    response = _controller_resource_evidence()
    if mutation == "missing_capacity":
        response.pop("host_memory_capacity_evidence")
    elif mutation == "incomplete_capacity":
        capacity = response["host_memory_capacity_evidence"]
        assert isinstance(capacity, dict)
        capacity["complete"] = False
    elif mutation == "unbounded_capacity":
        capacity = response["host_memory_capacity_evidence"]
        assert isinstance(capacity, dict)
        capacity["memtotal_before"] = 1 << 64
        capacity["memtotal_after"] = 1 << 64
    elif mutation == "missing_oom_counter":
        candidate = response["candidate_oom_event_evidence"]
        assert isinstance(candidate, dict)
        final = candidate["final"]
        assert isinstance(final, dict)
        final.pop("oom_group_kill")
    elif mutation == "nonzero_oom_counter":
        recovery = response["recovery_oom_event_evidence"]
        assert isinstance(recovery, dict)
        final = recovery["final"]
        delta = recovery["delta"]
        assert isinstance(final, dict)
        assert isinstance(delta, dict)
        final["oom_kill"] = 1
        delta["oom_kill"] = 1
    else:
        candidate = response["candidate_cpu_stat_evidence"]
        assert isinstance(candidate, dict)
        baseline = candidate["baseline"]
        assert isinstance(baseline, dict)
        baseline.pop("throttled_usec")

    with pytest.raises(controller.RehearsalError, match=expected_code):
        controller._validated_resource_evidence(response)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_before",
        "boolean_before",
        "negative_before",
        "over_total_after",
        "below_start_floor",
        "below_run_floor",
    ],
)
def test_controller_requires_bounded_host_available_memory(
    mutation: str,
) -> None:
    response = _controller_resource_evidence()
    if mutation == "missing_before":
        response.pop("host_memavailable_before_kib")
    elif mutation == "boolean_before":
        response["host_memavailable_before_kib"] = True
    elif mutation == "negative_before":
        response["host_memavailable_before_kib"] = -1
    elif mutation == "over_total_after":
        response["host_memavailable_after_kib"] = 1_500_001
    elif mutation == "below_start_floor":
        response["host_memavailable_before_kib"] = controller.START_RESERVE_KIB - 1
    else:
        response["host_memavailable_after_kib"] = controller.RUN_RESERVE_KIB - 1

    with pytest.raises(controller.RehearsalError, match="host_response_invalid"):
        controller._validated_resource_evidence(response)


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_role",
        "missing_counter",
        "boolean_counter",
        "negative_counter",
        "unbounded_counter",
        "counter_reset",
        "incorrect_delta",
    ],
)
def test_controller_rejects_incomplete_or_inconsistent_cpu_evidence(
    mutation: str,
) -> None:
    response = _controller_resource_evidence()
    evidence = response["candidate_cpu_stat_evidence"]
    assert isinstance(evidence, dict)
    baseline = evidence["baseline"]
    final = evidence["final"]
    delta = evidence["delta"]
    assert isinstance(baseline, dict)
    assert isinstance(final, dict)
    assert isinstance(delta, dict)
    if mutation == "wrong_role":
        evidence["resource_role"] = "recovery"
    elif mutation == "missing_counter":
        final.pop("nr_periods")
    elif mutation == "boolean_counter":
        baseline["usage_usec"] = True
    elif mutation == "negative_counter":
        final["nr_periods"] = -1
    elif mutation == "unbounded_counter":
        final["usage_usec"] = controller.MAX_RESOURCE_COUNTER + 1
    elif mutation == "counter_reset":
        final["usage_usec"] = 99
    else:
        delta["usage_usec"] += 1

    with pytest.raises(controller.RehearsalError, match="host_response_invalid"):
        controller._validated_resource_evidence(response)


def test_candidate_memory_evidence_is_bound_to_768_mib(monkeypatch) -> None:
    memory_events = "oom 0\noom_kill 0\noom_group_kill 0\n"
    cpu_stat = (
        "usage_usec 100\nuser_usec 60\nsystem_usec 40\n"
        "nr_periods 5\nnr_throttled 2\nthrottled_usec 40\n"
    )

    def fake_run(*arguments: object, **_kwargs: object) -> CompletedProcess[bytes]:
        command = arguments[0]
        assert isinstance(command, list)
        assert "/sys/fs/cgroup" in command[-1]
        assert "memory.events" in command[-1]
        assert "cpu.stat" in command[-1]
        assert "--env" not in command
        payload = {
            "limit": host_helper.CANDIDATE_MEMORY_LIMIT,
            "peak": 520 * 1024 * 1024,
            "events_bytes": len(memory_events),
            "events": memory_events,
            "cpu_stat_bytes": len(cpu_stat),
            "cpu_stat": cpu_stat,
        }
        return CompletedProcess([], 0, json.dumps(payload).encode(), b"")

    monkeypatch.setattr(host_helper, "_run", fake_run)
    candidate = host_helper._memory_usage("a" * 64, expected_role="candidate")
    assert candidate == {
        "limit": 768 * 1024 * 1024,
        "peak": 520 * 1024 * 1024,
        "oom_events": {"oom": 0, "oom_kill": 0, "oom_group_kill": 0},
        "cpu_stat": {
            "usage_usec": 100,
            "nr_periods": 5,
            "nr_throttled": 2,
            "throttled_usec": 40,
        },
    }
    with pytest.raises(host_helper.RehearsalError, match="container_memory_limit_mismatch"):
        host_helper._memory_usage("a" * 64, expected_role="recovery")


def test_recovery_memory_evidence_is_bound_to_384_mib(monkeypatch) -> None:
    memory_events = "oom 0\noom_kill 0\noom_group_kill 0\n"
    cpu_stat = (
        "usage_usec 200\nuser_usec 140\nsystem_usec 60\n"
        "nr_periods 8\nnr_throttled 1\nthrottled_usec 25\n"
    )
    payload = {
        "limit": host_helper.RECOVERY_MEMORY_LIMIT,
        "peak": 300 * 1024 * 1024,
        "events_bytes": len(memory_events),
        "events": memory_events,
        "cpu_stat_bytes": len(cpu_stat),
        "cpu_stat": cpu_stat,
    }
    monkeypatch.setattr(
        host_helper,
        "_run",
        lambda *_args, **_kwargs: CompletedProcess([], 0, json.dumps(payload).encode(), b""),
    )

    recovery = host_helper._memory_usage("a" * 64, expected_role="recovery")

    assert recovery == {
        "limit": 384 * 1024 * 1024,
        "peak": 300 * 1024 * 1024,
        "oom_events": {"oom": 0, "oom_kill": 0, "oom_group_kill": 0},
        "cpu_stat": {
            "usage_usec": 200,
            "nr_periods": 8,
            "nr_throttled": 1,
            "throttled_usec": 25,
        },
    }


def test_host_memory_observation_requires_total_and_available_counters() -> None:
    assert host_helper._parse_meminfo_kib(
        b"MemTotal:       1000000 kB\nMemAvailable:    400000 kB\n"
    ) == (1_000_000, 400_000)

    with pytest.raises(
        host_helper.RehearsalError, match="host_memory_evidence_incomplete"
    ) as raised:
        host_helper._parse_meminfo_kib(b"MemAvailable: 400000 kB\n")

    assert raised.value.details == {
        "host_memory_evidence_complete": False,
        "missing_counters": ["MemTotal"],
        "invalid_counters": [],
        "capacity_claim": "unavailable",
    }


def test_host_memory_observation_rejects_unbounded_meminfo() -> None:
    with pytest.raises(
        host_helper.RehearsalError, match="host_memory_evidence_too_large"
    ) as raised:
        host_helper._parse_meminfo_kib(b"x" * (host_helper.MAX_MEMINFO_BYTES + 1))

    assert raised.value.details["capacity_claim"] == "unavailable"
    assert raised.value.details["host_memory_evidence_complete"] is False

    with pytest.raises(
        host_helper.RehearsalError, match="host_memory_evidence_incomplete"
    ) as raised:
        host_helper._parse_meminfo_kib(
            b"MemTotal: 18446744073709551616 kB\nMemAvailable: 1000 kB\n"
        )

    assert raised.value.details["invalid_counters"] == ["MemTotal"]
    assert raised.value.details["capacity_claim"] == "unavailable"


def test_oom_event_evidence_records_complete_zero_baselines_and_deltas() -> None:
    baseline = {
        "limit": host_helper.CANDIDATE_MEMORY_LIMIT,
        "peak": 100,
        "oom_events": {name: 0 for name in host_helper.OOM_EVENT_COUNTERS},
    }
    final = {
        "limit": host_helper.CANDIDATE_MEMORY_LIMIT,
        "peak": 200,
        "oom_events": {name: 0 for name in host_helper.OOM_EVENT_COUNTERS},
    }

    evidence = host_helper._oom_event_evidence(baseline, final, role="candidate")

    assert evidence == {
        "complete": True,
        "baseline": {name: 0 for name in host_helper.OOM_EVENT_COUNTERS},
        "final": {name: 0 for name in host_helper.OOM_EVENT_COUNTERS},
        "delta": {name: 0 for name in host_helper.OOM_EVENT_COUNTERS},
        "zero_oom_events": True,
    }


def test_oom_event_evidence_rejects_missing_counters_without_zero_claim(monkeypatch) -> None:
    cpu_stat = "usage_usec 1\nnr_periods 1\nnr_throttled 0\nthrottled_usec 0\n"
    payload = {
        "limit": host_helper.RECOVERY_MEMORY_LIMIT,
        "peak": 100,
        "events_bytes": len("oom 0\noom_kill 0\n"),
        "events": "oom 0\noom_kill 0\n",
        "cpu_stat_bytes": len(cpu_stat),
        "cpu_stat": cpu_stat,
    }
    monkeypatch.setattr(
        host_helper,
        "_run",
        lambda *_args, **_kwargs: CompletedProcess([], 0, json.dumps(payload).encode(), b""),
    )

    with pytest.raises(
        host_helper.RehearsalError, match="cgroup_memory_event_counters_incomplete"
    ) as raised:
        host_helper._memory_usage("a" * 64, expected_role="recovery")

    assert raised.value.details["resource_role"] == "recovery"
    assert raised.value.details["missing_counters"] == ["oom_group_kill"]
    assert raised.value.details["oom_event_evidence_complete"] is False
    assert raised.value.details["zero_oom_claim"] == "unavailable"


def test_oom_event_evidence_rejects_nonzero_deltas_with_observed_counts() -> None:
    baseline = {
        "limit": host_helper.RECOVERY_MEMORY_LIMIT,
        "peak": 100,
        "oom_events": {name: 0 for name in host_helper.OOM_EVENT_COUNTERS},
    }
    final = {
        "limit": host_helper.RECOVERY_MEMORY_LIMIT,
        "peak": 200,
        "oom_events": {"oom": 1, "oom_kill": 0, "oom_group_kill": 0},
    }

    with pytest.raises(host_helper.RehearsalError, match="cgroup_oom_event_observed") as raised:
        host_helper._oom_event_evidence(baseline, final, role="recovery")

    assert raised.value.details["resource_role"] == "recovery"
    assert raised.value.details["oom_event_evidence"]["delta"] == {
        "oom": 1,
        "oom_kill": 0,
        "oom_group_kill": 0,
    }
    assert raised.value.details["oom_event_evidence"]["zero_oom_events"] is False


def test_oom_event_evidence_rejects_nonzero_initial_counters() -> None:
    baseline = {
        "limit": host_helper.CANDIDATE_MEMORY_LIMIT,
        "peak": 100,
        "oom_events": {"oom": 0, "oom_kill": 1, "oom_group_kill": 0},
    }

    with pytest.raises(host_helper.RehearsalError, match="cgroup_oom_event_observed") as raised:
        host_helper._oom_event_evidence(baseline, baseline, role="candidate")

    assert raised.value.details["oom_event_evidence"]["baseline"]["oom_kill"] == 1
    assert raised.value.details["oom_event_evidence"]["delta"]["oom_kill"] == 0
    assert raised.value.details["oom_event_evidence"]["zero_oom_events"] is False


def test_cpu_stat_evidence_records_role_bound_deltas_without_rejecting_throttling() -> None:
    baseline = {
        "cpu_stat": {
            "usage_usec": 100,
            "nr_periods": 5,
            "nr_throttled": 2,
            "throttled_usec": 40,
        }
    }
    final = {
        "cpu_stat": {
            "usage_usec": 240,
            "nr_periods": 12,
            "nr_throttled": 4,
            "throttled_usec": 90,
        }
    }

    evidence = host_helper._cpu_stat_evidence(baseline, final, role="candidate")  # type: ignore[arg-type]

    assert evidence == {
        "complete": True,
        "resource_role": "candidate",
        "baseline": baseline["cpu_stat"],
        "final": final["cpu_stat"],
        "delta": {
            "usage_usec": 140,
            "nr_periods": 7,
            "nr_throttled": 2,
            "throttled_usec": 50,
        },
    }


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("missing", "cgroup_cpu_stat_counters_incomplete"),
        ("boolean", "cgroup_cpu_stat_counters_incomplete"),
        ("negative", "cgroup_cpu_stat_counters_incomplete"),
        ("unbounded", "cgroup_cpu_stat_counters_incomplete"),
        ("reset", "cgroup_cpu_stat_counter_reset"),
    ],
)
def test_cpu_stat_evidence_fails_closed_on_invalid_or_reset_counters(
    mutation: str, expected_code: str
) -> None:
    baseline = {
        "cpu_stat": {
            "usage_usec": 100,
            "nr_periods": 5,
            "nr_throttled": 2,
            "throttled_usec": 40,
        }
    }
    final = {
        "cpu_stat": {
            "usage_usec": 240,
            "nr_periods": 12,
            "nr_throttled": 4,
            "throttled_usec": 90,
        }
    }
    if mutation == "missing":
        final["cpu_stat"].pop("nr_periods")
    elif mutation == "boolean":
        baseline["cpu_stat"]["usage_usec"] = True
    elif mutation == "negative":
        final["cpu_stat"]["nr_periods"] = -1
    elif mutation == "unbounded":
        final["cpu_stat"]["usage_usec"] = host_helper.MAX_RESOURCE_COUNTER_VALUE + 1
    else:
        final["cpu_stat"]["usage_usec"] = 99

    with pytest.raises(host_helper.RehearsalError, match=expected_code):
        host_helper._cpu_stat_evidence(baseline, final, role="recovery")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "text",
    [
        "usage_usec 1\nnr_periods 1\nnr_throttled 1\n",
        "usage_usec -1\nnr_periods 1\nnr_throttled 1\nthrottled_usec 1\n",
        "usage_usec invalid\nnr_periods 1\nnr_throttled 1\nthrottled_usec 1\n",
        "usage_usec 1\nusage_usec 2\nnr_periods 1\nnr_throttled 1\nthrottled_usec 1\n",
        "usage_usec 18446744073709551616\nnr_periods 1\nnr_throttled 1\nthrottled_usec 1\n",
    ],
)
def test_cpu_stat_parser_rejects_incomplete_or_invalid_counters(text: str) -> None:
    with pytest.raises(host_helper.RehearsalError, match="cgroup_cpu_stat_counters_incomplete"):
        host_helper._parse_cpu_stat(text, len(text), role="candidate")


def test_cpu_stat_parser_ignores_bounded_dotted_unknown_counter() -> None:
    text = "usage_usec 1\nnr_periods 1\nnr_throttled 1\nthrottled_usec 1\n"
    text += "core_sched.force_idle_usec 0\n"

    assert host_helper._parse_cpu_stat(text, len(text), role="candidate") == {
        "usage_usec": 1,
        "nr_periods": 1,
        "nr_throttled": 1,
        "throttled_usec": 1,
    }


def test_cpu_stat_parser_rejects_oversized_evidence() -> None:
    text = "usage_usec 1\nnr_periods 1\nnr_throttled 1\nthrottled_usec 1\n"
    with pytest.raises(host_helper.RehearsalError, match="cgroup_cpu_stat_unavailable"):
        host_helper._parse_cpu_stat(
            text, host_helper.MAX_CGROUP_CPU_STAT_BYTES + 1, role="candidate"
        )


def test_production_headroom_floors_are_unchanged_and_fail_closed(monkeypatch) -> None:
    assert host_helper.START_RESERVE_KIB == 512 * 1024
    assert host_helper.RUN_RESERVE_KIB == 128 * 1024
    monkeypatch.setattr(
        host_helper, "_readiness", lambda: {"status": "ready", "schema_version": 12}
    )

    monkeypatch.setattr(host_helper, "_memavailable_kib", lambda: host_helper.START_RESERVE_KIB - 1)
    with pytest.raises(host_helper.RehearsalError, match="host_memory_reserve_breached"):
        host_helper._check_production([0], startup=True)

    monkeypatch.setattr(host_helper, "_memavailable_kib", lambda: host_helper.RUN_RESERVE_KIB - 1)
    with pytest.raises(host_helper.RehearsalError, match="host_memory_reserve_breached"):
        host_helper._check_production([0])


def test_invalid_container_role_fails_closed_for_resource_resolution() -> None:
    with pytest.raises(host_helper.RehearsalError, match="container_role_invalid"):
        host_helper._memory_limit_for_role("cli")


def test_recovery_container_must_satisfy_expected_network(monkeypatch) -> None:
    revision = "a" * 40
    pair = "b" * 64
    output = (
        b"402653184|402653184|100000|100000|0|128|true|none|"
        b'["ALL"]|["SETUID","SETGID"]|{}|0:0|'
        b'["no-new-privileges:true"]\n'
    )
    monkeypatch.setattr(
        host_helper,
        "_run",
        lambda *_args, **_kwargs: CompletedProcess([], 0, output, b""),
    )
    with pytest.raises(host_helper.RehearsalError, match="container_profile_mismatch"):
        host_helper._verify_container_profile(
            "a" * 64, expected_network="bridge", expected_role="recovery"
        )
    with pytest.raises(host_helper.RehearsalError, match="disposable_volume_identity_invalid"):
        host_helper._verify_volume("production-volume", revision, pair)


def test_container_cleanup_verifies_labels_stop_and_absence_before_volume_cleanup(
    monkeypatch,
) -> None:
    revision = "a" * 40
    pair = "b" * 64
    volume = "signal-ledger-pr1-aaaaaaaa-" + "c" * 16
    name = volume + "-candidate"
    container_id = "9" * 64
    run_id = volume.rsplit("-", 1)[1]
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> CompletedProcess[bytes]:
        calls.append(command)
        if command[1] == "inspect" and "--format" in command:
            if command[3] == "{{.State.Running}}":
                output = b"false\n"
            else:
                output = (
                    f"{container_id}|/{name}|true|{host_helper.TASK_ID}|{revision}|{pair}|"
                    f"candidate|{volume}|{run_id}|true\n"
                ).encode()
            return CompletedProcess(command, 0, output, b"")
        if command[1] == "stop":
            return CompletedProcess(command, 0, f"{name}\n".encode(), b"")
        if command[1] == "rm":
            return CompletedProcess(command, 0, f"{name}\n".encode(), b"")
        if command[1] == "ps":
            return CompletedProcess(command, 0, b"", b"")
        raise AssertionError(f"unexpected fixed Docker action {command[1]}")

    monkeypatch.setattr(host_helper, "_run", fake_run)
    host_helper._remove_owned_container(name, revision, pair, volume)
    assert [call[1] for call in calls] == ["inspect", "stop", "inspect", "rm", "ps"]
    assert calls[1][-1] == container_id
    assert calls[3][-1] == container_id


def test_failed_container_inspect_never_removes_unverified_name(monkeypatch) -> None:
    revision = "a" * 40
    pair = "b" * 64
    volume = "signal-ledger-pr1-aaaaaaaa-" + "c" * 16
    name = volume + "-candidate"
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> CompletedProcess[bytes]:
        calls.append(command)
        if command[1] == "inspect":
            return CompletedProcess(command, 1, b"", b"")
        if command[1] == "ps":
            return CompletedProcess(command, 0, b"", b"")
        raise AssertionError("unverified container must never be removed")

    monkeypatch.setattr(host_helper, "_run", fake_run)
    host_helper._remove_owned_container(name, revision, pair, volume)
    assert [call[1] for call in calls] == ["inspect", "ps"]


def test_container_cleanup_rejects_wrong_run_label_without_removal(monkeypatch) -> None:
    revision = "a" * 40
    pair = "b" * 64
    volume = "signal-ledger-pr1-aaaaaaaa-" + "c" * 16
    name = volume + "-candidate"
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> CompletedProcess[bytes]:
        calls.append(command)
        if command[1] == "inspect":
            output = (
                f"{'9' * 64}|/{name}|true|{host_helper.TASK_ID}|{revision}|{pair}|"
                f"candidate|{volume}|{'d' * 16}|false\n"
            ).encode()
            return CompletedProcess(command, 0, output, b"")
        raise AssertionError("wrong task/run labels must block cleanup")

    monkeypatch.setattr(host_helper, "_run", fake_run)
    with pytest.raises(host_helper.RehearsalError, match="container_cleanup_identity_mismatch"):
        host_helper._remove_owned_container(name, revision, pair, volume)
    assert [call[1] for call in calls] == ["inspect"]


def test_owned_network_cleanup_removes_by_id_after_empty_endpoint_check(monkeypatch) -> None:
    revision = "a" * 40
    pair = "b" * 64
    volume = f"signal-ledger-pr1-{revision[:8]}-{'c' * 16}"
    name = host_helper._candidate_network_name(volume)
    network_id = "d" * 64
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> CompletedProcess[bytes]:
        calls.append(command)
        if command[1:3] == ["network", "inspect"] and calls.count(command) == 1:
            return CompletedProcess(
                command,
                0,
                _owned_network_inspect_output(name, network_id, volume, revision, pair),
                b"",
            )
        if command[1:3] == ["network", "rm"]:
            return CompletedProcess(command, 0, b"", b"")
        if command[1:3] == ["network", "inspect"]:
            return CompletedProcess(command, 1, b"", b"")
        if command[1:3] == ["network", "ls"]:
            return CompletedProcess(command, 0, b"", b"")
        raise AssertionError("unexpected network cleanup command")

    monkeypatch.setattr(host_helper, "_run", fake_run)
    host_helper._remove_owned_network(name, revision, pair, volume, expected_id=network_id)
    assert [command[1:3] for command in calls] == [
        ["network", "inspect"],
        ["network", "rm"],
        ["network", "inspect"],
        ["network", "ls"],
    ]
    assert calls[1][-1] == network_id
    assert calls[0][-1] == name


def test_owned_network_cleanup_retains_network_with_any_endpoint(monkeypatch) -> None:
    revision = "a" * 40
    pair = "b" * 64
    volume = f"signal-ledger-pr1-{revision[:8]}-{'c' * 16}"
    name = host_helper._candidate_network_name(volume)
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> CompletedProcess[bytes]:
        calls.append(command)
        return CompletedProcess(
            command,
            0,
            _owned_network_inspect_output(
                name,
                "d" * 64,
                volume,
                revision,
                pair,
                endpoints={"unowned-container": {"Name": "unowned-container"}},
            ),
            b"",
        )

    monkeypatch.setattr(host_helper, "_run", fake_run)
    with pytest.raises(host_helper.RehearsalError, match="candidate_network_identity_mismatch"):
        host_helper._remove_owned_network(name, revision, pair, volume)
    assert [command[1:3] for command in calls] == [["network", "inspect"]]


def test_network_cleanup_precedes_volume_and_waits_for_container_absence(monkeypatch) -> None:
    revision = "a" * 40
    pair = "b" * 64
    volume = f"signal-ledger-pr1-{revision[:8]}-{'c' * 16}"
    name = host_helper._candidate_network_name(volume)
    network_id = "d" * 64
    calls: list[str] = []
    monkeypatch.setattr(
        host_helper,
        "_remove_owned_network",
        lambda *_args, **_kwargs: calls.append("network"),
    )
    monkeypatch.setattr(
        host_helper,
        "_remove_volume_if_owned",
        lambda *_args: calls.append("volume") or True,
    )

    assert host_helper._cleanup_network_before_volume(
        containers_removed=True,
        network_name=name,
        network_id=network_id,
        network_created=True,
        revision=revision,
        pair_sha256=pair,
        volume=volume,
        volume_created=True,
    ) == (True, True)
    assert calls == ["network", "volume"]

    assert host_helper._cleanup_network_before_volume(
        containers_removed=False,
        network_name=name,
        network_id=network_id,
        network_created=True,
        revision=revision,
        pair_sha256=pair,
        volume=volume,
        volume_created=True,
    ) == (False, False)
    assert calls == ["network", "volume"]


def test_incoming_parent_is_group_traversable_by_fixed_operator(
    monkeypatch,
) -> None:
    command: list[str] = []
    monkeypatch.setattr(
        controller, "_run_fixed", lambda args, **_kwargs: command.extend(args) or b""
    )
    config = controller.RehearsalConfig(
        Path("/fixed/key"), Path("/fixed/known-hosts"), "a" * 40, "b" * 64
    )
    controller._ensure_incoming_directories(config)
    assert "-o root -g signalops -m 0750 /var/lib/signal-ledger-pr-rehearsal" in command[-1]
    assert "-o signalops -g signalops -m 0700" in command[-1]


def test_host_projection_preserves_early_closed_owner_evidence_without_answers() -> None:
    raw = {
        "failure_stage": "turn_poll_and_search_confirmation",
        "safe_error_code": "provider_unavailable",
        "owner_evidence": [
            {
                "owner_index": 0,
                "terminal_status": "failed",
                "turn_error_code": "provider_unavailable",
                "turn_failure_stage": "before_model_session_event",
                "model_id_matches": False,
                "assistant_message_count": 0,
                "assistant_text_bytes": 0,
                "answer_nonempty": False,
                "workspace_summary_digest_matches": False,
                "workspace_summary_receipt_count": 0,
                "selected_model_id_matches": False,
                "native_search_source_count": 0,
                "conversation_event_count": 3,
                "answer": "never expose this answer",
            }
        ],
    }
    projected = host_helper._native_failure_projection(raw)
    assert projected["failure_stage"] == "turn_poll_and_search_confirmation"
    assert projected["owner_evidence"] == [
        {
            "owner_index": 0,
            "terminal_status": "failed",
            "turn_error_code": "provider_unavailable",
            "turn_failure_stage": "before_model_session_event",
            "model_id_matches": False,
            "answer_nonempty": False,
            "workspace_summary_digest_matches": False,
            "selected_model_id_matches": False,
            "assistant_message_count": 0,
            "assistant_text_bytes": 0,
            "workspace_summary_receipt_count": 0,
            "native_search_source_count": 0,
            "conversation_event_count": 3,
        }
    ]
    assert "never expose" not in json.dumps(projected)


def test_controller_failure_projection_keeps_closed_turn_error_stage_and_owner_evidence() -> None:
    projected = controller._safe_native_failure(
        {
            "failure_stage": "turn_poll_and_search_confirmation",
            "missing_conditions": [],
            "owner_evidence": [
                {
                    "owner_index": 1,
                    "terminal_status": "failed",
                    "turn_error_code": "provider_unavailable",
                    "turn_failure_stage": "before_model_session_event",
                    "assistant_text_bytes": 0,
                    "answer_nonempty": False,
                }
            ],
        }
    )
    assert projected == {
        "failure_stage": "turn_poll_and_search_confirmation",
        "missing_conditions": [],
        "owner_evidence": [
            {
                "owner_index": 1,
                "terminal_status": "failed",
                "turn_error_code": "provider_unavailable",
                "turn_failure_stage": "before_model_session_event",
                "assistant_text_bytes": 0,
                "answer_nonempty": False,
            }
        ],
    }
    rejected = controller._safe_native_failure(
        {
            "failure_stage": "turn_poll_and_search_confirmation",
            "missing_conditions": [],
            "owner_evidence": [
                {
                    "owner_index": 1,
                    "terminal_status": "failed",
                    "turn_error_code": "raw provider said do not log this",
                    "turn_failure_stage": "before_model_session_event",
                }
            ],
        }
    )
    assert rejected is None


def _write_docker_archive(
    path: Path,
    image_id: str,
    *,
    repo_tags: list[str] | None = None,
    layer_payload: bytes = b"synthetic layer",
    extra_members: int = 0,
) -> None:
    manifest = json.dumps(
        [
            {
                "Config": image_id.removeprefix("sha256:") + ".json",
                "RepoTags": repo_tags,
                "Layers": ["layer.tar"],
            }
        ]
    ).encode()
    with (
        path.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as archive,
    ):
        for name, payload in (
            ("manifest.json", manifest),
            (image_id.removeprefix("sha256:") + ".json", b"{}"),
            ("layer.tar", layer_payload),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
        for index in range(extra_members):
            member = tarfile.TarInfo(f"empty-{index}")
            member.size = 0
            archive.addfile(member, io.BytesIO())


def _write_reference_type_archive(
    path: Path, image_id: str, *, config_kind: str = "file", layer_kind: str = "file"
) -> None:
    config_path = image_id.removeprefix("sha256:") + ".json"
    manifest = json.dumps(
        [{"Config": config_path, "RepoTags": [], "Layers": ["layer.tar"]}],
        separators=(",", ":"),
    ).encode()
    with (
        path.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as archive,
    ):
        manifest_member = tarfile.TarInfo("manifest.json")
        manifest_member.size = len(manifest)
        archive.addfile(manifest_member, io.BytesIO(manifest))
        for name, kind, payload in (
            (config_path, config_kind, b"{}"),
            ("layer.tar", layer_kind, b"layer"),
        ):
            member = tarfile.TarInfo(name)
            if kind == "symlink":
                member.type = tarfile.SYMTYPE
                member.linkname = "outside-sensitive-file"
            elif kind == "directory":
                member.type = tarfile.DIRTYPE
            else:
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))
                continue
            archive.addfile(member)


def _write_pax_archive(
    path: Path, image_id: str, comment_size: int, *, metadata_members: int = 1
) -> None:
    manifest = json.dumps(
        [
            {
                "Config": image_id.removeprefix("sha256:") + ".json",
                "RepoTags": [],
                "Layers": [f"layer-{index}.tar" for index in range(metadata_members)],
            }
        ]
    ).encode()
    with (
        path.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive,
    ):
        for index in range(metadata_members):
            extension = tarfile.TarInfo(f"layer-{index}.tar")
            extension.size = 1
            extension.pax_headers = {"comment": "x" * comment_size}
            archive.addfile(extension, io.BytesIO(b"x"))
        config = tarfile.TarInfo(image_id.removeprefix("sha256:") + ".json")
        config.size = 2
        archive.addfile(config, io.BytesIO(b"{}"))
        member = tarfile.TarInfo("manifest.json")
        member.size = len(manifest)
        archive.addfile(member, io.BytesIO(manifest))


def _write_oci_archive(path: Path) -> str:
    config = b"{}"
    layer = b"synthetic layer blob"
    config_digest = hashlib.sha256(config).hexdigest()
    layer_digest = hashlib.sha256(layer).hexdigest()
    config_descriptor = {
        "mediaType": "application/vnd.oci.image.config.v1+json",
        "digest": f"sha256:{config_digest}",
        "size": len(config),
    }
    layer_descriptor = {
        "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
        "digest": f"sha256:{layer_digest}",
        "size": len(layer),
    }
    image_manifest = json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": config_descriptor,
            "layers": [layer_descriptor],
        },
        separators=(",", ":"),
    ).encode()
    image_digest = hashlib.sha256(image_manifest).hexdigest()
    image_id = f"sha256:{image_digest}"
    docker_manifest = [
        {
            "Config": f"blobs/sha256/{config_digest}",
            "RepoTags": None,
            "Layers": [f"blobs/sha256/{layer_digest}"],
        }
    ]
    index = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [
            {
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "digest": image_id,
                "size": len(image_manifest),
            }
        ],
    }
    members = (
        ("blobs", None),
        ("blobs/sha256", None),
        (f"blobs/sha256/{config_digest}", config),
        (f"blobs/sha256/{layer_digest}", layer),
        (f"blobs/sha256/{image_digest}", image_manifest),
        ("index.json", json.dumps(index, separators=(",", ":")).encode()),
        ("oci-layout", b'{"imageLayoutVersion":"1.0.0"}'),
        ("manifest.json", json.dumps(docker_manifest, separators=(",", ":")).encode()),
    )
    with (
        path.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as archive,
    ):
        for name, payload in members:
            member = tarfile.TarInfo(name)
            if payload is None:
                member.type = tarfile.DIRTYPE
                archive.addfile(member)
            else:
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))
    return image_id


def test_archive_scan_is_bounded_and_rejects_tag_collisions(tmp_path: Path, monkeypatch) -> None:
    image_id = "sha256:" + "a" * 64
    archive = tmp_path / "image.tar.gz"
    _write_docker_archive(archive, image_id)
    host_helper._verify_archive_manifest(archive, image_id)

    tagged = tmp_path / "tagged.tar.gz"
    _write_docker_archive(tagged, image_id, repo_tags=["stock-probs:latest"])
    with pytest.raises(host_helper.RehearsalError, match="image_archive_identity_mismatch"):
        host_helper._verify_archive_manifest(tagged, image_id)

    monkeypatch.setattr(host_helper, "MAX_ARCHIVE_DECODED_BYTES", 1024)
    with pytest.raises(host_helper.RehearsalError, match="image_archive_decoded_limit"):
        host_helper._verify_archive_manifest(archive, image_id)

    large_layer = tmp_path / "large-valid-layer.tar.gz"
    _write_docker_archive(large_layer, image_id, layer_payload=b"x" * (4 * 1024 * 1024))
    monkeypatch.setattr(host_helper, "MAX_ARCHIVE_DECODED_BYTES", 8 * 1024 * 1024)
    host_helper._verify_archive_manifest(large_layer, image_id)


@pytest.mark.parametrize(
    ("config_kind", "layer_kind", "error"),
    (
        ("symlink", "file", "image_archive_member_type_invalid"),
        ("file", "directory", "image_archive_identity_mismatch"),
    ),
)
def test_archive_referenced_members_must_be_regular_files(
    tmp_path: Path, config_kind: str, layer_kind: str, error: str
) -> None:
    image_id = "sha256:" + "e" * 64
    archive = tmp_path / f"reference-{config_kind}-{layer_kind}.tar.gz"
    _write_reference_type_archive(archive, image_id, config_kind=config_kind, layer_kind=layer_kind)
    with pytest.raises(host_helper.RehearsalError, match=error):
        host_helper._verify_archive_manifest(archive, image_id)


def test_archive_scanner_accepts_strict_oci_layout(tmp_path: Path) -> None:
    archive = tmp_path / "oci-image.tar.gz"
    image_id = _write_oci_archive(archive)
    host_helper._verify_archive_manifest(archive, image_id)

    with pytest.raises(host_helper.RehearsalError, match="image_archive_identity_mismatch"):
        host_helper._verify_archive_manifest(archive, "sha256:" + "f" * 64)


def test_archive_scan_bounds_member_count_and_samples_production_health(
    tmp_path: Path, monkeypatch
) -> None:
    image_id = "sha256:" + "b" * 64
    archive = tmp_path / "many-members.tar.gz"
    _write_docker_archive(archive, image_id, extra_members=2)
    monkeypatch.setattr(host_helper, "MAX_ARCHIVE_MEMBERS", 2)
    with pytest.raises(host_helper.RehearsalError, match="image_archive_member_limit"):
        host_helper._verify_archive_manifest(archive, image_id)

    monkeypatch.setattr(host_helper, "MAX_ARCHIVE_MEMBERS", 64)
    samples: list[int] = [0]
    monkeypatch.setattr(host_helper, "MONITOR_ACTIVE", True)
    monkeypatch.setattr(host_helper, "PRODUCTION_SAMPLE_COUNT", samples)
    ticks = 0

    def advancing_clock() -> float:
        nonlocal ticks
        ticks += 6
        return float(ticks)

    monkeypatch.setattr(host_helper.time, "monotonic", advancing_clock)
    monkeypatch.setattr(
        host_helper,
        "_check_production",
        lambda sample_count: sample_count.__setitem__(0, sample_count[0] + 1) or 0,
    )
    host_helper._verify_archive_manifest(archive, image_id)
    assert samples and samples[0] > 0


def test_archive_scanner_rejects_large_pax_header_before_expanding_its_body(
    tmp_path: Path, monkeypatch
) -> None:
    image_id = "sha256:" + "c" * 64
    ordinary_pax = tmp_path / "ordinary-pax.tar.gz"
    _write_pax_archive(ordinary_pax, image_id, comment_size=32)
    host_helper._verify_archive_manifest(ordinary_pax, image_id)

    archive = tmp_path / "oversized-pax.tar.gz"
    _write_pax_archive(archive, image_id, comment_size=2 * 1024 * 1024)
    readers: list[host_helper._BoundedArchiveReader] = []
    reader_class = host_helper._BoundedArchiveReader

    def capture_reader(source):
        reader = reader_class(source)
        readers.append(reader)
        return reader

    monkeypatch.setattr(host_helper, "_BoundedArchiveReader", capture_reader)
    with pytest.raises(host_helper.RehearsalError, match="image_archive_metadata_bytes_limit"):
        host_helper._verify_archive_manifest(archive, image_id)
    assert len(readers) == 1
    assert readers[0].decoded_bytes <= host_helper.COPY_CHUNK


def test_archive_scanner_caps_cumulative_pax_metadata(tmp_path: Path, monkeypatch) -> None:
    image_id = "sha256:" + "d" * 64
    archive = tmp_path / "cumulative-pax.tar.gz"
    _write_pax_archive(archive, image_id, comment_size=600_000, metadata_members=2)
    readers: list[host_helper._BoundedArchiveReader] = []
    reader_class = host_helper._BoundedArchiveReader

    def capture_reader(source):
        reader = reader_class(source)
        readers.append(reader)
        return reader

    monkeypatch.setattr(host_helper, "_BoundedArchiveReader", capture_reader)
    with pytest.raises(host_helper.RehearsalError, match="image_archive_metadata_bytes_limit"):
        host_helper._verify_archive_manifest(archive, image_id)
    assert len(readers) == 1
    assert readers[0].decoded_bytes <= 700_000


def test_bounded_archive_reader_rejects_single_large_read_request() -> None:
    class Source:
        calls = 0

        def read(self, _size: int) -> bytes:
            self.calls += 1
            return b""

    source = Source()
    reader = host_helper._BoundedArchiveReader(source)
    with pytest.raises(host_helper.RehearsalError, match="image_archive_read_request_limit"):
        reader.read(host_helper.MAX_ARCHIVE_READ + 1)
    assert source.calls == 0
