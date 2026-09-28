"""Checks for the fixed-host Cloudflare Tunnel unit updater."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "infra" / "cloudflare" / "update-host-unit.sh"
UNIT = ROOT / "infra" / "cloudflare" / "signal-ledger-cloudflared.service"


def _private_file(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return path


def _run(
    tmp_path: Path, *, arguments: list[str] | None = None, ssh_exit: int = 0
) -> tuple[subprocess.CompletedProcess[str], str, bytes]:
    identity = _private_file(tmp_path / "operator-key", "operator-private-key\n")
    known_hosts = _private_file(tmp_path / "known-hosts", "45.79.180.32 ssh-ed25519 AAAA\n")
    log = tmp_path / "ssh.log"
    received = tmp_path / "received-unit"
    ssh = tmp_path / "ssh"
    ssh.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$FAKE_SSH_LOG\"\n"
        "cat > \"$FAKE_SSH_INPUT\"\n"
        "exit \"${FAKE_SSH_EXIT:-0}\"\n",
        encoding="utf-8",
    )
    ssh.chmod(0o700)
    environment = os.environ.copy()
    environment.update(
        {
            "SIGNAL_LEDGER_OPERATOR_IDENTITY_FILE": str(identity),
            "SIGNAL_LEDGER_KNOWN_HOSTS_FILE": str(known_hosts),
            "FAKE_SSH_LOG": str(log),
            "FAKE_SSH_INPUT": str(received),
            "FAKE_SSH_EXIT": str(ssh_exit),
            "PATH": f"{tmp_path}:{environment['PATH']}",
        }
    )
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
        log.read_text(encoding="utf-8") if log.exists() else "",
        received.read_bytes() if received.exists() else b"",
    )


def test_update_installs_exact_reviewed_unit_and_leaves_service_stopped(tmp_path: Path) -> None:
    result, ssh_log, received = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "service remains stopped" in result.stdout
    assert received == UNIT.read_bytes()
    assert "signalops@45.79.180.32" in ssh_log
    assert "StrictHostKeyChecking=yes" in ssh_log
    assert (
        "/usr/bin/sudo -n -- /usr/bin/install -o root -g root -m 0644 /dev/stdin "
        "'/etc/systemd/system/signal-ledger-cloudflared.service'"
    ) in ssh_log
    assert "systemctl daemon-reload" in ssh_log
    assert "systemctl disable --now signal-ledger-cloudflared.service" in ssh_log
    assert "systemctl is-active --quiet signal-ledger-cloudflared.service" in ssh_log
    assert hashlib.sha256(UNIT.read_bytes()).hexdigest() in ssh_log


def test_update_rejects_remote_command_arguments() -> None:
    result = subprocess.run(  # noqa: S603
        [str(SCRIPT), "--host", "attacker.example"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "no command, host, URL, or path arguments" in result.stderr


def test_update_fails_closed_when_ssh_fails(tmp_path: Path) -> None:
    result, _, _ = _run(tmp_path, ssh_exit=7)

    assert result.returncode == 2
    assert "fixed host unit update failed" in result.stderr
