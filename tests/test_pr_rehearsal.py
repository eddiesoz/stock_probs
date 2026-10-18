from __future__ import annotations

import ast
import copy
import gzip
import hashlib
import io
import json
import os
import re
import runpy
import secrets
import stat
import subprocess
import sys
import tarfile
from contextlib import nullcontext
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


def test_rehearsal_error_preserves_local_image_ledger_retirement_failure() -> None:
    error = schema13.RehearsalError(
        "the local rehearsal cleanup could not be verified",
        cleanup_unverified=("local_image_ledger_retirement",),
    )

    assert error.cleanup_unverified == ("local_image_ledger_retirement",)


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


def _hotfix_pair_manifest(
    reviewed_head: str,
    candidate_archive: bytes,
    recovery_archive: bytes,
) -> dict[str, object]:
    candidate_name = f"signal-ledger-image-{controller.HOTFIX_CANDIDATE_REVISION}.tar.gz"
    recovery_name = f"signal-ledger-image-{controller.PRODUCTION_BASELINE['revision']}.tar.gz"
    return {
        "format_version": 2,
        "contract": controller.HOTFIX_CONTRACT,
        "repository": controller.REPOSITORY,
        "revision": reviewed_head,
        "helper_source": {
            "pull_number": controller.HELPER_SOURCE_PR_NUMBER,
            "revision": reviewed_head,
        },
        "candidate": {
            "asset": candidate_name,
            "archive_sha256": hashlib.sha256(candidate_archive).hexdigest(),
            "archive_size": len(candidate_archive),
            "image_id": controller.HOTFIX_CANDIDATE_IMAGE_ID,
            "platform": "linux/amd64",
            "pull_number": controller.HOTFIX_PR_NUMBER,
            "revision": controller.HOTFIX_CANDIDATE_REVISION,
            "schema_version": 13,
            "source_context_sha256": controller.HOTFIX_CANDIDATE_CONTEXT_SHA256,
            "build_receipt_sha256": controller.HOTFIX_BUILD_RECEIPT_SHA256,
        },
        "recovery": {
            "asset": recovery_name,
            "archive_sha256": hashlib.sha256(recovery_archive).hexdigest(),
            "archive_size": len(recovery_archive),
            "image_id": controller.PRODUCTION_BASELINE["image_id"],
            "platform": "linux/amd64",
            "revision": controller.PRODUCTION_BASELINE["revision"],
            "schema_version": 13,
            "source_context_sha256": controller.HOTFIX_RECOVERY_CONTEXT_SHA256,
            "kind": controller.HOTFIX_RECOVERY_KIND,
            "prior_pair_manifest_sha256": controller.HOTFIX_PRIOR_PAIR_MANIFEST_SHA256,
            "assistant_rollout_mode": "invited",
        },
        "transition": {
            "from_schema": 13,
            "to_schema": 13,
            "migrations": [],
            "restore": False,
        },
        "recovery_overlay": {"kind": "none", "sha256": controller.HOTFIX_EMPTY_OVERLAY_SHA256},
    }


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


def _host_hotfix_manifest(
    helper_revision: str,
    candidate_archive: bytes,
    recovery_archive: bytes,
) -> dict[str, object]:
    return {
        "format_version": 2,
        "contract": host_helper.HOTFIX_CONTRACT,
        "repository": host_helper.REPOSITORY,
        "revision": helper_revision,
        "helper_source": {
            "pull_number": host_helper.HELPER_SOURCE_PR_NUMBER,
            "revision": helper_revision,
        },
        "candidate": {
            "asset": f"signal-ledger-image-{host_helper.HOTFIX_CANDIDATE_REVISION}.tar.gz",
            "archive_sha256": hashlib.sha256(candidate_archive).hexdigest(),
            "archive_size": len(candidate_archive),
            "image_id": host_helper.HOTFIX_CANDIDATE_IMAGE_ID,
            "platform": "linux/amd64",
            "pull_number": host_helper.HOTFIX_PR_NUMBER,
            "revision": host_helper.HOTFIX_CANDIDATE_REVISION,
            "schema_version": 13,
            "source_context_sha256": host_helper.HOTFIX_CANDIDATE_CONTEXT_SHA256,
            "build_receipt_sha256": host_helper.HOTFIX_BUILD_RECEIPT_SHA256,
        },
        "recovery": {
            "asset": (
                f"signal-ledger-image-{host_helper.HOTFIX_RECOVERY_BASELINE['revision']}.tar.gz"
            ),
            "archive_sha256": hashlib.sha256(recovery_archive).hexdigest(),
            "archive_size": len(recovery_archive),
            "image_id": host_helper.HOTFIX_RECOVERY_BASELINE["image_id"],
            "platform": "linux/amd64",
            "revision": host_helper.HOTFIX_RECOVERY_BASELINE["revision"],
            "schema_version": 13,
            "source_context_sha256": host_helper.HOTFIX_RECOVERY_CONTEXT_SHA256,
            "kind": host_helper.HOTFIX_RECOVERY_KIND,
            "prior_pair_manifest_sha256": host_helper.HOTFIX_PRIOR_PAIR_MANIFEST_SHA256,
            "assistant_rollout_mode": "invited",
        },
        "transition": {"from_schema": 13, "to_schema": 13, "migrations": [], "restore": False},
        "recovery_overlay": {"kind": "none", "sha256": host_helper.HOTFIX_EMPTY_OVERLAY_SHA256},
    }


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


def test_schema13_hotfix_pair_accepts_exact_pr9_candidate_and_5ad_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed_head = "a" * 40
    candidate_archive = b"synthetic PR9 OCI archive"
    recovery_archive = b"synthetic 5ad OCI archive"
    recovery_digest = hashlib.sha256(recovery_archive).hexdigest()
    monkeypatch.setattr(controller, "HOTFIX_RECOVERY_ARCHIVE_SHA256", recovery_digest)
    monkeypatch.setattr(controller, "HOTFIX_RECOVERY_ARCHIVE_SIZE", len(recovery_archive))
    tmp_path.chmod(0o700)
    (tmp_path / f"signal-ledger-image-{controller.HOTFIX_CANDIDATE_REVISION}.tar.gz").write_bytes(
        candidate_archive
    )
    (
        tmp_path / f"signal-ledger-image-{controller.PRODUCTION_BASELINE['revision']}.tar.gz"
    ).write_bytes(recovery_archive)
    manifest = _hotfix_pair_manifest(reviewed_head, candidate_archive, recovery_archive)
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    (tmp_path / f"signal-ledger-pair-{reviewed_head}.json").write_bytes(manifest_bytes)
    monkeypatch.setattr(controller, "ARTIFACT_DIRECTORY", tmp_path)

    verified_manifest, assets = controller._artifact_pair(
        reviewed_head,
        candidate_image_id=controller.HOTFIX_CANDIDATE_IMAGE_ID,
        candidate_source_context_sha256=controller.HOTFIX_CANDIDATE_CONTEXT_SHA256,
        recovery_image_id=controller.PRODUCTION_BASELINE["image_id"],
        recovery_source_context_sha256=controller.HOTFIX_RECOVERY_CONTEXT_SHA256,
        recovery_overlay_sha256=controller.HOTFIX_EMPTY_OVERLAY_SHA256,
        pair_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
    )

    assert verified_manifest["contract"] == controller.HOTFIX_CONTRACT
    assert assets["candidate"] == candidate_archive
    assert assets["recovery"] == recovery_archive


def _dual_head_hotfix_manifest(
    helper_head: str,
    reviewed_pr9_head: str,
    candidate_archive: bytes,
    recovery_archive: bytes,
) -> dict[str, object]:
    manifest = _hotfix_pair_manifest(helper_head, candidate_archive, recovery_archive)
    manifest.update(
        {
            "format_version": 3,
            "contract": controller.HOTFIX_V3_CONTRACT,
            "reviewed_pr_head_sha": reviewed_pr9_head,
            "image_source_revision": controller.HOTFIX_V3_IMAGE_SOURCE_REVISION,
        }
    )
    candidate = manifest["candidate"]
    assert isinstance(candidate, dict)
    candidate.update(
        {
            "asset": (f"signal-ledger-image-{controller.HOTFIX_V3_IMAGE_SOURCE_REVISION}.tar.gz"),
            "image_id": controller.HOTFIX_V3_IMAGE_ID,
            "revision": controller.HOTFIX_V3_IMAGE_SOURCE_REVISION,
            "source_context_sha256": controller.HOTFIX_V3_IMAGE_CONTEXT_SHA256,
            "build_receipt_sha256": controller.HOTFIX_V3_BUILD_RECEIPT_SHA256,
        }
    )
    return manifest


def test_schema13_dual_head_pair_keeps_test_head_separate_from_candidate_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper_head = "a" * 40
    reviewed_pr9_head = controller.HOTFIX_V3_REVIEWED_PR_HEAD_SHA
    candidate_archive = b"synthetic current 68c image"
    recovery_archive = b"synthetic retained 5ad image"
    monkeypatch.setattr(
        controller, "HOTFIX_RECOVERY_ARCHIVE_SHA256", hashlib.sha256(recovery_archive).hexdigest()
    )
    monkeypatch.setattr(controller, "HOTFIX_RECOVERY_ARCHIVE_SIZE", len(recovery_archive))
    manifest = _dual_head_hotfix_manifest(
        helper_head, reviewed_pr9_head, candidate_archive, recovery_archive
    )
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    (
        tmp_path / f"signal-ledger-image-{controller.HOTFIX_V3_IMAGE_SOURCE_REVISION}.tar.gz"
    ).write_bytes(candidate_archive)
    (
        tmp_path / f"signal-ledger-image-{controller.PRODUCTION_BASELINE['revision']}.tar.gz"
    ).write_bytes(recovery_archive)
    (tmp_path / f"signal-ledger-pair-{helper_head}.json").write_bytes(manifest_bytes)
    monkeypatch.setattr(controller, "ARTIFACT_DIRECTORY", tmp_path)

    verified, assets = controller._artifact_pair(
        helper_head,
        candidate_image_id=controller.HOTFIX_V3_IMAGE_ID,
        candidate_source_context_sha256=controller.HOTFIX_V3_IMAGE_CONTEXT_SHA256,
        recovery_image_id=controller.PRODUCTION_BASELINE["image_id"],
        recovery_source_context_sha256=controller.HOTFIX_RECOVERY_CONTEXT_SHA256,
        recovery_overlay_sha256=controller.HOTFIX_EMPTY_OVERLAY_SHA256,
        pair_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
    )

    assert verified["revision"] == helper_head
    assert verified["reviewed_pr_head_sha"] == reviewed_pr9_head
    assert verified["image_source_revision"] == controller.HOTFIX_V3_IMAGE_SOURCE_REVISION
    assert verified["candidate"]["revision"] == controller.HOTFIX_V3_IMAGE_SOURCE_REVISION
    assert assets["candidate"] == candidate_archive

    for field, invalid in (
        ("reviewed_pr_head_sha", "d" * 40),
        ("image_source_revision", reviewed_pr9_head),
    ):
        changed = copy.deepcopy(manifest)
        changed[field] = invalid
        raw = json.dumps(changed, sort_keys=True, separators=(",", ":")).encode()
        (tmp_path / f"signal-ledger-pair-{helper_head}.json").write_bytes(raw)
        with pytest.raises(controller.RehearsalError, match="pair_manifest_identity_mismatch"):
            controller._artifact_pair(
                helper_head,
                candidate_image_id=controller.HOTFIX_V3_IMAGE_ID,
                candidate_source_context_sha256=controller.HOTFIX_V3_IMAGE_CONTEXT_SHA256,
                recovery_image_id=controller.PRODUCTION_BASELINE["image_id"],
                recovery_source_context_sha256=controller.HOTFIX_RECOVERY_CONTEXT_SHA256,
                recovery_overlay_sha256=controller.HOTFIX_EMPTY_OVERLAY_SHA256,
                pair_manifest_sha256=hashlib.sha256(raw).hexdigest(),
            )


def test_schema13_host_helper_requires_the_same_explicit_dual_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper_head = "a" * 40
    reviewed_pr9_head = controller.HOTFIX_V3_REVIEWED_PR_HEAD_SHA
    candidate_archive = b"synthetic current 68c image"
    recovery_archive = b"synthetic retained 5ad image"
    monkeypatch.setattr(
        host_helper,
        "HOTFIX_RECOVERY_ARCHIVE_SHA256",
        hashlib.sha256(recovery_archive).hexdigest(),
    )
    monkeypatch.setattr(host_helper, "HOTFIX_RECOVERY_ARCHIVE_SIZE", len(recovery_archive))
    manifest = _dual_head_hotfix_manifest(
        helper_head, reviewed_pr9_head, candidate_archive, recovery_archive
    )
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    candidate_hash = hashlib.sha256(candidate_archive).hexdigest()
    recovery_hash = hashlib.sha256(recovery_archive).hexdigest()
    payload = {
        "candidate_image_id": host_helper.HOTFIX_V3_IMAGE_ID,
        "recovery_image_id": host_helper.HOTFIX_RECOVERY_BASELINE["image_id"],
        "candidate_source_context_sha256": host_helper.HOTFIX_V3_IMAGE_CONTEXT_SHA256,
        "recovery_source_context_sha256": host_helper.HOTFIX_RECOVERY_CONTEXT_SHA256,
        "recovery_overlay_sha256": host_helper.HOTFIX_EMPTY_OVERLAY_SHA256,
        "pair_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "reviewed_pr_head_sha": reviewed_pr9_head,
        "candidate_archive_sha256": candidate_hash,
        "recovery_archive_sha256": recovery_hash,
    }
    staged_path = tmp_path / "staged.tar.gz"

    def stage_asset(
        name: str,
        *,
        expected_digest: str,
        role: str,
        image_id: str,
        **_kwargs: object,
    ) -> host_helper.StagedArchive:
        data = candidate_archive if role == "candidate" else recovery_archive
        assert hashlib.sha256(data).hexdigest() == expected_digest
        staged_path.write_bytes(data)
        return host_helper.StagedArchive(
            staged_path,
            expected_digest,
            len(data),
            image_id,
        )

    monkeypatch.setattr(host_helper, "_stage_asset", stage_asset)
    verified, assets = host_helper._verify_hotfix_pair(
        payload,
        helper_head,
        manifest,
        manifest_bytes,
        candidate_hash=candidate_hash,
        recovery_hash=recovery_hash,
    )

    assert verified["reviewed_pr_head_sha"] == reviewed_pr9_head
    assert assets["candidate"].image_id == host_helper.HOTFIX_V3_IMAGE_ID
    assert assets["candidate"].size == len(candidate_archive)

    changed_payload = {**payload, "reviewed_pr_head_sha": "c" * 40}
    with pytest.raises(host_helper.RehearsalError, match="pair_manifest_identity_mismatch"):
        host_helper._verify_hotfix_pair(
            changed_payload,
            helper_head,
            manifest,
            manifest_bytes,
            candidate_hash=candidate_hash,
            recovery_hash=recovery_hash,
        )

    changed_manifest = {**manifest, "reviewed_pr_head_sha": "d" * 40}
    changed_manifest_bytes = json.dumps(
        changed_manifest, sort_keys=True, separators=(",", ":")
    ).encode()
    changed_manifest_payload = {
        **payload,
        "reviewed_pr_head_sha": "d" * 40,
        "pair_manifest_sha256": hashlib.sha256(changed_manifest_bytes).hexdigest(),
    }
    with pytest.raises(host_helper.RehearsalError, match="pair_manifest_identity_mismatch"):
        host_helper._verify_hotfix_pair(
            changed_manifest_payload,
            helper_head,
            changed_manifest,
            changed_manifest_bytes,
            candidate_hash=candidate_hash,
            recovery_hash=recovery_hash,
        )


