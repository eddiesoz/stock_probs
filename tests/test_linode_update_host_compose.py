"""Checks for the fixed-host reviewed Compose updater."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "infra" / "linode" / "update-host-compose.sh"


def _remote_python() -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    marker = "REMOTE_PYTHON=\"$(cat <<'PYTHON'\n"
    start = source.index(marker) + len(marker)
    return source[start : source.index("\nPYTHON\n)\"", start)]


def test_help_describes_fixed_review_inputs_and_accepts_no_mutation_arguments() -> None:
    result = subprocess.run(  # noqa: S603
        [str(SCRIPT), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--reviewed-revision SHA --compose-sha256 SHA256" in result.stderr
    assert "origin/main" in result.stderr

    rejected = subprocess.run(  # noqa: S603
        [str(SCRIPT), "--host", "attacker.example"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode == 2
    assert "no command, host, URL, or path arguments" in rejected.stderr


def test_local_source_gate_requires_clean_exact_main_and_reviewed_checksum() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'EXPECTED_REPOSITORY="https://github.com/eddiesoz/stock_probs.git"' in source
    assert 'git -C "$ROOT" status --porcelain --untracked-files=normal' in source
    assert 'git -C "$ROOT" ls-remote --exit-code --refs' in source
    assert '[[ "$head_revision" == "$remote_main" ]]' in source
    assert '[[ "$head_revision" == "$reviewed_revision" ]]' in source
    assert '[[ "$compose_sha256" == "$reviewed_compose_sha256" ]]' in source
    assert '100644\ blob\ *$' in source


def test_fixed_host_upload_uses_pinned_operator_ssh_and_only_compose_bytes() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'readonly REMOTE_HOST="45.79.180.32"' in source
    assert 'readonly REMOTE_USER="signalops"' in source
    assert 'readonly COMPOSE_SOURCE="$ROOT/compose.production.yaml"' in source
    assert 'StrictHostKeyChecking=yes' in source
    assert 'GlobalKnownHostsFile=/dev/null' in source
    assert 'REMOTE_TARGET" "$remote_command" \\' in source
    assert '<"$COMPOSE_SOURCE" >/dev/null 2>&1' in source
    assert "signal-ledger-deploy-helper" not in source


def test_remote_installer_is_valid_python_and_rejects_unsafe_targets() -> None:
    remote_python = _remote_python()
    ast.parse(remote_python)

    assert 'APP_DIRECTORY = "signal-ledger"' in remote_python
    assert 'COMPOSE_NAME = "compose.production.yaml"' in remote_python
    assert "os.O_NOFOLLOW" in remote_python
    assert "follow_symlinks=False" in remote_python
    assert "stat.S_IMODE(metadata.st_mode) != 0o644" in remote_python
    assert "metadata.st_nlink != 1" in remote_python
    assert "os.replace(" in remote_python
    assert "MAX_COMPOSE_BYTES = 1024 * 1024" in remote_python
    assert "compose_update_failed" in remote_python


def test_remote_installer_takes_the_deploy_helper_lock_before_target_access() -> None:
    remote_python = _remote_python()
    deploy_helper = (ROOT / "scripts" / "production-deploy-helper.py").read_text(
        encoding="utf-8"
    )

    assert 'STATE_DIRECTORY = "signal-ledger"' in remote_python
    assert 'VAR_DIRECTORY = "var"' in remote_python
    assert 'LIB_DIRECTORY = "lib"' in remote_python
    assert 'LOCK_NAME = "deploy.lock"' in remote_python
    assert 'STATE_ROOT = Path("/var/lib/signal-ledger")' in deploy_helper
    assert 'LOCK_FILE = STATE_ROOT / "deploy.lock"' in deploy_helper
    assert "fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)" in deploy_helper
    assert 'os.open(VAR_DIRECTORY, DIRECTORY_FLAGS, dir_fd=root_fd)' in remote_python
    assert 'os.open(LIB_DIRECTORY, DIRECTORY_FLAGS, dir_fd=var_fd)' in remote_python
    assert 'os.open(STATE_DIRECTORY, DIRECTORY_FLAGS, dir_fd=lib_fd)' in remote_python
    assert "os.open(LOCK_NAME, os.O_RDWR | os.O_NOFOLLOW, dir_fd=state_fd)" in remote_python
    assert "fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)" in remote_python
    assert "fcntl.flock(lock_fd, fcntl.LOCK_UN)" in remote_python
    lock_open = next(line for line in remote_python.splitlines() if "lock_fd = os.open" in line)
    assert "O_CREAT" not in lock_open
    assert "lock_metadata.st_uid != 0" in remote_python
    assert "lock_metadata.st_nlink != 1" in remote_python
    assert remote_python.index("fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)") < (
        remote_python.index("before = _target_metadata(app_fd)")
    )
    assert remote_python.index("fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)") < (
        remote_python.index("os.replace(")
    )
    assert remote_python.index("fcntl.flock(lock_fd, fcntl.LOCK_UN)") > remote_python.index(
        "os.replace("
    )


def test_remote_installer_does_not_restart_the_application_or_tunnel() -> None:
    remote_python = _remote_python()

    assert "docker" not in remote_python
    assert "systemctl" not in remote_python
    assert "Compose installed on the fixed host; current services and tunnel were not changed" in (
        SCRIPT.read_text(encoding="utf-8")
    )
