"""Checks for the fixed-host Cloudflare owner-canary enablement boundary."""

from __future__ import annotations

import copy
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "infra" / "cloudflare" / "enable-canary.sh"
ACCOUNT_ID = "f4c09c14a6618297f411e9ee75305013"
ZONE_ID = "53092409b9e2a417c3af37656b48ce64"
TUNNEL_ID = "ad7dfd41-9b9a-4b5c-92c0-6c72ca2d1c2f"


def _state() -> dict[str, object]:
    return {
        "values": {
            "outputs": {
                "exposure_mode": {"value": "canary"},
                "public_hostname": {"value": "ledger.jtmb.cc"},
                "tunnel_id": {"value": TUNNEL_ID},
            },
            "root_module": {
                "resources": [
                    {
                        "address": "cloudflare_zero_trust_access_application.canary[0]",
                        "values": {
                            "zone_id": ZONE_ID,
                            "type": "self_hosted",
                            "domain": "ledger.jtmb.cc",
                            "destinations": [{"type": "public", "uri": "ledger.jtmb.cc"}],
                            "policies": [
                                {
                                    "decision": "allow",
                                    "include": [{"email": {"email": "owner@example.com"}}],
                                    "exclude": [],
                                }
                            ],
                        },
                    },
                    {
                        "address": "cloudflare_ruleset.signal_ledger_cache_bypass",
                        "values": {
                            "zone_id": ZONE_ID,
                            "name": "Signal Ledger cache bypass",
                            "kind": "zone",
                            "phase": "http_request_cache_settings",
                            "rules": [
                                {
                                    "action": "set_cache_settings",
                                    "enabled": True,
                                    "expression": '(http.host eq "ledger.jtmb.cc")',
                                    "action_parameters": {
                                        "cache": False,
                                        "browser_ttl": {"mode": "bypass"},
                                    },
                                }
                            ],
                        },
                    },
                    {
                        "address": "cloudflare_zero_trust_tunnel_cloudflared.signal_ledger",
                        "values": {
                            "id": TUNNEL_ID,
                            "account_id": ACCOUNT_ID,
                            "name": "signal-ledger",
                            "config_src": "cloudflare",
                        },
                    },
                    {
                        "address": "cloudflare_zero_trust_tunnel_cloudflared_config.signal_ledger",
                        "values": {
                            "account_id": ACCOUNT_ID,
                            "tunnel_id": TUNNEL_ID,
                            "config": {
                                "ingress": [
                                    {
                                        "hostname": "ledger.jtmb.cc",
                                        "path": None,
                                        "service": "http://127.0.0.1:8000",
                                        "origin_request": None,
                                    },
                                    {
                                        "hostname": None,
                                        "path": None,
                                        "service": "http_status:404",
                                        "origin_request": None,
                                    },
                                ]
                            }
                        },
                    },
                    {
                        "address": "cloudflare_dns_record.canary[0]",
                        "values": {
                            "zone_id": ZONE_ID,
                            "name": "ledger.jtmb.cc",
                            "type": "CNAME",
                            "proxied": True,
                            "content": f"{TUNNEL_ID}.cfargotunnel.com",
                        },
                    },
                ]
            },
        }
    }


def _private_file(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return path


def _fake_tools(tmp_path: Path) -> tuple[Path, Path]:
    terraform = tmp_path / "terraform"
    terraform.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$FAKE_TERRAFORM_LOG\"\n"
        "if [ \"$2\" = \"plan\" ]; then\n"
        "  exit \"${FAKE_TERRAFORM_PLAN_EXIT:-0}\"\n"
        "fi\n"
        "cat \"$FAKE_TERRAFORM_STATE\"\n",
        encoding="utf-8",
    )
    terraform.chmod(0o700)
    ssh = tmp_path / "ssh"
    ssh.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$FAKE_SSH_LOG\"\n"
        "exit \"${FAKE_SSH_EXIT:-0}\"\n",
        encoding="utf-8",
    )
    ssh.chmod(0o700)
    python = tmp_path / "python3"
    python.write_text(
        "#!/bin/sh\n"
        "printf 'python %s\\n' \"$*\" >> \"$FAKE_TERRAFORM_LOG\"\n"
        f"exec {shlex.quote(sys.executable)} \"$@\"\n",
        encoding="utf-8",
    )
    python.chmod(0o700)
    return terraform, ssh