def test_schema12_to_13_v1_pair_manifest_remains_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed_head = "a" * 40
    candidate_context = "b" * 64
    recovery_context = "c" * 64
    overlay_sha256 = "d" * 64
    candidate_image_id = "sha256:" + "e" * 64
    recovery_image_id = "sha256:" + "f" * 64
    candidate_archive = b"existing schema12-to-13 candidate archive"
    recovery_archive = b"existing schema13 recovery archive"
    candidate_name = f"signal-ledger-image-{reviewed_head}.tar.gz"
    recovery_name = f"signal-ledger-recovery-{reviewed_head}.tar.gz"
    (tmp_path / candidate_name).write_bytes(candidate_archive)
    (tmp_path / recovery_name).write_bytes(recovery_archive)
    manifest = {
        "format_version": 1,
        "repository": controller.REPOSITORY,
        "revision": reviewed_head,
        "source_context_sha256": candidate_context,
        "migration": {
            "from_schema": 12,
            "to_schema": 13,
            "sha256": controller.MIGRATION_SHA256,
        },
        "candidate": {
            "asset": candidate_name,
            "image_id": candidate_image_id,
            "archive_sha256": hashlib.sha256(candidate_archive).hexdigest(),
            "archive_size": len(candidate_archive),
            "platform": "linux/amd64",
            "revision": reviewed_head,
            "schema_version": 13,
            "source_context_sha256": candidate_context,
        },
        "recovery": {
            "asset": recovery_name,
            "image_id": recovery_image_id,
            "archive_sha256": hashlib.sha256(recovery_archive).hexdigest(),
            "archive_size": len(recovery_archive),
            "platform": "linux/amd64",
            "revision": reviewed_head,
            "schema_version": 13,
            "assistant_enabled": False,
            "source_context_sha256": recovery_context,
            "base_revision": controller.DEPLOYED_BASELINE["revision"],
            "base_image_id": controller.DEPLOYED_BASELINE["image_id"],
            "base_archive_sha256": controller.DEPLOYED_BASELINE["archive_sha256"],
            "overlay_sha256": overlay_sha256,
            "migration_sha256": controller.MIGRATION_SHA256,
        },
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest_path = tmp_path / f"signal-ledger-pair-{reviewed_head}.json"
    manifest_path.write_bytes(manifest_bytes)
    monkeypatch.setattr(controller, "ARTIFACT_DIRECTORY", tmp_path)

    verified, assets = controller._artifact_pair(
        reviewed_head,
        candidate_image_id=candidate_image_id,
        candidate_source_context_sha256=candidate_context,
        recovery_image_id=recovery_image_id,
        recovery_source_context_sha256=recovery_context,
        recovery_overlay_sha256=overlay_sha256,
        pair_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
    )

    assert verified["format_version"] == 1
    assert assets == {
        "manifest": manifest_bytes,
        "candidate": candidate_archive,
        "recovery": recovery_archive,
    }


@pytest.mark.parametrize(
    "mutation",
    ["wrong_helper_pr", "wrong_candidate_pr", "migration", "old_recovery_image"],
)
def test_schema13_hotfix_pair_rejects_wrong_candidate_or_transition_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    reviewed_head = "a" * 40
    candidate_archive = b"synthetic PR9 OCI archive"
    recovery_archive = b"synthetic 5ad OCI archive"
    monkeypatch.setattr(
        controller, "HOTFIX_RECOVERY_ARCHIVE_SHA256", hashlib.sha256(recovery_archive).hexdigest()
    )
    monkeypatch.setattr(controller, "HOTFIX_RECOVERY_ARCHIVE_SIZE", len(recovery_archive))
    manifest = _hotfix_pair_manifest(reviewed_head, candidate_archive, recovery_archive)
    if mutation == "wrong_helper_pr":
        manifest["helper_source"]["pull_number"] = controller.PULL_NUMBER
    elif mutation == "wrong_candidate_pr":
        manifest["candidate"]["pull_number"] = 11
    elif mutation == "migration":
        manifest["transition"]["migrations"] = [controller.MIGRATION_SHA256]
    else:
        manifest["recovery"]["image_id"] = controller.RECOVERY_PRODUCTION_BASELINE["image_id"]
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    (tmp_path / f"signal-ledger-image-{controller.HOTFIX_CANDIDATE_REVISION}.tar.gz").write_bytes(
        candidate_archive
    )
    (
        tmp_path / f"signal-ledger-image-{controller.PRODUCTION_BASELINE['revision']}.tar.gz"
    ).write_bytes(recovery_archive)
    (tmp_path / f"signal-ledger-pair-{reviewed_head}.json").write_bytes(manifest_bytes)
    monkeypatch.setattr(controller, "ARTIFACT_DIRECTORY", tmp_path)

    with pytest.raises(controller.RehearsalError, match="pair_manifest_identity_mismatch"):
        controller._artifact_pair(
            reviewed_head,
            candidate_image_id=controller.HOTFIX_CANDIDATE_IMAGE_ID,
            candidate_source_context_sha256=controller.HOTFIX_CANDIDATE_CONTEXT_SHA256,
            recovery_image_id=controller.PRODUCTION_BASELINE["image_id"],
            recovery_source_context_sha256=controller.HOTFIX_RECOVERY_CONTEXT_SHA256,
            recovery_overlay_sha256=controller.HOTFIX_EMPTY_OVERLAY_SHA256,
            pair_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        )


def test_hotfix_pull_request_gate_uses_fixed_pr9_and_exact_candidate_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_body = json.dumps(
        {
            "state": "open",
            "base": {"ref": "main"},
            "head": {
                "sha": controller.HOTFIX_CANDIDATE_REVISION,
                "repo": {"full_name": controller.REPOSITORY},
            },
            "draft": False,
        }
    ).encode()
    calls: list[tuple[str, str]] = []

    class Response:
        status = 200

        def read(self, _maximum: int) -> bytes:
            return response_body

    class Connection:
        def __init__(self, host: str, *, timeout: int) -> None:
            assert host == "api.github.com"
            assert timeout == 10

        def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
            assert headers["Accept"] == "application/vnd.github+json"
            calls.append((method, path))

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            return None

    monkeypatch.setattr(controller.http.client, "HTTPSConnection", Connection)

    receipt = controller.verify_hotfix_pull_request()

    assert calls == [("GET", f"/repos/{controller.REPOSITORY}/pulls/9")]
    assert receipt["head_sha"] == controller.HOTFIX_CANDIDATE_REVISION
    assert receipt["pull_number"] == 9


def test_host_v2_pair_manifest_stages_exact_candidate_and_previous_production_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper_revision = "a" * 40
    candidate_archive = b"candidate-oci-archive"
    recovery_archive = b"previous-production-oci-archive"
    recovery_digest = hashlib.sha256(recovery_archive).hexdigest()
    monkeypatch.setattr(host_helper, "HOTFIX_RECOVERY_ARCHIVE_SHA256", recovery_digest)
    monkeypatch.setattr(host_helper, "HOTFIX_RECOVERY_ARCHIVE_SIZE", len(recovery_archive))
    manifest = _host_hotfix_manifest(helper_revision, candidate_archive, recovery_archive)
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    candidate_digest = hashlib.sha256(candidate_archive).hexdigest()
    staged: list[tuple[str, str, str]] = []

    monkeypatch.setattr(host_helper, "_read_small_asset", lambda *_args: manifest_bytes)

    def stage(name: str, **kwargs):
        staged.append((name, kwargs["image_id"], kwargs["revision"]))
        size = len(candidate_archive) if kwargs["role"] == "candidate" else len(recovery_archive)
        digest = candidate_digest if kwargs["role"] == "candidate" else recovery_digest
        return host_helper.StagedArchive(
            Path(f"/{kwargs['role']}.tar.gz"), digest, size, kwargs["image_id"]
        )

    monkeypatch.setattr(host_helper, "_stage_asset", stage)
    payload = {
        "candidate_image_id": host_helper.HOTFIX_CANDIDATE_IMAGE_ID,
        "candidate_source_context_sha256": host_helper.HOTFIX_CANDIDATE_CONTEXT_SHA256,
        "recovery_image_id": host_helper.HOTFIX_RECOVERY_BASELINE["image_id"],
        "recovery_source_context_sha256": host_helper.HOTFIX_RECOVERY_CONTEXT_SHA256,
        "recovery_overlay_sha256": host_helper.HOTFIX_EMPTY_OVERLAY_SHA256,
        "pair_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "candidate_archive_sha256": candidate_digest,
        "recovery_archive_sha256": recovery_digest,
    }

    result_manifest, staged_archives = host_helper._verify_pair(payload, helper_revision)

    assert result_manifest["contract"] == host_helper.HOTFIX_CONTRACT
    assert set(staged_archives) == {"candidate", "recovery"}
    assert staged == [
        (
            f"signal-ledger-pr1-{helper_revision}-candidate.tar.gz",
            host_helper.HOTFIX_CANDIDATE_IMAGE_ID,
            host_helper.HOTFIX_CANDIDATE_REVISION,
        ),
        (
            f"signal-ledger-pr1-{helper_revision}-recovery.tar.gz",
            host_helper.HOTFIX_RECOVERY_BASELINE["image_id"],
            host_helper.HOTFIX_RECOVERY_BASELINE["revision"],
        ),
    ]


@pytest.mark.parametrize("mutation", ["wrong_helper_pr", "old_recovery_image"])
def test_host_v2_pair_rejects_identity_mismatch_before_staging(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    helper_revision = "a" * 40
    candidate_archive = b"candidate-oci-archive"
    recovery_archive = b"previous-production-oci-archive"
    recovery_digest = hashlib.sha256(recovery_archive).hexdigest()
    monkeypatch.setattr(host_helper, "HOTFIX_RECOVERY_ARCHIVE_SHA256", recovery_digest)
    monkeypatch.setattr(host_helper, "HOTFIX_RECOVERY_ARCHIVE_SIZE", len(recovery_archive))
    manifest = _host_hotfix_manifest(helper_revision, candidate_archive, recovery_archive)
    if mutation == "wrong_helper_pr":
        manifest["helper_source"]["pull_number"] = host_helper.PULL_NUMBER
    else:
        manifest["recovery"]["image_id"] = host_helper.RECOVERY_PRODUCTION_BASELINE["image_id"]
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    stage_calls: list[str] = []
    monkeypatch.setattr(host_helper, "_read_small_asset", lambda *_args: manifest_bytes)
    monkeypatch.setattr(
        host_helper,
        "_stage_asset",
        lambda name, **_kwargs: stage_calls.append(name),
    )
    payload = {
        "candidate_image_id": host_helper.HOTFIX_CANDIDATE_IMAGE_ID,
        "candidate_source_context_sha256": host_helper.HOTFIX_CANDIDATE_CONTEXT_SHA256,
        "recovery_image_id": host_helper.HOTFIX_RECOVERY_BASELINE["image_id"],
        "recovery_source_context_sha256": host_helper.HOTFIX_RECOVERY_CONTEXT_SHA256,
        "recovery_overlay_sha256": host_helper.HOTFIX_EMPTY_OVERLAY_SHA256,
        "pair_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "candidate_archive_sha256": hashlib.sha256(candidate_archive).hexdigest(),
        "recovery_archive_sha256": recovery_digest,
    }

    with pytest.raises(host_helper.RehearsalError, match="pair_manifest_identity_mismatch"):
        host_helper._verify_pair(payload, helper_revision)
    assert stage_calls == []


@pytest.mark.parametrize(
    "raw", [b'{"format_version":2,"format_version":2}', b'{"format_version":true}']
)
def test_host_pair_version_probe_rejects_duplicate_or_untyped_version(
    monkeypatch: pytest.MonkeyPatch,
    raw: bytes,
) -> None:
    monkeypatch.setattr(host_helper, "_read_small_asset", lambda *_args: raw)
    payload = {
        "reviewed_head_sha": "a" * 40,
        "pair_manifest_sha256": hashlib.sha256(raw).hexdigest(),
    }
    with pytest.raises(host_helper.RehearsalError, match="pair_manifest_invalid"):
        host_helper._pair_manifest_version(payload)


def test_host_pair_dispatch_keeps_v1_schema_migration_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "repository": host_helper.REPOSITORY,
        "pull_number": host_helper.PULL_NUMBER,
        "reviewed_head_sha": "a" * 40,
    }
    expected = {"status": "legacy-v1"}
    monkeypatch.setattr(host_helper, "_pair_manifest_version", lambda _payload: 1)
    monkeypatch.setattr(
        host_helper, "_run_pair_v1", lambda observed: expected if observed is payload else {}
    )
    monkeypatch.setattr(
        host_helper,
        "_run_pair_v2",
        lambda _payload: pytest.fail("v1 dispatch must keep the migration runner"),
    )

    assert host_helper._run_pair(payload) == expected


def _valid_host_pair_request_payload(
    *, reviewed_pr_head_sha: str | None = None
) -> dict[str, object]:
    """Build the exact fixed payload shape emitted by the PR pair caller."""
    payload: dict[str, object] = {
        "repository": host_helper.REPOSITORY,
        "pull_number": host_helper.HELPER_SOURCE_PR_NUMBER,
        "reviewed_head_sha": "a" * 40,
        "candidate_image_id": "sha256:" + "b" * 64,
        "candidate_source_context_sha256": "c" * 64,
        "recovery_image_id": "sha256:" + "d" * 64,
        "recovery_source_context_sha256": "e" * 64,
        "recovery_overlay_sha256": "f" * 64,
        "pair_manifest_sha256": "1" * 64,
        "candidate_archive_sha256": "2" * 64,
        "recovery_archive_sha256": "3" * 64,
    }
    if reviewed_pr_head_sha is not None:
        payload["reviewed_pr_head_sha"] = reviewed_pr_head_sha
    return payload


@pytest.mark.parametrize(
    ("pull_number", "reviewed_pr_head_sha"),
    [
        (host_helper.PULL_NUMBER, None),
        (host_helper.HELPER_SOURCE_PR_NUMBER, None),
        (host_helper.HELPER_SOURCE_PR_NUMBER, host_helper.HOTFIX_V3_REVIEWED_PR_HEAD_SHA),
    ],
)
def test_host_pair_request_parser_accepts_only_fixed_version_shapes(
    pull_number: int,
    reviewed_pr_head_sha: str | None,
) -> None:
    payload = _valid_host_pair_request_payload(reviewed_pr_head_sha=reviewed_pr_head_sha)
    payload["pull_number"] = pull_number
    request = {"operation": "rehearse_pr_pair", "payload": payload}

    operation, parsed_payload = host_helper._parse_request(
        json.dumps(request, separators=(",", ":")).encode("utf-8")
    )

    assert operation == "rehearse_pr_pair"
    assert parsed_payload == payload


@pytest.mark.parametrize(
    ("change", "expected_error"),
    [
        ("missing_required", "payload_invalid"),
        ("malformed_v3_head", "reviewed_pr_head_invalid"),
        ("extra_field", "payload_invalid"),
        ("explicit_version_field", "payload_invalid"),
        ("boolean_pull_number", "fixed_pull_request_mismatch"),
        ("unknown_pull_number", "fixed_pull_request_mismatch"),
        ("v3_wrong_pull_number", "fixed_pull_request_mismatch"),
    ],
)
def test_host_pair_request_parser_rejects_invalid_versioned_payloads(
    change: str,
    expected_error: str,
) -> None:
    payload = _valid_host_pair_request_payload(
        reviewed_pr_head_sha=host_helper.HOTFIX_V3_REVIEWED_PR_HEAD_SHA
    )
    if change == "missing_required":
        del payload["candidate_archive_sha256"]
    elif change == "malformed_v3_head":
        payload["reviewed_pr_head_sha"] = "not-a-revision"
    elif change == "extra_field":
        payload["arbitrary_command"] = "run"
    elif change == "explicit_version_field":
        payload["format_version"] = 3
    elif change == "boolean_pull_number":
        payload["pull_number"] = True
    elif change == "unknown_pull_number":
        payload["pull_number"] = 12
    elif change == "v3_wrong_pull_number":
        payload["pull_number"] = host_helper.PULL_NUMBER

    request = {"operation": "rehearse_pr_pair", "payload": payload}
    with pytest.raises(host_helper.RehearsalError, match=expected_error):
        host_helper._parse_request(json.dumps(request, separators=(",", ":")).encode("utf-8"))


@pytest.mark.parametrize(
    ("format_version", "pull_number", "reviewed_pr_head_sha", "expected_error"),
    [
        (1, host_helper.PULL_NUMBER, None, None),
        (2, host_helper.HELPER_SOURCE_PR_NUMBER, None, None),
        (3, host_helper.HELPER_SOURCE_PR_NUMBER, host_helper.HOTFIX_V3_REVIEWED_PR_HEAD_SHA, None),
        (1, host_helper.HELPER_SOURCE_PR_NUMBER, None, "fixed_pull_request_mismatch"),
        (2, host_helper.PULL_NUMBER, None, "fixed_pull_request_mismatch"),
        (3, host_helper.HELPER_SOURCE_PR_NUMBER, None, "payload_invalid"),
        (3, host_helper.HELPER_SOURCE_PR_NUMBER, "not-a-revision", "reviewed_pr_head_invalid"),
        (
            2,
            host_helper.HELPER_SOURCE_PR_NUMBER,
            host_helper.HOTFIX_V3_REVIEWED_PR_HEAD_SHA,
            "payload_invalid",
        ),
        (4, host_helper.HELPER_SOURCE_PR_NUMBER, None, "pair_manifest_version_unsupported"),
    ],
)
def test_host_pair_dispatch_binds_payload_shape_and_pull_to_manifest_version(
    monkeypatch: pytest.MonkeyPatch,
    format_version: int,
    pull_number: int,
    reviewed_pr_head_sha: str | None,
    expected_error: str | None,
) -> None:
    payload = _valid_host_pair_request_payload(reviewed_pr_head_sha=reviewed_pr_head_sha)
    payload["pull_number"] = pull_number
    expected = {"format_version": format_version}
    dispatched: list[tuple[str, dict[str, object], int | None]] = []
    monkeypatch.setattr(host_helper, "_pair_manifest_version", lambda _payload: format_version)
    monkeypatch.setattr(
        host_helper,
        "_run_pair_v1",
        lambda observed: dispatched.append(("v1", observed, None)) or expected,
    )
    monkeypatch.setattr(
        host_helper,
        "_run_pair_v2",
        lambda observed, *, format_version=2: dispatched.append(("v2", observed, format_version))
        or expected,
    )

    if expected_error is not None:
        with pytest.raises(host_helper.RehearsalError, match=expected_error):
            host_helper._run_pair(payload)
        assert dispatched == []
    else:
        assert host_helper._run_pair(payload) == expected
        assert dispatched == [
            ("v1", payload, None) if format_version == 1 else ("v2", payload, format_version)
        ]


def test_recovery_process_profile_preserves_v1_and_supports_pinned_v2_supervisor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probes: list[str] = []
    v1_result = {
        "uid": 10001,
        "gid": 10001,
        "cap_eff": 0,
        "cap_prm": 0,
        "cap_bnd": 192,
        "no_new_privileges": True,
        "tmp_writable": True,
        "worker_home_private": True,
        "native_worker_absent": True,
    }
    v2_result = {
        **v1_result,
        "container_supervisor_present": True,
        "opencode_binary_present": True,
        "assistant_package_present": True,
        "assistant_disabled_readiness": True,
        "pid1_supervisor_verified": True,
        "app_wrapper_identity_verified": True,
        "app_process_identity_verified": True,
        "process_inventory_bounded": True,
    }

    def run(command: list[str], **_kwargs: object) -> CompletedProcess[bytes]:
        probe = command[-1]
        probes.append(probe)
        result = v2_result if "assistant_disabled_readiness" in probe else v1_result
        return CompletedProcess(command, 0, json.dumps(result).encode(), b"")

    monkeypatch.setattr(host_helper, "_run", run)

    assert host_helper._recovery_process_profile("a" * 64)["native_worker_absent"] is True
    assert (
        host_helper._recovery_process_profile("b" * 64, same_schema_hotfix=True)[
            "container_supervisor_present"
        ]
        is True
    )
    assert "assert not pathlib.Path('/usr/local/bin/opencode').exists()" in probes[0]
    assert "find_spec('stock_probs.assistant') is None" in probes[0]
    assert "stock_probs.container_supervisor" not in probes[0]
    assert probes[1] == host_helper._recovery_process_profile_probe_v2()


@pytest.mark.parametrize("cap_bnd", [0, 256])
def test_v2_recovery_process_profile_rejects_unexpected_reported_bound_capabilities(
    monkeypatch: pytest.MonkeyPatch,
    cap_bnd: int,
) -> None:
    profile = {
        "uid": 10001,
        "gid": 10001,
        "cap_eff": 0,
        "cap_prm": 0,
        "cap_bnd": cap_bnd,
        "no_new_privileges": True,
        "tmp_writable": True,
        "worker_home_private": True,
        "native_worker_absent": True,
        "container_supervisor_present": True,
        "opencode_binary_present": True,
        "assistant_package_present": True,
        "assistant_disabled_readiness": True,
        "pid1_supervisor_verified": True,
        "app_wrapper_identity_verified": True,
        "app_process_identity_verified": True,
        "process_inventory_bounded": True,
    }

    def run(command: list[str], **_kwargs: object) -> CompletedProcess[bytes]:
        return CompletedProcess(command, 0, json.dumps(profile).encode(), b"")

    monkeypatch.setattr(host_helper, "_run", run)

    with pytest.raises(host_helper.RehearsalError, match="recovery_process_identity_invalid"):
        host_helper._recovery_process_profile("a" * 64, same_schema_hotfix=True)


def _profile_proc_status(
    uid: int | tuple[int, int, int, int],
    gid: int | tuple[int, int, int, int],
    *,
    ppid: int,
    cap_eff: int,
    cap_prm: int,
    cap_bnd: int = 192,
    no_new_privileges: int = 1,
) -> str:
    uid_values = (uid,) * 4 if isinstance(uid, int) else uid
    gid_values = (gid,) * 4 if isinstance(gid, int) else gid
    return (
        f"Uid:\t{' '.join(str(value) for value in uid_values)}\n"
        f"Gid:\t{' '.join(str(value) for value in gid_values)}\n"
        f"PPid:\t{ppid}\n"
        f"CapEff:\t{cap_eff:016x}\nCapPrm:\t{cap_prm:016x}\n"
        f"CapBnd:\t{cap_bnd:016x}\nNoNewPrivs:\t{no_new_privileges}\n"
    )


def _write_profile_proc(
    proc_root: Path,
    pid: int,
    command: tuple[str, ...],
    *,
    uid: int | tuple[int, int, int, int],
    gid: int | tuple[int, int, int, int],
    ppid: int | None = None,
    cap_eff: int = 0,
    cap_prm: int = 0,
    cap_bnd: int = 192,
    no_new_privileges: int = 1,
) -> Path:
    process_path = proc_root / str(pid)
    process_path.mkdir(exist_ok=True)
    if ppid is None:
        ppid = {1: 0, 101: 1, 102: 101}.get(pid, 1)
    (process_path / "status").write_text(
        _profile_proc_status(
            uid,
            gid,
            ppid=ppid,
            cap_eff=cap_eff,
            cap_prm=cap_prm,
            cap_bnd=cap_bnd,
            no_new_privileges=no_new_privileges,
        ),
        encoding="ascii",
    )
    (process_path / "cmdline").write_bytes(b"\0".join(item.encode() for item in command) + b"\0")
    return process_path


def _execute_generated_v2_recovery_probe(
    tmp_path: Path,
    scenario: str = "valid",
) -> dict[str, object]:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    root = tmp_path / "image-root"
    opencode = root / "usr/local/bin/opencode"
    opencode.parent.mkdir(parents=True)
    opencode.write_bytes(b"pinned image binary fixture")
    (root / "tmp").mkdir()
    (root / "run/assistant-worker-home").mkdir(parents=True)

    pid1_command = (
        "python",
        "-m",
        "stock_probs.container_supervisor",
        "serve",
        "--host",
        "0.0.0.0",  # noqa: S104 - listener remains inside the container
        "--port",
        "8000",
        "--allow-non-loopback",
    )
    app_wrapper_command = (
        "/usr/local/bin/python",
        "-m",
        "stock_probs.container_supervisor",
        "--child",
        "app",
    )
    app_command = (
        "/usr/local/bin/python",
        "/usr/local/bin/stock-probs",
        "serve",
        "--host",
        "0.0.0.0",  # noqa: S104 - binds internally; published host port stays loopback-only
        "--port",
        "8000",
        "--allow-non-loopback",
    )
    _write_profile_proc(
        proc_root,
        1,
        pid1_command,
        uid=0,
        gid=0,
        ppid=0,
        cap_eff=192,
        cap_prm=192,
    )
    app_wrapper = _write_profile_proc(
        proc_root,
        101,
        app_wrapper_command,
        uid=10001,
        gid=10001,
        ppid=1,
    )
    app_process = _write_profile_proc(
        proc_root,
        102,
        app_command,
        uid=10001,
        gid=10001,
        ppid=101,
    )
    _write_profile_proc(
        proc_root,
        900,
        ("/usr/local/bin/python", "-c", "profile probe"),
        uid=10001,
        gid=10001,
    )

    if scenario == "wrong-wrapper-parent":
        _write_profile_proc(
            proc_root,
            101,
            app_wrapper_command,
            uid=10001,
            gid=10001,
            ppid=900,
        )
    elif scenario == "wrong-app-parent":
        _write_profile_proc(
            proc_root,
            102,
            app_command,
            uid=10001,
            gid=10001,
            ppid=1,
        )
    elif scenario == "missing-ppid":
        status_path = proc_root / "102" / "status"
        status = status_path.read_text(encoding="ascii")
        expected = "PPid:\t101\n"
        assert status.count(expected) == 1
        status_path.write_text(status.replace(expected, "", 1), encoding="ascii")
    elif scenario == "duplicate-ppid":
        status_path = proc_root / "102" / "status"
        with status_path.open("a", encoding="ascii") as status_file:
            status_file.write("PPid:\t101\n")
    elif scenario == "pid1-missing-serve":
        _write_profile_proc(
            proc_root,
            1,
            pid1_command[:3],
            uid=0,
            gid=0,
            ppid=0,
            cap_eff=192,
            cap_prm=192,
        )
    elif scenario == "pid1-mutated-serve-args":
        _write_profile_proc(
            proc_root,
            1,
            (*pid1_command[:-3], "9000", "--allow-non-loopback"),
            uid=0,
            gid=0,
            ppid=0,
            cap_eff=192,
            cap_prm=192,
        )
    elif scenario == "wrong-app-interpreter":
        _write_profile_proc(
            proc_root,
            102,
            ("/usr/bin/python", *app_command[1:]),
            uid=10001,
            gid=10001,
            ppid=101,
        )
    elif scenario == "wrong-app-script":
        _write_profile_proc(
            proc_root,
            102,
            (app_command[0], "/usr/local/bin/stock-probs-other", *app_command[2:]),
            uid=10001,
            gid=10001,
            ppid=101,
        )
    elif scenario == "root-app":
        _write_profile_proc(
            proc_root,
            102,
            tuple((app_process / "cmdline").read_bytes().decode().split("\0")[:-1]),
            uid=0,
            gid=0,
        )
    elif scenario == "extra-app-caps":
        _write_profile_proc(
            proc_root,
            101,
            tuple((app_wrapper / "cmdline").read_bytes().decode().split("\0")[:-1]),
            uid=10001,
            gid=10001,
            ppid=1,
            cap_prm=64,
        )
    elif scenario == "root-app-wrapper":
        _write_profile_proc(
            proc_root,
            101,
            tuple((app_wrapper / "cmdline").read_bytes().decode().split("\0")[:-1]),
            uid=0,
            gid=0,
        )
    elif scenario == "extra-app-process-caps":
        _write_profile_proc(
            proc_root,
            102,
            tuple((app_process / "cmdline").read_bytes().decode().split("\0")[:-1]),
            uid=10001,
            gid=10001,
            ppid=101,
            cap_eff=64,
        )
    elif scenario == "app-identity-fields":
        _write_profile_proc(
            proc_root,
            102,
            tuple((app_process / "cmdline").read_bytes().decode().split("\0")[:-1]),
            uid=(10001, 10001, 0, 10001),
            gid=10001,
            ppid=101,
        )
    elif scenario == "app-no-new-privileges":
        _write_profile_proc(
            proc_root,
            102,
            tuple((app_process / "cmdline").read_bytes().decode().split("\0")[:-1]),
            uid=10001,
            gid=10001,
            ppid=101,
            no_new_privileges=0,
        )
    elif scenario == "missing-app":
        for child in app_process.iterdir():
            child.unlink()
        app_process.rmdir()
    elif scenario == "running-worker":
        _write_profile_proc(
            proc_root,
            103,
            (
                "/usr/local/bin/python",
                "-m",
                "stock_probs.container_supervisor",
                "--child",
                "worker",
            ),
            uid=10002,
            gid=10002,
        )
    elif scenario == "running-opencode":
        _write_profile_proc(
            proc_root,
            103,
            (
                "/usr/local/bin/opencode",
                "serve",
                "--hostname",
                "127.0.0.1",
                "--port",
                "4097",
            ),
            uid=10002,
            gid=10002,
        )
    elif scenario == "bad-pid1":
        _write_profile_proc(
            proc_root,
            1,
            pid1_command,
            uid=0,
            gid=0,
            ppid=0,
            cap_eff=192,
            cap_prm=192,
            cap_bnd=256,
        )
    elif scenario == "bad-pid1-identity":
        _write_profile_proc(
            proc_root,
            1,
            pid1_command,
            uid=10001,
            gid=10001,
            cap_eff=192,
            cap_prm=192,
        )
    elif scenario == "extra-app-bound-caps":
        _write_profile_proc(
            proc_root,
            102,
            tuple((app_process / "cmdline").read_bytes().decode().split("\0")[:-1]),
            uid=10001,
            gid=10001,
            ppid=101,
            cap_bnd=256,
        )
    elif scenario == "unknown-root-process":
        _write_profile_proc(
            proc_root,
            103,
            ("/bin/sh", "-c", "id"),
            uid=0,
            gid=0,
        )
    elif scenario == "oversized-process-table":
        for pid in range(1000, 1125):
            (proc_root / str(pid)).mkdir()
    elif scenario == "oversized-cmdline":
        process_path = _write_profile_proc(
            proc_root,
            103,
            ("/bin/sh", "-c", "id"),
            uid=10001,
            gid=10001,
        )
        (process_path / "cmdline").write_bytes(b"x" * 8193)
    elif scenario == "oversized-status":
        process_path = _write_profile_proc(
            proc_root,
            103,
            ("/bin/sh", "-c", "id"),
            uid=10001,
            gid=10001,
        )
        with (process_path / "status").open("ab") as status_file:
            status_file.write(b"x" * 8193)
    elif scenario == "missing-opencode":
        opencode.unlink()

    readiness_payload: dict[str, object] = {
        "status": "ready",
        "schema_version": 13,
        "assistant": {"enabled": False, "status": "disabled"},
    }
    if scenario == "assistant-enabled":
        readiness_payload["assistant"] = {"enabled": True, "status": "ready"}
    readiness_bytes = json.dumps(readiness_payload).encode()

    def find_module(name: str) -> object | None:
        return (
            object()
            if name in {"stock_probs.assistant", "stock_probs.container_supervisor"}
            else None
        )

    def open_readiness(url: str, *, timeout: int):
        assert url == "http://127.0.0.1:8000/api/v1/readiness"
        assert timeout == 2
        return nullcontext(SimpleNamespace(read=lambda limit: readiness_bytes[:limit]))

    def write_marker(filesystem_root: Path, area: str, name: str) -> None:
        if area == "worker_home" and scenario != "worker-home-writable":
            raise PermissionError
        target = filesystem_root / ("tmp" if area == "tmp" else "run/assistant-worker-home") / name
        target.open("x", encoding="ascii").close()
        if area == "worker_home":
            return
        if scenario == "tmp-readonly":
            target.unlink()
            raise PermissionError

    def remove_marker(filesystem_root: Path, area: str, name: str) -> None:
        target = filesystem_root / ("tmp" if area == "tmp" else "run/assistant-worker-home") / name
        target.unlink()

    probe_path = tmp_path / "generated-profile-probe.py"
    probe_path.write_text(host_helper._recovery_process_profile_probe_v2(), encoding="utf-8")
    namespace = runpy.run_path(str(probe_path), run_name="recovery_profile_fixture")
    collector = namespace["_collect_recovery_profile"]
    assert callable(collector)
    return collector(
        proc_root,
        root,
        900,
        "/usr/local/bin/python",
        find_module,
        open_readiness,
        write_marker,
        remove_marker,
    )


def test_v2_generated_recovery_probe_validates_synthetic_process_topology(
    tmp_path: Path,
) -> None:
    profile = _execute_generated_v2_recovery_probe(tmp_path)

    assert profile["pid1_supervisor_verified"] is True
    assert profile["app_wrapper_identity_verified"] is True
    assert profile["app_process_identity_verified"] is True
    assert profile["process_inventory_bounded"] is True
    assert profile["native_worker_absent"] is True
    assert profile["assistant_disabled_readiness"] is True
    assert profile["worker_home_private"] is True
    assert profile["tmp_writable"] is True


@pytest.mark.parametrize(
    "scenario",
    [
        "wrong-wrapper-parent",
        "wrong-app-parent",
        "missing-ppid",
        "duplicate-ppid",
        "pid1-missing-serve",
        "pid1-mutated-serve-args",
        "wrong-app-interpreter",
        "wrong-app-script",
        "root-app",
        "root-app-wrapper",
        "extra-app-caps",
        "extra-app-process-caps",
        "app-identity-fields",
        "app-no-new-privileges",
        "missing-app",
        "running-worker",
        "running-opencode",
        "bad-pid1",
        "bad-pid1-identity",
        "extra-app-bound-caps",
        "unknown-root-process",
        "oversized-process-table",
        "oversized-cmdline",
        "oversized-status",
        "missing-opencode",
        "assistant-enabled",
        "worker-home-writable",
        "tmp-readonly",
    ],
)
def test_v2_generated_recovery_probe_rejects_unsafe_synthetic_topologies(
    tmp_path: Path,
    scenario: str,
) -> None:
    with pytest.raises((AssertionError, PermissionError)):
        _execute_generated_v2_recovery_probe(tmp_path, scenario)


@pytest.mark.parametrize("native_failure", [False, True])
def test_v2_runner_requires_enabled_native_phase_before_write_and_recovery(
    monkeypatch: pytest.MonkeyPatch,
    native_failure: bool,
) -> None:
    helper_revision = "a" * 40
    candidate_archive = b"candidate-oci-archive"
    recovery_archive = b"previous-production-oci-archive"
    candidate_hash = hashlib.sha256(candidate_archive).hexdigest()
    recovery_hash = hashlib.sha256(recovery_archive).hexdigest()
    monkeypatch.setattr(host_helper, "HOTFIX_RECOVERY_ARCHIVE_SHA256", recovery_hash)
    monkeypatch.setattr(host_helper, "HOTFIX_RECOVERY_ARCHIVE_SIZE", len(recovery_archive))
    manifest = _host_hotfix_manifest(helper_revision, candidate_archive, recovery_archive)
    manifest_hash = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    candidate_staged = host_helper.StagedArchive(
        Path("/not-created/candidate.tar.gz"),
        candidate_hash,
        len(candidate_archive),
        host_helper.HOTFIX_CANDIDATE_IMAGE_ID,
    )
    recovery_staged = host_helper.StagedArchive(
        Path("/not-created/recovery.tar.gz"),
        recovery_hash,
        len(recovery_archive),
        host_helper.HOTFIX_RECOVERY_BASELINE["image_id"],
    )
    zero_events = {name: 0 for name in host_helper.OOM_EVENT_COUNTERS}
    sample_offsets = {"a" * 64: 100, "c" * 64: 200, "b" * 64: 300}
    sample_counts: dict[str, int] = {}

    def memory_sample(container: str, *, expected_role: str = "candidate"):
        sample_index = sample_counts.get(container, 0)
        sample_counts[container] = sample_index + 1
        offset = sample_offsets[container]
        return {
            "limit": host_helper._memory_limit_for_role(expected_role),
            "peak": offset * 10 + sample_index,
            "oom_events": zero_events.copy(),
            "cpu_stat": {
                name: offset + sample_index * 10 + index
                for index, name in enumerate(host_helper.CPU_STAT_COUNTERS)
            },
        }

    production_checks: list[bool] = []
    starts: list[tuple[str, str, bool, str, str | None, str, str]] = []
    removed: list[str] = []
    events: list[str] = []
    load_revisions: list[str] = []
    snapshot_value = {
        "marker_present": True,
        "sha256": "d" * 64,
        "security_state_sha256": "e" * 64,
    }
    monkeypatch.setattr(
        host_helper,
        "_verify_installed_source",
        lambda *_args, **_kwargs: {"seed.py": "f" * 64},
    )
    monkeypatch.setattr(host_helper, "_verify_helper_source_pull_request", lambda _revision: None)

    def verify_candidate_pull_request(reviewed_pr_head_sha: str | None = None) -> None:
        assert reviewed_pr_head_sha is None

    monkeypatch.setattr(host_helper, "_verify_hotfix_pull_request", verify_candidate_pull_request)
    monkeypatch.setattr(
        host_helper, "_production_container", lambda: dict(host_helper.PRODUCTION_BASELINE)
    )
    monkeypatch.setattr(
        host_helper,
        "_readiness",
        lambda: {
            "status": "ready",
            "schema_version": 13,
            "assistant": {"enabled": False, "status": "disabled"},
        },
    )
    monkeypatch.setattr(host_helper, "_production_loopback_matches", lambda: True)
    monkeypatch.setattr(host_helper, "_host_memory_kib", lambda: (8 * 1024 * 1024, 2 * 1024 * 1024))
    monkeypatch.setattr(
        host_helper,
        "_check_production",
        lambda _samples, **kwargs: production_checks.append(kwargs.get("startup", False))
        or 2 * 1024 * 1024,
    )
    monkeypatch.setattr(
        host_helper,
        "_verify_pair",
        lambda *_args: (manifest, {"candidate": candidate_staged, "recovery": recovery_staged}),
    )
    monkeypatch.setattr(
        host_helper,
        "_load_image",
        lambda revision, _role, _image, _archive: load_revisions.append(revision),
    )
    monkeypatch.setattr(
        host_helper,
        "_run",
        lambda command, **_kwargs: CompletedProcess(command, 0, (command[-1] + "\n").encode(), b""),
    )
    monkeypatch.setattr(host_helper, "_verify_volume", lambda *_args: None)
    monkeypatch.setattr(host_helper, "_create_candidate_network", lambda *_args: "c" * 64)

    def start_app(image_id, volume, name, **kwargs):
        role = kwargs["role"]
        if role == "candidate":
            candidate_start_count = sum(row[1] == "candidate" for row in starts)
            container = "a" * 64 if candidate_start_count % 2 == 0 else "c" * 64
        else:
            container = "b" * 64
        starts.append(
            (
                image_id,
                role,
                kwargs["assistant_enabled"],
                name,
                kwargs["network"],
                volume,
                hashlib.sha256(kwargs["auth_session_secret"].encode()).hexdigest(),
            )
        )
        events.append(f"start:{role}:{kwargs['assistant_enabled']}")
        return container

    monkeypatch.setattr(host_helper, "_start_app", start_app)
    monkeypatch.setattr(host_helper, "_memory_usage", memory_sample)
    monkeypatch.setattr(
        host_helper,
        "_wait_ready",
        lambda container, **kwargs: events.append(
            f"ready:{'recovery' if container == 'b' * 64 else 'candidate'}:{kwargs['enabled']}"
        ),
    )
    monkeypatch.setattr(host_helper, "_copy_probe_files", lambda *_args: None)
    monkeypatch.setattr(
        host_helper,
        "_seed",
        lambda _container: {
            "users": [
                {"username": "owner-a", "password": "synthetic-a"},
                {"username": "owner-b", "password": "synthetic-b"},
            ],
            "synthetic_user_ids": [11, 12],
        },
    )

    def run_native(container: str, users: list[dict[str, str]], _samples: list[int]):
        assert container == "c" * 64
        assert len(users) == 2
        events.append("candidate:native")
        if native_failure:
            raise host_helper.RehearsalError("native_driver_failed")
        return {
            "native_v2": True,
            "model_id": "openai/gpt-6.1-sol",
            "mcp_workspace_summary_calls": 2,
            "builtin_search_source_count": 8,
            "simultaneous_two_owner_turns": True,
            "owner_isolation": True,
        }

    monkeypatch.setattr(host_helper, "_run_native_workload", run_native)

    def fixture(container: str, operation: str, request: dict[str, object]):
        role = "recovery" if container == "b" * 64 else "candidate"
        events.append(f"{role}:{operation}")
        return {"request_id": "marker-1"} if operation == "marker" else dict(snapshot_value)

    monkeypatch.setattr(host_helper, "_seed_operation", fixture)
    monkeypatch.setattr(host_helper, "_schema_version", lambda image, *_args, **_kwargs: 13)
    monkeypatch.setattr(
        host_helper,
        "_recovery_process_profile",
        lambda _container, **kwargs: {
            "uid": 10001,
            "gid": 10001,
            "cap_eff": 0,
            "cap_prm": 0,
            "cap_bnd": 192,
            "no_new_privileges": True,
            "worker_home_private": True,
            "native_worker_absent": True,
            "tmp_writable": True,
            "container_supervisor_present": kwargs.get("same_schema_hotfix") is True,
            "opencode_binary_present": kwargs.get("same_schema_hotfix") is True,
            "assistant_package_present": kwargs.get("same_schema_hotfix") is True,
            "assistant_disabled_readiness": kwargs.get("same_schema_hotfix") is True,
            "pid1_supervisor_verified": kwargs.get("same_schema_hotfix") is True,
            "app_wrapper_identity_verified": kwargs.get("same_schema_hotfix") is True,
            "app_process_identity_verified": kwargs.get("same_schema_hotfix") is True,
            "process_inventory_bounded": kwargs.get("same_schema_hotfix") is True,
        },
    )
    monkeypatch.setattr(
        host_helper,
        "_remove_owned_container",
        lambda name, *_args: (removed.append(name), events.append(f"remove:{name}")),
    )
    monkeypatch.setattr(
        host_helper,
        "_cleanup_network_before_volume",
        lambda **_kwargs: (True, True),
    )
    monkeypatch.setattr(host_helper, "_cleanup_assets", lambda *_args: None)
    monkeypatch.setattr(
        host_helper,
        "_volume_cli",
        lambda *_args, **_kwargs: pytest.fail(
            "same-schema rehearsal must not invoke migration or restore"
        ),
    )
    payload = {
        "repository": host_helper.REPOSITORY,
        "pull_number": host_helper.HELPER_SOURCE_PR_NUMBER,
        "reviewed_head_sha": helper_revision,
        "candidate_image_id": host_helper.HOTFIX_CANDIDATE_IMAGE_ID,
        "candidate_source_context_sha256": host_helper.HOTFIX_CANDIDATE_CONTEXT_SHA256,
        "recovery_image_id": host_helper.HOTFIX_RECOVERY_BASELINE["image_id"],
        "recovery_source_context_sha256": host_helper.HOTFIX_RECOVERY_CONTEXT_SHA256,
        "recovery_overlay_sha256": host_helper.HOTFIX_EMPTY_OVERLAY_SHA256,
        "pair_manifest_sha256": manifest_hash,
        "candidate_archive_sha256": candidate_hash,
        "recovery_archive_sha256": recovery_hash,
    }

    if native_failure:
        with pytest.raises(host_helper.RehearsalError, match="native_driver_failed"):
            host_helper._run_pair_v2(payload)
        assert [row[2] for row in starts] == [False, True]
        assert starts[0][6] == starts[1][6]
        assert "candidate:marker" not in events
        assert not any(row[1] == "recovery" for row in starts)
        assert removed == [starts[0][3], starts[1][3]]
        return

    result = host_helper._run_pair_v2(payload)

    assert [row[0] for row in starts] == [
        host_helper.HOTFIX_CANDIDATE_IMAGE_ID,
        host_helper.HOTFIX_CANDIDATE_IMAGE_ID,
        host_helper.HOTFIX_RECOVERY_BASELINE["image_id"],
    ]
    assert [row[1] for row in starts] == ["candidate", "candidate", "recovery"]
    assert [row[2] for row in starts] == [False, True, False]
    assert len({row[6] for row in starts}) == 1
    assert len(starts[0][6]) == 64
    assert starts[0][4] == host_helper._candidate_network_name(starts[0][5])
    assert starts[1][4] == starts[0][4]
    assert starts[2][4] == "none"
    assert starts[0][5] == starts[1][5] == starts[2][5]
    assert load_revisions == [
        host_helper.HOTFIX_CANDIDATE_REVISION,
        host_helper.HOTFIX_RECOVERY_BASELINE["revision"],
    ]
    assert events.index("candidate:native") > events.index("ready:candidate:True")
    assert events.index("candidate:marker") > events.index("candidate:native")
    assert events.index("candidate:snapshot") > events.index("candidate:marker")
    assert events.index(f"remove:{starts[1][3]}") < events.index("start:recovery:False")
    assert result["same_disposable_volume"] is True
    assert result["production_mutation"] is False
    assert result["schema13_same_schema_verified"] is True
    assert result["migration_commands_executed"] == 0
    assert result["restore_commands_executed"] == 0
    assert result["post_start_write_preserved"] is True
    assert result["schema_after_recovery"] == 13
    assert result["recovery_process_isolation_verified"] is True
    assert result["candidate_disabled_seed_verified"] is True
    assert result["candidate_enabled_readiness_verified"] is True
    assert result["native_workload_verified"] is True
    assert result["native_model_id"] == "openai/gpt-6.1-sol"
    assert result["mcp_workspace_summary_calls"] == 2
    assert result["native_search_source_count"] == 8
    assert result["simultaneous_two_owner_turns"] is True
    assert result["ownership_isolation_verified"] is True
    assert result["candidate_cpu_stat_evidence"]["baseline"]["usage_usec"] == 200
    assert result["candidate_cpu_stat_evidence"]["final"]["usage_usec"] == 210
    assert result["volume_removed"] is True
    assert result["images_retained"] is True
    assert production_checks[0] is True

    first_pair_key_digest = starts[0][6]
    first_pair_volume = starts[0][5]
    starts.clear()
    host_helper._run_pair_v2(payload)
    assert len(starts) == 3
    assert len({row[6] for row in starts}) == 1
    assert starts[0][6] != first_pair_key_digest
    assert len({row[5] for row in starts}) == 1
    assert starts[0][5] != first_pair_volume


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
    assert calls == ["pair", "source", "pull_request"]
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


def test_v2_review_pins_use_helper_pr11_and_candidate_pr9_without_pr2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision = "a" * 40
    manifest = {
        "format_version": 2,
        "revision": revision,
        "candidate": {
            "image_id": controller.HOTFIX_CANDIDATE_IMAGE_ID,
            "source_context_sha256": controller.HOTFIX_CANDIDATE_CONTEXT_SHA256,
        },
        "recovery": {
            "image_id": controller.PRODUCTION_BASELINE["image_id"],
            "source_context_sha256": controller.HOTFIX_RECOVERY_CONTEXT_SHA256,
        },
        "recovery_overlay": {"sha256": controller.HOTFIX_EMPTY_OVERLAY_SHA256},
    }
    manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode()
    events: list[str] = []
    monkeypatch.setattr(controller, "_environment_review_pins", lambda: None)
    monkeypatch.setattr(controller, "_read_review_metadata", lambda: None)
    monkeypatch.setattr(
        controller,
        "_run_fixed",
        lambda *_args, **_kwargs: (revision + "\n").encode(),
    )
    monkeypatch.setattr(controller, "_read_regular_file", lambda *_args, **_kwargs: manifest_bytes)
    monkeypatch.setattr(
        controller,
        "_artifact_pair",
        lambda *_args, **_kwargs: events.append("manifest-v2"),
    )
    monkeypatch.setattr(
        controller,
        "_verify_local_helper_checkout",
        lambda _revision: events.append("clean-helper-checkout"),
    )
    monkeypatch.setattr(
        controller,
        "verify_helper_source_pull_request",
        lambda _revision: events.append("helper-pr11"),
    )

    def verify_candidate_pull_request(reviewed_pr_head_sha: str | None = None) -> None:
        assert reviewed_pr_head_sha is None
        events.append("candidate-pr9")

    monkeypatch.setattr(controller, "verify_hotfix_pull_request", verify_candidate_pull_request)
    monkeypatch.setattr(
        controller,
        "verify_pull_request",
        lambda *_args: pytest.fail("v2 must not gate helper source through PR #2"),
    )
    monkeypatch.setattr(
        controller,
        "_write_review_metadata",
        lambda *_args: events.append("write-review-pins"),
    )

    result = controller.write_review_pins_from_current_pair()

    assert events == [
        "manifest-v2",
        "clean-helper-checkout",
        "helper-pr11",
        "candidate-pr9",
        "write-review-pins",
    ]
    assert result == {
        "reviewed_pr_head_sha": revision,
        "reviewed_pair_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }


@pytest.mark.parametrize(("format_version", "expected_pull_number"), [(1, 2), (2, 11), (3, 11)])
def test_controller_pair_dispatch_preserves_v1_and_v2_v3_source_contracts(
    monkeypatch: pytest.MonkeyPatch,
    format_version: int,
    expected_pull_number: int,
) -> None:
    revision = "a" * 40
    pair_digest = "b" * 64
    manifest: dict[str, object] = {
        "format_version": format_version,
        "candidate": {"archive_sha256": "c" * 64},
        "recovery": {"archive_sha256": "d" * 64},
    }
    if format_version == 3:
        manifest["reviewed_pr_head_sha"] = controller.HOTFIX_V3_REVIEWED_PR_HEAD_SHA
    config = controller.RehearsalConfig(
        Path("/unused/identity"),
        Path("/unused/known-hosts"),
        revision,
        pair_digest,
    )
    events: list[object] = []
    monkeypatch.setattr(
        controller.RehearsalConfig,
        "from_env",
        classmethod(lambda _cls: config),
    )
    monkeypatch.setattr(
        controller,
        "_artifact_pair",
        lambda *_args, **_kwargs: (manifest, {"manifest": b"m", "candidate": b"c"}),
    )
    monkeypatch.setattr(controller, "verify_pull_request", lambda _sha: events.append("pr2"))
    monkeypatch.setattr(
        controller,
        "verify_helper_source_pull_request",
        lambda _sha: events.append("pr11"),
    )
    monkeypatch.setattr(
        controller,
        "verify_hotfix_pull_request",
        lambda *_args: events.append("pr9"),
    )
    monkeypatch.setattr(
        controller,
        "_verify_local_helper_checkout",
        lambda _sha: events.append("helper-checkout"),
    )
    monkeypatch.setattr(
        controller,
        "_verify_local_reviewed_source",
        lambda *_args, **_kwargs: events.append("v1-source-check"),
    )
    monkeypatch.setattr(
        controller,
        "_verify_local_v3_pr_lineage",
        lambda *_args, **_kwargs: events.append("v3-lineage"),
    )
    monkeypatch.setattr(
        controller,
        "_source_bundle",
        lambda **_kwargs: ({"bootstrap": b"b"}, {"bootstrap": "e" * 64}),
    )
    monkeypatch.setattr(controller, "_ensure_incoming_directories", lambda _config: None)
    monkeypatch.setattr(
        controller,
        "_stage_source_bundle",
        lambda *_args, **kwargs: events.append(("source-stage", kwargs["helper_source_contract"])),
    )
    monkeypatch.setattr(controller, "_stage_assets", lambda *_args: events.append("asset-stage"))
    monkeypatch.setattr(controller, "_cleanup_staged_assets", lambda *_args: None)
    monkeypatch.setattr(controller, "_ssh_prefix", lambda _config: ["ssh"])

    def stop_at_host(command: list[str], **kwargs: object) -> bytes:
        encoded = kwargs["input_bytes"]
        assert isinstance(encoded, bytes)
        request = json.loads(encoded)
        operation, payload = host_helper._parse_request(encoded)
        assert operation == request["operation"] == "rehearse_pr_pair"
        assert payload == request["payload"]
        if format_version == 3:
            assert payload["reviewed_pr_head_sha"] == controller.HOTFIX_V3_REVIEWED_PR_HEAD_SHA
        else:
            assert "reviewed_pr_head_sha" not in payload
        events.append(("host-payload", payload["pull_number"]))
        raise controller.RehearsalError("fixture_host_boundary")

    monkeypatch.setattr(controller, "_run_fixed", stop_at_host)

    with pytest.raises(controller.RehearsalError, match="fixture_host_boundary"):
        controller.rehearse_pr_pair(
            reviewed_head_sha=revision,
            candidate_image_id="sha256:" + "1" * 64,
            candidate_source_context_sha256="2" * 64,
            recovery_image_id="sha256:" + "3" * 64,
            recovery_source_context_sha256="4" * 64,
            recovery_overlay_sha256="5" * 64,
            pair_manifest_sha256=pair_digest,
        )

    expected_contract = controller.HOTFIX_CONTRACT if format_version in {2, 3} else None
    assert ("source-stage", expected_contract) in events
    assert ("host-payload", expected_pull_number) in events
    if format_version == 1:
        assert "pr2" in events and "pr11" not in events and "pr9" not in events
    else:
        assert "pr11" in events and "pr9" in events and "pr2" not in events
        if format_version == 3:
            assert "v3-lineage" in events
            assert manifest["reviewed_pr_head_sha"] == controller.HOTFIX_V3_REVIEWED_PR_HEAD_SHA


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
            assert path == "/repos/eddiesoz/stock_probs/pulls/2"
            assert headers["Accept"] == "application/vnd.github+json"

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            pass

    monkeypatch.setattr(bootstrap.http.client, "HTTPSConnection", Connection)
    bootstrap._verify_pull_request(revision)


def test_controller_verifies_fixed_open_pr2_head(monkeypatch) -> None:
    revision = "a" * 40
    payload = {
        "state": "open",
        "draft": True,
        "base": {"ref": "main"},
        "head": {"sha": revision, "repo": {"full_name": controller.REPOSITORY}},
    }
    requests: list[tuple[str, str, dict[str, str]]] = []

    class Response:
        status = 200

        def read(self, size: int) -> bytes:
            assert size == controller.MAX_RESPONSE_BYTES + 1
            return json.dumps(payload).encode()

    class Connection:
        def __init__(self, host: str, *, timeout: int) -> None:
            assert host == "api.github.com"
            assert timeout == 10

        def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
            requests.append((method, path, headers))

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            pass

    monkeypatch.setattr(controller.http.client, "HTTPSConnection", Connection)

    receipt = controller.verify_pull_request(revision)

    assert requests[0][0:2] == (
        "GET",
        f"/repos/{controller.REPOSITORY}/pulls/2",
    )
    assert receipt == {
        "repository": controller.REPOSITORY,
        "pull_number": 2,
        "state": "open",
        "base": "main",
        "head_sha": revision,
        "draft": True,
    }


def test_controller_verifies_fixed_open_pr11_helper_head(monkeypatch) -> None:
    revision = "a" * 40
    payload = {
        "state": "open",
        "draft": True,
        "base": {"ref": "main"},
        "head": {"sha": revision, "repo": {"full_name": controller.REPOSITORY}},
    }
    requests: list[tuple[str, str]] = []

    class Response:
        status = 200

        def read(self, size: int) -> bytes:
            assert size == controller.MAX_RESPONSE_BYTES + 1
            return json.dumps(payload).encode()

    class Connection:
        def __init__(self, host: str, *, timeout: int) -> None:
            assert host == "api.github.com"
            assert timeout == 10

        def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
            requests.append((method, path))

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            pass

    monkeypatch.setattr(controller.http.client, "HTTPSConnection", Connection)

    receipt = controller.verify_helper_source_pull_request(revision)

    assert requests == [
        ("GET", f"/repos/{controller.REPOSITORY}/pulls/11"),
    ]
    assert receipt["pull_number"] == 11
    assert receipt["head_sha"] == revision


def test_bootstrap_helper_contract_selects_only_fixed_pr11(monkeypatch) -> None:
    revision = "a" * 40
    payload = {
        "state": "open",
        "base": {"ref": "main"},
        "head": {"sha": revision, "repo": {"full_name": bootstrap.REPOSITORY}},
    }
    requests: list[tuple[str, str]] = []

    class Response:
        status = 200

        def read(self, size: int) -> bytes:
            assert size == bootstrap.RESPONSE_LIMIT + 1
            return json.dumps(payload).encode()

    class Connection:
        def __init__(self, host: str, *, timeout: int) -> None:
            assert host == "api.github.com"
            assert timeout == 10

        def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
            requests.append((method, path))

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            pass

    monkeypatch.setattr(bootstrap.http.client, "HTTPSConnection", Connection)

    bootstrap._verify_pull_request(
        revision,
        pull_number=bootstrap.HELPER_SOURCE_PR_NUMBER,
    )
    assert requests == [("GET", f"/repos/{bootstrap.REPOSITORY}/pulls/11")]
    with pytest.raises(bootstrap.InstallError, match="reviewed_pr_invalid"):
        bootstrap._verify_pull_request(revision, pull_number=3)
    with pytest.raises(bootstrap.InstallError, match="reviewed_pr_mismatch"):
        bootstrap._verify_pull_request("b" * 40, pull_number=11)


def test_host_helper_verifies_fixed_open_pr2_head(monkeypatch) -> None:
    revision = "a" * 40
    payload = {
        "state": "open",
        "base": {"ref": "main"},
        "head": {"sha": revision, "repo": {"full_name": host_helper.REPOSITORY}},
    }
    requests: list[tuple[str, str]] = []

    class Response:
        status = 200

        def read(self, size: int) -> bytes:
            assert size == host_helper.MAX_PR_RESPONSE + 1
            return json.dumps(payload).encode()

    class Connection:
        def __init__(self, host: str, *, timeout: int) -> None:
            assert host == "api.github.com"
            assert timeout == 10

        def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
            requests.append((method, path))

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            pass

    monkeypatch.setattr(host_helper.http.client, "HTTPSConnection", Connection)

    host_helper._verify_pull_request(revision)

    assert requests == [("GET", f"/repos/{host_helper.REPOSITORY}/pulls/2")]


def test_host_helper_verifies_fixed_open_pr11_helper_head(monkeypatch) -> None:
    revision = "a" * 40
    payload = {
        "state": "open",
        "base": {"ref": "main"},
        "head": {"sha": revision, "repo": {"full_name": host_helper.REPOSITORY}},
    }
    requests: list[tuple[str, str]] = []

    class Response:
        status = 200

        def read(self, size: int) -> bytes:
            assert size == host_helper.MAX_PR_RESPONSE + 1
            return json.dumps(payload).encode()

    class Connection:
        def __init__(self, host: str, *, timeout: int) -> None:
            assert host == "api.github.com"
            assert timeout == 10

        def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
            requests.append((method, path))

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            pass

    monkeypatch.setattr(host_helper.http.client, "HTTPSConnection", Connection)

    host_helper._verify_helper_source_pull_request(revision)

    assert requests == [("GET", f"/repos/{host_helper.REPOSITORY}/pulls/11")]


def test_host_installed_manifest_binds_v1_pr2_and_v2_pr11_separately(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    revision = "a" * 40
    pair_digest = "b" * 64
    source_files = {name: f"installed {name}".encode() for name in host_helper.INSTALLED_FILES}
    manifest: dict[str, object] = {
        "format_version": 1,
        "repository": host_helper.REPOSITORY,
        "pull_number": host_helper.PULL_NUMBER,
        "reviewed_head_sha": revision,
        "reviewed_pair_manifest_sha256": pair_digest,
        "files": {
            name: hashlib.sha256(contents).hexdigest() for name, contents in source_files.items()
        },
        "installed_at": "2026-10-16T00:00:00Z",
    }

    def read_root_file(path: Path, _maximum: int) -> bytes:
        if path == host_helper.INSTALLED_MANIFEST:
            return json.dumps(manifest).encode()
        if path == host_helper.PRODUCTION_HELPER:
            return source_files["production-deploy-helper.py"]
        return source_files[path.name]

    monkeypatch.setattr(host_helper, "_read_root_file", read_root_file)

    assert host_helper._verify_installed_source(revision, pair_digest) == manifest["files"]

    manifest["pull_number"] = host_helper.HELPER_SOURCE_PR_NUMBER
    manifest["helper_source_contract"] = host_helper.HOTFIX_CONTRACT
    production_helper = tmp_path / "signal-ledger-deploy-helper"
    production_helper.write_bytes(b"reviewed production helper")
    production_helper.chmod(0o750)
    monkeypatch.setattr(host_helper, "PRODUCTION_HELPER", production_helper)
    source_files["production-deploy-helper.py"] = production_helper.read_bytes()
    manifest["files"] = {
        name: hashlib.sha256(contents).hexdigest() for name, contents in source_files.items()
    }
    manifest["previous_production_helper_sha256"] = host_helper.PREVIOUS_PRODUCTION_HELPER_SHA256
    assert (
        host_helper._verify_installed_source(
            revision,
            pair_digest,
            helper_source_contract=host_helper.HOTFIX_CONTRACT,
        )
        == manifest["files"]
    )

    manifest["files"]["production-deploy-helper.py"] = "0" * 64
    with pytest.raises(host_helper.RehearsalError, match="installed_source_digest_mismatch"):
        host_helper._verify_installed_source(
            revision,
            pair_digest,
            helper_source_contract=host_helper.HOTFIX_CONTRACT,
        )
    manifest["files"]["production-deploy-helper.py"] = hashlib.sha256(
        source_files["production-deploy-helper.py"]
    ).hexdigest()
    manifest["previous_production_helper_sha256"] = "0" * 64
    with pytest.raises(host_helper.RehearsalError, match="installed_manifest_mismatch"):
        host_helper._verify_installed_source(
            revision,
            pair_digest,
            helper_source_contract=host_helper.HOTFIX_CONTRACT,
        )
    manifest["previous_production_helper_sha256"] = host_helper.PREVIOUS_PRODUCTION_HELPER_SHA256

    manifest["pull_number"] = host_helper.PULL_NUMBER
    with pytest.raises(host_helper.RehearsalError, match="installed_manifest_mismatch"):
        host_helper._verify_installed_source(
            revision,
            pair_digest,
            helper_source_contract=host_helper.HOTFIX_CONTRACT,
        )
    with pytest.raises(host_helper.RehearsalError, match="installed_manifest_mismatch"):
        host_helper._verify_installed_source(
            revision,
            pair_digest,
            helper_source_contract="pull=11",
        )


def test_host_v1_v2_and_v3_runner_keep_contracts_and_require_v3_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, object]] = []

    def installed_source(revision: str, pair_digest: str, **kwargs: object) -> dict[str, str]:
        events.append(("installed", kwargs.get("helper_source_contract")))
        return {"host_helper.py": "a" * 64}

    def helper_pr(revision: str) -> None:
        events.append(("helper_pr11", revision))

    def candidate_pr(reviewed_pr_head_sha: str | None) -> None:
        events.append(("candidate_pr9", reviewed_pr_head_sha))

    def candidate_lineage(reviewed_pr_head_sha: str, helper_revision: str) -> None:
        events.append(("candidate_lineage", (reviewed_pr_head_sha, helper_revision)))

    def stop_before_runtime() -> dict[str, object]:
        raise RuntimeError("stop before any runtime work")

    monkeypatch.setattr(host_helper, "_verify_installed_source", installed_source)
    monkeypatch.setattr(host_helper, "_verify_helper_source_pull_request", helper_pr)
    monkeypatch.setattr(host_helper, "_verify_hotfix_pull_request", candidate_pr)
    monkeypatch.setattr(host_helper, "_verify_v3_pr_lineage", candidate_lineage)
    monkeypatch.setattr(host_helper, "_production_container", stop_before_runtime)
    common = {
        "repository": host_helper.REPOSITORY,
        "reviewed_head_sha": "c" * 40,
        "pair_manifest_sha256": "d" * 64,
    }

    with pytest.raises(host_helper.RehearsalError, match="fixed_pull_request_mismatch"):
        host_helper._run_pair_v2({**common, "pull_number": host_helper.PULL_NUMBER})
    assert events == []

    with pytest.raises(RuntimeError, match="stop before any runtime work"):
        host_helper._run_pair_v2({**common, "pull_number": host_helper.HELPER_SOURCE_PR_NUMBER})
    assert events == [
        ("installed", host_helper.HOTFIX_CONTRACT),
        ("helper_pr11", "c" * 40),
        ("candidate_pr9", None),
    ]

    events.clear()
    with pytest.raises(RuntimeError, match="stop before any runtime work"):
        host_helper._run_pair_v2(
            {
                **common,
                "pull_number": host_helper.HELPER_SOURCE_PR_NUMBER,
                "reviewed_pr_head_sha": host_helper.HOTFIX_V3_REVIEWED_PR_HEAD_SHA,
            },
            format_version=3,
        )
    assert events == [
        ("installed", host_helper.HOTFIX_CONTRACT),
        ("helper_pr11", "c" * 40),
        ("candidate_pr9", host_helper.HOTFIX_V3_REVIEWED_PR_HEAD_SHA),
        (
            "candidate_lineage",
            (host_helper.HOTFIX_V3_REVIEWED_PR_HEAD_SHA, "c" * 40),
        ),
    ]

    events.clear()
    monkeypatch.setattr(
        host_helper,
        "_verify_pull_request",
        lambda revision: events.append(("legacy_pr2", revision))
        or (_ for _ in ()).throw(RuntimeError("stop after v1 PR gate")),
    )
    with pytest.raises(host_helper.RehearsalError, match="fixed_pull_request_mismatch"):
        host_helper._run_pair_v1({**common, "pull_number": host_helper.HELPER_SOURCE_PR_NUMBER})
    assert events == []
    with pytest.raises(RuntimeError, match="stop after v1 PR gate"):
        host_helper._run_pair_v1({**common, "pull_number": host_helper.PULL_NUMBER})
    assert events == [("installed", None), ("legacy_pr2", "c" * 40)]


def _valid_host_v3_lineage_responses() -> dict[str, object]:
    image_source = host_helper.HOTFIX_V3_IMAGE_SOURCE_REVISION
    reviewed_head = host_helper.HOTFIX_V3_REVIEWED_PR_HEAD_SHA
    helper_head = "a" * 40
    path = "tests/test_assistant_final_boundary_coverage.py"
    old_line = '    assert captured["url"] == "https://opencode.ai/zen/v1/chat/completions"'
    new_line = (
        '    assert captured["url"] == "https://opencode.ai/inference/openai/v1/chat/completions"'
    )
    root_base, root_head = "b" * 40, "c" * 40
    nested_base, nested_head = "d" * 40, "e" * 40
    base_blob, head_blob = "f" * 40, "1" * 40
    return {
        f"/repos/{host_helper.REPOSITORY}/compare/{image_source}...{reviewed_head}?per_page=1": {
            "status": "ahead",
            "ahead_by": 1,
            "behind_by": 0,
            "total_commits": 1,
            "base_commit": {
                "sha": image_source,
                "commit": {"tree": {"sha": root_base}},
            },
            "commits": [{"sha": reviewed_head, "commit": {"tree": {"sha": root_head}}}],
            "files": [
                {
                    "filename": path,
                    "status": "modified",
                    "additions": 1,
                    "deletions": 1,
                    "changes": 2,
                    "sha": head_blob,
                    "patch": (f"@@ -12 +12 @@\n-{old_line}\n+{new_line}\n"),
                }
            ],
        },
        f"/repos/{host_helper.REPOSITORY}/compare/{reviewed_head}...{helper_head}?per_page=1": {
            "status": "ahead",
            "ahead_by": 2,
            "behind_by": 0,
            "total_commits": 2,
        },
        f"/repos/{host_helper.REPOSITORY}/git/trees/{root_base}": {
            "truncated": False,
            "tree": [{"path": "tests", "mode": "040000", "type": "tree", "sha": nested_base}],
        },
        f"/repos/{host_helper.REPOSITORY}/git/trees/{root_head}": {
            "truncated": False,
            "tree": [{"path": "tests", "mode": "040000", "type": "tree", "sha": nested_head}],
        },
        f"/repos/{host_helper.REPOSITORY}/git/trees/{nested_base}": {
            "truncated": False,
            "tree": [
                {
                    "path": path.rsplit("/", 1)[1],
                    "mode": "100644",
                    "type": "blob",
                    "sha": base_blob,
                }
            ],
        },
        f"/repos/{host_helper.REPOSITORY}/git/trees/{nested_head}": {
            "truncated": False,
            "tree": [
                {
                    "path": path.rsplit("/", 1)[1],
                    "mode": "100644",
                    "type": "blob",
                    "sha": head_blob,
                }
            ],
        },
    }


def test_host_v3_lineage_binds_exact_delta_to_regular_commit_tree_blobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = _valid_host_v3_lineage_responses()
    requests: list[str] = []

    def read(path: str) -> object:
        requests.append(path)
        return responses[path]

    monkeypatch.setattr(host_helper, "_read_v3_github_json", read)
    host_helper._verify_v3_pr_lineage(
        host_helper.HOTFIX_V3_REVIEWED_PR_HEAD_SHA,
        "a" * 40,
    )
    assert len(requests) == 6
    assert requests[0].endswith("?per_page=1")
    assert requests[1].endswith("?per_page=1")
    assert all("/git/trees/" in request for request in requests[2:])


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("extra_file", "reviewed_pr_test_diff_mismatch"),
        ("suffix_patch", "reviewed_pr_test_diff_mismatch"),
        ("wrong_head_blob", "reviewed_pr_test_diff_mismatch"),
        ("head_symlink", "reviewed_pr_tree_identity_mismatch"),
        ("duplicate_path", "reviewed_pr_tree_invalid"),
        ("oversized_tree", "reviewed_pr_tree_invalid"),
        ("truncated_tree", "reviewed_pr_tree_invalid"),
        ("unknown_entry_field", "reviewed_pr_tree_invalid"),
        ("duplicate_blob", "reviewed_pr_test_diff_mismatch"),
    ],
)
def test_host_v3_lineage_rejects_inconsistent_diff_or_tree_proof(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    error: str,
) -> None:
    responses = _valid_host_v3_lineage_responses()
    compare_path = (
        f"/repos/{host_helper.REPOSITORY}/compare/"
        f"{host_helper.HOTFIX_V3_IMAGE_SOURCE_REVISION}..."
        f"{host_helper.HOTFIX_V3_REVIEWED_PR_HEAD_SHA}?per_page=1"
    )
    root_head = "c" * 40
    nested_head = "e" * 40
    if mutation == "extra_file":
        compare = responses[compare_path]
        assert isinstance(compare, dict)
        compare["files"].append(dict(compare["files"][0]))
    elif mutation == "suffix_patch":
        compare = responses[compare_path]
        assert isinstance(compare, dict)
        compare["files"][0]["patch"] += "+assert True # approved URL\n"
    elif mutation == "wrong_head_blob":
        compare = responses[compare_path]
        assert isinstance(compare, dict)
        compare["files"][0]["sha"] = "9" * 40
    elif mutation == "head_symlink":
        responses[f"/repos/{host_helper.REPOSITORY}/git/trees/{nested_head}"]["tree"][0]["mode"] = (
            "120000"
        )
    elif mutation == "duplicate_path":
        nested = responses[f"/repos/{host_helper.REPOSITORY}/git/trees/{nested_head}"]
        nested["tree"].append(dict(nested["tree"][0]))
    elif mutation == "oversized_tree":
        root = responses[f"/repos/{host_helper.REPOSITORY}/git/trees/{root_head}"]
        assert isinstance(root, dict)
        root["tree"] = [
            {"path": f"entry-{index}", "mode": "100644", "type": "blob", "sha": "f" * 40}
            for index in range(2049)
        ]
    elif mutation == "truncated_tree":
        responses[f"/repos/{host_helper.REPOSITORY}/git/trees/{root_head}"]["truncated"] = True
    elif mutation == "unknown_entry_field":
        responses[f"/repos/{host_helper.REPOSITORY}/git/trees/{root_head}"]["tree"][0][
            "unexpected"
        ] = "value"
    elif mutation == "duplicate_blob":
        compare = responses[compare_path]
        assert isinstance(compare, dict)
        compare["files"][0]["sha"] = "f" * 40
    else:
        raise AssertionError(mutation)

    monkeypatch.setattr(host_helper, "_read_v3_github_json", lambda path: responses[path])
    with pytest.raises(host_helper.RehearsalError, match=error):
        host_helper._verify_v3_pr_lineage(
            host_helper.HOTFIX_V3_REVIEWED_PR_HEAD_SHA,
            "a" * 40,
        )


