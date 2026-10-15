"""Focused contracts for the fixed app-only temporary recovery image inputs."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import stat
import tarfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / "scripts/production-deploy-helper.py"


def _helper():
    spec = importlib.util.spec_from_file_location("production_deploy_helper", HELPER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _temporary_tag(helper) -> str:
    return (
        f"signal-ledger:temporary-recovery-build-{helper.TEMPORARY_RECOVERY_SOURCE_REVISION[:12]}"
    )


def _manifest(helper) -> dict[str, Any]:
    return {
        "format_version": 1,
        "kind": "temporary_recovery",
        "built_or_published": True,
        "source_revision": helper.TEMPORARY_RECOVERY_SOURCE_REVISION,
        "source_manifest_sha256": helper.TEMPORARY_RECOVERY_SOURCE_MANIFEST_SHA256,
        "base_revision": helper.PAIR_BASE_REVISION,
        "base_source_archive_sha256": helper.TEMPORARY_RECOVERY_BASE_ARCHIVE_SHA256,
        "base_source_context_sha256": helper.TEMPORARY_RECOVERY_BASE_CONTEXT_SHA256,
        "source_context_sha256": helper.TEMPORARY_RECOVERY_SOURCE_CONTEXT_SHA256,
        "migration_sha256": helper.PAIR_MIGRATION_SHA256,
        "overlay_sha256": helper.TEMPORARY_RECOVERY_OVERLAY_SHA256,
        "overlay_files": dict(helper.TEMPORARY_RECOVERY_FILE_SHA256),
        "schema_version": 13,
        "image": {
            "archive_sha256": "d" * 64,
            "archive_size": 1234,
            "image_id": "sha256:" + "c" * 64,
            "platform": "linux/amd64",
            "image_revision": helper.TEMPORARY_RECOVERY_SOURCE_REVISION,
            "repo_tag": _temporary_tag(helper),
            "entrypoint": ["python", "-m", "stock_probs.recovery_supervisor"],
            "command": helper.TEMPORARY_RECOVERY_COMMAND,
        },
    }


def _pretend_file_is_root_owned(monkeypatch: pytest.MonkeyPatch, helper) -> None:
    real_fstat = os.fstat

    def fake_fstat(descriptor: int):
        result = real_fstat(descriptor)
        return SimpleNamespace(
            st_mode=result.st_mode,
            st_uid=0,
            st_nlink=result.st_nlink,
            st_size=result.st_size,
            st_dev=result.st_dev,
            st_ino=result.st_ino,
            st_mtime_ns=result.st_mtime_ns,
            st_ctime_ns=result.st_ctime_ns,
        )

    monkeypatch.setattr(helper.os, "fstat", fake_fstat)


def _docker_archive(
    path: Path,
    tag: str,
    *,
    image_id: str = "sha256:" + "c" * 64,
    order: tuple[str, ...] | None = None,
    extra_members: tuple[tuple[str, bytes], ...] = (),
) -> bytes:
    image_hex = image_id.removeprefix("sha256:")
    layer_id = "a" * 64
    repository, tag_name = tag.rsplit(":", 1)
    manifest = json.dumps(
        [
            {
                "Config": f"{image_hex}.json",
                "RepoTags": [tag],
                "Layers": [f"{layer_id}/layer.tar"],
            }
        ],
        separators=(",", ":"),
    ).encode()
    contents = {
        "manifest.json": manifest,
        f"{image_hex}.json": b"opaque config bytes; verifier must not read",
        "repositories": json.dumps(
            {repository: {tag_name: layer_id}}, separators=(",", ":")
        ).encode(),
        f"{layer_id}/": None,
        f"{layer_id}/VERSION": b"1.0\n",
        f"{layer_id}/json": b"opaque layer metadata",
        f"{layer_id}/layer.tar": b"opaque layer bytes",
    }
    contents.update(extra_members)
    ordered_names = order or tuple(contents)
    with tarfile.open(path, mode="w:gz") as archive:
        for name in ordered_names:
            content = contents[name]
            member = tarfile.TarInfo(name)
            if content is None:
                member.type = tarfile.DIRTYPE
                archive.addfile(member)
            else:
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
    return path.read_bytes()


def _oci_archive(
    path: Path,
    tag: str,
    *,
    index_descriptor_updates: dict[str, object] | None = None,
    additional_descriptors: list[dict[str, object]] | None = None,
    extra_members: tuple[tuple[str, bytes], ...] = (),
) -> tuple[bytes, str]:
    config = b"opaque config bytes; verifier must not read"
    layer = b"opaque layer bytes; verifier must not read"
    config_digest = hashlib.sha256(config).hexdigest()
    layer_digest = hashlib.sha256(layer).hexdigest()
    config_path = f"blobs/sha256/{config_digest}"
    layer_path = f"blobs/sha256/{layer_digest}"
    image_manifest = json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "digest": f"sha256:{config_digest}",
                "size": len(config),
            },
            "layers": [
                {
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    "digest": f"sha256:{layer_digest}",
                    "size": len(layer),
                }
            ],
        },
        separators=(",", ":"),
    ).encode()
    manifest_digest = hashlib.sha256(image_manifest).hexdigest()
    image_manifest_path = f"blobs/sha256/{manifest_digest}"
    descriptor: dict[str, object] = {
        "digest": f"sha256:{manifest_digest}",
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "size": len(image_manifest),
        "annotations": {
            "org.opencontainers.image.created": "2025-09-15T00:00:00Z",
            "org.opencontainers.image.ref.name": tag,
        },
        "platform": {"os": "linux", "architecture": "amd64"},
    }
    descriptor.update(index_descriptor_updates or {})
    index = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [descriptor, *(additional_descriptors or [])],
    }
    docker_manifest = [{"Config": config_path, "RepoTags": [tag], "Layers": [layer_path]}]
    contents = {
        "blobs/": None,
        "blobs/sha256/": None,
        image_manifest_path: image_manifest,
        config_path: config,
        layer_path: layer,
        "index.json": json.dumps(index, separators=(",", ":")).encode(),
        "oci-layout": b'{"imageLayoutVersion":"1.0.0"}',
        "manifest.json": json.dumps(docker_manifest, separators=(",", ":")).encode(),
    }
    contents.update(extra_members)
    # Keep the OCI manifest before index.json to exercise member-order independent binding.
    with tarfile.open(path, mode="w:gz") as archive:
        for name, content in contents.items():
            member = tarfile.TarInfo(name)
            if content is None:
                member.type = tarfile.DIRTYPE
                archive.addfile(member)
            else:
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
    return path.read_bytes(), f"sha256:{config_digest}"


def _bound_legacy_archive(
    helper, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    archive_path = tmp_path / "image.tar.gz"
    raw = _docker_archive(archive_path, _temporary_tag(helper))
    archive_path.chmod(0o600)
    monkeypatch.setattr(helper, "TEMPORARY_RECOVERY_ARCHIVE", archive_path)
    _pretend_file_is_root_owned(monkeypatch, helper)
    manifest = _manifest(helper)
    manifest["image"]["archive_sha256"] = hashlib.sha256(raw).hexdigest()
    manifest["image"]["archive_size"] = len(raw)
    return manifest


def test_temporary_manifest_pins_new09f_image_and_complete_recovery_overlay() -> None:
    helper = _helper()
    manifest = _manifest(helper)

    validated = helper._validate_temporary_recovery_manifest(manifest)

    assert validated["source_revision"] == helper.TEMPORARY_RECOVERY_SOURCE_REVISION
    assert validated["base_revision"] == helper.PAIR_BASE_REVISION
    assert validated["base_source_archive_sha256"] == helper.TEMPORARY_RECOVERY_BASE_ARCHIVE_SHA256
    assert validated["source_context_sha256"] == helper.TEMPORARY_RECOVERY_SOURCE_CONTEXT_SHA256
    assert validated["overlay_sha256"] == helper.TEMPORARY_RECOVERY_OVERLAY_SHA256
    assert validated["overlay_files"]["src/stock_probs/provider.py"] == (
        "1b4a4c94f049a3068985d11919e96f1b5c4b459bdfdae7e985bec8b888eb3ad1"
    )
    assert validated["migration_sha256"] == helper.PAIR_MIGRATION_SHA256
    assert validated["schema_version"] == 13
    assert validated["image"]["image_revision"] != helper.PRODUCTION_PREDECESSOR_REVISION
    assert validated["image"]["image_id"] not in {
        helper.PRODUCTION_PREDECESSOR_IMAGE_ID,
        helper.PROTECTED_A9_IMAGE_ID,
    }
    assert helper.TEMPORARY_RECOVERY_COMMAND == [
        "serve",
        "--host",
        "0.0.0.0",  # noqa: S104 - fixed container bind, protected by loopback Compose publish.
        "--port",
        "8000",
        "--allow-non-loopback",
    ]


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("source_revision",), "5ad2c3fddfce5a5a631b72cd832a53f24757c44a"),
        (("overlay_files", "src/stock_probs/provider.py"), "0" * 64),
        (("migration_sha256",), "0" * 64),
        (("schema_version",), 12),
        (("image", "image_revision"), "da2764e8477698fa7d686be93a4711e35478e802"),
        (
            ("image", "image_id"),
            "sha256:a9b5147cff0016e443589e8c7b72e83764ca4bac45866ef3ad9bbcd3b308c13f",
        ),
        (("image", "repo_tag"), "signal-ledger:temporary-recovery-build-aaaaaaaaaaaa"),
        (("image", "repo_tag"), "ghcr.io/attacker/image:latest"),
    ],
)
def test_temporary_manifest_rejects_source_provider_schema_and_image_drift(
    path: tuple[str, ...], replacement: object
) -> None:
    helper = _helper()
    manifest = _manifest(helper)
    target = manifest
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement

    with pytest.raises(helper.HostError, match="temporary_recovery_manifest_invalid"):
        helper._validate_temporary_recovery_manifest(manifest)


def test_canonical_review_inputs_reject_duplicate_and_noncanonical_json() -> None:
    helper = _helper()

    with pytest.raises(helper.HostError, match="approval_invalid"):
        helper._canonical_json_object(b'{"a":1,"a":1}', "approval_invalid")
    with pytest.raises(helper.HostError, match="approval_invalid"):
        helper._canonical_json_object(b'{ "a":1}', "approval_invalid")
    assert helper._canonical_json_object(b'{"a":1}', "approval_invalid") == {"a": 1}


def test_separate_approval_must_pin_exact_reviewed_manifest_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _helper()
    manifest = _manifest(helper)
    manifest_raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
    approval = {
        "format_version": 1,
        "kind": "temporary_recovery",
        "review_status": "approved",
        "manifest_sha256": manifest_sha256,
    }
    approval_raw = json.dumps(approval, sort_keys=True, separators=(",", ":")).encode()
    monkeypatch.setattr(helper, "_assert_root_owned_directory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        helper,
        "_read_root_owned_json",
        lambda path, **_kwargs: (approval, approval_raw)
        if path == helper.TEMPORARY_RECOVERY_APPROVAL
        else (manifest, manifest_raw),
    )

    loaded, loaded_sha256 = helper._load_temporary_recovery_authorization()

    assert loaded["image"]["image_id"] == manifest["image"]["image_id"]
    assert loaded_sha256 == manifest_sha256
    approval["manifest_sha256"] = "0" * 64
    with pytest.raises(helper.HostError, match="temporary_recovery_manifest_digest_mismatch"):
        helper._load_temporary_recovery_authorization()


def test_root_owned_json_reader_accepts_only_private_single_link_regular_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    path = tmp_path / "manifest.json"
    raw = b'{"kind":"temporary_recovery"}'
    path.write_bytes(raw)
    path.chmod(0o600)
    _pretend_file_is_root_owned(monkeypatch, helper)

    value, content = helper._read_root_owned_json(
        path, maximum_bytes=128, error_code="manifest_invalid"
    )

    assert value == {"kind": "temporary_recovery"}
    assert content == raw
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_root_owned_json_reader_rejects_wrong_owner_mode_hardlink_and_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    path = tmp_path / "manifest.json"
    path.write_bytes(b'{"kind":"temporary_recovery"}')
    path.chmod(0o600)
    with pytest.raises(helper.HostError, match="manifest_invalid"):
        helper._read_root_owned_json(path, maximum_bytes=128, error_code="manifest_invalid")

    _pretend_file_is_root_owned(monkeypatch, helper)
    path.chmod(0o640)
    with pytest.raises(helper.HostError, match="manifest_invalid"):
        helper._read_root_owned_json(path, maximum_bytes=128, error_code="manifest_invalid")

    path.chmod(0o600)
    linked = tmp_path / "manifest-copy.json"
    os.link(path, linked)
    with pytest.raises(helper.HostError, match="manifest_invalid"):
        helper._read_root_owned_json(path, maximum_bytes=128, error_code="manifest_invalid")

    symlink = tmp_path / "manifest-link.json"
    symlink.symlink_to(path)
    with pytest.raises(helper.HostError, match="manifest_invalid"):
        helper._read_root_owned_json(symlink, maximum_bytes=128, error_code="manifest_invalid")


def test_temporary_state_directory_must_be_root_owned_and_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    _pretend_file_is_root_owned(monkeypatch, helper)

    helper._assert_root_owned_directory(directory, private=True)
    directory.chmod(0o750)
    with pytest.raises(helper.HostError, match="temporary_recovery_state_unsafe"):
        helper._assert_root_owned_directory(directory, private=True)


def test_temporary_image_runtime_contract_checks_exact_id_label_schema_and_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _helper()
    manifest = _manifest(helper)
    calls = {"revision": helper.TEMPORARY_RECOVERY_SOURCE_REVISION, "schema": 13}
    monkeypatch.setattr(helper, "_image_id", lambda _ref: manifest["image"]["image_id"])
    monkeypatch.setattr(helper, "_image_revision", lambda _ref: calls["revision"])
    monkeypatch.setattr(helper, "_image_platform", lambda _ref: "linux/amd64")
    monkeypatch.setattr(helper, "_image_schema", lambda _ref: calls["schema"])
    monkeypatch.setattr(helper, "_image_has_recovery_entrypoint", lambda _ref: True)

    helper._assert_temporary_image(manifest, "signal-ledger:temporary-recovery-0123")
    calls["revision"] = helper.PRODUCTION_PREDECESSOR_REVISION
    with pytest.raises(helper.HostError, match="temporary_recovery_image_contract_mismatch"):
        helper._assert_temporary_image(manifest, "signal-ledger:temporary-recovery-0123")
    calls["revision"] = helper.TEMPORARY_RECOVERY_SOURCE_REVISION
    calls["schema"] = 12
    with pytest.raises(helper.HostError, match="temporary_recovery_image_contract_mismatch"):
        helper._assert_temporary_image(manifest, "signal-ledger:temporary-recovery-0123")


def test_temporary_container_profile_requires_loopback_readonly_nnp_and_app_uid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    helper = _helper()
    image_id = "sha256:" + "c" * 64
    container_id = "a" * 64
    inspect_fields = [
        container_id,
        image_id,
        "10",
        "true",
        "true",
        "null",
        "0:0",
        json.dumps(["no-new-privileges:true"]),
        json.dumps(["ALL"]),
        json.dumps(["SETGID", "SETUID"]),
        json.dumps({"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8000"}]}),
        str(768 * 1024 * 1024),
        str(1_000_000_000),
        "128",
    ]
    commands: list[list[str]] = []
    process_output = "PID PPID UID COMMAND\n10 99 10001 stock-probs\n"
    statuses = {
        10: {
            "pid": 10,
            "ppid": 99,
            "uid": 10001,
            "uids": (10001, 10001, 10001, 10001),
            "name": "stock-probs",
            "namespace_pid": 1,
            "CapPrm": 0,
            "CapEff": 0,
            "CapBnd": 0xC0,
            "CapAmb": 0,
        }
    }
    monkeypatch.setattr(
        helper,
        "_app_container_identity",
        lambda *_args, **_kwargs: (container_id, 10),
    )
    monkeypatch.setattr(helper, "_read_container_process_status", lambda pid: statuses[pid])

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        commands.append(command)
        output = "|".join(inspect_fields) if command[1] == "inspect" else process_output
        return SimpleNamespace(stdout=output)

    monkeypatch.setattr(helper, "_run", fake_run)

    container_id = helper._assert_temporary_container_profile(
        tmp_path / "compose", expected_image_id=image_id, process_profile="temporary_app_pid1"
    )

    assert container_id == "a" * 64
    assert all(".Config.Env" not in " ".join(command) for command in commands)
    process_output = "PID PPID UID COMMAND\n10 99 10001 python\n"
    statuses[10]["name"] = "python"
    with pytest.raises(helper.HostError, match="temporary_recovery_process_profile_invalid"):
        helper._assert_temporary_container_profile(
            tmp_path / "compose", expected_image_id=image_id, process_profile="temporary_app_pid1"
        )
    process_output = "PID PPID UID COMMAND\n10 99 10001 stock-probs\n"
    statuses[10]["name"] = "stock-probs"
    inspect_fields[10] = json.dumps(
        {"8000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8000"}]}  # noqa: S104 - invalid fixture
    )
    with pytest.raises(helper.HostError, match="temporary_recovery_container_profile_invalid"):
        helper._assert_temporary_container_profile(
            tmp_path / "compose", expected_image_id=image_id, process_profile="temporary_app_pid1"
        )

    inspect_fields[10] = json.dumps({"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8000"}]})
    process_output = "PID PPID UID COMMAND\n10 99 10001 stock-probs\n11 10 10002 bun\n"
    statuses[11] = {
        **statuses[10],
        "pid": 11,
        "ppid": 10,
        "uid": 10002,
        "uids": (10002, 10002, 10002, 10002),
        "name": "bun",
        "namespace_pid": 2,
    }
    with pytest.raises(helper.HostError, match="temporary_recovery_worker_present"):
        helper._assert_temporary_container_profile(
            tmp_path / "compose", expected_image_id=image_id, process_profile="temporary_app_pid1"
        )


def test_temporary_container_profile_distinguishes_retained_supervisor_and_transient_healthcheck(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    helper = _helper()
    container_id = "a" * 64
    image_id = "sha256:" + "c" * 64
    inspect_fields = [
        container_id,
        image_id,
        "10",
        "true",
        "true",
        "null",
        "0:0",
        json.dumps(["no-new-privileges:true"]),
        json.dumps(["ALL"]),
        json.dumps(["SETUID", "SETGID"]),
        json.dumps({"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8000"}]}),
        str(768 * 1024 * 1024),
        str(1_000_000_000),
        "128",
    ]

    def process(
        pid: int, ppid: int, uid: int, name: str, namespace_pid: int, *, root: bool = False
    ) -> dict[str, object]:
        caps = 0xC0 if root else 0
        return {
            "pid": pid,
            "ppid": ppid,
            "uid": uid,
            "uids": (uid, uid, uid, uid),
            "name": name,
            "namespace_pid": namespace_pid,
            "CapPrm": caps,
            "CapEff": caps,
            "CapBnd": 0xC0,
            "CapAmb": 0,
        }

    root_supervisor = process(10, 99, 0, "python", 1, root=True)
    app_relay = process(11, 10, 10001, "python", 2)
    app_server = process(12, 11, 10001, "python", 3)
    worker_relay = process(13, 10, 10002, "python", 4)
    opencode_worker = process(14, 13, 10002, "opencode", 5)
    healthcheck = process(15, 55, 0, "python", 6, root=True)
    statuses = {
        10: root_supervisor,
        11: app_relay,
        12: app_server,
        13: worker_relay,
        14: opencode_worker,
        15: healthcheck,
    }
    invited_before = (
        "PID PPID UID COMMAND\n"
        "10 99 0 python\n11 10 10001 python\n12 11 10001 python\n"
        "13 10 10002 python\n14 13 10002 opencode\n15 55 0 python\n"
    )
    invited_after = invited_before.rsplit("15 55 0 python\n", maxsplit=1)[0]
    top_outputs = [invited_before, invited_after]
    monkeypatch.setattr(
        helper, "_app_container_identity", lambda *_args, **_kwargs: (container_id, 10)
    )
    monkeypatch.setattr(helper, "_read_container_process_status", lambda pid: statuses[pid])
    monkeypatch.setattr(helper, "_wait_out_temporary_healthcheck", lambda *_args: None)

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        if command[1] == "inspect":
            return SimpleNamespace(stdout="|".join(inspect_fields))
        return SimpleNamespace(stdout=top_outputs.pop(0))

    monkeypatch.setattr(helper, "_run", fake_run)

    assert (
        helper._assert_temporary_container_profile(
            tmp_path / "compose",
            expected_image_id=image_id,
            process_profile="retained_supervisor_app_invited",
        )
        == container_id
    )
    assert not top_outputs

    root_supervisor["CapEff"] = 0
    top_outputs.append(invited_after)
    with pytest.raises(helper.HostError, match="temporary_recovery_process_profile_invalid"):
        helper._assert_temporary_container_profile(
            tmp_path / "compose",
            expected_image_id=image_id,
            process_profile="retained_supervisor_app_invited",
        )

    root_supervisor["CapEff"] = 0xC0
    disabled = "PID PPID UID COMMAND\n10 99 0 python\n11 10 10001 python\n12 11 10001 python\n"
    top_outputs.append(disabled)
    assert (
        helper._assert_temporary_container_profile(
            tmp_path / "compose",
            expected_image_id=image_id,
            process_profile="retained_supervisor_app_disabled",
        )
        == container_id
    )

    descendant_healthcheck = process(15, 10, 0, "python", 4, root=True)
    statuses[15] = descendant_healthcheck
    top_outputs.append(disabled + "15 10 0 python\n")
    with pytest.raises(helper.HostError, match="temporary_recovery_worker_present"):
        helper._assert_temporary_container_profile(
            tmp_path / "compose",
            expected_image_id=image_id,
            process_profile="retained_supervisor_app_disabled",
        )


def test_archive_verifier_binds_exact_repo_tag_to_exact_archive_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    archive_path = tmp_path / "image.tar.gz"
    raw = _docker_archive(archive_path, _temporary_tag(helper))
    archive_path.chmod(0o600)
    monkeypatch.setattr(helper, "TEMPORARY_RECOVERY_ARCHIVE", archive_path)
    _pretend_file_is_root_owned(monkeypatch, helper)
    manifest = _manifest(helper)
    manifest["image"]["archive_sha256"] = hashlib.sha256(raw).hexdigest()
    manifest["image"]["archive_size"] = len(raw)

    helper._assert_temporary_recovery_archive(manifest)

    manifest["image"]["archive_sha256"] = "0" * 64
    with pytest.raises(helper.HostError, match="temporary_recovery_archive_digest_mismatch"):
        helper._assert_temporary_recovery_archive(manifest)


def test_archive_verifier_rejects_expired_whole_verification_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    manifest = _bound_legacy_archive(helper, tmp_path, monkeypatch)
    clock_values = iter((10.0, 11.0))
    monkeypatch.setattr(helper.time, "monotonic", lambda: next(clock_values))
    monkeypatch.setattr(helper, "TEMPORARY_RECOVERY_ARCHIVE_VERIFY_TIMEOUT_SECONDS", 1.0)

    with pytest.raises(helper.HostError, match="temporary_recovery_archive_timeout"):
        helper._assert_temporary_recovery_archive(
            manifest, memory_reserve_kib=helper.TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB
        )


@pytest.mark.parametrize("clock_value", [float("nan"), float("inf"), float("-inf"), True, None])
def test_archive_verifier_rejects_nonfinite_or_invalid_monotonic_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock_value: object
) -> None:
    helper = _helper()
    manifest = _bound_legacy_archive(helper, tmp_path, monkeypatch)
    monkeypatch.setattr(helper.time, "monotonic", lambda: clock_value)

    with pytest.raises(helper.HostError, match="temporary_recovery_archive_clock_invalid"):
        helper._assert_temporary_recovery_archive(manifest)


def test_archive_verifier_rejects_backward_monotonic_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    manifest = _bound_legacy_archive(helper, tmp_path, monkeypatch)
    clock_values = iter((10.0, 9.0))
    monkeypatch.setattr(helper.time, "monotonic", lambda: next(clock_values))

    with pytest.raises(helper.HostError, match="temporary_recovery_archive_clock_invalid"):
        helper._assert_temporary_recovery_archive(manifest)


def test_archive_verifier_samples_reserve_during_second_tar_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    manifest = _bound_legacy_archive(helper, tmp_path, monkeypatch)
    monkeypatch.setattr(helper, "TEMPORARY_RECOVERY_MEMORY_SAMPLE_INTERVAL_SECONDS", 0.0)
    real_lseek = helper.os.lseek
    scans = 0

    def track_scan(descriptor: int, offset: int, whence: int) -> int:
        nonlocal scans
        result = real_lseek(descriptor, offset, whence)
        if offset == 0 and whence == os.SEEK_SET:
            scans += 1
        return result

    monkeypatch.setattr(helper.os, "lseek", track_scan)
    monkeypatch.setattr(
        helper,
        "_memory_available_kib",
        lambda: helper.TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB - 1
        if scans >= 2
        else helper.TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB + 100,
    )

    with pytest.raises(helper.HostError, match="host_memory_reserve_breached"):
        helper._assert_temporary_recovery_archive(
            manifest, memory_reserve_kib=helper.TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB
        )

    assert scans == 2


def test_archive_verifier_enforces_deadline_during_second_tar_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    manifest = _bound_legacy_archive(helper, tmp_path, monkeypatch)
    monkeypatch.setattr(helper, "TEMPORARY_RECOVERY_ARCHIVE_VERIFY_TIMEOUT_SECONDS", 5.0)
    clock_value = [10.0]
    monkeypatch.setattr(helper.time, "monotonic", lambda: clock_value[0])
    real_lseek = helper.os.lseek
    scans = 0

    def expire_on_second_scan(descriptor: int, offset: int, whence: int) -> int:
        nonlocal scans
        result = real_lseek(descriptor, offset, whence)
        if offset == 0 and whence == os.SEEK_SET:
            scans += 1
            if scans == 2:
                clock_value[0] = 15.0
        return result

    monkeypatch.setattr(helper.os, "lseek", expire_on_second_scan)

    with pytest.raises(helper.HostError, match="temporary_recovery_archive_timeout"):
        helper._assert_temporary_recovery_archive(manifest)

    assert scans == 2


def test_archive_verifier_finds_manifest_after_image_members(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    archive_path = tmp_path / "image.tar.gz"
    image_hex = _manifest(helper)["image"]["image_id"].removeprefix("sha256:")
    layer_id = "a" * 64
    raw = _docker_archive(
        archive_path,
        _temporary_tag(helper),
        order=(
            f"{image_hex}.json",
            "repositories",
            f"{layer_id}/",
            f"{layer_id}/VERSION",
            f"{layer_id}/json",
            f"{layer_id}/layer.tar",
            "manifest.json",
        ),
    )
    archive_path.chmod(0o600)
    monkeypatch.setattr(helper, "TEMPORARY_RECOVERY_ARCHIVE", archive_path)
    _pretend_file_is_root_owned(monkeypatch, helper)
    manifest = _manifest(helper)
    manifest["image"]["archive_sha256"] = hashlib.sha256(raw).hexdigest()
    manifest["image"]["archive_size"] = len(raw)

    helper._assert_temporary_recovery_archive(manifest)


def test_archive_verifier_accepts_closed_oci_graph_without_reading_config_or_layers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    archive_path = tmp_path / "oci-image.tar.gz"
    tag = _temporary_tag(helper)
    raw, image_id = _oci_archive(archive_path, tag)
    archive_path.chmod(0o600)
    monkeypatch.setattr(helper, "TEMPORARY_RECOVERY_ARCHIVE", archive_path)
    _pretend_file_is_root_owned(monkeypatch, helper)
    manifest = _manifest(helper)
    manifest["image"]["image_id"] = image_id
    manifest["image"]["archive_sha256"] = hashlib.sha256(raw).hexdigest()
    manifest["image"]["archive_size"] = len(raw)

    with tarfile.open(archive_path, mode="r:gz") as archive:
        index = json.load(archive.extractfile("index.json"))
        oci_manifest_path = "blobs/sha256/" + index["manifests"][0]["digest"].removeprefix(
            "sha256:"
        )
        image_manifest = json.load(archive.extractfile(oci_manifest_path))
    forbidden_reads = {
        image_manifest["config"]["digest"].replace("sha256:", "blobs/sha256/"),
        *(
            layer["digest"].replace("sha256:", "blobs/sha256/")
            for layer in image_manifest["layers"]
        ),
    }
    extracted: list[str] = []
    real_extractfile = tarfile.TarFile.extractfile

    def guarded_extractfile(self, member):
        name = member if isinstance(member, str) else member.name
        if name in forbidden_reads:
            raise AssertionError(f"archive verifier read protected payload {name}")
        extracted.append(name)
        return real_extractfile(self, member)

    monkeypatch.setattr(tarfile.TarFile, "extractfile", guarded_extractfile)
    helper._assert_temporary_recovery_archive(manifest)

    assert set(extracted) == {"manifest.json", "oci-layout", "index.json", oci_manifest_path}


@pytest.mark.parametrize(
    ("index_descriptor_updates", "additional_descriptors", "extra_members"),
    [
        ({"platform": {"os": "linux", "architecture": "arm64"}}, None, ()),
        (
            {
                "annotations": {
                    "org.opencontainers.image.created": "2025-09-15T00:00:00Z",
                    "org.opencontainers.image.ref.name": "signal-ledger:other",
                }
            },
            None,
            (),
        ),
        (
            None,
            [
                {
                    "digest": "sha256:" + "e" * 64,
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "size": 1,
                }
            ],
            (),
        ),
        (None, None, (("blobs/sha256/" + "f" * 64, b"unreferenced"),)),
    ],
)
def test_archive_verifier_rejects_oci_platform_tag_graph_and_unknown_blob_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    index_descriptor_updates: dict[str, object] | None,
    additional_descriptors: list[dict[str, object]] | None,
    extra_members: tuple[tuple[str, bytes], ...],
) -> None:
    helper = _helper()
    archive_path = tmp_path / "oci-invalid.tar.gz"
    tag = _temporary_tag(helper)
    raw, image_id = _oci_archive(
        archive_path,
        tag,
        index_descriptor_updates=index_descriptor_updates,
        additional_descriptors=additional_descriptors,
        extra_members=extra_members,
    )
    archive_path.chmod(0o600)
    monkeypatch.setattr(helper, "TEMPORARY_RECOVERY_ARCHIVE", archive_path)
    _pretend_file_is_root_owned(monkeypatch, helper)
    manifest = _manifest(helper)
    manifest["image"]["image_id"] = image_id
    manifest["image"]["archive_sha256"] = hashlib.sha256(raw).hexdigest()
    manifest["image"]["archive_size"] = len(raw)

    with pytest.raises(helper.HostError, match="temporary_recovery_archive_invalid"):
        helper._assert_temporary_recovery_archive(manifest)


def test_archive_verifier_rejects_oci_config_digest_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    archive_path = tmp_path / "oci-wrong-config.tar.gz"
    raw, _image_id = _oci_archive(archive_path, _temporary_tag(helper))
    archive_path.chmod(0o600)
    monkeypatch.setattr(helper, "TEMPORARY_RECOVERY_ARCHIVE", archive_path)
    _pretend_file_is_root_owned(monkeypatch, helper)
    manifest = _manifest(helper)
    manifest["image"]["archive_sha256"] = hashlib.sha256(raw).hexdigest()
    manifest["image"]["archive_size"] = len(raw)

    with pytest.raises(helper.HostError, match="temporary_recovery_archive_invalid"):
        helper._assert_temporary_recovery_archive(manifest)


@pytest.mark.parametrize(
    ("member_limit",),
    [(100_000,), (3,)],
)
def test_archive_verifier_rejects_extra_members_and_member_overflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    member_limit: int,
) -> None:
    helper = _helper()
    archive_path = tmp_path / "image.tar.gz"
    raw = _docker_archive(
        archive_path,
        _temporary_tag(helper),
        extra_members=(("unexpected.txt", b"extra"),),
    )
    archive_path.chmod(0o600)
    monkeypatch.setattr(helper, "TEMPORARY_RECOVERY_ARCHIVE", archive_path)
    monkeypatch.setattr(helper, "MAX_TEMPORARY_ARCHIVE_MEMBERS", member_limit)
    _pretend_file_is_root_owned(monkeypatch, helper)
    manifest = _manifest(helper)
    manifest["image"]["archive_sha256"] = hashlib.sha256(raw).hexdigest()
    manifest["image"]["archive_size"] = len(raw)

    with pytest.raises(helper.HostError, match="temporary_recovery_archive_invalid"):
        helper._assert_temporary_recovery_archive(manifest)


@pytest.mark.parametrize(
    ("order", "extra_members"),
    [
        (("manifest.json", "manifest.json"), ()),
        (None, (("../escape", b"x"),)),
    ],
)
def test_archive_verifier_rejects_duplicate_and_unsafe_members(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    order: tuple[str, ...] | None,
    extra_members: tuple[tuple[str, bytes], ...],
) -> None:
    helper = _helper()
    archive_path = tmp_path / "image.tar.gz"
    raw = _docker_archive(
        archive_path,
        _temporary_tag(helper),
        order=order,
        extra_members=extra_members,
    )
    archive_path.chmod(0o600)
    monkeypatch.setattr(helper, "TEMPORARY_RECOVERY_ARCHIVE", archive_path)
    _pretend_file_is_root_owned(monkeypatch, helper)
    manifest = _manifest(helper)
    manifest["image"]["archive_sha256"] = hashlib.sha256(raw).hexdigest()
    manifest["image"]["archive_size"] = len(raw)

    with pytest.raises(helper.HostError, match="temporary_recovery_archive_invalid"):
        helper._assert_temporary_recovery_archive(manifest)


def test_archive_verifier_rejects_member_size_overflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    archive_path = tmp_path / "image.tar.gz"
    raw = _docker_archive(
        archive_path,
        _temporary_tag(helper),
    )
    archive_path.chmod(0o600)
    monkeypatch.setattr(helper, "TEMPORARY_RECOVERY_ARCHIVE", archive_path)
    monkeypatch.setattr(helper, "MAX_TEMPORARY_ARCHIVE_MEMBER_BYTES", 1)
    _pretend_file_is_root_owned(monkeypatch, helper)
    manifest = _manifest(helper)
    manifest["image"]["archive_sha256"] = hashlib.sha256(raw).hexdigest()
    manifest["image"]["archive_size"] = len(raw)

    with pytest.raises(helper.HostError, match="temporary_recovery_archive_invalid"):
        helper._assert_temporary_recovery_archive(manifest)


def test_archive_verifier_rejects_legacy_repository_tag_or_image_id_collisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    archive_path = tmp_path / "legacy-collision.tar.gz"
    tag = _temporary_tag(helper)
    extra_members = (
        (
            "repositories",
            json.dumps(
                {
                    "signal-ledger": {
                        tag.rsplit(":", 1)[1]: "a" * 64,
                        "unexpected": "b" * 64,
                    }
                },
                separators=(",", ":"),
            ).encode(),
        ),
    )
    raw = _docker_archive(archive_path, tag, extra_members=extra_members)
    archive_path.chmod(0o600)
    monkeypatch.setattr(helper, "TEMPORARY_RECOVERY_ARCHIVE", archive_path)
    _pretend_file_is_root_owned(monkeypatch, helper)
    manifest = _manifest(helper)
    manifest["image"]["archive_sha256"] = hashlib.sha256(raw).hexdigest()
    manifest["image"]["archive_size"] = len(raw)

    with pytest.raises(helper.HostError, match="temporary_recovery_archive_invalid"):
        helper._assert_temporary_recovery_archive(manifest)

    wrong_id = "sha256:" + "b" * 64
    raw = _docker_archive(archive_path, tag, image_id=wrong_id)
    manifest["image"]["archive_sha256"] = hashlib.sha256(raw).hexdigest()
    manifest["image"]["archive_size"] = len(raw)
    with pytest.raises(helper.HostError, match="temporary_recovery_archive_invalid"):
        helper._assert_temporary_recovery_archive(manifest)


def test_archive_verifier_rejects_duplicate_manifest_json_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    archive_path = tmp_path / "image.tar.gz"
    tag = _temporary_tag(helper)
    encoded_tags = json.dumps([tag], separators=(",", ":")).encode()
    duplicate_manifest = (
        b'[{"Config":"config.json","RepoTags":'
        + encoded_tags
        + b',"RepoTags":'
        + encoded_tags
        + b","
        + b'"Layers":["layer/layer.tar"]}]'
    )
    with tarfile.open(archive_path, mode="w:gz") as archive:
        for name, content in (
            ("config.json", b"{}"),
            ("layer/layer.tar", b"layer bytes"),
            ("manifest.json", duplicate_manifest),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    raw = archive_path.read_bytes()
    archive_path.chmod(0o600)
    monkeypatch.setattr(helper, "TEMPORARY_RECOVERY_ARCHIVE", archive_path)
    _pretend_file_is_root_owned(monkeypatch, helper)
    manifest = _manifest(helper)
    manifest["image"]["archive_sha256"] = hashlib.sha256(raw).hexdigest()
    manifest["image"]["archive_size"] = len(raw)

    with pytest.raises(helper.HostError, match="temporary_recovery_archive_invalid"):
        helper._assert_temporary_recovery_archive(manifest)


def test_archive_verifier_rejects_unbound_tag_and_extra_image_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    archive_path = tmp_path / "image.tar.gz"
    raw = _docker_archive(archive_path, "signal-ledger:unexpected")
    archive_path.chmod(0o600)
    monkeypatch.setattr(helper, "TEMPORARY_RECOVERY_ARCHIVE", archive_path)
    _pretend_file_is_root_owned(monkeypatch, helper)
    manifest = _manifest(helper)
    manifest["image"]["archive_sha256"] = hashlib.sha256(raw).hexdigest()
    manifest["image"]["archive_size"] = len(raw)

    with pytest.raises(helper.HostError, match="temporary_recovery_archive_invalid"):
        helper._assert_temporary_recovery_archive(manifest)

    manifest_value = [
        {
            "Config": "config.json",
            "RepoTags": [manifest["image"]["repo_tag"]],
            "Layers": ["a/layer.tar"],
        },
        {"Config": "other.json", "RepoTags": ["other:tag"], "Layers": ["b/layer.tar"]},
    ]
    raw_manifest = json.dumps(manifest_value, separators=(",", ":")).encode()
    with tarfile.open(archive_path, mode="w:gz") as archive:
        member = tarfile.TarInfo("manifest.json")
        member.size = len(raw_manifest)
        archive.addfile(member, io.BytesIO(raw_manifest))
    archive_bytes = archive_path.read_bytes()
    manifest["image"]["archive_sha256"] = hashlib.sha256(archive_bytes).hexdigest()
    manifest["image"]["archive_size"] = len(archive_bytes)

    with pytest.raises(helper.HostError, match="temporary_recovery_archive_invalid"):
        helper._assert_temporary_recovery_archive(manifest)