def _run(
    tmp_path: Path,
    state: dict[str, object],
    *,
    arguments: list[str] | None = None,
    plan_exit: int = 0,
    owner_email_file: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], str, str]:
    identity = _private_file(tmp_path / "operator-key", "operator-private-key\n")
    known_hosts = _private_file(tmp_path / "known-hosts", "45.79.180.32 ssh-ed25519 AAAA\n")
    if owner_email_file is None:
        owner_email_file = _private_file(tmp_path / "owner-email", "owner@example.com\n")
    state_file = _private_file(tmp_path / "terraform.tfstate", json.dumps(state))
    terraform, _ = _fake_tools(tmp_path)
    ssh_log = tmp_path / "ssh.log"
    terraform_log = tmp_path / "terraform.log"
    tf_data_dir = tmp_path / "terraform-data"
    tf_data_dir.mkdir()
    tf_data_dir.chmod(0o700)
    environment = os.environ.copy()
    environment["SIGNAL_LEDGER_OPERATOR_IDENTITY_FILE"] = str(identity)
    environment["SIGNAL_LEDGER_KNOWN_HOSTS_FILE"] = str(known_hosts)
    environment["SIGNAL_LEDGER_OWNER_EMAIL_FILE"] = str(owner_email_file)
    environment["SIGNAL_LEDGER_CLOUDFLARE_STATE_FILE"] = str(state_file)
    environment["SIGNAL_LEDGER_CLOUDFLARE_TF_DATA_DIR"] = str(tf_data_dir)
    environment["SIGNAL_LEDGER_TERRAFORM_BIN"] = str(terraform)
    environment["CLOUDFLARE_API_TOKEN"] = "test-token-value"  # noqa: S105
    environment["FAKE_TERRAFORM_STATE"] = str(state_file)
    environment["FAKE_TERRAFORM_LOG"] = str(terraform_log)
    environment["FAKE_TERRAFORM_PLAN_EXIT"] = str(plan_exit)
    environment["FAKE_SSH_LOG"] = str(ssh_log)
    environment["PATH"] = f"{tmp_path}:{environment['PATH']}"
    result = subprocess.run(  # noqa: S603
        [str(SCRIPT), *(arguments or [])],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    return (
        result,
        ssh_log.read_text(encoding="utf-8") if ssh_log.exists() else "",
        terraform_log.read_text(encoding="utf-8") if terraform_log.exists() else "",
    )


def test_enable_canary_verifies_state_before_fixed_remote_commands(tmp_path: Path) -> None:
    result, ssh_log, terraform_log = _run(tmp_path, _state())

    assert result.returncode == 0, result.stderr
    assert "Owner-only Cloudflare canary verified" in result.stdout
    assert "45.79.180.32" in ssh_log
    assert "signalops@45.79.180.32" in ssh_log
    assert "StrictHostKeyChecking=yes" in ssh_log
    assert "systemctl enable --now signal-ledger-cloudflared.service" in ssh_log
    assert "systemctl is-active --quiet signal-ledger-cloudflared.service" in ssh_log
    assert ssh_log.count("signal-ledger-cloudflared.service") == 2
    assert "-detailed-exitcode" in terraform_log
    assert "-refresh-only" not in terraform_log
    assert "-refresh=false" not in terraform_log
    assert f"-chdir={ROOT / 'infra' / 'cloudflare'} show -json" in terraform_log
    assert f"-var=zone_id={ZONE_ID}" in terraform_log
    assert "-var=exposure_mode=canary" in terraform_log
    assert any(line.startswith("python ") for line in terraform_log.splitlines())
    assert "test-token-value" not in result.stdout + result.stderr + terraform_log
    assert "owner@example.com" not in result.stdout + result.stderr + terraform_log + ssh_log


def test_enable_canary_rejects_missing_owner_email_before_ssh(tmp_path: Path) -> None:
    missing = tmp_path / "missing-owner-email"

    result, ssh_log, terraform_log = _run(tmp_path, _state(), owner_email_file=missing)

    assert result.returncode == 2
    assert "owner email file must be a regular non-symlink file" in result.stderr
    assert "owner@example.com" not in result.stdout + result.stderr + terraform_log + ssh_log
    assert ssh_log == ""
    assert terraform_log == ""


@pytest.mark.parametrize("kind", ["mode", "symlink", "multiline", "malformed"])
def test_enable_canary_rejects_unsafe_owner_email_before_ssh(
    tmp_path: Path, kind: str
) -> None:
    owner_email = tmp_path / "owner-email"
    if kind == "mode":
        _private_file(owner_email, "owner@example.com\n").chmod(0o644)
    elif kind == "symlink":
        target = _private_file(tmp_path / "owner-email-target", "owner@example.com\n")
        owner_email.symlink_to(target)
    elif kind == "multiline":
        _private_file(owner_email, "owner@example.com\nsecond@example.com\n")
    else:
        _private_file(owner_email, "not-an-email\n")

    result, ssh_log, terraform_log = _run(tmp_path, _state(), owner_email_file=owner_email)

    assert result.returncode == 2
    assert "owner@example.com" not in result.stdout + result.stderr + terraform_log + ssh_log
    assert ssh_log == ""
    assert terraform_log == ""


def test_enable_canary_rejects_unverified_access_before_ssh(tmp_path: Path) -> None:
    state = _state()
    access = state["values"]["root_module"]["resources"][0]  # type: ignore[index]
    access["values"]["policies"][0]["include"][0]["email"]["email"] = "other@example.com"  # type: ignore[index]

    result, ssh_log, _ = _run(tmp_path, state)

    assert result.returncode != 0
    assert "access_policy_owner" in result.stderr
    assert ssh_log == ""


def test_enable_canary_rejects_closed_state_before_ssh(tmp_path: Path) -> None:
    state = copy.deepcopy(_state())
    state["values"]["outputs"]["exposure_mode"]["value"] = "closed"  # type: ignore[index]

    result, ssh_log, _ = _run(tmp_path, state)

    assert result.returncode != 0
    assert "exposure_mode_is_not_owner_canary" in result.stderr
    assert ssh_log == ""


@pytest.mark.parametrize("plan_exit", [1, 2])
def test_enable_canary_rejects_stale_or_unavailable_cloudflare_refresh(
    tmp_path: Path, plan_exit: int
) -> None:
    result, ssh_log, terraform_log = _run(tmp_path, _state(), plan_exit=plan_exit)

    assert result.returncode == 2
    assert "provider-refreshed plan failed or detected drift" in result.stderr
    assert ssh_log == ""
    assert "-detailed-exitcode" in terraform_log
    assert "-refresh-only" not in terraform_log
    assert "-refresh=false" not in terraform_log


def test_enable_canary_rejects_wrong_zone_identity_before_ssh(tmp_path: Path) -> None:
    state = _state()
    access = state["values"]["root_module"]["resources"][0]  # type: ignore[index]
    access["values"]["zone_id"] = "00000000000000000000000000000000"  # type: ignore[index]

    result, ssh_log, _ = _run(tmp_path, state)

    assert result.returncode != 0
    assert "access_application_identity" in result.stderr
    assert ssh_log == ""


def test_enable_canary_rejects_unlinked_tunnel_ids_before_ssh(tmp_path: Path) -> None:
    state = _state()
    config = state["values"]["root_module"]["resources"][3]  # type: ignore[index]
    config["values"]["tunnel_id"] = "11111111-1111-4111-8111-111111111111"  # type: ignore[index]

    result, ssh_log, _ = _run(tmp_path, state)

    assert result.returncode != 0
    assert "tunnel_config_identity" in result.stderr
    assert ssh_log == ""


def test_enable_canary_rejects_remote_command_arguments() -> None:
    result = subprocess.run(  # noqa: S603
        [str(SCRIPT), "--host", "attacker.example"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "no command, host, URL, or path arguments" in result.stderr


def test_enable_canary_fails_closed_if_enable_command_fails(tmp_path: Path) -> None:
    identity = _private_file(tmp_path / "operator-key", "operator-private-key\n")
    known_hosts = _private_file(tmp_path / "known-hosts", "45.79.180.32 ssh-ed25519 AAAA\n")
    owner_email = _private_file(tmp_path / "owner-email", "owner@example.com\n")
    state_file = _private_file(tmp_path / "terraform.tfstate", json.dumps(_state()))
    terraform, _ = _fake_tools(tmp_path)
    ssh_log = tmp_path / "ssh.log"
    terraform_log = tmp_path / "terraform.log"
    tf_data_dir = tmp_path / "terraform-data"
    tf_data_dir.mkdir()
    tf_data_dir.chmod(0o700)
    environment = os.environ.copy()
    environment.update(
        {
            "SIGNAL_LEDGER_OPERATOR_IDENTITY_FILE": str(identity),
            "SIGNAL_LEDGER_KNOWN_HOSTS_FILE": str(known_hosts),
            "SIGNAL_LEDGER_OWNER_EMAIL_FILE": str(owner_email),
            "SIGNAL_LEDGER_CLOUDFLARE_STATE_FILE": str(state_file),
            "SIGNAL_LEDGER_CLOUDFLARE_TF_DATA_DIR": str(tf_data_dir),
            "SIGNAL_LEDGER_TERRAFORM_BIN": str(terraform),
            "CLOUDFLARE_API_TOKEN": "test-token-value",  # noqa: S105
            "FAKE_TERRAFORM_STATE": str(state_file),
            "FAKE_TERRAFORM_LOG": str(terraform_log),
            "FAKE_SSH_LOG": str(ssh_log),
            "FAKE_SSH_EXIT": "7",
            "PATH": f"{tmp_path}:{environment['PATH']}",
        }
    )

    result = subprocess.run(  # noqa: S603
        [str(SCRIPT)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "fixed host tunnel enable failed" in result.stderr
    assert ssh_log.read_text(encoding="utf-8").count("signal-ledger-cloudflared.service") == 1