def test_host_v3_lineage_rejects_unpinned_head_before_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        host_helper,
        "_read_v3_github_json",
        lambda _path: pytest.fail("unpinned manifest head must fail before API access"),
    )
    with pytest.raises(host_helper.RehearsalError, match="hotfix_pr_head_unreviewed"):
        host_helper._verify_v3_pr_lineage("9" * 40, "a" * 40)


def test_host_v3_github_reader_rejects_duplicate_json_keys_and_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status = 200

        def read(self, maximum: int) -> bytes:
            assert maximum == host_helper.MAX_PR_RESPONSE + 1
            return b'{"status":"ahead","status":"behind"}'

    class Connection:
        def __init__(self, host: str, *, timeout: int) -> None:
            assert host == "api.github.com" and timeout == 10

        def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
            assert method == "GET"
            assert path.endswith("?per_page=1")
            assert "Authorization" not in headers

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            pass

    monkeypatch.setattr(host_helper.http.client, "HTTPSConnection", Connection)
    route = (
        f"/repos/{host_helper.REPOSITORY}/compare/"
        f"{host_helper.HOTFIX_V3_IMAGE_SOURCE_REVISION}..."
        f"{host_helper.HOTFIX_V3_REVIEWED_PR_HEAD_SHA}?per_page=1"
    )
    with pytest.raises(host_helper.RehearsalError, match="v3_lineage_invalid"):
        host_helper._read_v3_github_json(route)
    with pytest.raises(host_helper.RehearsalError, match="v3_lineage_route_invalid"):
        host_helper._read_v3_github_json("/repos/eddiesoz/stock_probs/issues")


def test_host_v3_github_reader_rejects_oversized_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status = 200

        def read(self, maximum: int) -> bytes:
            assert maximum == host_helper.MAX_PR_RESPONSE + 1
            return b" " * maximum

    class Connection:
        def __init__(self, host: str, *, timeout: int) -> None:
            assert host == "api.github.com" and timeout == 10
            self.closed = False
            connections.append(self)

        def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
            assert method == "GET"
            assert path.startswith(f"/repos/{host_helper.REPOSITORY}/compare/")
            assert "Authorization" not in headers

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            self.closed = True

    connections: list[Connection] = []
    monkeypatch.setattr(host_helper.http.client, "HTTPSConnection", Connection)
    route = (
        f"/repos/{host_helper.REPOSITORY}/compare/"
        f"{host_helper.HOTFIX_V3_IMAGE_SOURCE_REVISION}..."
        f"{host_helper.HOTFIX_V3_REVIEWED_PR_HEAD_SHA}?per_page=1"
    )
    with pytest.raises(host_helper.RehearsalError, match="v3_lineage_unavailable"):
        host_helper._read_v3_github_json(route)
    assert len(connections) == 1 and connections[0].closed is True


@pytest.mark.parametrize(
    ("head_mode", "same_blob", "error"),
    [
        ("100644", False, None),
        ("120000", False, "reviewed_pr_tree_identity_mismatch"),
        ("100644", True, "reviewed_pr_test_diff_mismatch"),
    ],
)
def test_controller_v3_admission_requires_exact_delta_and_regular_blobs(
    monkeypatch: pytest.MonkeyPatch,
    head_mode: str,
    same_blob: bool,
    error: str | None,
) -> None:
    path = "tests/test_assistant_final_boundary_coverage.py"
    old_line = '    assert captured["url"] == "https://opencode.ai/zen/v1/chat/completions"'
    new_line = (
        '    assert captured["url"] == "https://opencode.ai/inference/openai/v1/chat/completions"'
    )
    commands: list[list[str]] = []
    base_blob, head_blob = "f" * 40, "1" * 40
    if same_blob:
        head_blob = base_blob

    def run_fixed(command: list[str], *, timeout: float, input_bytes: bytes | None = None) -> bytes:
        assert timeout == 10 and input_bytes is None
        commands.append(command)
        if command[1] == "merge-base":
            return b""
        if command[1] == "diff":
            if "--name-status" in command:
                return f"M\t{path}\n".encode()
            if "--numstat" in command:
                return f"1\t1\t{path}\n".encode()
            if "--summary" in command:
                return b""
            if "--unified=0" in command:
                return f"-{old_line}\n+{new_line}\n".encode()
        if command[1] == "ls-tree":
            commit_sha = command[4]
            mode = (
                head_mode if commit_sha == controller.HOTFIX_V3_REVIEWED_PR_HEAD_SHA else "100644"
            )
            blob_sha = (
                head_blob if commit_sha == controller.HOTFIX_V3_REVIEWED_PR_HEAD_SHA else base_blob
            )
            return f"{mode} blob {blob_sha}\t{path}\0".encode()
        raise AssertionError(command)

    monkeypatch.setattr(controller, "_run_fixed", run_fixed)
    if error is None:
        controller._verify_local_v3_pr_lineage(
            controller.HOTFIX_V3_REVIEWED_PR_HEAD_SHA,
            "a" * 40,
        )
        assert len(commands) == 8
    else:
        with pytest.raises(controller.RehearsalError, match=error):
            controller._verify_local_v3_pr_lineage(
                controller.HOTFIX_V3_REVIEWED_PR_HEAD_SHA,
                "a" * 40,
            )


def test_controller_rejects_unpinned_pr9_before_local_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        controller,
        "_run_fixed",
        lambda *_args, **_kwargs: pytest.fail("unpinned head must fail before Git"),
    )
    with pytest.raises(controller.RehearsalError, match="reviewed_pr_head_invalid"):
        controller._verify_local_v3_pr_lineage("9" * 40, "a" * 40)


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


@pytest.mark.parametrize("helper_source_contract", [None, controller.HOTFIX_CONTRACT])
def test_source_upload_and_reviewed_bootstrap_share_the_sha_prefixed_names(
    monkeypatch,
    helper_source_contract: str | None,
) -> None:
    revision = "a" * 40
    pair_digest = "b" * 64
    config = controller.RehearsalConfig(
        Path("/unused/operator-key"), Path("/unused/known-hosts"), revision, pair_digest
    )
    include_production_helper = helper_source_contract == controller.HOTFIX_CONTRACT
    names = controller._source_stage_names(
        revision, include_production_helper=include_production_helper
    )
    expected_assets = {
        role
        for role in bootstrap.ASSETS
        if include_production_helper or role != "production_helper"
    }
    assert set(names) == expected_assets
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
        response = {
            "status": "installed",
            "reviewed_head_sha": payload["reviewed_head_sha"],
            "reviewed_pair_manifest_sha256": payload["reviewed_pair_manifest_sha256"],
            "asset_sha256": payload["asset_sha256"],
        }
        if "helper_source_contract" in payload:
            response["helper_source_contract"] = payload["helper_source_contract"]
            response["pull_number"] = controller.HELPER_SOURCE_PR_NUMBER
            response["production_helper_sha256"] = payload["asset_sha256"]["production_helper"]
            response["previous_production_helper_sha256"] = (
                bootstrap.PREVIOUS_PRODUCTION_HELPER_SHA256
            )
        return json.dumps(response).encode()

    monkeypatch.setattr(controller, "_run_fixed", fake_run_fixed)
    assets = {role: f"{role} source".encode() for role in names}
    hashes = {role: hashlib.sha256(data).hexdigest() for role, data in assets.items()}
    controller._stage_source_bundle(
        config,
        revision,
        pair_digest,
        assets,
        hashes,
        helper_source_contract=helper_source_contract,
    )

    assert staged == [names]
    command, input_bytes = captured[0]
    assert command[-1] == (
        f"sudo -n /usr/bin/python3 {controller.INCOMING_DIRECTORY}/{names['bootstrap']}"
    )
    request = json.loads(input_bytes)
    assert request["payload"]["reviewed_head_sha"] == revision
    assert request["payload"]["asset_sha256"] == hashes
    if helper_source_contract is None:
        assert "helper_source_contract" not in request["payload"]
    else:
        assert request["payload"]["helper_source_contract"] == helper_source_contract
    with pytest.raises(controller.RehearsalError, match="reviewed_pr_head_invalid"):
        controller._source_stage_names("../bootstrap.py")
    with pytest.raises(bootstrap.InstallError, match="bootstrap_asset_name_invalid"):
        bootstrap._staged_asset_path(revision, "../../bootstrap.py")


