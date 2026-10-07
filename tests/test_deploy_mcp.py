"""The deployment MCP cannot turn tool arguments into SSH commands."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "deploy_mcp"))

from controller import (  # noqa: E402
    FIREWALL_RESOURCE,
    MAX_RESPONSE_BYTES,
    DeployConfig,
    DeployController,
    DeployError,
    _run_bounded_ssh,
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
