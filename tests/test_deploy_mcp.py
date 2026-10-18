"""The deployment MCP cannot turn tool arguments into SSH commands."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "deploy_mcp"))

from controller import (  # noqa: E402
    FIREWALL_RESOURCE,
    HOTFIX_CANDIDATE_REVISION,
    HOTFIX_PAIR_CONTRACT,
    HOTFIX_PAIR_CONTRACT_V3,
    HOTFIX_V3_CANDIDATE_REVISION,
    MAX_RESPONSE_BYTES,
    DeployConfig,
    DeployController,
    DeployError,
    _run_bounded_ssh,
    _valid_hotfix_identity,
    _validate_firewall_plan,
)


def _controller(tmp_path: Path) -> DeployController:
    identity = tmp_path / "identity"
    known_hosts = tmp_path / "known_hosts"
    identity.write_text("dummy")
    known_hosts.write_text("dummy")
    identity.chmod(0o600)
    known_hosts.chmod(0o600)
    return DeployController(DeployConfig("example.com", "deploy", identity, known_hosts))


def _next_temporary_recovery_response(
    *,
    prior_id: str = "a" * 32,
    view_sha256: str = "b" * 64,
    record_sha256: str = "d" * 64,
    available_kib: int = 600_000,
) -> dict[str, object]:
    operation_id = hashlib.sha256(
        b"signal-ledger-temporary-recovery-next-cycle-v1\0"
        + prior_id.encode("ascii")
        + b"\0"
        + view_sha256.encode("ascii")
    ).hexdigest()[:32]
    link = {
        "format_version": 1,
        "kind": "temporary_recovery_cycle_link",
        "status": "intent",
        "prior_operation_id": prior_id,
        "prior_record_sha256": record_sha256,
        "prior_view_sha256": view_sha256,
        "new_operation_id": operation_id,
        "history_name": f"closed-{prior_id}-{record_sha256}.json",
        "database_policy": "reuse_schema_13_no_restore",
    }
    link_sha256 = hashlib.sha256(
        json.dumps(link, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    admitted = available_kib >= 512 * 1024
    return {
        "status": "ok",
        "result": (
            "temporary_recovery_ready"
            if admitted
            else "temporary_recovery_ready_startup_floor_unmet"
        ),
        "operation_kind": "temporary_recovery",
        "operation_id": operation_id,
        "source_revision": "63597953c9d1ab387563dadfe705b78a2861a426",
        "image_ref": f"signal-ledger:temporary-recovery-{operation_id}",
        "image_id": "sha256:" + "c" * 64,
        "archive_sha256": "e" * 64,
        "manifest_sha256": "f" * 64,
        "schema_version": 13,
        "assistant_rollout_mode": "disabled",
        "backup": {
            "trigger": "pre_deploy",
            "name": "pre-deploy-5ad2c3fddfce5a5a-01234567.spbackup",
            "sha256": "1" * 64,
            "schema_version": 13,
            "verified": True,
            "promoted": False,
        },
        "available_kib": available_kib,
        "startup_floor_kib": 512 * 1024,
        "start_admission_allowed": admitted,
        "health": {
            "status": "ready",
            "schema_version": 13,
            "assistant": {"enabled": False, "status": "disabled"},
        },
        "prior_operation_id": prior_id,
        "prior_record_sha256": record_sha256,
        "prior_view_sha256": view_sha256,
        "cycle_link_sha256": link_sha256,
        "cycle_link_status": "started",
    }


def test_invalid_revision_rejected_before_ssh(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    with patch("controller.subprocess.run") as run:
        with pytest.raises(DeployError, match="revision_invalid"):
            controller.plan_deploy("main; touch /tmp/x", "c" * 64)
        run.assert_not_called()


def test_ssh_command_is_fixed_and_payload_is_structured(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    response = {
        "status": "ok",
        "revision": "a" * 40,
        "plan_id": "b" * 32,
        "image_digest": "c" * 64,
        "image_ref": "ghcr.io/jtmb/signal-ledger@sha256:" + "c" * 64,
    }
    child = (
        "import json,sys; request=json.load(sys.stdin); "
        "assert request['operation']=='plan_deploy'; "
        "assert request['payload']['revision']=='a'*40; "
        "assert request['payload']['expected_image_digest']=='c'*64; "
        f"sys.stdout.write({json.dumps(json.dumps(response))})"
    )
    real_popen = subprocess.Popen

    def fake_popen(_command: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        return real_popen([sys.executable, "-c", child], **kwargs)

    with patch("controller.subprocess.Popen", side_effect=fake_popen) as popen:
        result = controller.plan_deploy("a" * 40, "c" * 64)
        args, _kwargs = popen.call_args
        assert args[0][-1] == "signal-ledger-deploy-helper"
        assert args[0][-2] == "deploy@example.com"
        assert result["plan_id"] == "b" * 32


def test_release_plan_sends_only_archive_hash_and_image_id(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    revision = "a" * 40
    archive_sha256 = "c" * 64
    image_id = "sha256:" + "d" * 64
    response = {
        "status": "ok",
        "transport": "github_release",
        "revision": revision,
        "plan_id": "b" * 32,
        "archive_sha256": archive_sha256,
        "image_id": image_id,
        "image_ref": f"signal-ledger:sha-{revision}",
        "platform": "linux/amd64",
        "archive_size": 1234,
    }
    expected_payload = {
        "revision": revision,
        "archive_sha256": archive_sha256,
        "image_id": image_id,
    }
    child = (
        "import json,sys; request=json.load(sys.stdin); "
        "assert request['operation']=='plan_deploy'; "
        f"assert request['payload']=={json.dumps(expected_payload)}; "
        f"sys.stdout.write({json.dumps(json.dumps(response))})"
    )
    real_popen = subprocess.Popen

    def fake_popen(_command: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        return real_popen([sys.executable, "-c", child], **kwargs)

    with patch("controller.subprocess.Popen", side_effect=fake_popen):
        result = controller.plan_deploy(revision, archive_sha256, image_id)
    assert result["image_id"] == image_id


def test_schema13_release_plan_carries_pair_hash_and_validates_recovery_identity(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path)
    revision = "a" * 40
    archive_sha256 = "b" * 64
    image_id = "sha256:" + "c" * 64
    pair_sha256 = "d" * 64
    recovery_archive_sha = "e" * 64
    recovery_image_id = "sha256:" + "f" * 64
    response = {
        "status": "ok",
        "transport": "github_release",
        "revision": revision,
        "plan_id": "1" * 32,
        "archive_sha256": archive_sha256,
        "image_id": image_id,
        "image_ref": f"signal-ledger:sha-{revision}",
        "platform": "linux/amd64",
        "archive_size": 1234,
        "pair_manifest_sha256": pair_sha256,
        "recovery_image_id": recovery_image_id,
        "recovery_archive_sha256": recovery_archive_sha,
        "recovery_archive_size": 2345,
        "recovery_platform": "linux/amd64",
        "recovery_schema_version": 13,
    }
    expected_payload = {
        "revision": revision,
        "archive_sha256": archive_sha256,
        "image_id": image_id,
        "pair_manifest_sha256": pair_sha256,
    }
    child = (
        "import json,sys; request=json.load(sys.stdin); "
        "assert request['operation']=='plan_deploy'; "
        f"assert request['payload']=={json.dumps(expected_payload)}; "
        f"sys.stdout.write({json.dumps(json.dumps(response))})"
    )
    real_popen = subprocess.Popen

    def fake_popen(_command: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        return real_popen([sys.executable, "-c", child], **kwargs)

    with patch("controller.subprocess.Popen", side_effect=fake_popen):
        result = controller.plan_deploy(
            revision,
            archive_sha256,
            image_id,
            expected_pair_manifest_sha256=pair_sha256,
        )
    assert result["pair_manifest_sha256"] == pair_sha256
    assert result["recovery_image_id"] == recovery_image_id


def test_hotfix_release_plan_keeps_app_and_helper_source_revisions_distinct(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path)
    revision = "f6a51d5c821e6b1ab7974a94f4ff795da10130bc"
    helper_source_revision = "a" * 40
    archive_sha256 = "b" * 64
    image_id = "sha256:" + "c" * 64
    pair_sha256 = "d" * 64
    response = {
        "status": "ok",
        "transport": "github_release",
        "revision": revision,
        "plan_id": "1" * 32,
        "archive_sha256": archive_sha256,
        "image_id": image_id,
        "image_ref": f"signal-ledger:sha-{revision}",
        "platform": "linux/amd64",
        "archive_size": 1234,
        "pair_manifest_sha256": pair_sha256,
        "recovery_contract": "schema13_same_schema_hotfix_v1",
        "helper_source_revision": helper_source_revision,
        "recovery_image_id": "sha256:" + "e" * 64,
        "recovery_archive_sha256": "f" * 64,
        "recovery_archive_size": 2345,
        "recovery_platform": "linux/amd64",
        "recovery_schema_version": 13,
    }
    expected_payload = {
        "revision": revision,
        "archive_sha256": archive_sha256,
        "image_id": image_id,
        "pair_manifest_sha256": pair_sha256,
    }
    child = (
        "import json,sys; request=json.load(sys.stdin); "
        "assert request['operation']=='plan_deploy'; "
        f"assert request['payload']=={json.dumps(expected_payload)}; "
        f"sys.stdout.write({json.dumps(json.dumps(response))})"
    )
    real_popen = subprocess.Popen

    def fake_popen(_command: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        return real_popen([sys.executable, "-c", child], **kwargs)

    with patch("controller.subprocess.Popen", side_effect=fake_popen):
        result = controller.plan_deploy(
            revision,
            archive_sha256,
            image_id,
            expected_pair_manifest_sha256=pair_sha256,
        )

    assert result["revision"] == revision
    assert result["helper_source_revision"] == helper_source_revision


@pytest.mark.parametrize(
    "source_revision",
    [None, "not-a-commit", "f6a51d5c821e6b1ab7974a94f4ff795da10130bc"],
)
def test_hotfix_release_plan_rejects_missing_or_misbound_helper_source(
    tmp_path: Path,
    source_revision: str | None,
) -> None:
    controller = _controller(tmp_path)
    revision = "f6a51d5c821e6b1ab7974a94f4ff795da10130bc"
    archive_sha256 = "b" * 64
    image_id = "sha256:" + "c" * 64
    pair_sha256 = "d" * 64
    response = {
        "status": "ok",
        "transport": "github_release",
        "revision": revision,
        "plan_id": "1" * 32,
        "archive_sha256": archive_sha256,
        "image_id": image_id,
        "image_ref": f"signal-ledger:sha-{revision}",
        "platform": "linux/amd64",
        "archive_size": 1234,
        "pair_manifest_sha256": pair_sha256,
        "recovery_contract": "schema13_same_schema_hotfix_v1",
        "helper_source_revision": source_revision,
        "recovery_image_id": "sha256:" + "e" * 64,
        "recovery_archive_sha256": "f" * 64,
        "recovery_archive_size": 2345,
        "recovery_platform": "linux/amd64",
        "recovery_schema_version": 13,
    }
    child = (
        "import json,sys; json.load(sys.stdin); "
        f"sys.stdout.write({json.dumps(json.dumps(response))})"
    )
    real_popen = subprocess.Popen

    def fake_popen(_command: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        return real_popen([sys.executable, "-c", child], **kwargs)

    with (
        patch("controller.subprocess.Popen", side_effect=fake_popen),
        pytest.raises(DeployError, match="remote_response_invalid"),
    ):
        controller.plan_deploy(
            revision,
            archive_sha256,
            image_id,
            expected_pair_manifest_sha256=pair_sha256,
        )


def test_release_deploy_requires_matching_archive_and_image_id(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    revision = "a" * 40
    archive_sha256 = "c" * 64
    image_id = "sha256:" + "d" * 64
    response = {
        "status": "ok",
        "transport": "github_release",
        "result": "deployed",
        "plan_id": "b" * 32,
        "revision": revision,
        "archive_sha256": archive_sha256,
        "image_id": image_id,
    }
    expected_payload = {
        "plan_id": "b" * 32,
        "revision": revision,
        "archive_sha256": archive_sha256,
        "image_id": image_id,
    }
    child = (
        "import json,sys; request=json.load(sys.stdin); "
        "assert request['operation']=='deploy'; "
        f"assert request['payload']=={json.dumps(expected_payload)}; "
        f"sys.stdout.write({json.dumps(json.dumps(response))})"
    )
    real_popen = subprocess.Popen

    def fake_popen(_command: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        return real_popen([sys.executable, "-c", child], **kwargs)

    with patch("controller.subprocess.Popen", side_effect=fake_popen):
        result = controller.deploy("b" * 32, revision, archive_sha256, image_id)
    assert result["image_id"] == image_id


def test_hotfix_deploy_preserves_helper_source_without_accepting_it_as_input(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path)
    revision = "f6a51d5c821e6b1ab7974a94f4ff795da10130bc"
    helper_source_revision = "a" * 40
    archive_sha256 = "c" * 64
    image_id = "sha256:" + "d" * 64
    pair_sha256 = "e" * 64
    response = {
        "status": "ok",
        "result": "deployed",
        "plan_id": "b" * 32,
        "revision": revision,
        "transport": "github_release",
        "archive_sha256": archive_sha256,
        "image_id": image_id,
        "pair_manifest_sha256": pair_sha256,
        "recovery_contract": "schema13_same_schema_hotfix_v1",
        "helper_source_revision": helper_source_revision,
    }
    expected_payload = {
        "plan_id": "b" * 32,
        "revision": revision,
        "archive_sha256": archive_sha256,
        "image_id": image_id,
        "pair_manifest_sha256": pair_sha256,
    }
    child = (
        "import json,sys; request=json.load(sys.stdin); "
        "assert request['operation']=='deploy'; "
        f"assert request['payload']=={json.dumps(expected_payload)}; "
        f"sys.stdout.write({json.dumps(json.dumps(response))})"
    )
    real_popen = subprocess.Popen

    def fake_popen(_command: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        return real_popen([sys.executable, "-c", child], **kwargs)

    with patch("controller.subprocess.Popen", side_effect=fake_popen):
        result = controller.deploy(
            "b" * 32,
            revision,
            archive_sha256,
            image_id,
            pair_manifest_sha256=pair_sha256,
        )

    assert result["revision"] == revision
    assert result["helper_source_revision"] == helper_source_revision


def test_hotfix_status_preserves_current_app_and_helper_source_identities(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path)
    revision = "f6a51d5c821e6b1ab7974a94f4ff795da10130bc"
    helper_source_revision = "a" * 40
    response = {
        "status": "ok",
        "current": {
            "revision": revision,
            "helper_source_revision": helper_source_revision,
            "recovery_contract": "schema13_same_schema_hotfix_v1",
            "candidate_release_revision": revision,
        },
    }
    child = (
        "import json,sys; request=json.load(sys.stdin); "
        "assert request['operation']=='status'; "
        f"sys.stdout.write({json.dumps(json.dumps(response))})"
    )
    real_popen = subprocess.Popen

    def fake_popen(_command: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        return real_popen([sys.executable, "-c", child], **kwargs)

    with patch("controller.subprocess.Popen", side_effect=fake_popen):
        result = controller.status()

    assert result["current"]["revision"] == revision
    assert result["current"]["helper_source_revision"] == helper_source_revision
    assert result["current"]["candidate_release_revision"] == revision


def test_hotfix_recovery_rollback_reports_recovered_app_and_candidate_source(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path)
    candidate_revision = "f6a51d5c821e6b1ab7974a94f4ff795da10130bc"
    recovery_revision = "5ad2c3fddfce5a5a631b72cd832a53f24757c44a"
    helper_source_revision = "a" * 40
    recovery_image_id = "sha256:" + "b" * 64
    response = {
        "status": "ok",
        "result": "rolled_back",
        "revision": recovery_revision,
        "image_digest": "c" * 64,
        "transport": "github_release",
        "image_id": recovery_image_id,
        "release_role": "recovery",
        "recovery_contract": "schema13_same_schema_hotfix_v1",
        "candidate_release_revision": candidate_revision,
        "helper_source_revision": helper_source_revision,
    }
    expected_payload = {"revision": candidate_revision, "image_id": recovery_image_id}
    child = (
        "import json,sys; request=json.load(sys.stdin); "
        "assert request['operation']=='rollback'; "
        f"assert request['payload']=={json.dumps(expected_payload)}; "
        f"sys.stdout.write({json.dumps(json.dumps(response))})"
    )
    real_popen = subprocess.Popen

    def fake_popen(_command: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        return real_popen([sys.executable, "-c", child], **kwargs)

    with patch("controller.subprocess.Popen", side_effect=fake_popen):
        result = controller.rollback(candidate_revision, recovery_image_id)

    assert result["revision"] == recovery_revision
    assert result["candidate_release_revision"] == candidate_revision
    assert result["helper_source_revision"] == helper_source_revision


def test_hotfix_recovery_rollback_rejects_wrong_candidate_identity(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    candidate_revision = "f6a51d5c821e6b1ab7974a94f4ff795da10130bc"
    recovery_image_id = "sha256:" + "b" * 64
    response = {
        "status": "ok",
        "result": "rolled_back",
        "revision": "5ad2c3fddfce5a5a631b72cd832a53f24757c44a",
        "image_digest": "c" * 64,
        "transport": "github_release",
        "image_id": recovery_image_id,
        "release_role": "recovery",
        "recovery_contract": "schema13_same_schema_hotfix_v1",
        "candidate_release_revision": "d" * 40,
        "helper_source_revision": "a" * 40,
    }
    child = (
        "import json,sys; json.load(sys.stdin); "
        f"sys.stdout.write({json.dumps(json.dumps(response))})"
    )
    real_popen = subprocess.Popen

    def fake_popen(_command: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        return real_popen([sys.executable, "-c", child], **kwargs)

    with (
        patch("controller.subprocess.Popen", side_effect=fake_popen),
        pytest.raises(DeployError, match="remote_response_invalid"),
    ):
        controller.rollback(candidate_revision, recovery_image_id)


@pytest.mark.parametrize(
    "helper_source_revision",
    [None, "not-a-commit", "f6a51d5c821e6b1ab7974a94f4ff795da10130bc"],
)
def test_hotfix_recovery_rollback_rejects_invalid_helper_identity(
    tmp_path: Path,
    helper_source_revision: str | None,
) -> None:
    controller = _controller(tmp_path)
    candidate_revision = "f6a51d5c821e6b1ab7974a94f4ff795da10130bc"
    recovery_image_id = "sha256:" + "b" * 64
    response = {
        "status": "ok",
        "result": "rolled_back",
        "revision": "5ad2c3fddfce5a5a631b72cd832a53f24757c44a",
        "image_digest": "c" * 64,
        "transport": "github_release",
        "image_id": recovery_image_id,
        "release_role": "recovery",
        "recovery_contract": "schema13_same_schema_hotfix_v1",
        "candidate_release_revision": candidate_revision,
        "helper_source_revision": helper_source_revision,
    }
    child = (
        "import json,sys; json.load(sys.stdin); "
        f"sys.stdout.write({json.dumps(json.dumps(response))})"
    )
    real_popen = subprocess.Popen

    def fake_popen(_command: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        return real_popen([sys.executable, "-c", child], **kwargs)

    with (
        patch("controller.subprocess.Popen", side_effect=fake_popen),
        pytest.raises(DeployError, match="remote_response_invalid"),
    ):
        controller.rollback(candidate_revision, recovery_image_id)


def test_release_rollback_sends_full_image_id(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    revision = "a" * 40
    image_id = "sha256:" + "d" * 64
    response = {
        "status": "ok",
        "transport": "github_release",
        "result": "rolled_back",
        "revision": revision,
        "image_digest": "c" * 64,
        "image_id": image_id,
    }
    expected_payload = {"revision": revision, "image_id": image_id}
    child = (
        "import json,sys; request=json.load(sys.stdin); "
        "assert request['operation']=='rollback'; "
        f"assert request['payload']=={json.dumps(expected_payload)}; "
        f"sys.stdout.write({json.dumps(json.dumps(response))})"
    )
    real_popen = subprocess.Popen

    def fake_popen(_command: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        return real_popen([sys.executable, "-c", child], **kwargs)

    with patch("controller.subprocess.Popen", side_effect=fake_popen):
        result = controller.rollback(revision, image_id)
    assert result["image_id"] == image_id


def test_assistant_rollout_sends_only_current_reviewed_release_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = _controller(tmp_path)
    revision = "a" * 40
    archive_sha256 = "b" * 64
    image_id = "sha256:" + "c" * 64
    current = {
        "revision": revision,
        "transport": "github_release",
        "image_digest": archive_sha256,
        "archive_sha256": archive_sha256,
        "image_id": image_id,
        "platform": "linux/amd64",
        "schema_version": 13,
        "compose_digest": "d" * 64,
        "assistant_rollout_mode": "disabled",
    }
    monkeypatch.setattr(controller, "status", lambda: {"status": "ok", "current": current})
    monkeypatch.setattr(controller, "_local_rollout_revision", lambda: revision)
    calls: list[tuple[str, dict[str, object], int]] = []

    def invoke(operation: str, payload: dict[str, object], *, timeout: int):
        calls.append((operation, payload, timeout))
        return {
            "status": "ok",
            "result": "rollout_updated",
            "revision": revision,
            "archive_sha256": archive_sha256,
            "image_id": image_id,
            "schema_version": 13,
            "assistant_rollout_mode": "owner_canary",
            "health": {
                "status": "ready",
                "schema_version": 13,
                "assistant": {"enabled": True, "status": "ready"},
            },
        }

    monkeypatch.setattr(controller, "_invoke", invoke)
    result = controller.set_assistant_rollout("owner_canary")
    assert result["assistant_rollout_mode"] == "owner_canary"
    assert calls == [
        (
            "set_assistant_rollout",
            {
                "mode": "owner_canary",
                "revision": revision,
                "archive_sha256": archive_sha256,
                "image_id": image_id,
            },
            600,
        )
    ]


def test_hotfix_rollout_checks_helper_head_but_sends_candidate_app_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rollout = _controller(tmp_path)
    app_revision = HOTFIX_CANDIDATE_REVISION
    helper_revision = "f548fd94dad75c73b31621ee1a466ac7d41d06c2"
    archive_sha256 = "b" * 64
    image_id = "sha256:" + "c" * 64
    current = {
        "revision": app_revision,
        "release_role": "candidate",
        "recovery_contract": HOTFIX_PAIR_CONTRACT,
        "helper_source_revision": helper_revision,
        "pair_manifest_sha256": "0718ec4b9b3ae56a252432779b3bdad2eb7cc69a974e714a18ea19ea8b94d47e",
        "transport": "github_release",
        "image_digest": archive_sha256,
        "archive_sha256": archive_sha256,
        "image_id": image_id,
        "platform": "linux/amd64",
        "schema_version": 13,
        "compose_digest": "d" * 64,
        "assistant_rollout_mode": "disabled",
    }
    rollout.config = DeployConfig(
        "example.com",
        "deploy",
        rollout.config.identity_file,
        rollout.config.known_hosts_file,
        reviewed_revision=app_revision,
    )
    monkeypatch.setattr(rollout, "status", lambda: {"status": "ok", "current": current})
    monkeypatch.setattr(rollout, "_local_rollout_revision", lambda: helper_revision)
    calls: list[tuple[str, dict[str, object], int]] = []

    def invoke(operation: str, payload: dict[str, object], *, timeout: int):
        calls.append((operation, payload, timeout))
        return {
            "status": "ok",
            "result": "rollout_updated",
            "revision": app_revision,
            "archive_sha256": archive_sha256,
            "image_id": image_id,
            "schema_version": 13,
            "assistant_rollout_mode": "owner_canary",
            "health": {
                "status": "ready",
                "schema_version": 13,
                "assistant": {"enabled": True, "status": "ready"},
            },
        }

    monkeypatch.setattr(rollout, "_invoke", invoke)
    result = rollout.set_assistant_rollout("owner_canary")

    assert result["revision"] == app_revision
    assert calls == [
        (
            "set_assistant_rollout",
            {
                "mode": "owner_canary",
                "revision": app_revision,
                "archive_sha256": archive_sha256,
                "image_id": image_id,
            },
            600,
        )
    ]


def test_dual_head_identity_requires_separate_test_head_and_image_revision() -> None:
    helper_revision = "a" * 40
    reviewed_pr_head_sha = "b" * 40
    candidate = {
        "revision": HOTFIX_V3_CANDIDATE_REVISION,
        "recovery_contract": HOTFIX_PAIR_CONTRACT_V3,
        "helper_source_revision": helper_revision,
        "reviewed_pr_head_sha": reviewed_pr_head_sha,
    }

    assert _valid_hotfix_identity(candidate, HOTFIX_V3_CANDIDATE_REVISION)
    assert not _valid_hotfix_identity(
        {key: value for key, value in candidate.items() if key != "reviewed_pr_head_sha"},
        HOTFIX_V3_CANDIDATE_REVISION,
    )
    assert not _valid_hotfix_identity(
        {**candidate, "reviewed_pr_head_sha": "not-a-commit"},
        HOTFIX_V3_CANDIDATE_REVISION,
    )
    assert not _valid_hotfix_identity(
        {
            **candidate,
            "recovery_contract": HOTFIX_PAIR_CONTRACT,
        },
        HOTFIX_V3_CANDIDATE_REVISION,
    )
    assert not _valid_hotfix_identity(
        {
            "revision": HOTFIX_CANDIDATE_REVISION,
            "recovery_contract": HOTFIX_PAIR_CONTRACT,
            "helper_source_revision": helper_revision,
            "reviewed_pr_head_sha": reviewed_pr_head_sha,
        },
        HOTFIX_CANDIDATE_REVISION,
    )


def test_dual_head_rollback_response_keeps_candidate_revision_explicit() -> None:
    helper_revision = "a" * 40
    reviewed_pr_head_sha = "b" * 40
    response = {
        "recovery_contract": HOTFIX_PAIR_CONTRACT_V3,
        "helper_source_revision": helper_revision,
        "reviewed_pr_head_sha": reviewed_pr_head_sha,
        "candidate_release_revision": HOTFIX_V3_CANDIDATE_REVISION,
        "release_role": "recovery",
        "revision": "5ad2c3fddfce5a5a631b72cd832a53f24757c44a",
    }
    assert _valid_hotfix_identity(response, HOTFIX_V3_CANDIDATE_REVISION, rollback=True)
    assert not _valid_hotfix_identity(
        {key: value for key, value in response.items() if key != "reviewed_pr_head_sha"},
        HOTFIX_V3_CANDIDATE_REVISION,
        rollback=True,
    )


@pytest.mark.parametrize(
    "malformation",
    [
        "missing-helper-head",
        "app-head-is-not-helper-head",
        "missing-pair",
        "invalid-pair",
        "wrong-local-head",
    ],
)
def test_hotfix_rollout_rejects_unbound_helper_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    malformation: str,
) -> None:
    rollout = _controller(tmp_path)
    app_revision = HOTFIX_CANDIDATE_REVISION
    helper_revision = "f548fd94dad75c73b31621ee1a466ac7d41d06c2"
    current = {
        "revision": app_revision,
        "release_role": "candidate",
        "recovery_contract": HOTFIX_PAIR_CONTRACT,
        "helper_source_revision": helper_revision,
        "pair_manifest_sha256": "0718ec4b9b3ae56a252432779b3bdad2eb7cc69a974e714a18ea19ea8b94d47e",
        "transport": "github_release",
        "image_digest": "b" * 64,
        "archive_sha256": "b" * 64,
        "image_id": "sha256:" + "c" * 64,
        "platform": "linux/amd64",
        "schema_version": 13,
        "compose_digest": "d" * 64,
        "assistant_rollout_mode": "disabled",
    }
    if malformation == "missing-helper-head":
        current.pop("helper_source_revision")
    elif malformation == "app-head-is-not-helper-head":
        current["helper_source_revision"] = app_revision
    elif malformation == "missing-pair":
        current.pop("pair_manifest_sha256")
    elif malformation == "invalid-pair":
        current["pair_manifest_sha256"] = "invalid"
    local_revision = (
        app_revision
        if malformation == "wrong-local-head"
        else "f548fd94dad75c73b31621ee1a466ac7d41d06c2"
    )
    monkeypatch.setattr(rollout, "status", lambda: {"status": "ok", "current": current})
    monkeypatch.setattr(rollout, "_local_rollout_revision", lambda: local_revision)

    with patch.object(rollout, "_invoke") as invoke:
        with pytest.raises(DeployError, match="reviewed_release_mismatch"):
            rollout.set_assistant_rollout("owner_canary")
        invoke.assert_not_called()


def test_assistant_rollout_refuses_old_schema_and_stale_local_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = _controller(tmp_path)
    revision = "a" * 40
    archive_sha256 = "b" * 64
    image_id = "sha256:" + "c" * 64
    current = {
        "revision": revision,
        "transport": "github_release",
        "image_digest": archive_sha256,
        "archive_sha256": archive_sha256,
        "image_id": image_id,
        "platform": "linux/amd64",
        "schema_version": 12,
        "compose_digest": "d" * 64,
        "assistant_rollout_mode": "disabled",
    }
    monkeypatch.setattr(controller, "status", lambda: {"status": "ok", "current": current})
    monkeypatch.setattr(controller, "_local_rollout_revision", lambda: revision)
    with patch.object(controller, "_invoke") as invoke:
        with pytest.raises(DeployError, match="active_release_identity_invalid"):
            controller.set_assistant_rollout("owner_canary")
        invoke.assert_not_called()

    current["schema_version"] = 13
    monkeypatch.setattr(controller, "_local_rollout_revision", lambda: "e" * 40)
    with patch.object(controller, "_invoke") as invoke:
        with pytest.raises(DeployError, match="reviewed_release_mismatch"):
            controller.set_assistant_rollout("invited")
        invoke.assert_not_called()


def test_missing_config_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "SIGNAL_LEDGER_DEPLOY_HOST",
        "SIGNAL_LEDGER_DEPLOY_USER",
        "SIGNAL_LEDGER_DEPLOY_IDENTITY_FILE",
        "SIGNAL_LEDGER_DEPLOY_KNOWN_HOSTS_FILE",
    ):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(DeployError, match="deploy_target_unconfigured"):
        DeployConfig.from_env()


def test_mismatched_remote_plan_is_rejected(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    response = {
        "status": "ok",
        "revision": "d" * 40,
        "plan_id": "b" * 32,
        "image_digest": "c" * 64,
    }
    child = (
        f"import sys; sys.stdin.buffer.read(); sys.stdout.write({json.dumps(json.dumps(response))})"
    )
    real_popen = subprocess.Popen

    def fake_popen(_command: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        return real_popen([sys.executable, "-c", child], **kwargs)

    with (
        patch("controller.subprocess.Popen", side_effect=fake_popen),
        pytest.raises(DeployError, match="remote_response_invalid"),
    ):
        controller.plan_deploy("a" * 40, "c" * 64)


def test_remote_output_is_bounded_and_child_is_killed(tmp_path: Path) -> None:
    oversized = MAX_RESPONSE_BYTES + 1
    child = f"import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write(b'x'*{oversized})"
    real_popen = subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []

    def fake_popen(_command: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        process = real_popen([sys.executable, "-c", child], **kwargs)
        processes.append(process)
        return process

    with (
        patch("controller.subprocess.Popen", side_effect=fake_popen),
        pytest.raises(DeployError, match="remote_response_too_large"),
    ):
        _run_bounded_ssh(["ssh"], b"{}", timeout=5)

    assert processes and processes[0].poll() is not None


def test_remote_timeout_kills_child_and_returns_safe_error() -> None:
    child = "import sys,time; sys.stdin.buffer.read(); time.sleep(5)"
    real_popen = subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []

    def fake_popen(_command: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        process = real_popen([sys.executable, "-c", child], **kwargs)
        processes.append(process)
        return process

    with (
        patch("controller.subprocess.Popen", side_effect=fake_popen),
        pytest.raises(DeployError, match="remote_unavailable"),
    ):
        _run_bounded_ssh(["ssh"], b"{}", timeout=0.05)

    assert processes and processes[0].poll() is not None


def _terraform_controller(
    tmp_path: Path, plan_document: dict[str, object]
) -> tuple[DeployController, Path, Path]:
    """Build a controller with a fake Terraform binary that never exposes its token."""

    identity = tmp_path / "identity"
    known_hosts = tmp_path / "known_hosts"
    token_file = tmp_path / "linode-token"
    terraform = tmp_path / "terraform"
    state_file = tmp_path / "terraform.tfstate"
    command_log = tmp_path / "terraform-commands.jsonl"
    identity.write_text("dummy")
    known_hosts.write_text("dummy")
    token_file.write_text("fixture-token\n")
    state_file.write_bytes(b"fixture state metadata only")
    identity.chmod(0o600)
    known_hosts.chmod(0o600)
    token_file.chmod(0o600)
    state_file.chmod(0o600)
    terraform.write_text(
        "#!"
        + sys.executable
        + "\n"
        + "import json, os, sys\n"
        + f"log = {str(command_log)!r}\n"
        + f"plan = {json.dumps(plan_document)!r}\n"
        + "if os.environ.get('LINODE_TOKEN') != 'fixture-token': sys.exit(9)\n"
        + "args = sys.argv[1:]\n"
        + "command = next(value for value in args if value in {'init', 'plan', 'show', 'apply'})\n"
        + "with open(log, 'a', encoding='utf-8') as output:\n"
        + "    output.write(json.dumps(args) + '\\n')\n"
        + "if command == 'show': print(plan)\n"
    )
    terraform.chmod(0o700)
    return (
        DeployController(
            DeployConfig(
                "example.com",
                "deploy",
                identity,
                known_hosts,
                terraform,
                token_file,
                "a" * 40,
            )
        ),
        command_log,
        state_file,
    )


def _firewall_plan(before_cidr: str, after_cidr: str) -> dict[str, object]:
    """Return a minimal Terraform plan fixture for the fixed firewall resource."""

    def state(cidr: str) -> dict[str, object]:
        return {
            "id": "177236117",
            "label": "signal-ledger-fw",
            "inbound_policy": "DROP",
            "outbound_policy": "ACCEPT",
            "inbound": [
                {
                    "label": "ssh-operator",
                    "action": "ACCEPT",
                    "protocol": "TCP",
                    "ports": "22",
                    "ipv4": [cidr],
                }
            ],
        }

    return {
        "resource_changes": [
            {
                "address": FIREWALL_RESOURCE,
                "mode": "managed",
                "change": {
                    "actions": ["update"],
                    "before": state(before_cidr),
                    "after": state(after_cidr),
                },
            }
        ]
    }


def test_refresh_operator_access_applies_only_scoped_firewall_plan(tmp_path: Path) -> None:
    controller, command_log, state_file = _terraform_controller(
        tmp_path,
        _firewall_plan("198.51.100.7/32", "203.0.113.44/32"),
    )

    with patch("controller.TERRAFORM_STATE_PATH", state_file):
        result = controller.refresh_operator_access("203.0.113.44/32")

    assert result["status"] == "ok"
    assert result["result"] == "applied"
    assert result["resource"] == FIREWALL_RESOURCE
    assert result["operator_ipv4_cidr"] == "203.0.113.44/32"
    assert result["plan_actions"] == ["update"]
    assert "fixture-token" not in json.dumps(result)
    commands = [json.loads(line) for line in command_log.read_text().splitlines()]
    command_names = [
        next(value for value in command if value in {"init", "plan", "show", "apply"})
        for command in commands
    ]
    assert command_names == [
        "init",
        "plan",
        "show",
        "apply",
    ]
    plan_command = commands[1]
    assert f"-target={FIREWALL_RESOURCE}" in plan_command
    assert f"-state={state_file}" in plan_command
    assert "-var=firewall_id=177236117" in plan_command
    assert "-var=firewall_label=signal-ledger-fw" in plan_command
    assert f"-state={state_file}" in commands[3]
    assert f"-state={state_file}" not in commands[0]
    assert all("fixture-token" not in line for line in command_log.read_text().splitlines())


def test_refresh_operator_access_rejects_non_private_state_metadata(
    tmp_path: Path,
) -> None:
    controller, command_log, state_file = _terraform_controller(
        tmp_path,
        _firewall_plan("198.51.100.7/32", "203.0.113.44/32"),
    )
    state_file.chmod(0o640)

    with (
        patch("controller.TERRAFORM_STATE_PATH", state_file),
        pytest.raises(DeployError, match="terraform_state_permissions"),
    ):
        controller.refresh_operator_access("203.0.113.44/32")

    assert not command_log.exists()


def test_refresh_operator_access_rejects_non_network_input_before_credentials(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path)

    with pytest.raises(DeployError, match="operator_ipv4_cidr_invalid"):
        controller.refresh_operator_access("203.0.113.44/24")


def test_firewall_plan_rejects_changes_outside_operator_cidr() -> None:
    plan = _firewall_plan("198.51.100.7/32", "203.0.113.44/32")
    resource = plan["resource_changes"][0]
    assert isinstance(resource, dict)
    detail = resource["change"]
    assert isinstance(detail, dict)
    after = detail["after"]
    assert isinstance(after, dict)
    after["outbound_policy"] = "DROP"

    with pytest.raises(DeployError, match="terraform_scope_violation"):
        _validate_firewall_plan(plan, "203.0.113.44/32")


def test_firewall_plan_allows_provider_computed_metadata_and_empty_ipv6_null() -> None:
    plan = _firewall_plan("198.51.100.7/32", "203.0.113.44/32")
    resource = plan["resource_changes"][0]
    assert isinstance(resource, dict)
    detail = resource["change"]
    assert isinstance(detail, dict)
    for state_key, fingerprint, updated, version in (
        ("before", "old-fingerprint", "old-updated", 1),
        ("after", "new-fingerprint", "new-updated", 2),
    ):
        state = detail[state_key]
        assert isinstance(state, dict)
        state["fingerprint"] = fingerprint
        state["updated"] = updated
        state["version"] = version
        inbound = state["inbound"]
        assert isinstance(inbound, list)
        rule = inbound[0]
        assert isinstance(rule, dict)
        rule["ipv6"] = None

    assert _validate_firewall_plan(plan, "203.0.113.44/32") == ["update"]


def test_firewall_plan_rejects_ipv6_operator_rule() -> None:
    plan = _firewall_plan("198.51.100.7/32", "203.0.113.44/32")
    resource = plan["resource_changes"][0]
    assert isinstance(resource, dict)
    detail = resource["change"]
    assert isinstance(detail, dict)
    after = detail["after"]
    assert isinstance(after, dict)
    inbound = after["inbound"]
    assert isinstance(inbound, list)
    rule = inbound[0]
    assert isinstance(rule, dict)
    rule["ipv6"] = ["2001:db8::/128"]

    with pytest.raises(DeployError, match="terraform_scope_violation"):
        _validate_firewall_plan(plan, "203.0.113.44/32")


def test_firewall_plan_rejects_non_cidr_computed_metadata_drift() -> None:
    plan = _firewall_plan("198.51.100.7/32", "203.0.113.44/32")
    resource = plan["resource_changes"][0]
    assert isinstance(resource, dict)
    detail = resource["change"]
    assert isinstance(detail, dict)
    before = detail["before"]
    after = detail["after"]
    assert isinstance(before, dict) and isinstance(after, dict)
    before["status"] = "enabled"
    after["status"] = "disabled"

    with pytest.raises(DeployError, match="terraform_scope_violation"):
        _validate_firewall_plan(plan, "203.0.113.44/32")


@pytest.mark.parametrize("state_key", ["before", "after"])
def test_firewall_plan_requires_fixed_firewall_id(state_key: str) -> None:
    plan = _firewall_plan("198.51.100.7/32", "203.0.113.44/32")
    resource = plan["resource_changes"][0]
    assert isinstance(resource, dict)
    detail = resource["change"]
    assert isinstance(detail, dict)
    state = detail[state_key]
    assert isinstance(state, dict)
    state["id"] = "99887766"

    with pytest.raises(DeployError, match="terraform_scope_violation"):
        _validate_firewall_plan(plan, "203.0.113.44/32")


def test_noop_firewall_plan_requires_fixed_firewall_id() -> None:
    plan = _firewall_plan("198.51.100.7/32", "203.0.113.44/32")
    resource = plan["resource_changes"][0]
    assert isinstance(resource, dict)
    detail = resource["change"]
    assert isinstance(detail, dict)
    detail["actions"] = ["no-op"]
    after = detail["after"]
    assert isinstance(after, dict)
    after["id"] = "99887766"

    with pytest.raises(DeployError, match="terraform_scope_violation"):
        _validate_firewall_plan(plan, "203.0.113.44/32")


def test_next_temporary_recovery_controller_sends_only_inspected_prior_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = _controller(tmp_path)
    prior_id = "a" * 32
    view_sha256 = "b" * 64
    response = _next_temporary_recovery_response()
    assert response["operation_id"] == "ccd2fd1a94f4829b131b754e0f90d367"
    assert (
        response["cycle_link_sha256"]
        == "3b07ba3dea48431a01bac712d4ffd97cc02e8111ef7bd1e4cdb04815a4db8b41"
    )
    calls: list[tuple[str, dict[str, object], int]] = []

    def invoke(operation: str, payload: dict[str, object], *, timeout: int) -> dict[str, object]:
        calls.append((operation, payload, timeout))
        return response

    monkeypatch.setattr(controller, "_invoke", invoke)
    assert controller.start_next_temporary_recovery(prior_id, view_sha256) == response
    assert calls == [
        (
            "start_next_temporary_recovery",
            {"prior_operation_id": prior_id, "prior_view_sha256": view_sha256},
            900,
        )
    ]


def test_next_temporary_recovery_controller_accepts_floor_unmet_without_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = _controller(tmp_path)
    response = _next_temporary_recovery_response(available_kib=200_000)
    monkeypatch.setattr(controller, "_invoke", lambda *_args, **_kwargs: response)

    result = controller.start_next_temporary_recovery("a" * 32, "b" * 64)

    assert result["result"] == "temporary_recovery_ready_startup_floor_unmet"
    assert result["start_admission_allowed"] is False


@pytest.mark.parametrize(
    ("prior_id", "view_sha256"),
    [("not-an-id", "b" * 64), ("a" * 32, "not-a-digest")],
)
def test_next_temporary_recovery_controller_rejects_untyped_prior_identity(
    tmp_path: Path, prior_id: str, view_sha256: str
) -> None:
    controller = _controller(tmp_path)
    with (
        patch.object(controller, "_invoke") as invoke,
        pytest.raises(DeployError, match="temporary_recovery_prior_identity_invalid"),
    ):
        controller.start_next_temporary_recovery(prior_id, view_sha256)
    invoke.assert_not_called()


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("operation_id", "f" * 32),
        ("cycle_link_sha256", "e" * 64),
        ("prior_record_sha256", "2" * 64),
        ("prior_view_sha256", "3" * 64),
        ("prior_operation_id", "4" * 32),
        ("cycle_link_status", "intent"),
        ("status", "error"),
        ("result", "temporary_recovery_ready_startup_floor_unmet"),
        ("image_ref", "signal-ledger:temporary-recovery-" + "f" * 32),
        ("image_id", "sha256:" + "z" * 64),
        ("archive_sha256", "not-a-digest"),
        ("manifest_sha256", "not-a-digest"),
        ("source_revision", "0" * 40),
        ("schema_version", True),
        ("assistant_rollout_mode", "invited"),
        ("available_kib", True),
        ("startup_floor_kib", 1),
        ("start_admission_allowed", False),
    ],
)
def test_next_temporary_recovery_controller_rejects_unbound_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement: object,
) -> None:
    controller = _controller(tmp_path)
    prior_id = "a" * 32
    view_sha256 = "b" * 64
    response = _next_temporary_recovery_response()
    response[field] = replacement
    monkeypatch.setattr(controller, "_invoke", lambda *_args, **_kwargs: response)
    with pytest.raises(DeployError, match="remote_response_invalid"):
        controller.start_next_temporary_recovery(prior_id, view_sha256)


@pytest.mark.parametrize(
    "field",
    [
        "status",
        "image_ref",
        "image_id",
        "archive_sha256",
        "manifest_sha256",
        "backup",
        "health",
        "startup_floor_kib",
        "start_admission_allowed",
    ],
)
def test_next_temporary_recovery_controller_rejects_omitted_ready_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    controller = _controller(tmp_path)
    response = _next_temporary_recovery_response()
    del response[field]
    monkeypatch.setattr(controller, "_invoke", lambda *_args, **_kwargs: response)

    with pytest.raises(DeployError, match="remote_response_invalid"):
        controller.start_next_temporary_recovery("a" * 32, "b" * 64)


@pytest.mark.parametrize(
    ("container", "field", "replacement"),
    [
        ("backup", "verified", False),
        ("backup", "promoted", True),
        ("backup", "name", "pre-deploy-63597953c9d1ab38-01234567.spbackup"),
        ("backup", "schema_version", 12),
        ("backup", "name", "pre-deploy-5ad2c3fddfce5a5-01234567.spbackup"),
        ("health", "schema_version", 12),
        ("health", "status", "starting"),
    ],
)
def test_next_temporary_recovery_controller_rejects_mismatched_ready_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    container: str,
    field: str,
    replacement: object,
) -> None:
    controller = _controller(tmp_path)
    response = _next_temporary_recovery_response()
    nested = response[container]
    assert isinstance(nested, dict)
    nested[field] = replacement
    monkeypatch.setattr(controller, "_invoke", lambda *_args, **_kwargs: response)

    with pytest.raises(DeployError, match="remote_response_invalid"):
        controller.start_next_temporary_recovery("a" * 32, "b" * 64)


@pytest.mark.parametrize(("field", "replacement"), [("enabled", True), ("status", "ready")])
def test_next_temporary_recovery_controller_rejects_non_disabled_worker_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement: object,
) -> None:
    controller = _controller(tmp_path)
    response = _next_temporary_recovery_response()
    health = response["health"]
    assert isinstance(health, dict)
    assistant = health["assistant"]
    assert isinstance(assistant, dict)
    assistant[field] = replacement
    monkeypatch.setattr(controller, "_invoke", lambda *_args, **_kwargs: response)

    with pytest.raises(DeployError, match="remote_response_invalid"):
        controller.start_next_temporary_recovery("a" * 32, "b" * 64)


def test_next_temporary_recovery_controller_rejects_false_floor_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = _controller(tmp_path)
    response = _next_temporary_recovery_response(available_kib=200_000)
    response["start_admission_allowed"] = True
    monkeypatch.setattr(controller, "_invoke", lambda *_args, **_kwargs: response)

    with pytest.raises(DeployError, match="remote_response_invalid"):
        controller.start_next_temporary_recovery("a" * 32, "b" * 64)