@pytest.mark.parametrize(
    ("helper_source_contract", "expected_pull_number"),
    [(None, 2), (bootstrap.HELPER_SOURCE_CONTRACT, 11)],
)
def test_bootstrap_installs_from_and_cleans_only_sha_prefixed_source_files(
    monkeypatch,
    tmp_path: Path,
    helper_source_contract: str | None,
    expected_pull_number: int,
) -> None:
    revision = "c" * 40
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    install_root = tmp_path / "installed"
    selected_assets = {
        role: definition
        for role, definition in bootstrap.ASSETS.items()
        if helper_source_contract is not None or role != "production_helper"
    }
    sources = {
        relative: f"reviewed source for {role}".encode()
        for role, (relative, _name, _maximum) in selected_assets.items()
    }
    hashes: dict[str, str] = {}
    for role, (relative, staged_name, _maximum) in selected_assets.items():
        content = sources[relative]
        hashes[role] = hashlib.sha256(content).hexdigest()
        (incoming / f"signal-ledger-pr1-{revision}-{staged_name}").write_bytes(content)
        # Bare legacy names must not be read or removed by this SHA-bound installation.
        (incoming / staged_name).write_bytes(b"legacy name must remain untouched")

    installed: list[tuple[Path, bytes, int]] = []
    monkeypatch.setattr(bootstrap, "INCOMING", incoming)
    monkeypatch.setattr(bootstrap, "INSTALL_ROOT", install_root)
    monkeypatch.setattr(bootstrap, "INSTALLED_MANIFEST", install_root / "installed.json")
    production_helper = tmp_path / "usr-local-libexec" / "signal-ledger-deploy-helper"
    monkeypatch.setattr(bootstrap, "PRODUCTION_HELPER", production_helper)
    monkeypatch.setattr(
        bootstrap,
        "_prepare_previous_production_helper",
        lambda _candidate, **_kwargs: (
            b"known prior helper",
            bootstrap.PREVIOUS_PRODUCTION_HELPER_SHA256,
        ),
    )
    monkeypatch.setattr(bootstrap, "_read_fixed_root_file", lambda *_args: b"known prior helper")
    monkeypatch.setattr(bootstrap, "_install_locks", nullcontext)
    monkeypatch.setattr(bootstrap, "_safe_directory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bootstrap, "_safe_incoming_directory", lambda: None)
    monkeypatch.setattr(bootstrap, "_check_root_directory", lambda *_args: None)
    verified_pull_numbers: list[int] = []

    def verify_pull_request(_revision: str, *, pull_number: int) -> None:
        verified_pull_numbers.append(pull_number)

    monkeypatch.setattr(bootstrap, "_verify_pull_request", verify_pull_request)
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

    payload = {
        "reviewed_head_sha": revision,
        "reviewed_pair_manifest_sha256": "d" * 64,
        "asset_sha256": hashes,
    }
    if helper_source_contract is not None:
        payload["helper_source_contract"] = helper_source_contract
    result = bootstrap.install(payload)

    assert result["status"] == "installed"
    assert result["asset_sha256"] == hashes
    assert verified_pull_numbers == [expected_pull_number]
    expected_installed = {
        "host_helper.py",
        "seed.py",
        "native_driver.py",
        "installed.json",
    }
    if helper_source_contract is not None:
        expected_installed.add(production_helper.name)
    assert {path.name for path, _content, _mode in installed} == expected_installed
    installed_manifest = next(
        content for path, content, _mode in installed if path.name == "installed.json"
    )
    receipt = json.loads(installed_manifest)
    assert receipt["pull_number"] == expected_pull_number
    if helper_source_contract is None:
        assert "helper_source_contract" not in receipt
        assert "pull_number" not in result
    else:
        assert receipt["helper_source_contract"] == helper_source_contract
        assert receipt["previous_production_helper_sha256"] == (
            bootstrap.PREVIOUS_PRODUCTION_HELPER_SHA256
        )
        assert receipt["files"]["production-deploy-helper.py"] == hashes["production_helper"]
        assert result["helper_source_contract"] == helper_source_contract
        assert result["pull_number"] == expected_pull_number
        assert result["production_helper_sha256"] == hashes["production_helper"]
    for _role, (_relative, staged_name, _maximum) in selected_assets.items():
        assert not (incoming / f"signal-ledger-pr1-{revision}-{staged_name}").exists()
        assert (incoming / staged_name).read_bytes() == b"legacy name must remain untouched"


def test_bootstrap_install_locks_use_fixed_order_and_contention_blocks_install_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    deploy_root = tmp_path / "deploy-state"
    rehearsal_root = tmp_path / "rehearsal-state"
    deploy_root.mkdir()
    rehearsal_root.mkdir()
    deploy_lock = deploy_root / "deploy.lock"
    rehearsal_lock = rehearsal_root / "rehearsal.lock"
    deploy_lock.touch(mode=0o640)
    deploy_lock.chmod(0o640)
    rehearsal_lock.touch(mode=0o600)
    rehearsal_lock.chmod(0o600)
    monkeypatch.setattr(bootstrap, "DEPLOY_STATE_ROOT", deploy_root)
    monkeypatch.setattr(bootstrap, "STATE_ROOT", rehearsal_root)
    monkeypatch.setattr(bootstrap, "DEPLOY_LOCK", deploy_lock)
    monkeypatch.setattr(bootstrap, "REHEARSAL_LOCK", rehearsal_lock)
    monkeypatch.setattr(bootstrap, "_safe_directory", lambda *_args, **_kwargs: None)

    original_open = os.open
    original_fstat = os.fstat
    original_flock = bootstrap.fcntl.flock
    held_descriptor = original_open(rehearsal_lock, os.O_RDWR | os.O_NOFOLLOW)
    original_flock(held_descriptor, bootstrap.fcntl.LOCK_EX | bootstrap.fcntl.LOCK_NB)
    opened: list[Path] = []
    attempts: list[Path] = []
    descriptor_paths: dict[int, Path] = {held_descriptor: rehearsal_lock}
    writes: list[str] = []

    def tracked_open(path, flags, mode=0o777):
        descriptor = original_open(path, flags, mode)
        normalized = Path(path)
        if normalized in {deploy_lock, rehearsal_lock}:
            opened.append(normalized)
            descriptor_paths[descriptor] = normalized
        return descriptor

    def root_owned_fstat(descriptor: int) -> SimpleNamespace:
        metadata = original_fstat(descriptor)
        return SimpleNamespace(st_mode=metadata.st_mode, st_uid=0)

    def tracked_flock(descriptor: int, operation: int) -> None:
        if operation == bootstrap.fcntl.LOCK_EX | bootstrap.fcntl.LOCK_NB:
            attempts.append(descriptor_paths[descriptor])
        original_flock(descriptor, operation)

    monkeypatch.setattr(bootstrap.os, "open", tracked_open)
    monkeypatch.setattr(bootstrap.os, "fstat", root_owned_fstat)
    monkeypatch.setattr(bootstrap.fcntl, "flock", tracked_flock)

    try:
        with (
            pytest.raises(bootstrap.InstallError, match="install_operation_busy"),
            bootstrap._install_locks(),
        ):
            writes.append("install body entered")
    finally:
        original_flock(held_descriptor, bootstrap.fcntl.LOCK_UN)
        os.close(held_descriptor)

    assert opened == [deploy_lock, rehearsal_lock]
    assert attempts == [deploy_lock, rehearsal_lock]
    assert writes == []

    # The first lock was released after second-lock contention, so another owner can acquire it.
    descriptor = original_open(deploy_lock, os.O_RDWR | os.O_NOFOLLOW)
    try:
        original_flock(descriptor, bootstrap.fcntl.LOCK_EX | bootstrap.fcntl.LOCK_NB)
    finally:
        original_flock(descriptor, bootstrap.fcntl.LOCK_UN)
        os.close(descriptor)


@pytest.mark.parametrize("rollback_fails", [False, True], ids=["restored", "unverified"])
def test_bootstrap_install_manifest_failure_reports_rollback_state_and_preserves_backup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    rollback_fails: bool,
) -> None:
    revision = "e" * 40
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    install_root = tmp_path / "installed"
    install_root.mkdir()
    production_helper = tmp_path / "libexec" / "production-deploy-helper.py"
    production_helper.parent.mkdir()
    manifest_path = install_root / "installed.json"
    backup_path = tmp_path / "libexec" / "previous-production-deploy-helper.py"
    old_manifest = b'{"previous":"manifest"}\n'
    prior_helper = b"verified prior helper bytes"
    replacement_helper = b"reviewed replacement helper bytes"
    manifest_path.write_bytes(old_manifest)
    manifest_path.chmod(0o640)
    production_helper.write_bytes(prior_helper)
    production_helper.chmod(0o750)

    selected_assets = bootstrap.ASSETS
    sources: dict[str, bytes] = {}
    hashes: dict[str, str] = {}
    old_files: dict[Path, bytes] = {}
    replacement_files: dict[Path, bytes] = {}
    for role, (relative, staged_name, _maximum) in selected_assets.items():
        if role == "production_helper":
            content = replacement_helper
        else:
            content = f"reviewed {role} bytes".encode()
        sources[relative] = content
        hashes[role] = hashlib.sha256(content).hexdigest()
        (incoming / f"signal-ledger-pr1-{revision}-{staged_name}").write_bytes(content)
        if role not in {"bootstrap", "production_helper"}:
            destination = install_root / staged_name
            previous = f"previous {role} bytes".encode()
            destination.write_bytes(previous)
            destination.chmod(0o750 if role == "host_helper" else 0o640)
            old_files[destination] = previous
            replacement_files[destination] = content

    monkeypatch.setattr(bootstrap, "INCOMING", incoming)
    monkeypatch.setattr(bootstrap, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(bootstrap, "INSTALL_ROOT", install_root)
    monkeypatch.setattr(bootstrap, "INSTALLED_MANIFEST", manifest_path)
    monkeypatch.setattr(bootstrap, "PRODUCTION_HELPER", production_helper)
    monkeypatch.setattr(bootstrap, "PREVIOUS_PRODUCTION_HELPER", backup_path)
    monkeypatch.setattr(bootstrap, "_install_locks", nullcontext)
    monkeypatch.setattr(bootstrap, "_safe_directory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bootstrap, "_safe_incoming_directory", lambda: None)
    monkeypatch.setattr(bootstrap, "_check_root_directory", lambda *_args: None)
    monkeypatch.setattr(bootstrap, "_verify_pull_request", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        bootstrap,
        "_fetch_reviewed_source",
        lambda _revision, relative, _maximum: sources[relative],
    )

    failed_manifest_write = False
    failed_rollback_write = False

    def atomic_write(path: Path, contents: bytes, mode: int) -> None:
        nonlocal failed_manifest_write, failed_rollback_write
        if path == manifest_path and contents != old_manifest and not failed_manifest_write:
            failed_manifest_write = True
            raise OSError("simulated manifest publication failure")
        if (
            rollback_fails
            and failed_manifest_write
            and path == production_helper
            and contents == prior_helper
        ):
            failed_rollback_write = True
            raise OSError("simulated production helper rollback failure")
        temporary = path.with_name(f".{path.name}.test-tmp")
        temporary.write_bytes(contents)
        temporary.chmod(mode)
        temporary.replace(path)

    def prepare_previous_helper(_candidate: bytes, **_kwargs: object) -> tuple[bytes, str]:
        atomic_write(backup_path, prior_helper, 0o600)
        return prior_helper, bootstrap.PREVIOUS_PRODUCTION_HELPER_SHA256

    def read_fixed_root_file(path: Path, maximum: int, mode: int) -> bytes:
        metadata = path.lstat()
        assert stat.S_ISREG(metadata.st_mode)
        assert 0 < metadata.st_size <= maximum
        assert stat.S_IMODE(metadata.st_mode) == mode
        return path.read_bytes()

    monkeypatch.setattr(bootstrap, "_atomic_root_file", atomic_write)
    monkeypatch.setattr(bootstrap, "_prepare_previous_production_helper", prepare_previous_helper)
    monkeypatch.setattr(bootstrap, "_read_fixed_root_file", read_fixed_root_file)

    payload = {
        "reviewed_head_sha": revision,
        "reviewed_pair_manifest_sha256": "f" * 64,
        "asset_sha256": hashes,
        "helper_source_contract": bootstrap.HELPER_SOURCE_CONTRACT,
    }
    with pytest.raises(bootstrap.InstallError) as raised:
        bootstrap.install(payload)

    assert failed_manifest_write is True
    assert manifest_path.read_bytes() == old_manifest
    assert backup_path.read_bytes() == prior_helper
    assert stat.S_IMODE(backup_path.stat().st_mode) == 0o600
    if rollback_fails:
        assert raised.value.code == "install_rollback_unverified"
        assert failed_rollback_write is True
        assert production_helper.read_bytes() == replacement_helper
        assert {path: path.read_bytes() for path in replacement_files} == replacement_files
    else:
        assert raised.value.code == "sidecar_install_failed"
        assert failed_rollback_write is False
        assert production_helper.read_bytes() == prior_helper
        assert {path: path.read_bytes() for path in old_files} == old_files


def _installed_manifest_bytes(fields: dict[str, object]) -> bytes:
    return (
        json.dumps(
            {**fields, "installed_at": "2026-10-16T12:00:00Z"},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def _read_temp_root_file(path: Path, maximum: int, mode: int) -> bytes:
    """Mirror root-file shape/mode checks for unprivileged temporary fixtures."""

    try:
        metadata = path.lstat()
    except OSError as exc:
        raise bootstrap.InstallError("production_helper_file_unavailable") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != mode
        or not 1 <= metadata.st_size <= maximum
    ):
        raise bootstrap.InstallError("production_helper_file_unsafe")
    return path.read_bytes()


def test_bootstrap_retains_exact_predecessor_helper_and_rejects_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    previous = b"verified predecessor helper bytes"
    candidate = b"reviewed replacement helper bytes"
    previous_digest = hashlib.sha256(previous).hexdigest()
    helper_path = tmp_path / "signal-ledger-deploy-helper"
    backup_path = tmp_path / "previous-production-deploy-helper.py"
    manifest_path = tmp_path / "installed.json"
    helper_path.write_bytes(previous)
    helper_path.chmod(0o750)
    monkeypatch.setattr(bootstrap, "PRODUCTION_HELPER", helper_path)
    monkeypatch.setattr(bootstrap, "PREVIOUS_PRODUCTION_HELPER", backup_path)
    monkeypatch.setattr(bootstrap, "INSTALLED_MANIFEST", manifest_path)
    monkeypatch.setattr(bootstrap, "PREVIOUS_PRODUCTION_HELPER_SIZE", len(previous))
    monkeypatch.setattr(bootstrap, "PREVIOUS_PRODUCTION_HELPER_SHA256", previous_digest)

    writes: list[tuple[Path, int]] = []

    def atomic_write(path: Path, content: bytes, mode: int) -> None:
        path.write_bytes(content)
        path.chmod(mode)
        writes.append((path, mode))

    monkeypatch.setattr(bootstrap, "_read_fixed_root_file", _read_temp_root_file)
    monkeypatch.setattr(bootstrap, "_atomic_root_file", atomic_write)
    assert bootstrap._prepare_previous_production_helper(
        candidate,
        candidate_manifest_fields={},
    ) == (previous, previous_digest)
    assert backup_path.read_bytes() == previous
    assert stat.S_IMODE(backup_path.stat().st_mode) == 0o600
    assert writes == [(backup_path, 0o600)]

    assert bootstrap._prepare_previous_production_helper(
        candidate,
        candidate_manifest_fields={},
    ) == (previous, previous_digest)
    assert writes == [(backup_path, 0o600)]

    helper_path.write_bytes(b"unreviewed helper drift")
    helper_path.chmod(0o750)
    with pytest.raises(bootstrap.InstallError, match="production_helper_drift"):
        bootstrap._prepare_previous_production_helper(
            candidate,
            candidate_manifest_fields={},
        )
    assert writes == [(backup_path, 0o600)]

    backup_path.write_bytes(b"tampered predecessor")
    backup_path.chmod(0o600)
    with pytest.raises(bootstrap.InstallError, match="production_helper_backup_mismatch"):
        bootstrap._prepare_previous_production_helper(
            candidate,
            candidate_manifest_fields={},
        )
    assert writes == [(backup_path, 0o600)]


def _intermediate_helper_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[bytes, bytes, bytes, Path, Path, dict[str, object]]:
    original = b"immutable original helper fixture"
    intermediate = b"known intermediate helper fixture"
    candidate = b"new reviewed helper fixture"
    original_digest = hashlib.sha256(original).hexdigest()
    intermediate_digest = hashlib.sha256(intermediate).hexdigest()
    helper_path = tmp_path / "production-deploy-helper.py"
    backup_path = tmp_path / "previous-production-deploy-helper.py"
    install_root = tmp_path / "installed"
    install_root.mkdir()
    manifest_path = install_root / "installed.json"
    helper_path.write_bytes(intermediate)
    helper_path.chmod(0o750)
    backup_path.write_bytes(original)
    backup_path.chmod(0o600)
    expected_fields = dict(bootstrap.KNOWN_INTERMEDIATE_INSTALL_MANIFEST)
    expected_files: dict[str, str] = {}
    for name in bootstrap.KNOWN_INTERMEDIATE_INSTALLED_FILES:
        content = intermediate if name == "production-deploy-helper.py" else f"old {name}".encode()
        expected_files[name] = hashlib.sha256(content).hexdigest()
        if name == "production-deploy-helper.py":
            continue
        installed_path = install_root / name
        installed_path.write_bytes(content)
        installed_path.chmod(0o750 if name == "host_helper.py" else 0o640)
    expected_fields["files"] = expected_files
    monkeypatch.setattr(bootstrap, "PRODUCTION_HELPER", helper_path)
    monkeypatch.setattr(bootstrap, "PREVIOUS_PRODUCTION_HELPER", backup_path)
    monkeypatch.setattr(bootstrap, "INSTALL_ROOT", install_root)
    monkeypatch.setattr(bootstrap, "INSTALLED_MANIFEST", manifest_path)
    monkeypatch.setattr(bootstrap, "PREVIOUS_PRODUCTION_HELPER_SIZE", len(original))
    monkeypatch.setattr(bootstrap, "PREVIOUS_PRODUCTION_HELPER_SHA256", original_digest)
    monkeypatch.setattr(
        bootstrap,
        "KNOWN_INTERMEDIATE_PRODUCTION_HELPER_SHA256",
        intermediate_digest,
    )
    monkeypatch.setattr(bootstrap, "KNOWN_INTERMEDIATE_INSTALL_MANIFEST", expected_fields)
    monkeypatch.setattr(bootstrap, "_read_fixed_root_file", _read_temp_root_file)
    return original, intermediate, candidate, helper_path, backup_path, expected_fields


def test_bootstrap_accepts_exact_known_intermediate_helper_install_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assert bootstrap.KNOWN_INTERMEDIATE_PRODUCTION_HELPER_SHA256 == (
        "0d65ad8f1fa9825b1e4a964fa112f49b87a08ed415a8e5ce67802549045f6cd8"
    )
    assert bootstrap.KNOWN_INTERMEDIATE_REVIEWED_HEAD_SHA == (
        "cebe3870a62d3d433baaeba45845cf59ebb1e9bc"
    )
    assert bootstrap.KNOWN_INTERMEDIATE_PAIR_MANIFEST_SHA256 == (
        "6346e9d8d1f0ecb64e7ec1fa81a6b8cf56ee8e752ded7199219ae1a204bdf90c"
    )
    original, intermediate, candidate, helper_path, backup_path, expected_fields = (
        _intermediate_helper_fixture(monkeypatch, tmp_path)
    )
    original_digest = hashlib.sha256(original).hexdigest()
    manifest_path = bootstrap.INSTALLED_MANIFEST
    manifest_path.write_bytes(_installed_manifest_bytes(expected_fields))
    manifest_path.chmod(0o640)

    assert bootstrap._prepare_previous_production_helper(
        candidate,
        candidate_manifest_fields={},
    ) == (intermediate, original_digest)
    assert backup_path.read_bytes() == original
    assert hashlib.sha256(backup_path.read_bytes()).hexdigest() == original_digest


@pytest.mark.parametrize(
    "malformation",
    [
        "head",
        "pair",
        "file",
        "contract",
        "predecessor",
        "duplicate",
        "mode",
        "sidecar",
        "sidecar-mode",
        "helper-mode",
        "backup-mode",
        "missing",
    ],
)
def test_bootstrap_rejects_malformed_known_intermediate_install_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    malformation: str,
) -> None:
    original, _intermediate, candidate, _helper_path, backup_path, expected_fields = (
        _intermediate_helper_fixture(monkeypatch, tmp_path)
    )
    expected_manifest_path = bootstrap.INSTALLED_MANIFEST
    malformed_fields = dict(expected_fields)
    malformed_files = dict(expected_fields["files"])
    malformed_fields["files"] = malformed_files
    if malformation == "head":
        malformed_fields["reviewed_head_sha"] = "f" * 40
    elif malformation == "pair":
        malformed_fields["reviewed_pair_manifest_sha256"] = "f" * 64
    elif malformation == "file":
        malformed_files["seed.py"] = "f" * 64
    elif malformation == "contract":
        malformed_fields["helper_source_contract"] = "wrong-contract"
    elif malformation == "predecessor":
        malformed_fields["previous_production_helper_sha256"] = "f" * 64
    if malformation != "missing":
        manifest = _installed_manifest_bytes(malformed_fields)
        if malformation == "duplicate":
            manifest = b'{"format_version":1,' + manifest[1:]
        expected_manifest_path.write_bytes(manifest)
        expected_manifest_path.chmod(0o644 if malformation == "mode" else 0o640)
    else:
        expected_manifest_path.unlink(missing_ok=True)
    if malformation == "sidecar":
        (bootstrap.INSTALL_ROOT / "seed.py").write_bytes(b"unreviewed sidecar drift")
        (bootstrap.INSTALL_ROOT / "seed.py").chmod(0o640)
    elif malformation == "sidecar-mode":
        (bootstrap.INSTALL_ROOT / "host_helper.py").chmod(0o640)
    elif malformation == "helper-mode":
        bootstrap.PRODUCTION_HELPER.chmod(0o755)
    elif malformation == "backup-mode":
        backup_path.chmod(0o640)
    expected_error = (
        "production_helper_file_unsafe"
        if malformation in {"helper-mode", "backup-mode"}
        else "production_helper_manifest_mismatch"
    )
    with pytest.raises(bootstrap.InstallError, match=expected_error):
        bootstrap._prepare_previous_production_helper(
            candidate,
            candidate_manifest_fields={},
        )
    assert backup_path.read_bytes() == original
    assert hashlib.sha256(backup_path.read_bytes()).hexdigest() == (
        bootstrap.PREVIOUS_PRODUCTION_HELPER_SHA256
    )


def test_bootstrap_upgrade_restores_exact_intermediate_then_allows_exact_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    revision = "f" * 40
    pair_digest = "a" * 64
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    install_root = tmp_path / "installed"
    install_root.mkdir()
    state_root = tmp_path / "state"
    production_helper = tmp_path / "libexec" / "production-deploy-helper.py"
    production_helper.parent.mkdir()
    backup_path = state_root / "previous-production-deploy-helper.py"
    state_root.mkdir()
    manifest_path = install_root / "installed.json"
    original = b"immutable original helper fixture"
    intermediate = b"known intermediate helper fixture"
    candidate = b"new reviewed helper fixture"
    production_helper.write_bytes(intermediate)
    production_helper.chmod(0o750)
    backup_path.write_bytes(original)
    backup_path.chmod(0o600)

    old_manifest_files: dict[str, str] = {}
    old_sidecars: dict[Path, bytes] = {}
    sources: dict[str, bytes] = {}
    asset_hashes: dict[str, str] = {}
    for role, (relative, staged_name, _maximum) in bootstrap.ASSETS.items():
        if role == "production_helper":
            content = candidate
        else:
            content = f"candidate bytes for {role}".encode()
        sources[relative] = content
        asset_hashes[role] = hashlib.sha256(content).hexdigest()
        (incoming / f"signal-ledger-pr1-{revision}-{staged_name}").write_bytes(content)
        if role == "bootstrap":
            continue
        installed_name = staged_name
        if role != "production_helper":
            old_content = f"old {role}".encode()
            sidecar_path = install_root / installed_name
            sidecar_path.write_bytes(old_content)
            sidecar_path.chmod(0o750 if role == "host_helper" else 0o640)
            old_sidecars[sidecar_path] = old_content
            old_manifest_files[installed_name] = hashlib.sha256(old_content).hexdigest()
    old_manifest_files["production-deploy-helper.py"] = hashlib.sha256(intermediate).hexdigest()
    old_manifest_fields = dict(bootstrap.KNOWN_INTERMEDIATE_INSTALL_MANIFEST)
    old_manifest_fields["reviewed_head_sha"] = bootstrap.KNOWN_INTERMEDIATE_REVIEWED_HEAD_SHA
    old_manifest_fields["reviewed_pair_manifest_sha256"] = (
        bootstrap.KNOWN_INTERMEDIATE_PAIR_MANIFEST_SHA256
    )
    old_manifest_fields["files"] = old_manifest_files
    manifest_path.write_bytes(_installed_manifest_bytes(old_manifest_fields))
    manifest_path.chmod(0o640)

    monkeypatch.setattr(bootstrap, "INCOMING", incoming)
    monkeypatch.setattr(bootstrap, "STATE_ROOT", state_root)
    monkeypatch.setattr(bootstrap, "INSTALL_ROOT", install_root)
    monkeypatch.setattr(bootstrap, "INSTALLED_MANIFEST", manifest_path)
    monkeypatch.setattr(bootstrap, "PRODUCTION_HELPER", production_helper)
    monkeypatch.setattr(bootstrap, "PREVIOUS_PRODUCTION_HELPER", backup_path)
    monkeypatch.setattr(bootstrap, "PREVIOUS_PRODUCTION_HELPER_SIZE", len(original))
    monkeypatch.setattr(
        bootstrap,
        "PREVIOUS_PRODUCTION_HELPER_SHA256",
        hashlib.sha256(original).hexdigest(),
    )
    monkeypatch.setattr(
        bootstrap,
        "KNOWN_INTERMEDIATE_PRODUCTION_HELPER_SHA256",
        hashlib.sha256(intermediate).hexdigest(),
    )
    monkeypatch.setattr(bootstrap, "KNOWN_INTERMEDIATE_INSTALL_MANIFEST", old_manifest_fields)
    monkeypatch.setattr(bootstrap, "_read_fixed_root_file", _read_temp_root_file)
    monkeypatch.setattr(bootstrap, "_install_locks", nullcontext)
    monkeypatch.setattr(bootstrap, "_safe_directory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bootstrap, "_safe_incoming_directory", lambda: None)
    monkeypatch.setattr(bootstrap, "_check_root_directory", lambda *_args: None)
    monkeypatch.setattr(bootstrap, "_verify_pull_request", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        bootstrap,
        "_fetch_reviewed_source",
        lambda _revision, relative, _maximum: sources[relative],
    )
    prior_manifest = manifest_path.read_bytes()
    failed_first_manifest_write = False

    def atomic_write(path: Path, contents: bytes, mode: int) -> None:
        nonlocal failed_first_manifest_write
        if path == manifest_path and contents != prior_manifest and not failed_first_manifest_write:
            failed_first_manifest_write = True
            raise OSError("simulated receipt publication failure")
        temporary = path.with_name(f".{path.name}.test-tmp")
        temporary.write_bytes(contents)
        temporary.chmod(mode)
        temporary.replace(path)

    monkeypatch.setattr(bootstrap, "_atomic_root_file", atomic_write)
    payload = {
        "reviewed_head_sha": revision,
        "reviewed_pair_manifest_sha256": pair_digest,
        "asset_sha256": asset_hashes,
        "helper_source_contract": bootstrap.HELPER_SOURCE_CONTRACT,
    }
    with pytest.raises(bootstrap.InstallError, match="sidecar_install_failed"):
        bootstrap.install(payload)
    assert failed_first_manifest_write is True
    assert production_helper.read_bytes() == intermediate
    assert manifest_path.read_bytes() == prior_manifest
    assert {path: path.read_bytes() for path in old_sidecars} == old_sidecars
    assert backup_path.read_bytes() == original
    assert stat.S_IMODE(backup_path.stat().st_mode) == 0o600

    result = bootstrap.install(payload)
    assert result["status"] == "installed"
    assert production_helper.read_bytes() == candidate
    assert hashlib.sha256(backup_path.read_bytes()).hexdigest() == (
        bootstrap.PREVIOUS_PRODUCTION_HELPER_SHA256
    )
    assert stat.S_IMODE(backup_path.stat().st_mode) == 0o600
    completed_manifest = manifest_path.read_bytes()
    candidate_fields: dict[str, object] = {
        "format_version": 1,
        "repository": bootstrap.REPOSITORY,
        "pull_number": bootstrap.HELPER_SOURCE_PR_NUMBER,
        "reviewed_head_sha": revision,
        "reviewed_pair_manifest_sha256": pair_digest,
        "files": {
            installed_name: asset_hashes[role]
            for role, (_relative, installed_name, _maximum) in bootstrap.ASSETS.items()
            if role != "bootstrap"
        },
        "helper_source_contract": bootstrap.HELPER_SOURCE_CONTRACT,
        "previous_production_helper_sha256": bootstrap.PREVIOUS_PRODUCTION_HELPER_SHA256,
    }
    manifest_path.write_bytes(b'{"partial":true}\n')
    manifest_path.chmod(0o640)
    with pytest.raises(bootstrap.InstallError, match="production_helper_manifest_mismatch"):
        bootstrap._prepare_previous_production_helper(
            candidate,
            candidate_manifest_fields=candidate_fields,
        )
    assert production_helper.read_bytes() == candidate
    manifest_path.write_bytes(completed_manifest)
    manifest_path.chmod(0o640)
    for _role, (relative, staged_name, _maximum) in bootstrap.ASSETS.items():
        (incoming / f"signal-ledger-pr1-{revision}-{staged_name}").write_bytes(sources[relative])

    result = bootstrap.install(payload)
    assert result["status"] == "installed"
    assert production_helper.read_bytes() == candidate
    assert hashlib.sha256(backup_path.read_bytes()).hexdigest() == (
        bootstrap.PREVIOUS_PRODUCTION_HELPER_SHA256
    )


def _known_677_install_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[bytes, bytes, Path, dict[str, object], dict[Path, bytes]]:
    """Build the fixed 67723 receipt shape with synthetic installed file bytes."""

    original = b"immutable original helper fixture for 67723 receipt"
    original_digest = hashlib.sha256(original).hexdigest()
    helper = b"installed helper bytes for known-receipt unit tests"
    helper_digest = hashlib.sha256(helper).hexdigest()

    production_helper = tmp_path / "libexec" / "signal-ledger-deploy-helper"
    production_helper.parent.mkdir()
    production_helper.write_bytes(helper)
    production_helper.chmod(0o750)
    state_root = tmp_path / "state"
    state_root.mkdir()
    backup_path = state_root / "previous-production-deploy-helper.py"
    backup_path.write_bytes(original)
    backup_path.chmod(0o600)
    install_root = tmp_path / "installed"
    install_root.mkdir()
    manifest_path = install_root / "installed.json"

    installed_sidecars: dict[Path, bytes] = {}
    expected_fields = dict(bootstrap.KNOWN_INSTALLED_67723_INSTALL_MANIFEST)
    expected_files = dict(expected_fields["files"])
    for installed_name in expected_files:
        if installed_name == "production-deploy-helper.py":
            continue
        content = f"installed 67723 source for {installed_name}".encode()
        path = install_root / installed_name
        path.write_bytes(content)
        path.chmod(0o750 if installed_name == "host_helper.py" else 0o640)
        installed_sidecars[path] = content
        expected_files[installed_name] = hashlib.sha256(content).hexdigest()
    expected_files["production-deploy-helper.py"] = helper_digest
    expected_fields["files"] = expected_files
    expected_fields["previous_production_helper_sha256"] = original_digest
    manifest_path.write_bytes(_installed_manifest_bytes(expected_fields))
    manifest_path.chmod(0o640)

    monkeypatch.setattr(bootstrap, "PRODUCTION_HELPER", production_helper)
    monkeypatch.setattr(bootstrap, "PREVIOUS_PRODUCTION_HELPER", backup_path)
    monkeypatch.setattr(bootstrap, "PREVIOUS_PRODUCTION_HELPER_SIZE", len(original))
    monkeypatch.setattr(bootstrap, "PREVIOUS_PRODUCTION_HELPER_SHA256", original_digest)
    monkeypatch.setattr(bootstrap, "INSTALL_ROOT", install_root)
    monkeypatch.setattr(bootstrap, "INSTALLED_MANIFEST", manifest_path)
    monkeypatch.setattr(bootstrap, "KNOWN_INSTALLED_67723_PRODUCTION_HELPER_SHA256", helper_digest)
    # Production pins are asserted by the tests; fixture bytes model receipt matching only.
    monkeypatch.setattr(bootstrap, "KNOWN_INSTALLED_67723_INSTALL_MANIFEST", expected_fields)
    monkeypatch.setattr(bootstrap, "_read_fixed_root_file", _read_temp_root_file)
    return original, helper, manifest_path, expected_fields, installed_sidecars


def _known_c408_install_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[bytes, bytes, Path, dict[str, object], dict[Path, bytes]]:
    """Build the exact c408 receipt shape with synthetic installed file bytes."""
    original, helper, manifest_path, _prior_fields, sidecars = _known_677_install_fixture(
        monkeypatch, tmp_path
    )
    expected_fields = dict(bootstrap.KNOWN_INSTALLED_C408_INSTALL_MANIFEST)
    expected_files = dict(expected_fields["files"])
    for path, contents in sidecars.items():
        expected_files[path.name] = hashlib.sha256(contents).hexdigest()
    helper_digest = hashlib.sha256(helper).hexdigest()
    expected_files["production-deploy-helper.py"] = helper_digest
    expected_fields["files"] = expected_files
    expected_fields["previous_production_helper_sha256"] = hashlib.sha256(original).hexdigest()
    manifest_path.write_bytes(_installed_manifest_bytes(expected_fields))
    manifest_path.chmod(0o640)
    monkeypatch.setattr(bootstrap, "KNOWN_INSTALLED_C408_PRODUCTION_HELPER_SHA256", helper_digest)
    monkeypatch.setattr(bootstrap, "KNOWN_INSTALLED_C408_INSTALL_MANIFEST", expected_fields)
    return original, helper, manifest_path, expected_fields, sidecars


def _known_dd7_install_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[bytes, bytes, Path, dict[str, object], dict[Path, bytes]]:
    """Build a DD7 install receipt with synthetic sidecars and a fixed backup."""
    original, helper, manifest_path, _prior_fields, sidecars = _known_677_install_fixture(
        monkeypatch, tmp_path
    )
    expected_fields = dict(bootstrap.KNOWN_INSTALLED_DD7_INSTALL_MANIFEST)
    expected_files = dict(expected_fields["files"])
    for path, contents in sidecars.items():
        expected_files[path.name] = hashlib.sha256(contents).hexdigest()
    helper_digest = hashlib.sha256(helper).hexdigest()
    expected_files["production-deploy-helper.py"] = helper_digest
    expected_fields["files"] = expected_files
    expected_fields["previous_production_helper_sha256"] = hashlib.sha256(original).hexdigest()
    manifest_path.write_bytes(_installed_manifest_bytes(expected_fields))
    manifest_path.chmod(0o640)
    monkeypatch.setattr(bootstrap, "KNOWN_INSTALLED_DD7_PRODUCTION_HELPER_SHA256", helper_digest)
    monkeypatch.setattr(bootstrap, "KNOWN_INSTALLED_DD7_INSTALL_MANIFEST", expected_fields)
    return original, helper, manifest_path, expected_fields, sidecars


def _known_e1c6b17_install_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    installed_helper: bytes | None = None,
) -> tuple[bytes, bytes, Path, dict[str, object], dict[Path, bytes]]:
    """Build an E1 receipt with isolated sidecars and its immutable backup."""
    original, helper, manifest_path, _prior_fields, sidecars = _known_677_install_fixture(
        monkeypatch, tmp_path
    )
    if installed_helper is not None:
        helper = installed_helper
        bootstrap.PRODUCTION_HELPER.write_bytes(helper)
        bootstrap.PRODUCTION_HELPER.chmod(0o750)
    expected_fields = dict(bootstrap.KNOWN_INSTALLED_E1C6B17_INSTALL_MANIFEST)
    expected_files = dict(expected_fields["files"])
    for path, contents in sidecars.items():
        expected_files[path.name] = hashlib.sha256(contents).hexdigest()
    helper_digest = hashlib.sha256(helper).hexdigest()
    expected_files["production-deploy-helper.py"] = helper_digest
    expected_fields["files"] = expected_files
    expected_fields["previous_production_helper_sha256"] = hashlib.sha256(original).hexdigest()
    manifest_path.write_bytes(_installed_manifest_bytes(expected_fields))
    manifest_path.chmod(0o640)
    monkeypatch.setattr(
        bootstrap,
        "KNOWN_INSTALLED_E1C6B17_PRODUCTION_HELPER_SHA256",
        helper_digest,
    )
    monkeypatch.setattr(bootstrap, "KNOWN_INSTALLED_E1C6B17_INSTALL_MANIFEST", expected_fields)
    return original, helper, manifest_path, expected_fields, sidecars


def _known_532b2a0_install_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[bytes, bytes, Path, dict[str, object], dict[Path, bytes]]:
    """Build the exact 532b2a0 receipt shape with isolated installed files."""
    original, helper, manifest_path, _prior_fields, sidecars = _known_677_install_fixture(
        monkeypatch, tmp_path
    )
    expected_fields = dict(bootstrap.KNOWN_INSTALLED_532B2A0_INSTALL_MANIFEST)
    expected_files = dict(expected_fields["files"])
    for path, contents in sidecars.items():
        expected_files[path.name] = hashlib.sha256(contents).hexdigest()
    helper_digest = hashlib.sha256(helper).hexdigest()
    expected_files["production-deploy-helper.py"] = helper_digest
    expected_fields["files"] = expected_files
    expected_fields["previous_production_helper_sha256"] = hashlib.sha256(original).hexdigest()
    manifest_path.write_bytes(_installed_manifest_bytes(expected_fields))
    manifest_path.chmod(0o640)
    monkeypatch.setattr(
        bootstrap,
        "KNOWN_INSTALLED_E1C6B17_PRODUCTION_HELPER_SHA256",
        helper_digest,
    )
    monkeypatch.setattr(
        bootstrap,
        "KNOWN_INSTALLED_532B2A0_PRODUCTION_HELPER_SHA256",
        helper_digest,
    )
    monkeypatch.setattr(bootstrap, "KNOWN_INSTALLED_532B2A0_INSTALL_MANIFEST", expected_fields)
    return original, helper, manifest_path, expected_fields, sidecars


def _known_f548_install_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[bytes, bytes, Path, dict[str, object], dict[Path, bytes]]:
    """Build the F548 install receipt shape with isolated installed files."""
    original, helper, manifest_path, _prior_fields, sidecars = _known_677_install_fixture(
        monkeypatch, tmp_path
    )
    expected_fields = dict(bootstrap.KNOWN_INSTALLED_F548_INSTALL_MANIFEST)
    expected_files = dict(expected_fields["files"])
    for path, contents in sidecars.items():
        expected_files[path.name] = hashlib.sha256(contents).hexdigest()
    helper_digest = hashlib.sha256(helper).hexdigest()
    expected_files["production-deploy-helper.py"] = helper_digest
    expected_fields["files"] = expected_files
    expected_fields["previous_production_helper_sha256"] = hashlib.sha256(original).hexdigest()
    manifest_path.write_bytes(_installed_manifest_bytes(expected_fields))
    manifest_path.chmod(0o640)
    for name in (
        "KNOWN_INSTALLED_E1C6B17_PRODUCTION_HELPER_SHA256",
        "KNOWN_INSTALLED_532B2A0_PRODUCTION_HELPER_SHA256",
        "KNOWN_INSTALLED_F548_PRODUCTION_HELPER_SHA256",
    ):
        monkeypatch.setattr(bootstrap, name, helper_digest)
    monkeypatch.setattr(bootstrap, "KNOWN_INSTALLED_F548_INSTALL_MANIFEST", expected_fields)
    return original, helper, manifest_path, expected_fields, sidecars


def _known_e3ec8c7_install_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[bytes, bytes, Path, dict[str, object], dict[Path, bytes]]:
    """Build the exact installed H receipt shape with isolated sidecars."""
    original, _prior_helper, manifest_path, _prior_fields, sidecars = _known_677_install_fixture(
        monkeypatch, tmp_path
    )
    helper = b"installed helper bytes for the exact e3ec8c7 provenance fixture"
    bootstrap.PRODUCTION_HELPER.write_bytes(helper)
    bootstrap.PRODUCTION_HELPER.chmod(0o750)
    expected_fields = dict(bootstrap.KNOWN_INSTALLED_E3EC8C7_INSTALL_MANIFEST)
    expected_files = dict(expected_fields["files"])
    for path, contents in sidecars.items():
        expected_files[path.name] = hashlib.sha256(contents).hexdigest()
    helper_digest = hashlib.sha256(helper).hexdigest()
    assert helper_digest not in {
        _prior_fields["files"]["production-deploy-helper.py"],
        bootstrap.KNOWN_INSTALLED_C408_PRODUCTION_HELPER_SHA256,
    }
    expected_files["production-deploy-helper.py"] = helper_digest
    expected_fields["files"] = expected_files
    expected_fields["previous_production_helper_sha256"] = hashlib.sha256(original).hexdigest()
    manifest_path.write_bytes(_installed_manifest_bytes(expected_fields))
    manifest_path.chmod(0o640)
    monkeypatch.setattr(
        bootstrap, "KNOWN_INSTALLED_E3EC8C7_PRODUCTION_HELPER_SHA256", helper_digest
    )
    monkeypatch.setattr(bootstrap, "KNOWN_INSTALLED_E3EC8C7_INSTALLED_FILES", expected_files)
    monkeypatch.setattr(bootstrap, "KNOWN_INSTALLED_E3EC8C7_INSTALL_MANIFEST", expected_fields)
    return original, helper, manifest_path, expected_fields, sidecars


def _known_h2_install_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[bytes, bytes, Path, dict[str, object], dict[Path, bytes]]:
    """Build the exact H2 installed-receipt shape with isolated sidecars."""
    original, _prior_helper, manifest_path, _prior_fields, sidecars = _known_677_install_fixture(
        monkeypatch, tmp_path
    )
    helper = b"installed helper bytes for the exact H2 provenance fixture"
    bootstrap.PRODUCTION_HELPER.write_bytes(helper)
    bootstrap.PRODUCTION_HELPER.chmod(0o750)
    expected_fields = dict(bootstrap.KNOWN_INSTALLED_H2_INSTALL_MANIFEST)
    expected_files = dict(expected_fields["files"])
    for path, contents in sidecars.items():
        expected_files[path.name] = hashlib.sha256(contents).hexdigest()
    helper_digest = hashlib.sha256(helper).hexdigest()
    expected_files["production-deploy-helper.py"] = helper_digest
    expected_fields["files"] = expected_files
    expected_fields["previous_production_helper_sha256"] = hashlib.sha256(original).hexdigest()
    manifest_path.write_bytes(_installed_manifest_bytes(expected_fields))
    manifest_path.chmod(0o640)
    monkeypatch.setattr(bootstrap, "KNOWN_INSTALLED_H2_PRODUCTION_HELPER_SHA256", helper_digest)
    monkeypatch.setattr(bootstrap, "KNOWN_INSTALLED_H2_INSTALLED_FILES", expected_files)
    monkeypatch.setattr(bootstrap, "KNOWN_INSTALLED_H2_INSTALL_MANIFEST", expected_fields)
    return original, helper, manifest_path, expected_fields, sidecars


def _candidate_digest_retry_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[bytes, bytes, Path, dict[str, object]]:
    """Build an exact candidate-helper receipt distinct from every prior-state pin."""
    original, helper, manifest_path, expected_fields, _sidecars = _known_677_install_fixture(
        monkeypatch, tmp_path
    )
    # Force dispatch through the candidate-digest branch instead of any known prior state.
    for name in (
        "KNOWN_INSTALLED_67723_PRODUCTION_HELPER_SHA256",
        "KNOWN_INSTALLED_C408_PRODUCTION_HELPER_SHA256",
        "KNOWN_INSTALLED_E1C6B17_PRODUCTION_HELPER_SHA256",
        "KNOWN_INSTALLED_532B2A0_PRODUCTION_HELPER_SHA256",
        "KNOWN_INSTALLED_F548_PRODUCTION_HELPER_SHA256",
    ):
        monkeypatch.setattr(bootstrap, name, "f" * 64)
    return original, helper, manifest_path, expected_fields


def test_bootstrap_pins_exact_f548_install_provenance_and_accepts_current_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assert bootstrap.KNOWN_INSTALLED_F548_PRODUCTION_HELPER_SHA256 == (
        "4411def05a0cf757eef859b257d403d1c05eeed44c5c4265b86cb9905e1de730"
    )
    assert bootstrap.KNOWN_INSTALLED_F548_REVIEWED_HEAD_SHA == (
        "f548fd94dad75c73b31621ee1a466ac7d41d06c2"
    )
    assert bootstrap.KNOWN_INSTALLED_F548_PAIR_MANIFEST_SHA256 == (
        "0718ec4b9b3ae56a252432779b3bdad2eb7cc69a974e714a18ea19ea8b94d47e"
    )
    assert bootstrap.KNOWN_INSTALLED_F548_INSTALLED_FILES == {
        "host_helper.py": "16640749679c8ca995d2f1740d6364523e82e940fe7c8be59f5fe0b0878cf6f4",
        "seed.py": "56e79454482f20a2964766aa016e6f985673bb41571ac36bba21d09302d72b15",
        "native_driver.py": "5e72113ddbacff3d2cc44f44671bbb6e8dc5a1a49ae3292f0d8b2f91afd33c10",
        "production-deploy-helper.py": bootstrap.KNOWN_INSTALLED_F548_PRODUCTION_HELPER_SHA256,
    }
    assert bootstrap.KNOWN_INSTALLED_F548_INSTALL_MANIFEST == {
        "format_version": 1,
        "repository": bootstrap.REPOSITORY,
        "pull_number": bootstrap.HELPER_SOURCE_PR_NUMBER,
        "reviewed_head_sha": bootstrap.KNOWN_INSTALLED_F548_REVIEWED_HEAD_SHA,
        "reviewed_pair_manifest_sha256": bootstrap.KNOWN_INSTALLED_F548_PAIR_MANIFEST_SHA256,
        "files": bootstrap.KNOWN_INSTALLED_F548_INSTALLED_FILES,
        "helper_source_contract": bootstrap.HELPER_SOURCE_CONTRACT,
        "previous_production_helper_sha256": (
            "57b88adc91b13689d83c0d56a2dd9f756000624e847f0c7a107dff7cb382a915"
        ),
    }

    original, helper, manifest_path, old_fields, sidecars = _known_f548_install_fixture(
        monkeypatch, tmp_path
    )
    old_manifest = manifest_path.read_bytes()
    assert bootstrap._prepare_previous_production_helper(
        b"next reviewed production helper bytes",
        candidate_manifest_fields={
            **old_fields,
            "reviewed_head_sha": "a" * 40,
            "reviewed_pair_manifest_sha256": "b" * 64,
        },
    ) == (helper, bootstrap.PREVIOUS_PRODUCTION_HELPER_SHA256)
    assert manifest_path.read_bytes() == old_manifest
    assert {path: path.read_bytes() for path in sidecars} == sidecars
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original


@pytest.mark.parametrize("field", ["reviewed_head_sha", "reviewed_pair_manifest_sha256"])
def test_bootstrap_rejects_nearby_f548_install_provenance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
) -> None:
    original, helper, manifest_path, expected_fields, _sidecars = _known_f548_install_fixture(
        monkeypatch, tmp_path
    )
    malformed_fields = dict(expected_fields)
    malformed_fields[field] = "f" * (40 if field == "reviewed_head_sha" else 64)
    manifest_path.write_bytes(_installed_manifest_bytes(malformed_fields))
    manifest_path.chmod(0o640)

    with pytest.raises(bootstrap.InstallError, match="production_helper_manifest_mismatch"):
        bootstrap._prepare_previous_production_helper(
            b"next reviewed production helper bytes",
            candidate_manifest_fields={
                **expected_fields,
                "reviewed_head_sha": "a" * 40,
                "reviewed_pair_manifest_sha256": "b" * 64,
            },
        )
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original


def test_bootstrap_candidate_digest_retry_requires_exact_installed_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original, helper, manifest_path, expected_fields = _candidate_digest_retry_fixture(
        monkeypatch, tmp_path
    )
    assert bootstrap._prepare_previous_production_helper(
        helper,
        candidate_manifest_fields=expected_fields,
    ) == (helper, bootstrap.PREVIOUS_PRODUCTION_HELPER_SHA256)
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original


@pytest.mark.parametrize("field", ["reviewed_head_sha", "reviewed_pair_manifest_sha256"])
def test_bootstrap_candidate_digest_retry_rejects_manifest_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
) -> None:
    original, helper, manifest_path, expected_fields = _candidate_digest_retry_fixture(
        monkeypatch, tmp_path
    )
    malformed_fields = dict(expected_fields)
    malformed_fields[field] = "e" * (40 if field == "reviewed_head_sha" else 64)
    manifest_path.write_bytes(_installed_manifest_bytes(malformed_fields))
    manifest_path.chmod(0o640)

    with pytest.raises(bootstrap.InstallError, match="production_helper_manifest_mismatch"):
        bootstrap._prepare_previous_production_helper(
            helper,
            candidate_manifest_fields=expected_fields,
        )
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original


