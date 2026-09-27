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
    MAX_RESPONSE_BYTES,
    DeployConfig,
    DeployController,
    DeployError,
    _run_bounded_ssh,
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