def test_bootstrap_pins_exact_h_install_provenance_and_accepts_successor_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assert bootstrap.KNOWN_INSTALLED_E3EC8C7_PRODUCTION_HELPER_SHA256 == (
        "e2cf980ed2c5bcbedea51746d7eaa20aa08d2b1eab949bee2f43fd0ff89439f8"
    )
    assert bootstrap.KNOWN_INSTALLED_E3EC8C7_REVIEWED_HEAD_SHA == (
        "e3ec8c71bc1e94d0e4383c6a19f7673d8e463589"
    )
    assert bootstrap.KNOWN_INSTALLED_E3EC8C7_PAIR_MANIFEST_SHA256 == (
        "d8750dd9e01a6ea2f0f73c6cfc3a127edc9a99c66483a8457625e9673600f72f"
    )
    assert bootstrap.KNOWN_INSTALLED_E3EC8C7_INSTALLED_FILES == {
        "host_helper.py": "16640749679c8ca995d2f1740d6364523e82e940fe7c8be59f5fe0b0878cf6f4",
        "seed.py": "56e79454482f20a2964766aa016e6f985673bb41571ac36bba21d09302d72b15",
        "native_driver.py": "5e72113ddbacff3d2cc44f44671bbb6e8dc5a1a49ae3292f0d8b2f91afd33c10",
        "production-deploy-helper.py": bootstrap.KNOWN_INSTALLED_E3EC8C7_PRODUCTION_HELPER_SHA256,
    }
    assert bootstrap.KNOWN_INSTALLED_E3EC8C7_INSTALL_MANIFEST == {
        "format_version": 1,
        "repository": bootstrap.REPOSITORY,
        "pull_number": bootstrap.HELPER_SOURCE_PR_NUMBER,
        "reviewed_head_sha": bootstrap.KNOWN_INSTALLED_E3EC8C7_REVIEWED_HEAD_SHA,
        "reviewed_pair_manifest_sha256": bootstrap.KNOWN_INSTALLED_E3EC8C7_PAIR_MANIFEST_SHA256,
        "files": bootstrap.KNOWN_INSTALLED_E3EC8C7_INSTALLED_FILES,
        "helper_source_contract": bootstrap.HELPER_SOURCE_CONTRACT,
        "previous_production_helper_sha256": bootstrap.PREVIOUS_PRODUCTION_HELPER_SHA256,
    }

    original, helper, manifest_path, installed_fields, sidecars = _known_e3ec8c7_install_fixture(
        monkeypatch, tmp_path
    )
    original_manifest = manifest_path.read_bytes()
    successor_fields = {
        **installed_fields,
        "reviewed_head_sha": "a" * 40,
        "reviewed_pair_manifest_sha256": "b" * 64,
    }

    assert bootstrap._prepare_previous_production_helper(
        b"successor production helper bytes",
        candidate_manifest_fields=successor_fields,
    ) == (helper, bootstrap.PREVIOUS_PRODUCTION_HELPER_SHA256)
    assert manifest_path.read_bytes() == original_manifest
    assert {path: path.read_bytes() for path in sidecars} == sidecars
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original


@pytest.mark.parametrize("field", ["reviewed_head_sha", "reviewed_pair_manifest_sha256", "files"])
def test_bootstrap_rejects_h_install_provenance_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
) -> None:
    original, _helper, manifest_path, installed_fields, _sidecars = _known_e3ec8c7_install_fixture(
        monkeypatch, tmp_path
    )
    malformed_fields = dict(installed_fields)
    if field == "files":
        malformed_files = dict(installed_fields["files"])
        malformed_files["host_helper.py"] = "0" * 64
        malformed_fields["files"] = malformed_files
    else:
        malformed_fields[field] = "f" * (40 if field == "reviewed_head_sha" else 64)
    manifest_path.write_bytes(_installed_manifest_bytes(malformed_fields))
    manifest_path.chmod(0o640)

    with pytest.raises(bootstrap.InstallError, match="production_helper_manifest_mismatch"):
        bootstrap._prepare_previous_production_helper(
            b"successor production helper bytes",
            candidate_manifest_fields={
                **installed_fields,
                "reviewed_head_sha": "a" * 40,
                "reviewed_pair_manifest_sha256": "b" * 64,
            },
        )
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original


def test_bootstrap_pins_exact_h2_install_provenance_and_accepts_successor_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assert bootstrap.KNOWN_INSTALLED_H2_PRODUCTION_HELPER_SHA256 == (
        "650d80cb77edd2d9eb999296352efd18795d2437be750bc17420fa785f118480"
    )
    assert bootstrap.KNOWN_INSTALLED_H2_REVIEWED_HEAD_SHA == (
        "d8c765c3909125604b5be0503ee14bae94970d46"
    )
    assert bootstrap.KNOWN_INSTALLED_H2_PAIR_MANIFEST_SHA256 == (
        "6a5faad6d2b029408fd34790dc22b350d700d0a57d6e3d9af14daaa2b5953c14"
    )
    assert bootstrap.KNOWN_INSTALLED_H2_INSTALLED_FILES == {
        "host_helper.py": "16640749679c8ca995d2f1740d6364523e82e940fe7c8be59f5fe0b0878cf6f4",
        "seed.py": "56e79454482f20a2964766aa016e6f985673bb41571ac36bba21d09302d72b15",
        "native_driver.py": "5e72113ddbacff3d2cc44f44671bbb6e8dc5a1a49ae3292f0d8b2f91afd33c10",
        "production-deploy-helper.py": bootstrap.KNOWN_INSTALLED_H2_PRODUCTION_HELPER_SHA256,
    }
    assert bootstrap.KNOWN_INSTALLED_H2_INSTALL_MANIFEST == {
        "format_version": 1,
        "repository": bootstrap.REPOSITORY,
        "pull_number": bootstrap.HELPER_SOURCE_PR_NUMBER,
        "reviewed_head_sha": bootstrap.KNOWN_INSTALLED_H2_REVIEWED_HEAD_SHA,
        "reviewed_pair_manifest_sha256": bootstrap.KNOWN_INSTALLED_H2_PAIR_MANIFEST_SHA256,
        "files": bootstrap.KNOWN_INSTALLED_H2_INSTALLED_FILES,
        "helper_source_contract": bootstrap.HELPER_SOURCE_CONTRACT,
        "previous_production_helper_sha256": (
            "57b88adc91b13689d83c0d56a2dd9f756000624e847f0c7a107dff7cb382a915"
        ),
    }

    original, helper, manifest_path, installed_fields, sidecars = _known_h2_install_fixture(
        monkeypatch, tmp_path
    )
    old_manifest = manifest_path.read_bytes()
    successor_fields = {
        **installed_fields,
        "reviewed_head_sha": "a" * 40,
        "reviewed_pair_manifest_sha256": "b" * 64,
    }

    assert bootstrap._prepare_previous_production_helper(
        b"reviewed successor production helper bytes",
        candidate_manifest_fields=successor_fields,
    ) == (helper, bootstrap.PREVIOUS_PRODUCTION_HELPER_SHA256)
    assert manifest_path.read_bytes() == old_manifest
    assert {path: path.read_bytes() for path in sidecars} == sidecars
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original
    assert stat.S_IMODE(bootstrap.PREVIOUS_PRODUCTION_HELPER.stat().st_mode) == 0o600


def test_bootstrap_h2_completed_candidate_retry_requires_exact_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original, helper, manifest_path, installed_fields, sidecars = _known_h2_install_fixture(
        monkeypatch, tmp_path
    )
    successor_fields = dict(installed_fields)
    successor_files = dict(installed_fields["files"])
    successor_fields.update(
        {
            "reviewed_head_sha": "a" * 40,
            "reviewed_pair_manifest_sha256": "b" * 64,
            "files": successor_files,
        }
    )
    for path in sidecars:
        contents = f"completed H2 successor {path.name}".encode()
        path.write_bytes(contents)
        path.chmod(0o750 if path.name == "host_helper.py" else 0o640)
        successor_files[path.name] = hashlib.sha256(contents).hexdigest()
    successor_fields["files"] = successor_files
    manifest_path.write_bytes(_installed_manifest_bytes(successor_fields))
    manifest_path.chmod(0o640)
    completed_manifest = manifest_path.read_bytes()

    assert bootstrap._prepare_previous_production_helper(
        helper,
        candidate_manifest_fields=successor_fields,
    ) == (helper, bootstrap.PREVIOUS_PRODUCTION_HELPER_SHA256)
    assert manifest_path.read_bytes() == completed_manifest
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original
    assert stat.S_IMODE(bootstrap.PREVIOUS_PRODUCTION_HELPER.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "malformation",
    ["head", "pair", "files", "contract", "predecessor", "missing", "duplicate", "mode", "sidecar"],
)
def test_bootstrap_rejects_drifted_h2_install_provenance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    malformation: str,
) -> None:
    original, helper, manifest_path, expected_fields, sidecars = _known_h2_install_fixture(
        monkeypatch, tmp_path
    )
    malformed = dict(expected_fields)
    malformed_files = dict(expected_fields["files"])
    malformed["files"] = malformed_files
    if malformation == "head":
        malformed["reviewed_head_sha"] = "f" * 40
    elif malformation == "pair":
        malformed["reviewed_pair_manifest_sha256"] = "f" * 64
    elif malformation == "files":
        malformed_files["host_helper.py"] = "0" * 64
    elif malformation == "contract":
        malformed["helper_source_contract"] = "wrong-contract"
    elif malformation == "predecessor":
        malformed["previous_production_helper_sha256"] = "f" * 64
    if malformation == "missing":
        manifest_path.unlink()
    else:
        raw = _installed_manifest_bytes(malformed)
        if malformation == "duplicate":
            raw = b'{"format_version":1,' + raw[1:]
        manifest_path.write_bytes(raw)
        manifest_path.chmod(0o644 if malformation == "mode" else 0o640)
    if malformation == "sidecar":
        path = next(path for path in sidecars if path.name == "native_driver.py")
        path.write_bytes(b"unreviewed H2 sidecar drift")
        path.chmod(0o640)

    with pytest.raises(bootstrap.InstallError, match="production_helper_manifest_mismatch"):
        bootstrap._prepare_previous_production_helper(
            b"reviewed successor production helper bytes",
            candidate_manifest_fields={
                **expected_fields,
                "reviewed_head_sha": "a" * 40,
                "reviewed_pair_manifest_sha256": "b" * 64,
            },
        )
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original
    assert stat.S_IMODE(bootstrap.PREVIOUS_PRODUCTION_HELPER.stat().st_mode) == 0o600


def test_bootstrap_rejects_unrecognized_helper_with_h2_backup_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original, _helper, _manifest_path, _expected_fields, _sidecars = _known_h2_install_fixture(
        monkeypatch, tmp_path
    )
    bootstrap.PRODUCTION_HELPER.write_bytes(b"unreviewed replacement helper")
    bootstrap.PRODUCTION_HELPER.chmod(0o750)

    with pytest.raises(bootstrap.InstallError, match="production_helper_drift"):
        bootstrap._prepare_previous_production_helper(
            b"reviewed successor production helper bytes",
            candidate_manifest_fields={},
        )
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original


def test_bootstrap_rejects_changed_h2_immutable_backup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _original, helper, _manifest_path, _expected_fields, _sidecars = _known_h2_install_fixture(
        monkeypatch, tmp_path
    )
    tampered_backup = b"tampered immutable backup"
    bootstrap.PREVIOUS_PRODUCTION_HELPER.write_bytes(tampered_backup)
    bootstrap.PREVIOUS_PRODUCTION_HELPER.chmod(0o600)

    with pytest.raises(bootstrap.InstallError, match="production_helper_backup_mismatch"):
        bootstrap._prepare_previous_production_helper(
            b"reviewed successor production helper bytes",
            candidate_manifest_fields={},
        )
    assert bootstrap.PRODUCTION_HELPER.read_bytes() == helper
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == tampered_backup


@pytest.mark.parametrize("rollback_fails", [False, True], ids=["restored", "unverified"])
def test_bootstrap_h2_install_restores_helper_and_receipt_together_on_manifest_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    rollback_fails: bool,
) -> None:
    original, prior_helper, manifest_path, _old_fields, old_sidecars = _known_h2_install_fixture(
        monkeypatch, tmp_path
    )
    old_manifest = manifest_path.read_bytes()
    incoming = tmp_path / "incoming-h2"
    incoming.mkdir()
    revision = "c" * 40
    pair_digest = "d" * 64
    sources: dict[str, bytes] = {}
    staged_paths: dict[str, Path] = {}
    staged_contents: dict[Path, bytes] = {}
    hashes: dict[str, str] = {}
    candidate_helper = b"reviewed H2 successor production helper bytes"
    for role, (relative, staged_name, _maximum) in bootstrap.ASSETS.items():
        contents = (
            candidate_helper
            if role == "production_helper"
            else f"reviewed successor {role}".encode()
        )
        sources[relative] = contents
        hashes[role] = hashlib.sha256(contents).hexdigest()
        staged_path = incoming / f"signal-ledger-pr1-{revision}-{staged_name}"
        staged_paths[role] = staged_path
        staged_contents[staged_path] = contents

    monkeypatch.setattr(bootstrap, "INCOMING", incoming)
    monkeypatch.setattr(bootstrap, "STATE_ROOT", tmp_path / "state-h2")
    monkeypatch.setattr(bootstrap, "_install_locks", nullcontext)
    monkeypatch.setattr(bootstrap, "_safe_directory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bootstrap, "_safe_incoming_directory", lambda: None)
    monkeypatch.setattr(bootstrap, "_check_root_directory", lambda *_args: None)
    monkeypatch.setattr(bootstrap, "_verify_pull_request", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bootstrap, "_staged_asset_path", lambda _revision, role: staged_paths[role])
    monkeypatch.setattr(bootstrap, "_read_staged", lambda path, _maximum: staged_contents[path])
    monkeypatch.setattr(
        bootstrap,
        "_fetch_reviewed_source",
        lambda _revision, relative, _maximum: sources[relative],
    )

    failed_manifest_write = False
    failed_helper_restore = False

    def atomic_write(path: Path, contents: bytes, mode: int) -> None:
        nonlocal failed_manifest_write, failed_helper_restore
        if path == manifest_path and contents != old_manifest and not failed_manifest_write:
            failed_manifest_write = True
            raise OSError("simulated installed receipt publication failure")
        if (
            rollback_fails
            and failed_manifest_write
            and path == bootstrap.PRODUCTION_HELPER
            and contents == prior_helper
        ):
            failed_helper_restore = True
            raise OSError("simulated production helper restoration failure")
        temporary = path.with_name(f".{path.name}.h2-test-tmp")
        temporary.write_bytes(contents)
        temporary.chmod(mode)
        temporary.replace(path)

    monkeypatch.setattr(bootstrap, "_atomic_root_file", atomic_write)
    monkeypatch.setattr(
        bootstrap,
        "_read_fixed_root_file",
        lambda path, _maximum, _mode: path.read_bytes(),
    )
    payload = {
        "reviewed_head_sha": revision,
        "reviewed_pair_manifest_sha256": pair_digest,
        "asset_sha256": hashes,
        "helper_source_contract": bootstrap.HELPER_SOURCE_CONTRACT,
    }

    with pytest.raises(bootstrap.InstallError) as raised:
        bootstrap.install(payload)

    assert failed_manifest_write is True
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original
    assert stat.S_IMODE(bootstrap.PREVIOUS_PRODUCTION_HELPER.stat().st_mode) == 0o600
    assert manifest_path.read_bytes() == old_manifest
    if rollback_fails:
        assert raised.value.code == "install_rollback_unverified"
        assert failed_helper_restore is True
        assert bootstrap.PRODUCTION_HELPER.read_bytes() == candidate_helper
        assert {path: path.read_bytes() for path in old_sidecars} != old_sidecars
    else:
        assert raised.value.code == "sidecar_install_failed"
        assert failed_helper_restore is False
        assert bootstrap.PRODUCTION_HELPER.read_bytes() == prior_helper
        assert {path: path.read_bytes() for path in old_sidecars} == old_sidecars


def test_bootstrap_accepts_exact_dd7_install_and_preserves_immutable_backup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assert bootstrap.KNOWN_INSTALLED_DD7_PRODUCTION_HELPER_SHA256 == (
        "0d99260dfdc09f2e49a486932bd3b820ea62d4eec614f26899350d640b0ab76d"
    )
    assert bootstrap.KNOWN_INSTALLED_DD7_REVIEWED_HEAD_SHA == (
        "dd7f327202358c244253e36e4a0b0f52185a0f1c"
    )
    assert bootstrap.KNOWN_INSTALLED_DD7_PAIR_MANIFEST_SHA256 == (
        "f35dedd6ba9d49c9cb53aa036f1912b3082b7af144204dbae10378b341a08095"
    )
    assert bootstrap.KNOWN_INSTALLED_DD7_INSTALLED_FILES == {
        "host_helper.py": "383719bfd2700adcc76e662b15774ca3e32dd87f61b77a9fe65ff2458f6f6a8c",
        "seed.py": "56e79454482f20a2964766aa016e6f985673bb41571ac36bba21d09302d72b15",
        "native_driver.py": "5e72113ddbacff3d2cc44f44671bbb6e8dc5a1a49ae3292f0d8b2f91afd33c10",
        "production-deploy-helper.py": bootstrap.KNOWN_INSTALLED_DD7_PRODUCTION_HELPER_SHA256,
    }
    assert bootstrap.KNOWN_INSTALLED_DD7_INSTALL_MANIFEST["previous_production_helper_sha256"] == (
        "57b88adc91b13689d83c0d56a2dd9f756000624e847f0c7a107dff7cb382a915"
    )
    original, helper, manifest_path, old_fields, old_sidecars = _known_dd7_install_fixture(
        monkeypatch, tmp_path
    )
    old_manifest = manifest_path.read_bytes()
    candidate_fields = {**old_fields, "reviewed_head_sha": "a" * 40}
    candidate_fields["reviewed_pair_manifest_sha256"] = "b" * 64

    assert bootstrap._prepare_previous_production_helper(
        helper,
        candidate_manifest_fields=candidate_fields,
    ) == (helper, bootstrap.PREVIOUS_PRODUCTION_HELPER_SHA256)
    assert manifest_path.read_bytes() == old_manifest
    assert {path: path.read_bytes() for path in old_sidecars} == old_sidecars
    backup = bootstrap.PREVIOUS_PRODUCTION_HELPER
    assert backup.read_bytes() == original
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600


def test_bootstrap_accepts_exact_e1c6b17_install_and_preserves_immutable_backup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assert bootstrap.KNOWN_INSTALLED_E1C6B17_PRODUCTION_HELPER_SHA256 == (
        "4411def05a0cf757eef859b257d403d1c05eeed44c5c4265b86cb9905e1de730"
    )
    assert bootstrap.KNOWN_INSTALLED_E1C6B17_REVIEWED_HEAD_SHA == (
        "e1c6b178ace4d3501f69e32ec828e255b4c75142"
    )
    assert bootstrap.KNOWN_INSTALLED_E1C6B17_PAIR_MANIFEST_SHA256 == (
        "556a6dc79ba320560225838842aed5be3b1c1968f724812f52ac3d7129df2371"
    )
    assert bootstrap.KNOWN_INSTALLED_E1C6B17_INSTALLED_FILES == {
        "host_helper.py": "383719bfd2700adcc76e662b15774ca3e32dd87f61b77a9fe65ff2458f6f6a8c",
        "seed.py": "56e79454482f20a2964766aa016e6f985673bb41571ac36bba21d09302d72b15",
        "native_driver.py": "5e72113ddbacff3d2cc44f44671bbb6e8dc5a1a49ae3292f0d8b2f91afd33c10",
        "production-deploy-helper.py": bootstrap.KNOWN_INSTALLED_E1C6B17_PRODUCTION_HELPER_SHA256,
    }
    assert bootstrap.KNOWN_INSTALLED_E1C6B17_INSTALL_MANIFEST == {
        "format_version": 1,
        "repository": bootstrap.REPOSITORY,
        "pull_number": bootstrap.HELPER_SOURCE_PR_NUMBER,
        "reviewed_head_sha": bootstrap.KNOWN_INSTALLED_E1C6B17_REVIEWED_HEAD_SHA,
        "reviewed_pair_manifest_sha256": (bootstrap.KNOWN_INSTALLED_E1C6B17_PAIR_MANIFEST_SHA256),
        "files": bootstrap.KNOWN_INSTALLED_E1C6B17_INSTALLED_FILES,
        "helper_source_contract": bootstrap.HELPER_SOURCE_CONTRACT,
        "previous_production_helper_sha256": (
            "57b88adc91b13689d83c0d56a2dd9f756000624e847f0c7a107dff7cb382a915"
        ),
    }
    original, helper, manifest_path, old_fields, old_sidecars = _known_e1c6b17_install_fixture(
        monkeypatch, tmp_path
    )
    old_manifest = manifest_path.read_bytes()
    candidate_fields = {**old_fields, "reviewed_head_sha": "a" * 40}
    candidate_fields["reviewed_pair_manifest_sha256"] = "b" * 64

    assert bootstrap._prepare_previous_production_helper(
        helper,
        candidate_manifest_fields=candidate_fields,
    ) == (helper, bootstrap.PREVIOUS_PRODUCTION_HELPER_SHA256)
    assert manifest_path.read_bytes() == old_manifest
    assert {path: path.read_bytes() for path in old_sidecars} == old_sidecars
    backup = bootstrap.PREVIOUS_PRODUCTION_HELPER
    assert backup.read_bytes() == original
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600


def test_bootstrap_accepts_exact_532b2a0_prior_install_with_candidate_manifest_present(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assert bootstrap.KNOWN_INSTALLED_532B2A0_PRODUCTION_HELPER_SHA256 == (
        "4411def05a0cf757eef859b257d403d1c05eeed44c5c4265b86cb9905e1de730"
    )
    assert bootstrap.KNOWN_INSTALLED_532B2A0_REVIEWED_HEAD_SHA == (
        "532b2a0c96ec4eebc645ebb315a5419ae74b9251"
    )
    assert bootstrap.KNOWN_INSTALLED_532B2A0_PAIR_MANIFEST_SHA256 == (
        "e53b16c5670532b4167056533fc195a9f98f5bbd51dd9f2423e27f44ee001074"
    )
    assert bootstrap.KNOWN_INSTALLED_532B2A0_INSTALLED_FILES == {
        "host_helper.py": "5bf55b2433597d9b958eeecd01933c11b41f37a513d7921f10321812be70f1f4",
        "seed.py": "56e79454482f20a2964766aa016e6f985673bb41571ac36bba21d09302d72b15",
        "native_driver.py": "5e72113ddbacff3d2cc44f44671bbb6e8dc5a1a49ae3292f0d8b2f91afd33c10",
        "production-deploy-helper.py": bootstrap.KNOWN_INSTALLED_532B2A0_PRODUCTION_HELPER_SHA256,
    }
    original, helper, manifest_path, old_fields, old_sidecars = _known_532b2a0_install_fixture(
        monkeypatch, tmp_path
    )
    old_manifest = manifest_path.read_bytes()
    candidate_fields = {**old_fields, "reviewed_head_sha": "a" * 40}
    candidate_fields["reviewed_pair_manifest_sha256"] = "b" * 64

    assert bootstrap._prepare_previous_production_helper(
        b"next reviewed production helper bytes",
        candidate_manifest_fields=candidate_fields,
    ) == (helper, bootstrap.PREVIOUS_PRODUCTION_HELPER_SHA256)
    assert manifest_path.read_bytes() == old_manifest
    assert {path: path.read_bytes() for path in old_sidecars} == old_sidecars
    backup = bootstrap.PREVIOUS_PRODUCTION_HELPER
    assert backup.read_bytes() == original
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600


@pytest.mark.parametrize("malformation", ["head", "pair"])
def test_bootstrap_rejects_nearby_532b2a0_prior_install_tuple(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    malformation: str,
) -> None:
    original, helper, manifest_path, expected_fields, _sidecars = _known_532b2a0_install_fixture(
        monkeypatch, tmp_path
    )
    malformed_fields = dict(expected_fields)
    field = "reviewed_head_sha" if malformation == "head" else "reviewed_pair_manifest_sha256"
    malformed_fields[field] = "f" * (40 if malformation == "head" else 64)
    manifest_path.write_bytes(_installed_manifest_bytes(malformed_fields))
    manifest_path.chmod(0o640)

    with pytest.raises(bootstrap.InstallError, match="production_helper_manifest_mismatch"):
        bootstrap._prepare_previous_production_helper(
            b"next reviewed production helper bytes",
            candidate_manifest_fields={
                **expected_fields,
                "reviewed_head_sha": "a" * 40,
                "reviewed_pair_manifest_sha256": "b" * 64,
            },
        )
    backup = bootstrap.PREVIOUS_PRODUCTION_HELPER
    assert backup.read_bytes() == original
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600


def test_bootstrap_accepts_exact_candidate_receipt_for_same_e1c6b17_helper_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original, helper, manifest_path, old_fields, old_sidecars = _known_e1c6b17_install_fixture(
        monkeypatch, tmp_path
    )
    candidate_fields = {**old_fields, "reviewed_head_sha": "a" * 40}
    candidate_fields["reviewed_pair_manifest_sha256"] = "b" * 64
    manifest_path.write_bytes(_installed_manifest_bytes(candidate_fields))
    manifest_path.chmod(0o640)
    candidate_manifest = manifest_path.read_bytes()

    assert bootstrap._prepare_previous_production_helper(
        helper,
        candidate_manifest_fields=candidate_fields,
    ) == (helper, bootstrap.PREVIOUS_PRODUCTION_HELPER_SHA256)
    assert manifest_path.read_bytes() == candidate_manifest
    assert {path: path.read_bytes() for path in old_sidecars} == old_sidecars
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original
    assert stat.S_IMODE(bootstrap.PREVIOUS_PRODUCTION_HELPER.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "malformation",
    [
        "head",
        "pair",
        "files",
        "contract",
        "predecessor",
        "duplicate",
        "missing",
        "mode",
        "sidecar",
        "unknown",
    ],
)
def test_bootstrap_rejects_unknown_or_drifted_e1c6b17_install_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    malformation: str,
) -> None:
    original, helper, manifest_path, expected_fields, old_sidecars = _known_e1c6b17_install_fixture(
        monkeypatch, tmp_path
    )
    malformed = dict(expected_fields)
    malformed_files = dict(expected_fields["files"])
    malformed["files"] = malformed_files
    if malformation == "head":
        malformed["reviewed_head_sha"] = "f" * 40
    elif malformation == "pair":
        malformed["reviewed_pair_manifest_sha256"] = "f" * 64
    elif malformation == "files":
        malformed_files["native_driver.py"] = "f" * 64
    elif malformation == "contract":
        malformed["helper_source_contract"] = "wrong-contract"
    elif malformation == "predecessor":
        malformed["previous_production_helper_sha256"] = "f" * 64
    elif malformation == "unknown":
        malformed["unreviewed"] = True
    if malformation == "missing":
        manifest_path.unlink()
    else:
        raw = _installed_manifest_bytes(malformed)
        if malformation == "duplicate":
            raw = b'{"format_version":1,' + raw[1:]
        manifest_path.write_bytes(raw)
        manifest_path.chmod(0o644 if malformation == "mode" else 0o640)
    if malformation == "sidecar":
        path = next(path for path in old_sidecars if path.name == "native_driver.py")
        path.write_bytes(b"unreviewed E1 source drift")
        path.chmod(0o640)

    with pytest.raises(bootstrap.InstallError, match="production_helper_manifest_mismatch"):
        bootstrap._prepare_previous_production_helper(
            helper,
            candidate_manifest_fields={
                **expected_fields,
                "reviewed_head_sha": "a" * 40,
                "reviewed_pair_manifest_sha256": "b" * 64,
            },
        )
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original
    assert stat.S_IMODE(bootstrap.PREVIOUS_PRODUCTION_HELPER.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "malformation", ["head", "pair", "files", "predecessor", "missing", "sidecar"]
)
def test_bootstrap_rejects_drifted_dd7_install_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    malformation: str,
) -> None:
    original, helper, manifest_path, expected_fields, old_sidecars = _known_dd7_install_fixture(
        monkeypatch, tmp_path
    )
    malformed = dict(expected_fields)
    malformed_files = dict(expected_fields["files"])
    malformed["files"] = malformed_files
    if malformation == "head":
        malformed["reviewed_head_sha"] = "f" * 40
    elif malformation == "pair":
        malformed["reviewed_pair_manifest_sha256"] = "f" * 64
    elif malformation == "files":
        malformed_files["native_driver.py"] = "f" * 64
    elif malformation == "predecessor":
        malformed["previous_production_helper_sha256"] = "f" * 64
    elif malformation == "missing":
        manifest_path.unlink()
    elif malformation == "sidecar":
        path = next(path for path in old_sidecars if path.name == "native_driver.py")
        path.write_bytes(b"unreviewed DD7 source drift")
        path.chmod(0o640)
    if malformation != "missing":
        manifest_path.write_bytes(_installed_manifest_bytes(malformed))
        manifest_path.chmod(0o640)

    with pytest.raises(bootstrap.InstallError, match="production_helper_manifest_mismatch"):
        bootstrap._prepare_previous_production_helper(
            helper,
            candidate_manifest_fields={
                **expected_fields,
                "reviewed_head_sha": "a" * 40,
                "reviewed_pair_manifest_sha256": "b" * 64,
            },
        )
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original
    assert stat.S_IMODE(bootstrap.PREVIOUS_PRODUCTION_HELPER.stat().st_mode) == 0o600


def test_bootstrap_accepts_exact_67723_install_during_same_helper_source_upgrade(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assert bootstrap.KNOWN_INSTALLED_67723_PRODUCTION_HELPER_SHA256 == (
        "85ea6568514188b37c6b6f7b93dc902cf7003836b60983255e4a0337fc575371"
    )
    assert bootstrap.KNOWN_INSTALLED_67723_REVIEWED_HEAD_SHA == (
        "67723d36ea03b0628e59007af20c2910a64d06fb"
    )
    assert bootstrap.KNOWN_INSTALLED_67723_PAIR_MANIFEST_SHA256 == (
        "60f1288183685f104452b1fc1f51a823a31a09501f3807fe7023d988f950335e"
    )
    assert (
        bootstrap.KNOWN_INSTALLED_67723_INSTALL_MANIFEST["previous_production_helper_sha256"]
        == "57b88adc91b13689d83c0d56a2dd9f756000624e847f0c7a107dff7cb382a915"
    )
    assert bootstrap.KNOWN_INSTALLED_67723_INSTALLED_FILES == {
        "host_helper.py": "c2929e6d129cc56eeb21d3dcec7be484345e9d39ff1ed910dcb16901d62faf76",
        "seed.py": "56e79454482f20a2964766aa016e6f985673bb41571ac36bba21d09302d72b15",
        "native_driver.py": "5e72113ddbacff3d2cc44f44671bbb6e8dc5a1a49ae3292f0d8b2f91afd33c10",
        "production-deploy-helper.py": bootstrap.KNOWN_INSTALLED_67723_PRODUCTION_HELPER_SHA256,
    }
    original, helper, manifest_path, old_fields, old_sidecars = _known_677_install_fixture(
        monkeypatch, tmp_path
    )
    old_manifest = manifest_path.read_bytes()
    new_source_fields: dict[str, object] = {
        "format_version": 1,
        "repository": bootstrap.REPOSITORY,
        "pull_number": bootstrap.HELPER_SOURCE_PR_NUMBER,
        "reviewed_head_sha": "a" * 40,
        "reviewed_pair_manifest_sha256": "b" * 64,
        "files": {
            "host_helper.py": "383719bfd2700adcc76e662b15774ca3e32dd87f61b77a9fe65ff2458f6f6a8c",
            "seed.py": "56e79454482f20a2964766aa016e6f985673bb41571ac36bba21d09302d72b15",
            "native_driver.py": "5e72113ddbacff3d2cc44f44671bbb6e8dc5a1a49ae3292f0d8b2f91afd33c10",
            "production-deploy-helper.py": bootstrap.KNOWN_INSTALLED_67723_PRODUCTION_HELPER_SHA256,
        },
        "helper_source_contract": bootstrap.HELPER_SOURCE_CONTRACT,
        "previous_production_helper_sha256": bootstrap.PREVIOUS_PRODUCTION_HELPER_SHA256,
    }

    assert old_fields["reviewed_head_sha"] != new_source_fields["reviewed_head_sha"]
    old_pair_digest = old_fields["reviewed_pair_manifest_sha256"]
    new_pair_digest = new_source_fields["reviewed_pair_manifest_sha256"]
    assert old_pair_digest != new_pair_digest
    assert bootstrap._prepare_previous_production_helper(
        helper,
        candidate_manifest_fields=new_source_fields,
    ) == (helper, bootstrap.PREVIOUS_PRODUCTION_HELPER_SHA256)
    assert manifest_path.read_bytes() == old_manifest
    assert {path: path.read_bytes() for path in old_sidecars} == old_sidecars
    backup = bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes()
    assert backup == original
    assert stat.S_IMODE(bootstrap.PREVIOUS_PRODUCTION_HELPER.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "malformation",
    ["head", "pair", "files", "contract", "predecessor", "duplicate", "missing", "mode", "sidecar"],
)
def test_bootstrap_rejects_drifted_67723_install_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    malformation: str,
) -> None:
    original, helper, manifest_path, expected_fields, old_sidecars = _known_677_install_fixture(
        monkeypatch, tmp_path
    )
    malformed = dict(expected_fields)
    malformed_files = dict(expected_fields["files"])
    malformed["files"] = malformed_files
    if malformation == "head":
        malformed["reviewed_head_sha"] = "f" * 40
    elif malformation == "pair":
        malformed["reviewed_pair_manifest_sha256"] = "f" * 64
    elif malformation == "files":
        malformed_files["native_driver.py"] = "f" * 64
    elif malformation == "contract":
        malformed["helper_source_contract"] = "wrong-contract"
    elif malformation == "predecessor":
        malformed["previous_production_helper_sha256"] = "f" * 64
    if malformation == "missing":
        manifest_path.unlink()
    else:
        raw = _installed_manifest_bytes(malformed)
        if malformation == "duplicate":
            raw = b'{"format_version":1,' + raw[1:]
        manifest_path.write_bytes(raw)
        manifest_path.chmod(0o644 if malformation == "mode" else 0o640)
    if malformation == "sidecar":
        path = next(path for path in old_sidecars if path.name == "native_driver.py")
        path.write_bytes(b"unreviewed source drift")
        path.chmod(0o640)

    with pytest.raises(bootstrap.InstallError, match="production_helper_manifest_mismatch"):
        bootstrap._prepare_previous_production_helper(
            helper,
            candidate_manifest_fields={
                **expected_fields,
                "reviewed_head_sha": "a" * 40,
                "reviewed_pair_manifest_sha256": "b" * 64,
            },
        )
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original
    assert stat.S_IMODE(bootstrap.PREVIOUS_PRODUCTION_HELPER.stat().st_mode) == 0o600


def test_bootstrap_accepts_exact_c408_install_during_same_helper_source_upgrade(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assert bootstrap.KNOWN_INSTALLED_C408_PRODUCTION_HELPER_SHA256 == (
        "85ea6568514188b37c6b6f7b93dc902cf7003836b60983255e4a0337fc575371"
    )
    assert bootstrap.KNOWN_INSTALLED_C408_REVIEWED_HEAD_SHA == (
        "c408e9143143c4d71d0bb3a363e6f05f2c8dc221"
    )
    assert bootstrap.KNOWN_INSTALLED_C408_PAIR_MANIFEST_SHA256 == (
        "73bb45b1f03f59eccde7972aa9550ea97882f61d0810a21fdba65c3c676f74ee"
    )
    assert bootstrap.KNOWN_INSTALLED_C408_INSTALLED_FILES == {
        "host_helper.py": "383719bfd2700adcc76e662b15774ca3e32dd87f61b77a9fe65ff2458f6f6a8c",
        "seed.py": "56e79454482f20a2964766aa016e6f985673bb41571ac36bba21d09302d72b15",
        "native_driver.py": "5e72113ddbacff3d2cc44f44671bbb6e8dc5a1a49ae3292f0d8b2f91afd33c10",
        "production-deploy-helper.py": bootstrap.KNOWN_INSTALLED_C408_PRODUCTION_HELPER_SHA256,
    }
    assert bootstrap.KNOWN_INSTALLED_C408_INSTALL_MANIFEST == {
        "format_version": 1,
        "repository": bootstrap.REPOSITORY,
        "pull_number": bootstrap.HELPER_SOURCE_PR_NUMBER,
        "reviewed_head_sha": bootstrap.KNOWN_INSTALLED_C408_REVIEWED_HEAD_SHA,
        "reviewed_pair_manifest_sha256": bootstrap.KNOWN_INSTALLED_C408_PAIR_MANIFEST_SHA256,
        "files": bootstrap.KNOWN_INSTALLED_C408_INSTALLED_FILES,
        "helper_source_contract": bootstrap.HELPER_SOURCE_CONTRACT,
        "previous_production_helper_sha256": (
            "57b88adc91b13689d83c0d56a2dd9f756000624e847f0c7a107dff7cb382a915"
        ),
    }
    original, helper, manifest_path, old_fields, old_sidecars = _known_c408_install_fixture(
        monkeypatch, tmp_path
    )
    old_manifest = manifest_path.read_bytes()
    candidate_fields = dict(old_fields)
    candidate_fields["reviewed_head_sha"] = "a" * 40
    candidate_fields["reviewed_pair_manifest_sha256"] = "b" * 64

    assert bootstrap._prepare_previous_production_helper(
        helper,
        candidate_manifest_fields=candidate_fields,
    ) == (helper, bootstrap.PREVIOUS_PRODUCTION_HELPER_SHA256)
    assert manifest_path.read_bytes() == old_manifest
    assert {path: path.read_bytes() for path in old_sidecars} == old_sidecars
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original
    assert stat.S_IMODE(bootstrap.PREVIOUS_PRODUCTION_HELPER.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "malformation",
    ["head", "pair", "files", "contract", "predecessor", "duplicate", "missing", "mode", "sidecar"],
)
def test_bootstrap_rejects_drifted_c408_install_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    malformation: str,
) -> None:
    original, helper, manifest_path, expected_fields, old_sidecars = _known_c408_install_fixture(
        monkeypatch, tmp_path
    )
    malformed = dict(expected_fields)
    malformed_files = dict(expected_fields["files"])
    malformed["files"] = malformed_files
    if malformation == "head":
        malformed["reviewed_head_sha"] = "f" * 40
    elif malformation == "pair":
        malformed["reviewed_pair_manifest_sha256"] = "f" * 64
    elif malformation == "files":
        malformed_files["native_driver.py"] = "f" * 64
    elif malformation == "contract":
        malformed["helper_source_contract"] = "wrong-contract"
    elif malformation == "predecessor":
        malformed["previous_production_helper_sha256"] = "f" * 64
    if malformation == "missing":
        manifest_path.unlink()
    else:
        raw = _installed_manifest_bytes(malformed)
        if malformation == "duplicate":
            raw = b'{"format_version":1,' + raw[1:]
        manifest_path.write_bytes(raw)
        manifest_path.chmod(0o644 if malformation == "mode" else 0o640)
    if malformation == "sidecar":
        path = next(path for path in old_sidecars if path.name == "native_driver.py")
        path.write_bytes(b"unreviewed source drift")
        path.chmod(0o640)

    with pytest.raises(bootstrap.InstallError, match="production_helper_manifest_mismatch"):
        bootstrap._prepare_previous_production_helper(
            helper,
            candidate_manifest_fields={
                **expected_fields,
                "reviewed_head_sha": "a" * 40,
                "reviewed_pair_manifest_sha256": "b" * 64,
            },
        )
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original
    assert stat.S_IMODE(bootstrap.PREVIOUS_PRODUCTION_HELPER.stat().st_mode) == 0o600


@pytest.mark.parametrize("drift", ["current-helper", "backup-bytes", "backup-mode"])
def test_bootstrap_rejects_67723_helper_or_immutable_backup_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    drift: str,
) -> None:
    original, helper, _manifest_path, expected_fields, _old_sidecars = _known_677_install_fixture(
        monkeypatch, tmp_path
    )
    if drift == "current-helper":
        bootstrap.PRODUCTION_HELPER.write_bytes(b"unreviewed current helper drift")
        bootstrap.PRODUCTION_HELPER.chmod(0o750)
        expected_error = "production_helper_drift"
    elif drift == "backup-bytes":
        bootstrap.PREVIOUS_PRODUCTION_HELPER.write_bytes(b"unreviewed backup drift")
        bootstrap.PREVIOUS_PRODUCTION_HELPER.chmod(0o600)
        expected_error = "production_helper_backup_mismatch"
    else:
        bootstrap.PREVIOUS_PRODUCTION_HELPER.chmod(0o640)
        expected_error = "production_helper_file_unsafe"
    with pytest.raises(bootstrap.InstallError, match=expected_error):
        bootstrap._prepare_previous_production_helper(
            helper,
            candidate_manifest_fields=expected_fields,
        )
    if drift == "current-helper":
        assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original


def test_bootstrap_source_only_upgrade_compensates_and_retries_exact_67723_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original, helper, manifest_path, old_fields, old_sidecars = _known_677_install_fixture(
        monkeypatch, tmp_path
    )
    workspace = Path(__file__).resolve().parents[1]
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    state_root = bootstrap.PREVIOUS_PRODUCTION_HELPER.parent
    sources = {
        relative: (workspace / relative).read_bytes()
        for relative, _name, _maximum in bootstrap.ASSETS.values()
    }
    candidate_helper = sources["scripts/production-deploy-helper.py"]
    assert helper != candidate_helper
    revision = "a" * 40
    pair_digest = "b" * 64
    asset_hashes: dict[str, str] = {}

    def stage_sources() -> None:
        for role, (_relative, staged_name, _maximum) in bootstrap.ASSETS.items():
            content = sources[bootstrap.ASSETS[role][0]]
            asset_hashes[role] = hashlib.sha256(content).hexdigest()
            (incoming / f"signal-ledger-pr1-{revision}-{staged_name}").write_bytes(content)

    stage_sources()
    monkeypatch.setattr(bootstrap, "INCOMING", incoming)
    monkeypatch.setattr(bootstrap, "STATE_ROOT", state_root)
    monkeypatch.setattr(bootstrap, "_install_locks", nullcontext)
    monkeypatch.setattr(bootstrap, "_safe_directory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bootstrap, "_safe_incoming_directory", lambda: None)
    monkeypatch.setattr(bootstrap, "_check_root_directory", lambda *_args: None)
    monkeypatch.setattr(bootstrap, "_verify_pull_request", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        bootstrap,
        "_fetch_reviewed_source",
        lambda _revision, relative, _maximum: sources[relative],
    )
    prior_manifest = manifest_path.read_bytes()
    prior_sidecars = dict(old_sidecars)
    fail_receipt_once = True

    def atomic_write(path: Path, contents: bytes, mode: int) -> None:
        nonlocal fail_receipt_once
        if path == manifest_path and contents != prior_manifest and fail_receipt_once:
            fail_receipt_once = False
            raise OSError("simulated installed receipt publication failure")
        temporary = path.with_name(f".{path.name}.test-tmp")
        temporary.write_bytes(contents)
        temporary.chmod(mode)
        temporary.replace(path)

    monkeypatch.setattr(bootstrap, "_atomic_root_file", atomic_write)
    payload = {
        "reviewed_head_sha": revision,
        "reviewed_pair_manifest_sha256": pair_digest,
        "asset_sha256": asset_hashes,
        "helper_source_contract": bootstrap.HELPER_SOURCE_CONTRACT,
    }

    with pytest.raises(bootstrap.InstallError, match="sidecar_install_failed"):
        bootstrap.install(payload)
    assert manifest_path.read_bytes() == prior_manifest
    assert {path: path.read_bytes() for path in prior_sidecars} == prior_sidecars
    assert bootstrap.PRODUCTION_HELPER.read_bytes() == helper
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original
    assert stat.S_IMODE(bootstrap.PREVIOUS_PRODUCTION_HELPER.stat().st_mode) == 0o600

    result = bootstrap.install(payload)
    assert result["status"] == "installed"
    assert result["reviewed_head_sha"] == revision
    assert bootstrap.PRODUCTION_HELPER.read_bytes() == candidate_helper
    assert manifest_path.read_bytes() != prior_manifest
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original
    assert stat.S_IMODE(bootstrap.PREVIOUS_PRODUCTION_HELPER.stat().st_mode) == 0o600

    stage_sources()
    retry = bootstrap.install(payload)
    assert retry == result
    assert bootstrap.PRODUCTION_HELPER.read_bytes() == candidate_helper
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original
    assert old_fields["reviewed_head_sha"] == bootstrap.KNOWN_INSTALLED_67723_REVIEWED_HEAD_SHA


def test_bootstrap_e1_prior_helper_refresh_rolls_back_and_retries_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = Path(__file__).resolve().parents[1]
    sources = {
        relative: (workspace / relative).read_bytes()
        for relative, _name, _maximum in bootstrap.ASSETS.values()
    }
    candidate_helper = sources["scripts/production-deploy-helper.py"]
    original, helper, manifest_path, old_fields, old_sidecars = _known_e1c6b17_install_fixture(
        monkeypatch, tmp_path
    )
    assert helper != candidate_helper
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    state_root = bootstrap.PREVIOUS_PRODUCTION_HELPER.parent
    revision = "a" * 40
    pair_digest = "b" * 64
    asset_hashes: dict[str, str] = {}

    def stage_sources() -> None:
        for role, (relative, staged_name, _maximum) in bootstrap.ASSETS.items():
            content = sources[relative]
            asset_hashes[role] = hashlib.sha256(content).hexdigest()
            (incoming / f"signal-ledger-pr1-{revision}-{staged_name}").write_bytes(content)

    stage_sources()
    monkeypatch.setattr(bootstrap, "INCOMING", incoming)
    monkeypatch.setattr(bootstrap, "STATE_ROOT", state_root)
    monkeypatch.setattr(bootstrap, "_install_locks", nullcontext)
    monkeypatch.setattr(bootstrap, "_safe_directory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bootstrap, "_safe_incoming_directory", lambda: None)
    monkeypatch.setattr(bootstrap, "_check_root_directory", lambda *_args: None)
    monkeypatch.setattr(bootstrap, "_verify_pull_request", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        bootstrap,
        "_fetch_reviewed_source",
        lambda _revision, relative, _maximum: sources[relative],
    )
    prior_manifest = manifest_path.read_bytes()
    prior_sidecars = dict(old_sidecars)
    fail_receipt_once = True

    def atomic_write(path: Path, contents: bytes, mode: int) -> None:
        nonlocal fail_receipt_once
        if path == manifest_path and contents != prior_manifest and fail_receipt_once:
            fail_receipt_once = False
            raise OSError("simulated installed receipt publication failure")
        temporary = path.with_name(f".{path.name}.test-tmp")
        temporary.write_bytes(contents)
        temporary.chmod(mode)
        temporary.replace(path)

    monkeypatch.setattr(bootstrap, "_atomic_root_file", atomic_write)
    payload = {
        "reviewed_head_sha": revision,
        "reviewed_pair_manifest_sha256": pair_digest,
        "asset_sha256": asset_hashes,
        "helper_source_contract": bootstrap.HELPER_SOURCE_CONTRACT,
    }

    with pytest.raises(bootstrap.InstallError, match="sidecar_install_failed"):
        bootstrap.install(payload)
    assert manifest_path.read_bytes() == prior_manifest
    assert {path: path.read_bytes() for path in prior_sidecars} == prior_sidecars
    assert bootstrap.PRODUCTION_HELPER.read_bytes() == helper
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original
    assert stat.S_IMODE(bootstrap.PREVIOUS_PRODUCTION_HELPER.stat().st_mode) == 0o600

    result = bootstrap.install(payload)
    assert result["status"] == "installed"
    assert result["reviewed_head_sha"] == revision
    assert bootstrap.PRODUCTION_HELPER.read_bytes() == candidate_helper
    assert manifest_path.read_bytes() != prior_manifest
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original
    assert stat.S_IMODE(bootstrap.PREVIOUS_PRODUCTION_HELPER.stat().st_mode) == 0o600

    stage_sources()
    retry = bootstrap.install(payload)
    assert retry == result
    assert bootstrap.PRODUCTION_HELPER.read_bytes() == candidate_helper
    assert bootstrap.PREVIOUS_PRODUCTION_HELPER.read_bytes() == original
    assert old_fields["reviewed_head_sha"] == bootstrap.KNOWN_INSTALLED_E1C6B17_REVIEWED_HEAD_SHA


@pytest.mark.parametrize(
    "extra",
    [
        {"helper_source_contract": "pr=11"},
        {"helper_source_contract": "schema13_same_schema_hotfix_v3"},
        {"helper_source_contract": bootstrap.HELPER_SOURCE_CONTRACT, "pull_number": 11},
    ],
)
def test_bootstrap_rejects_arbitrary_helper_identity_payload(
    extra: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "reviewed_head_sha": "a" * 40,
        "reviewed_pair_manifest_sha256": "b" * 64,
        "asset_sha256": {name: "c" * 64 for name in bootstrap.ASSETS},
        **extra,
    }
    with pytest.raises(bootstrap.InstallError, match="payload_invalid"):
        bootstrap.install(payload)


def test_controller_rejects_bootstrap_install_receipt_for_wrong_helper_pr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision = "a" * 40
    config = controller.RehearsalConfig(
        Path("/unused/identity"),
        Path("/unused/known-hosts"),
        revision,
        "b" * 64,
    )
    monkeypatch.setattr(
        controller,
        "_source_stage_names",
        lambda _revision, **_kwargs: {"bootstrap": "bootstrap.py"},
    )
    monkeypatch.setattr(controller, "_stage_named_assets", lambda *_args: None)
    monkeypatch.setattr(controller, "_ssh_prefix", lambda _config: ["ssh"])
    monkeypatch.setattr(
        controller,
        "_run_fixed",
        lambda *_args, **_kwargs: json.dumps(
            {
                "status": "installed",
                "reviewed_head_sha": revision,
                "reviewed_pair_manifest_sha256": "b" * 64,
                "asset_sha256": {"bootstrap": "c" * 64},
                "pull_number": controller.PULL_NUMBER,
                "helper_source_contract": controller.HOTFIX_CONTRACT,
            }
        ).encode(),
    )

    with pytest.raises(controller.RehearsalError, match="bootstrap_install_failed"):
        controller._stage_source_bundle(
            config,
            revision,
            "b" * 64,
            {"bootstrap": b"bootstrap"},
            {"bootstrap": "c" * 64},
            helper_source_contract=controller.HOTFIX_CONTRACT,
        )


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


def test_fixed_command_failure_records_only_category_and_numeric_status() -> None:
    private_argument = "synthetic-secret-argv-value"
    with pytest.raises(host_helper.RehearsalError, match="fixed_command_failed") as failure:
        host_helper._run(
            [sys.executable, "-c", "import sys; sys.exit(23)", private_argument],
            timeout=5,
        )

    assert failure.value.details == {"command_category": "other_fixed", "exit_status": 23}
    assert private_argument not in json.dumps(failure.value.details)


def test_fixed_command_category_recognizes_only_closed_rehearsal_shapes() -> None:
    volume = "signal-ledger-pr1-12345678-0123456789abcdef"
    revision = "a" * 40
    pair = "b" * 64
    image_id = "sha256:" + "c" * 64
    container_id = "d" * 64

    assert (
        host_helper._fixed_command_category(
            ["/usr/bin/docker", "load", "--input", "/fixed/private/archive.tar.gz"]
        )
        == "image_load"
    )
    assert (
        host_helper._fixed_command_category(
            ["/usr/bin/docker", "image", "inspect", "--format", "{{.Id}}", image_id]
        )
        == "image_inspect"
    )
    assert (
        host_helper._fixed_command_category(
            [
                "/usr/bin/docker",
                "volume",
                "create",
                "--label",
                "org.stock-probs.pr-rehearsal=true",
                "--label",
                f"org.stock-probs.pr-rehearsal.head={revision}",
                "--label",
                f"org.stock-probs.pr-rehearsal.pair={pair}",
                volume,
            ]
        )
        == "volume_create"
    )
    fixture_categories = (
        ("seed", "fixture_seed"),
        ("verify-backup", "fixture_verify_backup"),
        ("restore-guard", "fixture_restore_guard"),
        ("marker", "fixture_marker"),
        ("snapshot", "fixture_snapshot"),
    )
    for operation, expected_category in fixture_categories:
        assert (
            host_helper._fixed_command_category(
                [
                    "/usr/bin/docker",
                    "exec",
                    "-i",
                    "--user",
                    "10001:10001",
                    container_id,
                    "python",
                    "/run/assistant/seed.py",
                    operation,
                ]
            )
            == expected_category
        )
    assert (
        host_helper._fixed_command_category(
            [
                "/usr/bin/docker",
                "volume",
                "inspect",
                "--format",
                host_helper.VOLUME_INSPECT_TEMPLATE,
                volume,
            ]
        )
        == "volume_inspect"
    )
    assert (
        host_helper._fixed_command_category(["/usr/bin/docker", "volume", "inspect", volume])
        == "volume_inspect"
    )
    assert (
        host_helper._fixed_command_category(
            [
                "/usr/bin/docker",
                "volume",
                "ls",
                "--filter",
                f"name=^{volume}$",
                "--format",
                "{{.Name}}",
            ]
        )
        == "volume_list"
    )
    assert (
        host_helper._fixed_command_category(["/usr/bin/docker", "volume", "rm", volume])
        == "volume_remove"
    )
    assert (
        host_helper._fixed_command_category(["/usr/bin/docker", "volume", "rm", volume, "--force"])
        == "other_fixed"
    )
    assert (
        host_helper._fixed_command_category(
            [
                "/usr/bin/docker",
                "exec",
                "-i",
                "--user",
                "10001:10001",
                container_id,
                "python",
                "/run/assistant/seed.py",
                "shell",
            ]
        )
        == "other_fixed"
    )
    assert (
        host_helper._fixed_command_category(
            ["/usr/bin/docker", "load", "--input", "/fixed/archive", "--password", "secret"]
        )
        == "other_fixed"
    )
    assert (
        host_helper._fixed_command_category(
            ["/bin/sh", "-c", "echo do-not-run", "synthetic-secret-argv-value"]
        )
        == "other_fixed"
    )


def test_controller_projects_only_typed_host_command_failure_and_receipt() -> None:
    projected = controller._safe_host_failure_details(
        {
            "status": "error",
            "code": "fixed_command_failed",
            "receipt_id": "a" * 32,
            "failure": {"command_category": "image_load", "exit_status": 1},
        }
    )
    assert projected == {
        "fixed_command_failure": {"command_category": "image_load", "exit_status": 1},
        "host_receipt_id": "a" * 32,
    }

    private_value = "synthetic-secret-argv-value"
    rejected = controller._safe_host_failure_details(
        {
            "status": "error",
            "code": "fixed_command_failed",
            "receipt_id": "not-a-receipt-id",
            "failure": {
                "command_category": "image_load",
                "exit_status": 1,
                "argv": [private_value],
            },
        }
    )
    assert rejected is None
    assert private_value not in json.dumps(rejected)


@pytest.mark.parametrize(
    "category",
    (
        "fixture_seed",
        "fixture_verify_backup",
        "fixture_restore_guard",
        "fixture_marker",
        "fixture_snapshot",
        "volume_inspect",
        "volume_list",
        "volume_remove",
    ),
)
def test_controller_projects_closed_command_and_cleanup_failure_categories(
    category: str,
) -> None:
    projected = controller._safe_host_failure_details(
        {
            "status": "error",
            "code": "fixed_command_failed",
            "failure": {"command_category": category, "exit_status": 23},
            "cleanup_failure": "asset_cleanup_unverified",
        }
    )
    assert projected == {
        "fixed_command_failure": {
            "command_category": category,
            "exit_status": 23,
        },
        "cleanup_failure": "asset_cleanup_unverified",
    }
    rejected = controller._safe_host_failure_details(
        {
            "status": "error",
            "code": "fixed_command_failed",
            "failure": {"command_category": category, "exit_status": 23},
            "cleanup_failure": "synthetic-private-path",
        }
    )
    assert rejected == {
        "fixed_command_failure": {
            "command_category": category,
            "exit_status": 23,
        }
    }


def test_record_cleanup_failure_preserves_first_closed_category() -> None:
    primary = host_helper.RehearsalError("primary_operation_failed")

    host_helper._record_cleanup_failure(primary, "container_removal_unverified")
    host_helper._record_cleanup_failure(primary, "asset_cleanup_unverified")

    assert primary.cleanup_failure == "container_removal_unverified"


def test_host_main_preserves_primary_details_and_first_cleanup_failure(
    monkeypatch,
) -> None:
    revision = "a" * 40
    primary = host_helper.RehearsalError(
        "fixed_command_failed",
        details={"command_category": "fixture_seed", "exit_status": 23},
    )
    host_helper._record_cleanup_failure(primary, "container_removal_unverified")

    def fail_run(_payload: dict[str, object]) -> dict[str, object]:
        raise primary

    def fail_asset_cleanup(_revision: str) -> dict[str, object]:
        raise host_helper.RehearsalError("cleanup_asset_unavailable")

    output_stream = SimpleNamespace(buffer=io.BytesIO())
    monkeypatch.setattr(host_helper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"{}")))
    monkeypatch.setattr(sys, "stdout", output_stream)
    monkeypatch.setattr(
        host_helper,
        "_parse_request",
        lambda _raw: ("rehearse_pr_pair", {"reviewed_head_sha": revision}),
    )
    monkeypatch.setattr(host_helper, "_prepare_host_paths", lambda: None)
    monkeypatch.setattr(host_helper, "_operation_locks", lambda **_kwargs: [])
    monkeypatch.setattr(host_helper, "_run_pair", fail_run)
    monkeypatch.setattr(host_helper, "_cleanup_assets", fail_asset_cleanup)

    assert host_helper.main() == 0
    assert json.loads(output_stream.buffer.getvalue()) == {
        "status": "error",
        "code": "fixed_command_failed",
        "failure": {"command_category": "fixture_seed", "exit_status": 23},
        "cleanup_failure": "container_removal_unverified",
    }


def test_host_main_returns_error_when_success_cleanup_fails(monkeypatch) -> None:
    revision = "a" * 40

    def pass_run(_payload: dict[str, object]) -> dict[str, object]:
        return {"status": "pass"}

    def fail_asset_cleanup(_revision: str) -> dict[str, object]:
        raise host_helper.RehearsalError("cleanup_asset_unavailable")

    output_stream = SimpleNamespace(buffer=io.BytesIO())
    monkeypatch.setattr(host_helper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"{}")))
    monkeypatch.setattr(sys, "stdout", output_stream)
    monkeypatch.setattr(
        host_helper,
        "_parse_request",
        lambda _raw: ("rehearse_pr_pair", {"reviewed_head_sha": revision}),
    )
    monkeypatch.setattr(host_helper, "_prepare_host_paths", lambda: None)
    monkeypatch.setattr(host_helper, "_operation_locks", lambda **_kwargs: [])
    monkeypatch.setattr(host_helper, "_run_pair", pass_run)
    monkeypatch.setattr(host_helper, "_cleanup_assets", fail_asset_cleanup)

    assert host_helper.main() == 0
    assert json.loads(output_stream.buffer.getvalue()) == {
        "status": "error",
        "code": "asset_cleanup_unverified",
    }


def test_controller_rejects_removed_generic_fixture_category() -> None:
    assert (
        controller._safe_fixed_command_failure(
            {"command_category": "container_fixture", "exit_status": 23}
        )
        is None
    )


def test_asset_cleanup_failure_preserves_primary_error_and_fails_closed(
    monkeypatch,
) -> None:
    revision = "a" * 40

    def fail_cleanup(_revision: str) -> dict[str, object]:
        raise host_helper.RehearsalError("cleanup_asset_unavailable")

    monkeypatch.setattr(host_helper, "_cleanup_assets", fail_cleanup)
    primary = host_helper.RehearsalError("historical_backup_verification_failed")

    host_helper._cleanup_assets_preserving_primary(revision, primary)

    assert primary.code == "historical_backup_verification_failed"
    assert primary.cleanup_failure == "asset_cleanup_unverified"
    with pytest.raises(host_helper.RehearsalError, match="asset_cleanup_unverified"):
        host_helper._cleanup_assets_preserving_primary(revision)


def test_controller_host_failure_projection_preserves_native_details() -> None:
    projected = controller._safe_host_failure_details(
        {
            "status": "error",
            "code": "native_workload_incomplete",
            "receipt_id": "b" * 32,
            "failure": {
                "failure_stage": "owner_evidence_and_isolation",
                "missing_conditions": ["owner1_answer_empty"],
            },
        }
    )
    assert projected == {
        "failure": {
            "failure_stage": "owner_evidence_and_isolation",
            "missing_conditions": ["owner1_answer_empty"],
        },
        "host_receipt_id": "b" * 32,
    }


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
            auth_session_secret="synthetic-auth-session-secret-for-unit-test-only",  # noqa: S106
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


def test_rehearsal_environment_uses_the_pair_session_secret_in_a_private_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "private"
    monkeypatch.setattr(host_helper, "TEMP_ROOT", private_root)
    secret = "synthetic-pair-session-secret-for-environment-test-only"  # noqa: S105

    env_path = host_helper._write_environment(
        assistant_enabled=False,
        auth_session_secret=secret,
    )

    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
    assert "STOCK_PROBS_AUTH_SESSION_SECRET=" + secret + "\n" in env_path.read_text()
    assert env_path.parent == private_root


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


def _controller_native_evidence() -> dict[str, object]:
    return {
        "candidate_disabled_seed_verified": True,
        "candidate_enabled_readiness_verified": True,
        "native_workload_verified": True,
        "native_model_id": "openai/gpt-6.1-sol",
        "mcp_workspace_summary_calls": 2,
        "native_search_source_count": 8,
        "simultaneous_two_owner_turns": True,
        "ownership_isolation_verified": True,
    }


def test_controller_requires_actual_enabled_candidate_native_evidence() -> None:
    evidence = controller._validated_native_evidence(_controller_native_evidence())

    assert evidence == _controller_native_evidence()


def test_common_host_response_preserves_v1_and_strictly_binds_v2_v3_identity() -> None:
    response: dict[str, object] = {
        "reviewed_head_sha": "a" * 40,
        "pair_manifest_sha256": "b" * 64,
        "candidate_image_id": "sha256:" + "c" * 64,
        "recovery_image_id": "sha256:" + "d" * 64,
        "same_disposable_volume": True,
        "production_mutation": False,
        "candidate_container_removed": True,
        "recovery_container_removed": True,
        "volume_removed": True,
        "images_retained": True,
        "architecture": "x86_64",
    }
    common = {
        "reviewed_head_sha": "a" * 40,
        "reviewed_pr_head_sha": None,
        "pair_manifest_sha256": "b" * 64,
        "candidate_image_id": "sha256:" + "c" * 64,
        "recovery_image_id": "sha256:" + "d" * 64,
    }

    controller._validate_common_host_response(response, format_version=1, **common)

    v2 = {
        **response,
        "contract": controller.HOTFIX_CONTRACT,
        "candidate_revision": controller.HOTFIX_CANDIDATE_REVISION,
        "candidate_source_context_sha256": controller.HOTFIX_CANDIDATE_CONTEXT_SHA256,
        "candidate_build_receipt_sha256": controller.HOTFIX_BUILD_RECEIPT_SHA256,
    }
    controller._validate_common_host_response(v2, format_version=2, **common)

    v3 = {
        **response,
        "contract": controller.HOTFIX_V3_CONTRACT,
        "candidate_revision": controller.HOTFIX_V3_IMAGE_SOURCE_REVISION,
        "candidate_source_context_sha256": controller.HOTFIX_V3_IMAGE_CONTEXT_SHA256,
        "candidate_build_receipt_sha256": controller.HOTFIX_V3_BUILD_RECEIPT_SHA256,
        "reviewed_pr_head_sha": controller.HOTFIX_V3_REVIEWED_PR_HEAD_SHA,
        "reviewed_pr_lineage_verified": True,
    }
    controller._validate_common_host_response(
        v3,
        format_version=3,
        **{**common, "reviewed_pr_head_sha": controller.HOTFIX_V3_REVIEWED_PR_HEAD_SHA},
    )
    with pytest.raises(controller.RehearsalError, match="host_response_invalid"):
        controller._validate_common_host_response(
            {**v3, "reviewed_pr_head_sha": "e" * 40},
            format_version=3,
            **{**common, "reviewed_pr_head_sha": "e" * 40},
        )
    with pytest.raises(controller.RehearsalError, match="host_response_invalid"):
        controller._validate_common_host_response(
            response,
            format_version=3,
            **{**common, "reviewed_pr_head_sha": controller.HOTFIX_V3_REVIEWED_PR_HEAD_SHA},
        )


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("candidate_disabled_seed_verified", False),
        ("candidate_enabled_readiness_verified", False),
        ("native_workload_verified", False),
        ("native_model_id", "openai/"),
        ("mcp_workspace_summary_calls", True),
        ("mcp_workspace_summary_calls", 1),
        ("native_search_source_count", True),
        ("native_search_source_count", 0),
        ("simultaneous_two_owner_turns", False),
        ("ownership_isolation_verified", False),
    ],
)
def test_controller_rejects_missing_or_malformed_native_acceptance(
    field: str,
    invalid: object,
) -> None:
    response = _controller_native_evidence()
    response[field] = invalid

    with pytest.raises(controller.RehearsalError, match="host_response_invalid"):
        controller._validated_native_evidence(response)


def test_v2_controller_projects_only_verified_native_and_resource_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed_head = "a" * 40
    pair_digest = "b" * 64
    config = controller.RehearsalConfig(
        Path("/unused/operator-key"),
        Path("/unused/known-hosts"),
        reviewed_head,
        pair_digest,
    )
    candidate_archive = b"candidate-oci-archive"
    recovery_archive = b"previous-production-oci-archive"
    manifest = _host_hotfix_manifest(reviewed_head, candidate_archive, recovery_archive)
    response: dict[str, object] = {
        "status": "pass",
        "contract": controller.HOTFIX_CONTRACT,
        "reviewed_head_sha": reviewed_head,
        "pair_manifest_sha256": pair_digest,
        "candidate_image_id": controller.HOTFIX_CANDIDATE_IMAGE_ID,
        "candidate_revision": controller.HOTFIX_CANDIDATE_REVISION,
        "candidate_source_context_sha256": controller.HOTFIX_CANDIDATE_CONTEXT_SHA256,
        "candidate_build_receipt_sha256": controller.HOTFIX_BUILD_RECEIPT_SHA256,
        "recovery_image_id": controller.PRODUCTION_BASELINE["image_id"],
        "same_disposable_volume": True,
        "production_mutation": False,
        "candidate_container_removed": True,
        "recovery_container_removed": True,
        "volume_removed": True,
        "images_retained": True,
        "architecture": "x86_64",
        "schema13_same_schema_verified": True,
        "migration_commands_executed": 0,
        "restore_commands_executed": 0,
        "post_start_write_preserved": True,
        "schema_after_recovery": 13,
        "production_assistant_enabled": False,
        "production_assistant_disabled_maintenance_verified": True,
        "recovery_process_isolation_verified": True,
        "production_baseline": dict(controller.PRODUCTION_BASELINE),
    }
    response.update(_controller_resource_evidence())
    response.update(_controller_native_evidence())

    monkeypatch.setattr(
        controller.RehearsalConfig,
        "from_env",
        classmethod(lambda _cls: config),
    )
    monkeypatch.setattr(
        controller,
        "_artifact_pair",
        lambda *_args, **_kwargs: (manifest, {"candidate": candidate_archive}),
    )
    monkeypatch.setattr(controller, "_verify_local_helper_checkout", lambda _head: None)
    monkeypatch.setattr(
        controller,
        "verify_helper_source_pull_request",
        lambda _head: {"head_sha": reviewed_head},
    )

    def verify_candidate_pull_request(
        reviewed_pr_head_sha: str | None = None,
    ) -> dict[str, str]:
        assert reviewed_pr_head_sha is None
        return {"head_sha": controller.HOTFIX_CANDIDATE_REVISION}

    monkeypatch.setattr(controller, "verify_hotfix_pull_request", verify_candidate_pull_request)
    monkeypatch.setattr(controller, "_source_bundle", lambda **_kwargs: ({"bootstrap": b"x"}, {}))
    monkeypatch.setattr(controller, "_ensure_incoming_directories", lambda _config: None)
    monkeypatch.setattr(controller, "_stage_source_bundle", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(controller, "_stage_assets", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        controller,
        "_run_fixed",
        lambda *_args, **_kwargs: json.dumps(response).encode("utf-8"),
    )

    result = controller.rehearse_pr_pair(
        reviewed_head_sha=reviewed_head,
        candidate_image_id=controller.HOTFIX_CANDIDATE_IMAGE_ID,
        candidate_source_context_sha256=controller.HOTFIX_CANDIDATE_CONTEXT_SHA256,
        recovery_image_id=controller.PRODUCTION_BASELINE["image_id"],
        recovery_source_context_sha256=controller.HOTFIX_RECOVERY_CONTEXT_SHA256,
        recovery_overlay_sha256=controller.HOTFIX_EMPTY_OVERLAY_SHA256,
        pair_manifest_sha256=pair_digest,
    )

    host_receipt = result["host_receipt"]
    assert isinstance(host_receipt, dict)
    assert host_receipt["production_assistant_enabled"] is False
    assert host_receipt["production_assistant_disabled_maintenance_verified"] is True
    assert host_receipt["candidate_disabled_seed_verified"] is True
    assert host_receipt["candidate_enabled_readiness_verified"] is True
    assert host_receipt["native_workload_verified"] is True
    assert host_receipt["native_model_id"] == "openai/gpt-6.1-sol"
    assert host_receipt["mcp_workspace_summary_calls"] == 2
    assert host_receipt["native_search_source_count"] == 8
    assert host_receipt["candidate_cpu_stat_evidence"]["baseline"]["usage_usec"] == 100


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


def test_hotfix_production_guard_requires_ready_disabled_loopback_maintenance_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = dict(host_helper.PRODUCTION_BASELINE)
    monkeypatch.setattr(host_helper, "HOTFIX_OPERATION_ACTIVE", True)
    monkeypatch.setattr(host_helper, "ACTIVE_PRODUCTION_BASELINE", baseline)
    monkeypatch.setattr(host_helper, "_memavailable_kib", lambda: host_helper.START_RESERVE_KIB)
    monkeypatch.setattr(host_helper, "_production_identity", lambda: baseline)
    monkeypatch.setattr(
        host_helper,
        "_readiness",
        lambda: {
            "status": "ready",
            "schema_version": 13,
            "assistant": {"enabled": False, "status": "disabled"},
        },
    )
    monkeypatch.setattr(host_helper, "_production_loopback_matches", lambda: True)
    samples = [0]

    assert host_helper._check_production(samples, startup=True) == host_helper.START_RESERVE_KIB
    assert samples == [1]


@pytest.mark.parametrize(
    ("assistant", "loopback"),
    [
        ({"enabled": False, "status": "ready"}, True),
        ({"enabled": True, "status": "disabled"}, True),
        ({"enabled": True, "status": "ready"}, False),
    ],
)
def test_hotfix_production_guard_fails_closed_on_assistant_or_loopback_change(
    monkeypatch: pytest.MonkeyPatch,
    assistant: dict[str, object],
    loopback: bool,
) -> None:
    baseline = dict(host_helper.PRODUCTION_BASELINE)
    monkeypatch.setattr(host_helper, "HOTFIX_OPERATION_ACTIVE", True)
    monkeypatch.setattr(host_helper, "ACTIVE_PRODUCTION_BASELINE", baseline)
    monkeypatch.setattr(host_helper, "_memavailable_kib", lambda: host_helper.START_RESERVE_KIB)
    monkeypatch.setattr(host_helper, "_production_identity", lambda: baseline)
    monkeypatch.setattr(
        host_helper,
        "_readiness",
        lambda: {"status": "ready", "schema_version": 13, "assistant": assistant},
    )
    monkeypatch.setattr(host_helper, "_production_loopback_matches", lambda: loopback)
    samples = [0]

    with pytest.raises(host_helper.RehearsalError, match="hotfix_production_boundary_changed"):
        host_helper._check_production(samples, startup=True)
    assert samples == [0]


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


def test_native_failure_projection_preserves_bounded_top_level_diagnostics() -> None:
    private_sentinel = "PRIVATE_COOKIE_SENTINEL"
    raw = {
        "failure_stage": "admin_step_up",
        "missing_conditions": [],
        "safe_error_code": "native_driver_failed",
        "http_status": 503,
        "response_body": private_sentinel,
    }

    host_projection = host_helper._native_failure_projection(raw)
    public_projection = controller._safe_native_failure(host_projection)

    expected = {
        "failure_stage": "admin_step_up",
        "missing_conditions": [],
        "safe_error_code": "native_driver_failed",
        "http_status": 503,
    }
    assert host_projection == expected
    assert public_projection == expected
    assert controller._safe_host_failure_details(
        {
            "status": "error",
            "code": "native_workload_incomplete",
            "failure": host_projection,
        }
    ) == {"failure": expected}
    assert private_sentinel not in json.dumps(host_projection)
    assert private_sentinel not in json.dumps(public_projection)


def test_native_failure_projection_keeps_legacy_receipts_without_optional_diagnostics() -> None:
    legacy = {"failure_stage": "admin_step_up", "missing_conditions": []}

    host_projection = host_helper._native_failure_projection(legacy)

    assert host_projection == legacy
    assert controller._safe_native_failure(host_projection) == legacy
    future_code = "future_native_driver_error_17"
    assert controller._safe_native_failure({**legacy, "safe_error_code": future_code}) == {
        **legacy,
        "safe_error_code": future_code,
    }


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("safe_error_code", "Native-Driver-Failed"),
        ("safe_error_code", 503),
        ("http_status", True),
        ("http_status", 99),
        ("http_status", 600),
    ],
)
def test_native_failure_projection_rejects_malformed_top_level_diagnostics(
    field: str, invalid_value: object
) -> None:
    raw = {"failure_stage": "admin_step_up", "missing_conditions": [], field: invalid_value}

    with pytest.raises(host_helper.RehearsalError, match="native_failure_diagnostic_invalid"):
        host_helper._native_failure_projection(raw)
    assert controller._safe_native_failure(raw) is None


def test_native_failure_projection_rejects_private_error_text_without_echoing_it() -> None:
    private_sentinel = "private prompt and cookie must not be returned"
    raw = {
        "failure_stage": "admin_step_up",
        "missing_conditions": [],
        "safe_error_code": private_sentinel,
    }

    with pytest.raises(host_helper.RehearsalError) as failure:
        host_helper._native_failure_projection(raw)
    public_projection = controller._safe_native_failure(raw)

    assert private_sentinel not in str(failure.value)
    assert public_projection is None
    assert private_sentinel not in json.dumps(public_projection)


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


def _write_oci_archive(
    path: Path,
    *,
    descriptor_overrides: dict[str, object] | None = None,
    additional_descriptors: list[dict[str, object]] | None = None,
    docker_manifest_overrides: dict[str, object] | None = None,
) -> str:
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
    docker_descriptor = {
        "Config": f"blobs/sha256/{config_digest}",
        "RepoTags": None,
        "Layers": [f"blobs/sha256/{layer_digest}"],
    }
    docker_descriptor.update(docker_manifest_overrides or {})
    docker_manifest = [docker_descriptor]
    index_descriptor = {
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "digest": image_id,
        "size": len(image_manifest),
    }
    index_descriptor.update(descriptor_overrides or {})
    index = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [index_descriptor, *(additional_descriptors or [])],
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


@pytest.mark.parametrize(
    "descriptor_overrides",
    (
        {},
        {"annotations": {"org.opencontainers.image.created": "2025-09-15T00:00:00Z"}},
        {"annotations": {"org.opencontainers.image.created": "2025-09-15T00:00:00.123456789Z"}},
    ),
)
def test_archive_scanner_accepts_optional_bounded_oci_created_annotation(
    tmp_path: Path, descriptor_overrides: dict[str, object]
) -> None:
    archive = tmp_path / "oci-created-annotation.tar.gz"
    image_id = _write_oci_archive(archive, descriptor_overrides=descriptor_overrides)

    host_helper._verify_archive_manifest(archive, image_id)


@pytest.mark.parametrize(
    "descriptor_overrides",
    (
        {"annotations": None},
        {"annotations": []},
        {"annotations": "org.opencontainers.image.created=2025-09-15T00:00:00Z"},
        {"annotations": {"org.opencontainers.image.created": None}},
        {"annotations": {"org.opencontainers.image.created": 1757894400}},
        {"annotations": {"org.opencontainers.image.created": "2025-02-30T00:00:00Z"}},
        {"annotations": {"org.opencontainers.image.created": "2025-09-15T00:00:00+00:00"}},
        {"annotations": {"org.opencontainers.image.created": "2025-09-15T00:00:00.1234567890Z"}},
        {"annotations": {"org.opencontainers.image.created": "https://example.test/image"}},
        {
            "annotations": {
                "org.opencontainers.image.created": "2025-09-15T00:00:00Z",
                "org.opencontainers.image.url": "https://example.test/image",
            }
        },
        {
            "annotations": {
                "org.opencontainers.image.created": "2025-09-15T00:00:00Z",
                "com.example.command": "sh -c id",
            }
        },
        {
            "annotations": {
                "org.opencontainers.image.created": "2025-09-15T00:00:00Z",
                "org.opencontainers.image.ref.name": "latest",
            }
        },
        {"url": "https://example.test/image"},
        {"command": "sh -c id"},
    ),
)
def test_archive_scanner_rejects_unapproved_oci_index_annotations_and_fields(
    tmp_path: Path, descriptor_overrides: dict[str, object]
) -> None:
    archive = tmp_path / "oci-invalid-annotation.tar.gz"
    image_id = _write_oci_archive(archive, descriptor_overrides=descriptor_overrides)

    with pytest.raises(host_helper.RehearsalError, match="image_archive_identity_mismatch"):
        host_helper._verify_archive_manifest(archive, image_id)


@pytest.mark.parametrize(
    "descriptor_overrides",
    (
        {"digest": "sha256:" + "f" * 64},
        {"mediaType": "application/vnd.docker.distribution.manifest.v2+json"},
        {"size": 0},
        {"size": True},
    ),
)
def test_archive_scanner_keeps_oci_index_descriptor_identity_exact(
    tmp_path: Path, descriptor_overrides: dict[str, object]
) -> None:
    archive = tmp_path / "oci-invalid-descriptor-reference.tar.gz"
    image_id = _write_oci_archive(archive, descriptor_overrides=descriptor_overrides)

    with pytest.raises(host_helper.RehearsalError, match="image_archive_identity_mismatch"):
        host_helper._verify_archive_manifest(archive, image_id)


def test_archive_scanner_rejects_multiple_oci_index_references(tmp_path: Path) -> None:
    archive = tmp_path / "oci-multiple-descriptors.tar.gz"
    image_id = _write_oci_archive(
        archive,
        additional_descriptors=[
            {
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "digest": "sha256:" + "a" * 64,
                "size": 1,
            }
        ],
    )
    with pytest.raises(host_helper.RehearsalError, match="image_archive_identity_mismatch"):
        host_helper._verify_archive_manifest(archive, image_id)


def test_archive_scanner_rejects_changed_oci_manifest_references(tmp_path: Path) -> None:
    for name, overrides in (
        ("config", {"Config": "blobs/sha256/" + "0" * 64}),
        ("layer", {"Layers": ["blobs/sha256/" + "0" * 64]}),
    ):
        archive = tmp_path / f"oci-invalid-{name}-reference.tar.gz"
        image_id = _write_oci_archive(archive, docker_manifest_overrides=overrides)
        with pytest.raises(host_helper.RehearsalError, match="image_archive_identity_mismatch"):
            host_helper._verify_archive_manifest(archive, image_id)


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


def test_live_candidate_baseline_stays_separate_from_schema12_pair_seed(monkeypatch) -> None:
    baseline = host_helper.PRODUCTION_BASELINE
    assert baseline == controller.PRODUCTION_BASELINE
    assert baseline == {
        "revision": "5ad2c3fddfce5a5a631b72cd832a53f24757c44a",
        "image_id": "sha256:78746f600815cac1941a9060f91bba41aca08f363714db466200c2d77e8ad7b1",
        "schema_version": 13,
    }
    assert host_helper.BASE_REVISION == "da2764e8477698fa7d686be93a4711e35478e802"
    assert host_helper.BASE_IMAGE_ID == (
        "sha256:d3e21ae9de800f0151c1eba74fb3d16423e1171985c33ea03057acbfe2278ec1"
    )
    assert controller.DEPLOYED_BASELINE == {
        "revision": host_helper.BASE_REVISION,
        "image_id": host_helper.BASE_IMAGE_ID,
        "archive_sha256": host_helper.BASE_ARCHIVE_SHA256,
    }
    monkeypatch.setattr(
        host_helper, "_readiness", lambda: {"status": "ready", "schema_version": 13}
    )
    _mock_production_docker_identity(monkeypatch, baseline)
    assert host_helper._production_container() == baseline


def _mock_production_docker_identity(
    monkeypatch,
    identity: dict[str, object],
    *,
    port_bindings: dict[str, object] | None = None,
) -> None:
    container_id = "a" * 64

    def run(command, **kwargs):
        assert kwargs.get("monitor_production") is False
        if command[1] == "ps":
            output = container_id
        elif command[3] == "{{json .HostConfig.PortBindings}}":
            output = json.dumps(
                port_bindings
                if port_bindings is not None
                else {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8000"}]}
            )
        else:
            output = f"{identity['image_id']}|running|{identity['revision']}"
        return CompletedProcess(command, 0, output.encode(), b"")

    monkeypatch.setattr(host_helper, "_run", run)


def test_recovery_baseline_requires_registered_image_record_and_loopback(monkeypatch) -> None:
    baseline = host_helper.RECOVERY_PRODUCTION_BASELINE
    monkeypatch.setattr(host_helper, "_recovery_record_matches", lambda: True)
    monkeypatch.setattr(
        host_helper,
        "_readiness",
        lambda: {
            "status": "ready",
            "schema_version": 13,
            "assistant": {"enabled": False, "status": "disabled"},
        },
    )
    _mock_production_docker_identity(monkeypatch, baseline)

    observed = host_helper._production_container()

    assert {key: observed[key] for key in baseline} == baseline
    assert observed["container_id"] == "a" * 64
    assert observed["container_revision"] == baseline["revision"]


@pytest.mark.parametrize(
    "port_bindings",
    [
        {"8000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8000"}]},  # noqa: S104
        {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8000"}], "9000/tcp": []},
    ],
)
def test_recovery_baseline_rejects_non_loopback_or_extra_port_bindings(monkeypatch, port_bindings):
    monkeypatch.setattr(host_helper, "_recovery_record_matches", lambda: True)
    _mock_production_docker_identity(
        monkeypatch, host_helper.RECOVERY_PRODUCTION_BASELINE, port_bindings=port_bindings
    )
    with pytest.raises(host_helper.RehearsalError, match="production_baseline_mismatch"):
        host_helper._production_identity()


@pytest.mark.parametrize(
    "assistant",
    [
        {"enabled": True, "status": "ready"},
        {"enabled": False, "status": "starting"},
        {"enabled": 0, "status": "disabled"},
    ],
)
def test_recovery_baseline_requires_ready_disabled_assistant(monkeypatch, assistant):
    monkeypatch.setattr(host_helper, "_recovery_record_matches", lambda: True)
    _mock_production_docker_identity(monkeypatch, host_helper.RECOVERY_PRODUCTION_BASELINE)
    monkeypatch.setattr(
        host_helper,
        "_readiness",
        lambda: {"status": "ready", "schema_version": 13, "assistant": assistant},
    )
    with pytest.raises(host_helper.RehearsalError, match="production_health_unavailable"):
        host_helper._production_container()


@pytest.mark.parametrize(
    "observed",
    [
        dict(host_helper.RECOVERY_PRODUCTION_BASELINE)
        | {
            "container_id": "b" * 64,
            "container_revision": "5ad2c3fddfce5a5a631b72cd832a53f24757c44a",
        },
        dict(host_helper.PRODUCTION_BASELINE),
    ],
)
def test_recurring_production_guard_rejects_baseline_change(monkeypatch, observed):
    active_baseline = dict(host_helper.RECOVERY_PRODUCTION_BASELINE) | {
        "container_id": "a" * 64,
        "container_revision": host_helper.RECOVERY_PRODUCTION_BASELINE["revision"],
    }
    monkeypatch.setattr(host_helper, "ACTIVE_PRODUCTION_BASELINE", active_baseline)
    monkeypatch.setattr(host_helper, "_production_identity", lambda: observed)
    monkeypatch.setattr(host_helper, "_memavailable_kib", lambda: host_helper.START_RESERVE_KIB)
    samples = [0]
    with pytest.raises(host_helper.RehearsalError, match="production_baseline_mismatch"):
        host_helper._check_production(samples, startup=True)
    assert samples == [0]


def test_recovery_release_record_is_exact_and_compose_digest_bound(
    tmp_path: Path, monkeypatch
) -> None:
    baseline = host_helper.RECOVERY_PRODUCTION_BASELINE
    revision = baseline["revision"]
    record = {
        "transport": "github_release",
        "release_role": "recovery",
        "revision": revision,
        "image_ref": f"signal-ledger:recovery-sha-{revision}",
        "image_digest": baseline["archive_sha256"],
        "archive_sha256": baseline["archive_sha256"],
        "image_id": baseline["image_id"],
        "archive_size": 103190644,
        "platform": "linux/amd64",
        "assistant_rollout_mode": "disabled",
        "pair_manifest_sha256": baseline["pair_manifest_sha256"],
        "migration_sha256": baseline["migration_sha256"],
        "recovery_image_ref": f"signal-ledger:recovery-sha-{revision}",
        "recovery_image_id": baseline["image_id"],
        "recovery_archive_sha256": baseline["archive_sha256"],
        "recovery_archive_size": 103190644,
        "recovery_platform": "linux/amd64",
        "recovery_schema_version": 13,
        "recovery_base_revision": host_helper.BASE_REVISION,
        "recovery_overlay_sha256": baseline["recovery_overlay_sha256"],
        "compose_digest": baseline["compose_digest"],
        "source_context_sha256": "9f2abef917d4832783d32cfbf31290cc50df76c942b4238aa7f1330d4bc4f7bb",
        "candidate_image_id": host_helper.PRODUCTION_BASELINE["image_id"],
        "candidate_archive_sha256": (
            "99b198f169958e63a4b1ee2380fa805c82a3bc75352d17f8feae2e4ad41185e5"
        ),
        "schema_version": 13,
    }
    release_root = tmp_path / "releases"
    release_root.mkdir(mode=0o700)
    record_path = tmp_path / "current.json"
    record_path.write_text(json.dumps(record), encoding="utf-8")
    record_path.chmod(0o600)
    compose_path = release_root / f"{revision}.compose.yaml"
    compose_path.write_bytes(b"bound recovery compose")
    compose_path.chmod(0o600)
    real_sha256 = host_helper.hashlib.sha256

    class ExpectedComposeDigest:
        def hexdigest(self) -> str:
            return baseline["compose_digest"]

    monkeypatch.setattr(host_helper, "PRODUCTION_CURRENT_RECORD", record_path)
    monkeypatch.setattr(host_helper, "PRODUCTION_RELEASE_ROOT", release_root)
    monkeypatch.setattr(
        host_helper,
        "_production_release_value",
        lambda path, _maximum: path.read_bytes(),
    )

    def sha256(value=b""):
        return ExpectedComposeDigest() if value == b"bound recovery compose" else real_sha256(value)

    monkeypatch.setattr(host_helper.hashlib, "sha256", sha256)
    assert host_helper._recovery_record_matches()

    for field, invalid in (
        ("release_role", "candidate"),
        ("image_id", host_helper.PRODUCTION_BASELINE["image_id"]),
        ("archive_sha256", "0" * 64),
        ("pair_manifest_sha256", "0" * 64),
        ("recovery_overlay_sha256", "0" * 64),
        ("compose_digest", "0" * 64),
        ("assistant_rollout_mode", "invited"),
        ("schema_version", 12),
    ):
        changed = dict(record)
        changed[field] = invalid
        record_path.write_text(json.dumps(changed), encoding="utf-8")
        assert not host_helper._recovery_record_matches(), field

    record_path.write_text(json.dumps(record), encoding="utf-8")
    compose_path.write_bytes(b"stale compose")
    assert not host_helper._recovery_record_matches()


def _recovery_baseline_receipt() -> dict[str, object]:
    return {
        **controller.RECOVERY_PRODUCTION_BASELINE,
        "container_id": "a" * 64,
        "container_revision": controller.RECOVERY_PRODUCTION_BASELINE["revision"],
    }


def _temporary_recovery_documents() -> tuple[
    dict[str, object], dict[str, object], dict[str, object], dict[str, object], bytes
]:
    image_id = "sha256:" + "d" * 64
    archive_sha256 = "f" * 64
    operation_id = "a" * 32
    created_at = "2026-10-15T17:00:00Z"
    manifest: dict[str, object] = {
        "format_version": 1,
        "kind": "temporary_recovery",
        "built_or_published": True,
        "source_revision": host_helper.TEMPORARY_RECOVERY_SOURCE_REVISION,
        "source_manifest_sha256": host_helper.TEMPORARY_RECOVERY_SOURCE_MANIFEST_SHA256,
        "base_revision": host_helper.BASE_REVISION,
        "base_source_archive_sha256": host_helper.TEMPORARY_RECOVERY_BASE_ARCHIVE_SHA256,
        "base_source_context_sha256": host_helper.TEMPORARY_RECOVERY_BASE_CONTEXT_SHA256,
        "source_context_sha256": host_helper.TEMPORARY_RECOVERY_SOURCE_CONTEXT_SHA256,
        "migration_sha256": host_helper.MIGRATION_SHA256,
        "overlay_sha256": host_helper.TEMPORARY_RECOVERY_OVERLAY_SHA256,
        "overlay_files": host_helper.TEMPORARY_RECOVERY_FILE_SHA256,
        "schema_version": 13,
        "image": {
            "archive_sha256": archive_sha256,
            "archive_size": 123_456,
            "image_id": image_id,
            "platform": "linux/amd64",
            "image_revision": host_helper.TEMPORARY_RECOVERY_SOURCE_REVISION,
            "repo_tag": host_helper.TEMPORARY_RECOVERY_IMAGE_BUILD_TAG,
            "entrypoint": ["python", "-m", "stock_probs.recovery_supervisor"],
            "command": host_helper.TEMPORARY_RECOVERY_COMMAND,
        },
    }
    manifest_raw = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
    operation: dict[str, object] = {
        "operation_kind": "temporary_recovery",
        "operation_id": operation_id,
        "phase": "startup_floor_passed",
        "created_at": created_at,
        "updated_at": "2026-10-15T17:01:00Z",
        "manifest_sha256": manifest_sha256,
        "source_manifest_sha256": host_helper.TEMPORARY_RECOVERY_SOURCE_MANIFEST_SHA256,
        "source_revision": host_helper.TEMPORARY_RECOVERY_SOURCE_REVISION,
        "source_context_sha256": host_helper.TEMPORARY_RECOVERY_SOURCE_CONTEXT_SHA256,
        "base_revision": host_helper.BASE_REVISION,
        "migration_sha256": host_helper.MIGRATION_SHA256,
        "overlay_sha256": host_helper.TEMPORARY_RECOVERY_OVERLAY_SHA256,
        "archive_sha256": archive_sha256,
        "archive_size": 123_456,
        "image_id": image_id,
        "build_tag": host_helper.TEMPORARY_RECOVERY_IMAGE_BUILD_TAG,
        "image_ref": f"signal-ledger:temporary-recovery-{operation_id}",
        "schema_version": 13,
        "compose_digest": host_helper.RECOVERY_PRODUCTION_BASELINE["compose_digest"],
        "original_record": {
            "revision": host_helper.PRODUCTION_BASELINE["revision"],
            "image_id": host_helper.PRODUCTION_BASELINE["image_id"],
            "image_ref": f"signal-ledger:sha-{host_helper.PRODUCTION_BASELINE['revision']}",
            "schema_version": 13,
            "assistant_rollout_mode": "invited",
            "compose_digest": host_helper.RECOVERY_PRODUCTION_BASELINE["compose_digest"],
        },
        "original_compose_revision": host_helper.PRODUCTION_BASELINE["revision"],
        "initial_available_kib": 600_000,
        "available_kib": 550_000,
        "backup": {
            "trigger": "pre_deploy",
            "name": "pre-deploy-5ad2c3fddfce5a5a.spbackup",
            "sha256": "c" * 64,
            "schema_version": 13,
            "verified": True,
            "promoted": False,
        },
        "startup_floor_kib": 540_000,
        "start_admission_allowed": True,
    }
    current: dict[str, object] = {
        "operation_kind": "temporary_recovery",
        "operation_id": operation_id,
        "status": "ready",
        "revision": host_helper.TEMPORARY_RECOVERY_SOURCE_REVISION,
        "image_ref": f"signal-ledger:temporary-recovery-{operation_id}",
        "image_digest": archive_sha256,
        "archive_sha256": archive_sha256,
        "archive_size": 123_456,
        "image_id": image_id,
        "transport": "temporary_recovery",
        "platform": "linux/amd64",
        "schema_version": 13,
        "assistant_rollout_mode": "disabled",
        "compose_digest": host_helper.RECOVERY_PRODUCTION_BASELINE["compose_digest"],
        "manifest_sha256": manifest_sha256,
        "source_manifest_sha256": host_helper.TEMPORARY_RECOVERY_SOURCE_MANIFEST_SHA256,
        "source_context_sha256": host_helper.TEMPORARY_RECOVERY_SOURCE_CONTEXT_SHA256,
        "base_revision": host_helper.BASE_REVISION,
        "migration_sha256": host_helper.MIGRATION_SHA256,
        "overlay_sha256": host_helper.TEMPORARY_RECOVERY_OVERLAY_SHA256,
        "started_at": created_at,
    }
    approval: dict[str, object] = {
        "format_version": 1,
        "kind": "temporary_recovery",
        "review_status": "approved",
        "manifest_sha256": manifest_sha256,
    }
    return current, operation, manifest, approval, manifest_raw


def _temporary_recovery_baseline_for_test(
    documents: tuple[
        dict[str, object], dict[str, object], dict[str, object], dict[str, object], bytes
    ],
) -> dict[str, object]:
    current, operation, manifest, approval, manifest_raw = documents
    return host_helper._temporary_recovery_documents_match(
        current,
        operation,
        manifest,
        approval,
        manifest_raw,
        image_id=manifest["image"]["image_id"],  # type: ignore[index]
        image_revision=host_helper.TEMPORARY_RECOVERY_SOURCE_REVISION,
        container_id="b" * 64,
    )


def test_temporary_recovery_baseline_binds_approved_records_and_original_images() -> None:
    baseline = _temporary_recovery_baseline_for_test(_temporary_recovery_documents())

    assert baseline["operation_kind"] == "temporary_recovery"
    assert "role" not in baseline
    assert baseline["phase"] == "startup_floor_passed"
    assert baseline["start_admission_allowed"] is True
    assert baseline["startup_floor_kib"] == 540_000
    assert baseline["image_id"] == "sha256:" + "d" * 64
    assert baseline["container_id"] == "b" * 64
    assert baseline["container_revision"] == host_helper.TEMPORARY_RECOVERY_SOURCE_REVISION
    assert baseline["original_image_id"] == host_helper.PRODUCTION_BASELINE["image_id"]
    assert (
        baseline["protected_recovery_image_id"]
        == host_helper.RECOVERY_PRODUCTION_BASELINE["image_id"]
    )
    assert baseline["protected_recovery_image_ref"] == (
        f"signal-ledger:recovery-sha-{host_helper.RECOVERY_PRODUCTION_BASELINE['revision']}"
    )


@pytest.mark.parametrize(
    ("target", "field", "invalid"),
    [
        ("manifest", "source_revision", "0" * 40),
        ("manifest", "overlay_sha256", "0" * 64),
        ("manifest", "unexpected", "unreviewed"),
        ("manifest_image", "repo_tag", "signal-ledger:temporary-recovery-build-other"),
        ("manifest_image", "image_id", host_helper.PRODUCTION_BASELINE["image_id"]),
        ("approval", "review_status", "pending"),
        ("approval", "manifest_sha256", "0" * 64),
        ("operation", "phase", "temporary_app_ready"),
        ("operation", "start_admission_allowed", 1),
        ("operation", "startup_floor_kib", host_helper.START_RESERVE_KIB - 1),
        ("operation", "source_context_sha256", "0" * 64),
        ("operation", "image_ref", "signal-ledger:sha-5ad"),
        ("operation", "operation_id", "not-an-operation-id"),
        ("operation", "image_id", host_helper.RECOVERY_PRODUCTION_BASELINE["image_id"]),
        ("operation", "archive_size", True),
        ("operation", "original_record.image_id", "sha256:" + "0" * 64),
        ("operation", "backup.verified", False),
        ("operation", "unexpected", "unreviewed"),
        ("current", "status", "starting"),
        ("current", "transport", "github_release"),
        ("current", "schema_version", 12),
        ("current", "unexpected", "unreviewed"),
    ],
)
def test_temporary_recovery_baseline_rejects_record_drift(
    target: str, field: str, invalid: object
) -> None:
    current, operation, manifest, approval, manifest_raw = copy.deepcopy(
        _temporary_recovery_documents()
    )
    record = {
        "manifest": manifest,
        "manifest_image": manifest["image"],
        "approval": approval,
        "operation": operation,
        "current": current,
    }[target]
    target_record = record
    target_field = field
    if "." in field:
        parent, target_field = field.split(".", 1)
        target_record = record[parent]
    target_record[target_field] = invalid
    if target == "manifest" or target == "manifest_image":
        manifest_raw = json.dumps(
            manifest, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        approval["manifest_sha256"] = hashlib.sha256(manifest_raw).hexdigest()
        operation["manifest_sha256"] = approval["manifest_sha256"]
        current["manifest_sha256"] = approval["manifest_sha256"]

    with pytest.raises(host_helper.RehearsalError, match="production_baseline_mismatch"):
        host_helper._temporary_recovery_documents_match(
            current,
            operation,
            manifest,
            approval,
            manifest_raw,
            image_id=manifest["image"]["image_id"],  # type: ignore[index]
            image_revision=host_helper.TEMPORARY_RECOVERY_SOURCE_REVISION,
            container_id="b" * 64,
        )


@pytest.mark.parametrize(
    "raw",
    [b'{"phase":"one","phase":"two"}', b'{"startup_floor_kib":NaN}', b"[]"],
)
def test_temporary_recovery_json_rejects_duplicate_nonfinite_and_nonobject(raw: bytes) -> None:
    with pytest.raises(host_helper.RehearsalError, match="production_baseline_mismatch"):
        host_helper._strict_json_object(raw)


def test_temporary_recovery_reader_rejects_unapproved_paths() -> None:
    with pytest.raises(host_helper.RehearsalError, match="production_baseline_mismatch"):
        host_helper._read_temporary_recovery_json(
            host_helper.PRODUCTION_STATE_ROOT / "unapproved.json", 128
        )


def test_temporary_recovery_identity_requires_approved_image_refs_and_platform(monkeypatch) -> None:
    baseline = _temporary_recovery_baseline_for_test(_temporary_recovery_documents())
    expected_rows = [
        f"{baseline['image_id']}|linux|amd64|{host_helper.TEMPORARY_RECOVERY_SOURCE_REVISION}"
    ] * 3 + [
        f"{host_helper.RECOVERY_PRODUCTION_BASELINE['image_id']}|linux|amd64|"
        f"{host_helper.RECOVERY_PRODUCTION_BASELINE['revision']}"
    ]
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert kwargs["monitor_production"] is False
        return CompletedProcess(command, 0, ("\n".join(expected_rows) + "\n").encode(), b"")

    monkeypatch.setattr(host_helper, "_run", run)
    assert host_helper._temporary_recovery_image_identity_matches(baseline)
    assert commands[0][1:4] == ["image", "inspect", "--format"]
    assert "exec" not in commands[0]

    expected_rows[0] = expected_rows[0].replace("|linux|amd64|", "|linux|arm64|")
    assert not host_helper._temporary_recovery_image_identity_matches(baseline)
    expected_rows[0] = expected_rows[0].replace("|linux|arm64|", "|linux|amd64|")
    expected_rows[2] = expected_rows[2].replace("sha256:" + "d" * 64, "sha256:" + "e" * 64)
    assert not host_helper._temporary_recovery_image_identity_matches(baseline)
    expected_rows[2] = expected_rows[2].replace("sha256:" + "e" * 64, "sha256:" + "d" * 64)
    expected_rows[3] = expected_rows[3].replace(
        host_helper.RECOVERY_PRODUCTION_BASELINE["image_id"], "sha256:" + "e" * 64
    )
    assert not host_helper._temporary_recovery_image_identity_matches(baseline)


def test_temporary_recovery_recurring_guard_rejects_operation_or_manifest_drift(
    monkeypatch,
) -> None:
    baseline = _temporary_recovery_baseline_for_test(_temporary_recovery_documents())
    changed = dict(baseline)
    changed["operation_id"] = "c" * 32
    monkeypatch.setattr(host_helper, "ACTIVE_PRODUCTION_BASELINE", baseline)
    monkeypatch.setattr(host_helper, "_production_identity", lambda: changed)
    monkeypatch.setattr(host_helper, "_memavailable_kib", lambda: host_helper.START_RESERVE_KIB)

    with pytest.raises(host_helper.RehearsalError, match="production_baseline_mismatch"):
        host_helper._check_production([0], startup=True)


def test_temporary_recovery_production_identity_checks_loopback_and_readiness(monkeypatch) -> None:
    documents = _temporary_recovery_documents()
    current, operation, manifest, approval, manifest_raw = documents
    image = manifest["image"]
    records = {
        host_helper.PRODUCTION_CURRENT_RECORD: (current, b"current"),
        host_helper.TEMPORARY_RECOVERY_OPERATION_PATH: (operation, b"operation"),
        host_helper.TEMPORARY_RECOVERY_MANIFEST_PATH: (manifest, manifest_raw),
        host_helper.TEMPORARY_RECOVERY_APPROVAL_PATH: (approval, b"approval"),
    }

    def read_json(path, _maximum):
        return records[path]

    monkeypatch.setattr(host_helper, "_read_temporary_recovery_json", read_json)
    monkeypatch.setattr(
        host_helper, "_temporary_recovery_image_identity_matches", lambda _base: True
    )
    baseline_for_docker = {
        "image_id": image["image_id"],
        "revision": host_helper.TEMPORARY_RECOVERY_SOURCE_REVISION,
    }
    _mock_production_docker_identity(monkeypatch, baseline_for_docker)

    baseline = host_helper._production_identity()
    assert baseline["operation_kind"] == "temporary_recovery"
    assert baseline["operation_id"] == operation["operation_id"]
    assert host_helper._production_readiness_matches(
        baseline,
        {
            "status": "ready",
            "schema_version": 13,
            "assistant": {"enabled": False, "status": "disabled"},
        },
    )
    assert not host_helper._production_readiness_matches(
        baseline,
        {
            "status": "ready",
            "schema_version": 13,
            "assistant": {"enabled": True, "status": "ready"},
        },
    )

    _mock_production_docker_identity(
        monkeypatch,
        baseline_for_docker,
        port_bindings={"8000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8000"}]},  # noqa: S104
    )
    with pytest.raises(host_helper.RehearsalError, match="production_baseline_mismatch"):
        host_helper._production_identity()


def test_mcp_receipt_accepts_candidate_recovery_and_temporary_baselines() -> None:
    assert controller._validated_production_baseline(dict(controller.PRODUCTION_BASELINE)) == (
        controller.PRODUCTION_BASELINE
    )
    recovery = _recovery_baseline_receipt()
    assert controller._validated_production_baseline(recovery) == recovery
    temporary = _temporary_recovery_baseline_for_test(_temporary_recovery_documents())
    assert {
        key: temporary[key] for key in controller.TEMPORARY_RECOVERY_PRODUCTION_BASELINE_FIELDS
    } == controller.TEMPORARY_RECOVERY_PRODUCTION_BASELINE_FIELDS
    assert {
        key: temporary[key] for key in host_helper.TEMPORARY_RECOVERY_PRODUCTION_BASELINE_FIELDS
    } == host_helper.TEMPORARY_RECOVERY_PRODUCTION_BASELINE_FIELDS
    assert controller._validated_production_baseline(temporary) == temporary


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("operation_kind", "recovery"),
        ("phase", "temporary_app_ready"),
        ("start_admission_allowed", False),
        ("source_manifest_sha256", "0" * 64),
        ("source_context_sha256", "0" * 64),
        ("base_revision", "0" * 40),
        ("overlay_sha256", "0" * 64),
        ("schema_version", True),
        ("assistant_enabled", 0),
        ("loopback_only", False),
        ("operation_id", "not-an-operation-id"),
        ("image_id", controller.PRODUCTION_BASELINE["image_id"]),
        ("image_ref", "signal-ledger:sha-5ad"),
        ("archive_sha256", "not-a-digest"),
        ("archive_size", True),
        ("manifest_sha256", "not-a-digest"),
        ("startup_floor_kib", controller.START_RESERVE_KIB - 1),
        ("container_id", "short-id"),
        ("container_revision", controller.PRODUCTION_BASELINE["revision"]),
        ("original_assistant_rollout_mode", "invited-ish"),
        ("original_assistant_rollout_mode", "disabled"),
        ("original_assistant_rollout_mode", "owner_canary"),
    ],
)
def test_mcp_receipt_rejects_malformed_temporary_baseline(field: str, invalid: object) -> None:
    value = _temporary_recovery_baseline_for_test(_temporary_recovery_documents())
    value[field] = invalid
    with pytest.raises(controller.RehearsalError, match="host_response_invalid"):
        controller._validated_production_baseline(value)


def test_mcp_receipt_rejects_unknown_temporary_baseline_field() -> None:
    value = _temporary_recovery_baseline_for_test(_temporary_recovery_documents())
    value["role"] = "recovery"
    with pytest.raises(controller.RehearsalError, match="host_response_invalid"):
        controller._validated_production_baseline(value)


def test_mcp_v2_receipt_accepts_only_exact_temporary_production_baseline() -> None:
    temporary = _temporary_recovery_baseline_for_test(_temporary_recovery_documents())

    assert controller._validated_v2_production_baseline(temporary) == temporary
    assert controller._validated_v2_production_baseline(dict(controller.PRODUCTION_BASELINE)) == (
        controller.PRODUCTION_BASELINE
    )
    with pytest.raises(controller.RehearsalError, match="host_response_invalid"):
        controller._validated_v2_production_baseline(_recovery_baseline_receipt())

    changed = dict(temporary)
    changed["schema_version"] = 12
    with pytest.raises(controller.RehearsalError, match="host_response_invalid"):
        controller._validated_v2_production_baseline(changed)


def test_v2_pair_accepts_fully_validated_temporary_baseline_before_assets(monkeypatch) -> None:
    baseline = _temporary_recovery_baseline_for_test(_temporary_recovery_documents())
    events: list[str] = []

    def verify_installed_source(_revision: str, _pair: str, **kwargs: object) -> dict[str, str]:
        assert kwargs == {"helper_source_contract": host_helper.HOTFIX_CONTRACT}
        events.append("installed_source")
        return {"host_helper.py": "a" * 64}

    def verify_helper_source_pull_request(revision: str) -> None:
        assert revision == "c" * 40
        events.append("helper_pr")

    def verify_hotfix_pull_request(reviewed_pr_head_sha: str | None = None) -> None:
        assert reviewed_pr_head_sha is None
        events.append("candidate_pr")

    monkeypatch.setattr(host_helper, "_verify_installed_source", verify_installed_source)
    monkeypatch.setattr(
        host_helper, "_verify_helper_source_pull_request", verify_helper_source_pull_request
    )
    monkeypatch.setattr(host_helper, "_verify_hotfix_pull_request", verify_hotfix_pull_request)
    monkeypatch.setattr(host_helper, "_production_container", lambda: baseline)
    monkeypatch.setattr(
        host_helper,
        "_readiness",
        lambda: {
            "status": "ready",
            "schema_version": 13,
            "assistant": {"enabled": False, "status": "disabled"},
        },
    )
    monkeypatch.setattr(host_helper, "_production_loopback_matches", lambda: True)

    with pytest.raises(host_helper.RehearsalError, match="candidate_image_id_invalid"):
        host_helper._run_pair_v2(
            {
                "repository": host_helper.REPOSITORY,
                "pull_number": host_helper.HELPER_SOURCE_PR_NUMBER,
                "reviewed_head_sha": "c" * 40,
                "pair_manifest_sha256": "d" * 64,
            }
        )
    assert events == ["installed_source", "helper_pr", "candidate_pr"]


def test_v2_pair_still_rejects_registered_recovery_as_production_baseline(monkeypatch) -> None:
    monkeypatch.setattr(host_helper, "_verify_installed_source", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(host_helper, "_verify_helper_source_pull_request", lambda _revision: None)

    def verify_candidate_pull_request(reviewed_pr_head_sha: str | None = None) -> None:
        assert reviewed_pr_head_sha is None

    monkeypatch.setattr(host_helper, "_verify_hotfix_pull_request", verify_candidate_pull_request)
    monkeypatch.setattr(host_helper, "_production_container", lambda: _recovery_baseline_receipt())

    with pytest.raises(host_helper.RehearsalError, match="hotfix_production_baseline_mismatch"):
        host_helper._run_pair_v2(
            {
                "repository": host_helper.REPOSITORY,
                "pull_number": host_helper.HELPER_SOURCE_PR_NUMBER,
                "reviewed_head_sha": "c" * 40,
                "pair_manifest_sha256": "d" * 64,
            }
        )


def test_hotfix_guard_accepts_validated_temporary_baseline(monkeypatch) -> None:
    baseline = _temporary_recovery_baseline_for_test(_temporary_recovery_documents())
    monkeypatch.setattr(host_helper, "HOTFIX_OPERATION_ACTIVE", True)
    monkeypatch.setattr(host_helper, "ACTIVE_PRODUCTION_BASELINE", baseline)
    monkeypatch.setattr(host_helper, "_memavailable_kib", lambda: host_helper.START_RESERVE_KIB)
    monkeypatch.setattr(host_helper, "_production_identity", lambda: baseline)
    monkeypatch.setattr(
        host_helper,
        "_readiness",
        lambda: {
            "status": "ready",
            "schema_version": 13,
            "assistant": {"enabled": False, "status": "disabled"},
        },
    )
    monkeypatch.setattr(host_helper, "_production_loopback_matches", lambda: True)
    samples = [0]

    assert host_helper._check_production(samples, startup=True) == host_helper.START_RESERVE_KIB
    assert samples == [1]


def test_mcp_receipt_accepts_exact_candidate_and_recovery_production_baselines() -> None:
    assert controller._validated_production_baseline(dict(controller.PRODUCTION_BASELINE)) == (
        controller.PRODUCTION_BASELINE
    )
    recovery = _recovery_baseline_receipt()
    assert controller._validated_production_baseline(recovery) == recovery


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("role", "candidate"),
        ("image_id", controller.PRODUCTION_BASELINE["image_id"]),
        ("archive_sha256", "0" * 64),
        ("pair_manifest_sha256", "0" * 64),
        ("recovery_overlay_sha256", "0" * 64),
        ("compose_digest", "0" * 64),
        ("assistant_rollout_mode", "invited"),
        ("assistant_enabled", True),
        ("assistant_enabled", 0),
        ("assistant_status", "ready"),
        ("loopback_only", False),
        ("schema_version", 12),
        ("container_revision", "0" * 40),
        ("container_id", "short"),
    ],
)
def test_mcp_receipt_rejects_partial_or_mismatched_recovery_baseline(field, invalid) -> None:
    value = _recovery_baseline_receipt()
    value[field] = invalid
    with pytest.raises(controller.RehearsalError, match="host_response_invalid"):
        controller._validated_production_baseline(value)


def test_mcp_receipt_rejects_candidate_role_and_unknown_baseline() -> None:
    candidate = dict(controller.PRODUCTION_BASELINE)
    candidate["role"] = "candidate"
    with pytest.raises(controller.RehearsalError, match="host_response_invalid"):
        controller._validated_production_baseline(candidate)
    with pytest.raises(controller.RehearsalError, match="host_response_invalid"):
        controller._validated_production_baseline({"role": "unknown"})


@pytest.mark.parametrize("monitor_production", [False, True])
def test_identity_subprocess_can_bypass_recurring_health_guard(monkeypatch, monitor_production):
    monkeypatch.setattr(host_helper, "MONITOR_ACTIVE", True)
    monkeypatch.setattr(host_helper, "OPERATION_DEADLINE", None)
    ticks = iter([0.0, 0.0, 6.0, 6.0])
    monkeypatch.setattr(host_helper.time, "monotonic", lambda: next(ticks, 6.0))
    checks = []

    def check(samples):
        checks.append(samples)
        raise host_helper.RehearsalError("nested_health_check")

    monkeypatch.setattr(host_helper, "_check_production", check)
    command = ["/usr/bin/printf", "identity"]
    if monitor_production:
        with pytest.raises(host_helper.RehearsalError, match="nested_health_check"):
            host_helper._run(command, timeout=30, monitor_production=True)
        assert len(checks) == 1
    else:
        result = host_helper._run(command, timeout=30, monitor_production=False)
        assert result.stdout == b"identity"
        assert checks == []


@pytest.mark.parametrize(
    ("phase", "floor"),
    [("preflight", 524288), ("startup", 524288), ("monitor", 131072), ("final", 131072)],
)
def test_memory_reserve_diagnostic_preserves_exact_phase_and_floor(phase, floor):
    error = host_helper._memory_reserve_failure(floor - 1, floor, phase)
    assert error.code == "host_memory_reserve_breached"
    assert controller._safe_host_failure_details(
        {"status": "error", "code": error.code, "failure": error.details}
    ) == {
        "memory_reserve_failure": {
            "memory_reserve_phase": phase,
            "host_memavailable_kib": floor - 1,
            "required_reserve_kib": floor,
        }
    }


@pytest.mark.parametrize(
    "failure",
    [
        {"memory_reserve_phase": "unknown", "host_memavailable_kib": 1, "required_reserve_kib": 2},
        {
            "memory_reserve_phase": "preflight",
            "host_memavailable_kib": 1,
            "required_reserve_kib": 131072,
        },
        {
            "memory_reserve_phase": "monitor",
            "host_memavailable_kib": True,
            "required_reserve_kib": 131072,
        },
        {
            "memory_reserve_phase": "monitor",
            "host_memavailable_kib": 1,
            "required_reserve_kib": 131072,
            "extra": 1,
        },
    ],
)
def test_memory_reserve_diagnostic_rejects_untyped_or_unknown_facts(failure):
    assert controller._safe_memory_reserve_failure(failure) is None
