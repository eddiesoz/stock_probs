"""Focused tests for the code-driven production host and data-seed boundaries."""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import sqlite3
import stat
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIGURE = ROOT / "scripts" / "configure-production-host.sh"
SEED = ROOT / "scripts" / "seed-production-data.sh"


def _private_file(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    path.chmod(0o600)
    return path


def _ssh_test_tools(
    tmp_path: Path,
    *,
    app_file: Path | None = None,
    token_file: Path | None = None,
) -> tuple[dict[str, str], Path]:
    tool_dir = tmp_path / "bin"
    tool_dir.mkdir()
    log = tmp_path / "remote.log"
    ssh = tool_dir / "ssh"
    ssh.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'command="${!#}"\n'
        'printf \'%s\\n\' "$command" >> "$FAKE_REMOTE_LOG"\n'
        'if [[ "$command" == *"signal-ledger-configure-transaction"* ]]; then\n'
        "    cat >/dev/null\n"
        "    printf 'CONFIGURED\\n'\n"
        "    exit 0\n"
        "fi\n"
        'if [[ "$command" == *"signal-ledger-seed-transaction"* ]]; then\n'
        '    if [[ -n "${FAKE_RUNNING_APP:-}" ]]; then\n'
        "        printf 'production app container is running\\n' >&2\n"
        "        cat >/dev/null\n"
        "        exit 1\n"
        "    fi\n"
        "    cat >/dev/null\n"
        "    printf 'SEEDED\\n'\n"
        "    exit 0\n"
        "fi\n"
        'if [[ "$command" == *"docker image inspect"* ]]; then\n'
        '    printf \'%s|%s\\n\' "$FAKE_IMAGE_ID" "$FAKE_REVISION"\n'
        "fi\n"
        'if [[ "$command" == *"docker ps"* && -n "${FAKE_RUNNING_APP:-}" ]]; then\n'
        "    printf '%s\\n' \"$FAKE_RUNNING_APP\"\n"
        "fi\n"
        'if [[ "$command" == *"sha256sum \'/etc/signal-ledger/app.env\'"* ]]; then\n'
        '    sha256sum "$FAKE_APP_FILE" | awk \'{print $1 "  /etc/signal-ledger/app.env"}\'\n'
        "fi\n"
        'if [[ "$command" == *"sha256sum \'/etc/cloudflared/tunnel.token\'"* ]]; then\n'
        '    sha256sum "$FAKE_TOKEN_FILE" | awk '
        "'{print $1 \"  /etc/cloudflared/tunnel.token\"}'\n"
        "fi\n"
        'if [[ "$command" == *"integrity_check"* ]]; then\n'
        "    printf '%s\\n' \"$FAKE_REMOTE_METADATA\"\n"
        "fi\n"
    )
    ssh.chmod(0o700)
    scp = tool_dir / "scp"
    scp.write_text(
        '#!/usr/bin/env bash\nset -eu\nprintf \'scp %s\\n\' "$*" >> "$FAKE_REMOTE_LOG"\n'
    )
    scp.chmod(0o700)
    environment = os.environ.copy()
    environment["PATH"] = f"{tool_dir}:{environment['PATH']}"
    environment["FAKE_REMOTE_LOG"] = str(log)
    if app_file is not None:
        environment["FAKE_APP_FILE"] = str(app_file)
    if token_file is not None:
        environment["FAKE_TOKEN_FILE"] = str(token_file)
    return environment, log


def _connection_files(tmp_path: Path) -> tuple[Path, Path]:
    return (
        _private_file(tmp_path / "operator-key", b"operator-private-key"),
        _private_file(tmp_path / "known-hosts", b"[203.0.113.10]:22 ssh-ed25519 key"),
    )


def _run(
    script: Path, arguments: list[str], environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [str(script), *arguments],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _embedded_source(script: Path, variable: str) -> str:
    source = script.read_text()
    match = re.search(
        rf"(?:read -r -d '' )?{re.escape(variable)} <<'PY' \|\| true\n(.*?)\nPY\n",
        source,
        re.DOTALL,
    )
    assert match is not None
    return match.group(1)


def _framed_payload(*values: bytes) -> bytes:
    return b"".join(struct.pack("!Q", len(value)) + value for value in values)


def _systemctl_stub(tmp_path: Path) -> Path:
    stub = tmp_path / "systemctl"
    stub.write_text(
        '#!/bin/sh\ncase "$1" in\n  is-enabled|is-active) exit 1 ;;\n  *) exit 0 ;;\nesac\n'
    )
    stub.chmod(0o700)
    return stub


def _configure_helper_source(tmp_path: Path, systemctl: Path) -> str:
    source = _embedded_source(CONFIGURE, "remote_config_python")
    app_root = tmp_path / "etc" / "signal-ledger"
    tunnel_root = tmp_path / "etc" / "cloudflared"
    lock = repr(str(tmp_path / "deploy.lock"))
    app = repr(str(app_root / "app.env"))
    token = repr(str(tunnel_root / "tunnel.token"))
    app_upload = repr(str(app_root / ".app.env.upload"))
    token_upload = repr(str(tunnel_root / ".tunnel.token.upload"))
    app_stage = repr(str(app_root / ".app.env.staged"))
    token_stage = repr(str(tunnel_root / ".tunnel.token.staged"))
    replacements = {
        'LOCK_FILE = "/var/lib/signal-ledger/deploy.lock"': f"LOCK_FILE = {lock}",
        'APP_ENV = "/etc/signal-ledger/app.env"': f"APP_ENV = {app}",
        'TUNNEL_TOKEN = "/etc/cloudflared/tunnel.token"': f"TUNNEL_TOKEN = {token}",
        'APP_UPLOAD = "/etc/signal-ledger/.app.env.upload"': f"APP_UPLOAD = {app_upload}",
        'TUNNEL_UPLOAD = "/etc/cloudflared/.tunnel.token.upload"': (
            f"TUNNEL_UPLOAD = {token_upload}"
        ),
        'APP_STAGE = "/etc/signal-ledger/.app.env.staged"': f"APP_STAGE = {app_stage}",
        'TUNNEL_STAGE = "/etc/cloudflared/.tunnel.token.staged"': f"TUNNEL_STAGE = {token_stage}",
    }
    for old, new in replacements.items():
        assert old in source
        source = source.replace(old, new, 1)
    source = source.replace('"/usr/bin/systemctl"', repr(str(systemctl)))
    source = source.replace(
        'cloudflared = pwd.getpwnam("cloudflared")',
        'cloudflared = type("User", (), {"pw_uid": os.getuid(), "pw_gid": os.getgid()})()',
    )
    source = source.replace(
        "publish(APP_STAGE, APP_ENV, 0, 0)",
        "publish(APP_STAGE, APP_ENV, os.getuid(), os.getgid())",
    )
    app_root.mkdir(parents=True)
    tunnel_root.mkdir(parents=True)
    return source


def _seed_helper_source(tmp_path: Path, docker: Path) -> str:
    source = _embedded_source(SEED, "remote_seed_python")
    seed_root = tmp_path / "seed"
    lock = repr(str(tmp_path / "deploy.lock"))
    seed_dir = repr(str(seed_root))
    seed_final = repr(str(seed_root / "legacy.sqlite3"))
    seed_stage = repr(str(seed_root / ".legacy.sqlite3.staged"))
    replacements = {
        'LOCK_FILE = "/var/lib/signal-ledger/deploy.lock"': f"LOCK_FILE = {lock}",
        'SEED_DIR = "/var/lib/signal-ledger/seed"': f"SEED_DIR = {seed_dir}",
        'SEED_FINAL = "/var/lib/signal-ledger/seed/legacy.sqlite3"': f"SEED_FINAL = {seed_final}",
        'SEED_STAGE = "/var/lib/signal-ledger/seed/.legacy.sqlite3.staged"': (
            f"SEED_STAGE = {seed_stage}"
        ),
    }
    for old, new in replacements.items():
        assert old in source
        source = source.replace(old, new, 1)
    source = source.replace('"/usr/bin/docker"', repr(str(docker)))
    source = source.replace("    os.chown(path, 10001, 10001)\n", "    pass\n")
    return source


def test_configure_host_rejects_group_readable_app_env_before_ssh(tmp_path: Path) -> None:
    identity, known_hosts = _connection_files(tmp_path)
    app_env = tmp_path / "app.env"
    app_env.write_text("STOCK_PROBS_PUBLIC_ORIGIN=https://ledger.jtmb.cc\n")
    app_env.chmod(0o640)
    token = _private_file(tmp_path / "tunnel.token", b"token-value\n")
    environment, log = _ssh_test_tools(tmp_path, app_file=app_env, token_file=token)

    result = _run(
        CONFIGURE,
        [
            "--host",
            "203.0.113.10",
            "--identity-file",
            str(identity),
            "--known-hosts-file",
            str(known_hosts),
            "--app-env-file",
            str(app_env),
            "--tunnel-token-file",
            str(token),
        ],
        environment,
    )

    assert result.returncode != 0
    assert "app.env file must not be group/other-readable" in result.stderr
    assert not log.exists()


def test_configure_host_transfers_fixed_files_and_reasserts_tunnel_disabled(tmp_path: Path) -> None:
    identity, known_hosts = _connection_files(tmp_path)
    app_env = _private_file(tmp_path / "app.env", b"STOCK_PROBS_AUTH_MODE=github\n")
    token = _private_file(tmp_path / "tunnel.token", b"token-value\n")
    environment, log = _ssh_test_tools(tmp_path, app_file=app_env, token_file=token)

    result = _run(
        CONFIGURE,
        [
            "--host",
            "203.0.113.10",
            "--identity-file",
            str(identity),
            "--known-hosts-file",
            str(known_hosts),
            "--app-env-file",
            str(app_env),
            "--tunnel-token-file",
            str(token),
        ],
        environment,
    )
    commands = log.read_text().splitlines()

    assert result.returncode == 0, result.stderr
    assert "Production host configuration installed" in result.stdout
    joined = "\n".join(commands)
    assert "/etc/signal-ledger/app.env" in joined
    assert "/etc/cloudflared/tunnel.token" in joined
    assert "signal-ledger-configure-transaction" in joined
    assert "fcntl.flock" in joined
    assert '"disable", "--now"' in joined
    first_disable = joined.index('"disable", "--now"')
    first_upload = joined.index("write_owned(APP_UPLOAD")
    assert first_disable < first_upload
    assert ".app.env.upload" in joined
    assert ".tunnel.token.upload" in joined
    assert "O_EXCL" in joined
    assert "O_NOFOLLOW" in joined
    assert "sys.stdin.buffer" in joined
    assert "owned_paths.remove(stage)" in joined
    assert "os.unlink(path)" in joined
    assert not any(command.startswith("scp ") for command in commands)
    assert b"token-value" not in result.stdout.encode() + result.stderr.encode()


def test_configure_transaction_stops_at_a_preheld_deploy_lock(tmp_path: Path) -> None:
    systemctl = _systemctl_stub(tmp_path)
    source = _configure_helper_source(tmp_path, systemctl)
    lock_path = tmp_path / "deploy.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o640)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-c", source],
            input=_framed_payload(b"new-app", b"new-token"),
            capture_output=True,
            check=False,
        )
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    assert result.returncode != 0
    assert b"deployment_busy" in result.stderr
    for relative in (
        "etc/signal-ledger/app.env",
        "etc/signal-ledger/.app.env.upload",
        "etc/signal-ledger/.app.env.staged",
        "etc/cloudflared/tunnel.token",
        "etc/cloudflared/.tunnel.token.upload",
        "etc/cloudflared/.tunnel.token.staged",
    ):
        assert not (tmp_path / relative).exists()


def test_configure_transaction_retry_has_no_upload_or_stage_residue(tmp_path: Path) -> None:
    systemctl = _systemctl_stub(tmp_path)
    source = _configure_helper_source(tmp_path, systemctl)
    app_path = tmp_path / "etc" / "signal-ledger" / "app.env"
    token_path = tmp_path / "etc" / "cloudflared" / "tunnel.token"
    for app_value, token_value in (
        (b"first-app", b"first-token"),
        (b"second-app", b"second-token"),
    ):
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-c", source],
            input=_framed_payload(app_value, token_value),
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr.decode()
        assert result.stdout == b"CONFIGURED\n"
        assert app_path.read_bytes() == app_value
        assert token_path.read_bytes() == token_value
        for path in (
            app_path.with_name(".app.env.upload"),
            app_path.with_name(".app.env.staged"),
            token_path.with_name(".tunnel.token.upload"),
            token_path.with_name(".tunnel.token.staged"),
        ):
            assert not path.exists()


def test_seed_transaction_stops_at_a_preheld_deploy_lock(tmp_path: Path) -> None:
    source = _seed_helper_source(tmp_path, tmp_path / "docker")
    lock_path = tmp_path / "deploy.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o640)
    revision = "c" * 40
    image_id = "sha256:" + "b" * 64
    expected = "a" * 64 + "|ok|6|1|1|1|1|0|1|0"
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-c", source, revision, image_id, expected],
            input=_framed_payload(b"snapshot"),
            capture_output=True,
            check=False,
        )
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    assert result.returncode != 0
    assert b"deployment_busy" in result.stderr
    assert not (tmp_path / "seed" / "legacy.sqlite3").exists()
    assert not (tmp_path / "seed" / ".legacy.sqlite3.staged").exists()


def test_configure_host_can_generate_private_production_app_env(tmp_path: Path) -> None:
    identity, known_hosts = _connection_files(tmp_path)
    client_id = _private_file(tmp_path / "github-client-id", b"123456\n")
    client_secret = _private_file(tmp_path / "github-client-secret", b"secret-value\n")
    generated = tmp_path / "app.env"
    token = _private_file(tmp_path / "tunnel.token", b"token-value\n")
    environment, log = _ssh_test_tools(tmp_path, app_file=generated, token_file=token)

    result = _run(
        CONFIGURE,
        [
            "--host",
            "203.0.113.10",
            "--identity-file",
            str(identity),
            "--known-hosts-file",
            str(known_hosts),
            "--generate-app-env-file",
            str(generated),
            "--github-client-id-file",
            str(client_id),
            "--github-client-secret-file",
            str(client_secret),
            "--tunnel-token-file",
            str(token),
        ],
        environment,
    )

    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(generated.stat().st_mode) == 0o600
    content = generated.read_text()
    assert "STOCK_PROBS_PUBLIC_ORIGIN=https://ledger.jtmb.cc" in content
    assert (
        "STOCK_PROBS_GITHUB_REDIRECT_URI=https://ledger.jtmb.cc/api/v1/auth/github/callback"
        in content
    )
    assert "STOCK_PROBS_OWNER_GITHUB_ID=86915618" in content
    assert "STOCK_PROBS_TRUSTED_PROXY_HOSTS=127.0.0.1,::1,localhost,172.30.219.1" in content
    assert "STOCK_PROBS_AUTH_SESSION_SECRET=" in content
    assert "secret-value" in content
    assert "secret-value" not in result.stdout + result.stderr
    assert log.exists()


def test_configure_host_rejects_compose_unsafe_generated_oauth_value(tmp_path: Path) -> None:
    identity, known_hosts = _connection_files(tmp_path)
    client_id = _private_file(tmp_path / "github-client-id", b"123456\n")
    client_secret = _private_file(tmp_path / "github-client-secret", b"secret$with#shell\n")
    generated = tmp_path / "app.env"
    token = _private_file(tmp_path / "tunnel.token", b"token-value\n")
    environment, log = _ssh_test_tools(tmp_path, app_file=generated, token_file=token)

    result = _run(
        CONFIGURE,
        [
            "--host",
            "203.0.113.10",
            "--identity-file",
            str(identity),
            "--known-hosts-file",
            str(known_hosts),
            "--generate-app-env-file",
            str(generated),
            "--github-client-id-file",
            str(client_id),
            "--github-client-secret-file",
            str(client_secret),
            "--tunnel-token-file",
            str(token),
        ],
        environment,
    )

    assert result.returncode != 0
    assert "github_client_secret_value_invalid" in result.stderr
    assert not generated.exists()
    assert not log.exists()


def _legacy_snapshot(path: Path) -> str:
    database = sqlite3.connect(path)
    database.executescript(
        "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);"
        "CREATE TABLE search_events(id INTEGER);"
        "CREATE TABLE forecast_runs(id INTEGER);"
        "CREATE TABLE forecast_inputs(id INTEGER);"
        "CREATE TABLE forecast_results(id INTEGER);"
        "CREATE TABLE outcomes(id INTEGER);"
        "CREATE TABLE instrument_list_items(kind TEXT);"
    )
    database.executemany(
        "INSERT INTO schema_migrations VALUES (?, 'test')",
        ((version,) for version in range(1, 7)),
    )
    database.executemany("INSERT INTO search_events VALUES (?)", ((value,) for value in (1, 2)))
    database.execute("INSERT INTO forecast_runs VALUES (1)")
    database.execute("INSERT INTO forecast_inputs VALUES (1)")
    database.executemany(
        "INSERT INTO forecast_results VALUES (?)", ((value,) for value in (1, 2, 3))
    )
    database.executemany(
        "INSERT INTO instrument_list_items VALUES (?)",
        ((kind,) for kind in ("portfolio", "watchlist", "watchlist")),
    )
    database.commit()
    database.close()
    path.chmod(0o600)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_seed_rejects_snapshot_hash_before_ssh(tmp_path: Path) -> None:
    identity, known_hosts = _connection_files(tmp_path)
    snapshot = _private_file(tmp_path / "snapshot.sqlite3", b"not sqlite")
    environment, log = _ssh_test_tools(tmp_path)

    result = _run(
        SEED,
        [
            "--host",
            "203.0.113.10",
            "--identity-file",
            str(identity),
            "--known-hosts-file",
            str(known_hosts),
            "--snapshot",
            str(snapshot),
            "--snapshot-sha256",
            "0" * 64,
            "--revision",
            "a" * 40,
            "--image-id",
            "sha256:" + "b" * 64,
        ],
        environment,
    )

    assert result.returncode != 0
    assert "local snapshot verification failed" in result.stderr
    assert not log.exists()


def test_seed_verifies_reviewed_image_and_copies_as_runtime_uid(tmp_path: Path) -> None:
    identity, known_hosts = _connection_files(tmp_path)
    snapshot = tmp_path / "snapshot.sqlite3"
    snapshot_hash = _legacy_snapshot(snapshot)
    revision = "a" * 40
    image_id = "sha256:" + "b" * 64
    remote_metadata = f"{snapshot_hash}|ok|6|2|1|1|3|0|1|2"
    environment, log = _ssh_test_tools(tmp_path)
    environment.update(
        {
            "FAKE_IMAGE_ID": image_id,
            "FAKE_REVISION": revision,
            "FAKE_REMOTE_METADATA": remote_metadata,
        }
    )

    result = _run(
        SEED,
        [
            "--host",
            "203.0.113.10",
            "--identity-file",
            str(identity),
            "--known-hosts-file",
            str(known_hosts),
            "--snapshot",
            str(snapshot),
            "--snapshot-sha256",
            snapshot_hash,
            "--revision",
            revision,
            "--image-id",
            image_id,
        ],
        environment,
    )
    commands = log.read_text().splitlines()
    joined = "\n".join(commands)

    assert result.returncode == 0, result.stderr
    assert "Legacy snapshot seeded" in result.stdout
    assert "signal-ledger-seed-transaction" in joined
    assert "fcntl.flock" in joined
    assert '"image"' in joined
    assert '"inspect"' in joined
    assert "signal-ledger_signal-ledger-data" in joined
    assert "--pull=never" in joined
    assert '"--user"' in joined
    assert "10001:10001" in joined
    assert "O_EXCL" in joined
    assert "O_NOFOLLOW" in joined
    assert "sys.stdin.buffer" in joined
    assert ".legacy.sqlite3.staged" in joined
    assert "/var/lib/signal-ledger/seed/legacy.sqlite3" in joined
    assert "staged_database_verification_failed" in joined
    assert joined.index("verify_stage") < joined.index("copy_to_volume")
    assert "volume_staging_verification_failed" in joined
    assert joined.index("verify_volume_staging") < joined.index("publish_volume")
    assert "os.unlink(SEED_STAGE)" in joined
    assert image_id in joined
    assert "signal-ledger:sha-" not in joined
    assert not any(line.startswith("scp ") for line in commands)


def test_seed_stream_uses_exclusive_no_follow_before_tracking_path() -> None:
    source = SEED.read_text()
    open_index = source.index(
        "descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW"
    )
    ownership_index = source.index("owned_paths.append(path)", open_index)
    assert open_index < ownership_index
    assert 'SEED_FINAL = "/var/lib/signal-ledger/seed/legacy.sqlite3"' in source


def test_seed_failed_verification_cleans_stage_and_allows_retry(tmp_path: Path) -> None:
    expected = "a" * 64 + "|ok|6|1|1|1|1|0|1|0"
    marker = tmp_path / "verify-once.marker"
    fake_target = tmp_path / "published-target"
    docker = tmp_path / "docker"
    docker.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "expected = os.environ['FAKE_EXPECTED']\n"
        "if args[:2] == ['image', 'inspect']:\n"
        "    print(os.environ['FAKE_IMAGE_ID'] + '|' + os.environ['FAKE_REVISION'])\n"
        "    raise SystemExit(0)\n"
        "if args and args[0] == 'ps':\n"
        "    raise SystemExit(0)\n"
        "if args[:2] == ['volume', 'inspect']:\n"
        "    raise SystemExit(0)\n"
        "if args[:2] == ['volume', 'create']:\n"
        "    raise SystemExit(0)\n"
        "if not args or args[0] != 'run':\n"
        "    raise SystemExit(2)\n"
        "code = args[args.index('-c') + 1] if '-c' in args else ''\n"
        "if 'sys.exit(1 if os.path.lexists' in code:\n"
        "    raise SystemExit(0)\n"
        "if 'digest = hashlib.sha256()' in code:\n"
        "    if not Path(os.environ['FAKE_MARKER']).exists():\n"
        "        Path(os.environ['FAKE_MARKER']).touch()\n"
        "        print('mismatch')\n"
        "    else:\n"
        "        print(expected)\n"
        "    raise SystemExit(0)\n"
        "if 'os.link(temporary, target)' in code:\n"
        "    Path(os.environ['FAKE_TARGET']).write_bytes(b'published')\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(0)\n"
    )
    docker.chmod(0o700)
    source = _seed_helper_source(tmp_path, docker)
    image_id = "sha256:" + "b" * 64
    revision = "c" * 40
    environment = os.environ.copy()
    environment.update(
        {
            "FAKE_EXPECTED": expected,
            "FAKE_IMAGE_ID": image_id,
            "FAKE_REVISION": revision,
            "FAKE_MARKER": str(marker),
            "FAKE_TARGET": str(fake_target),
        }
    )
    payload = _framed_payload(b"verified snapshot")

    failed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", source, revision, image_id, expected],
        input=payload,
        env=environment,
        capture_output=True,
        check=False,
    )
    assert failed.returncode != 0
    assert b"staged_database_verification_failed" in failed.stderr
    assert not (tmp_path / "seed" / ".legacy.sqlite3.staged").exists()
    assert not fake_target.exists()

    retried = subprocess.run(  # noqa: S603
        [sys.executable, "-c", source, revision, image_id, expected],
        input=payload,
        env=environment,
        capture_output=True,
        check=False,
    )
    assert retried.returncode == 0, retried.stderr.decode()
    assert retried.stdout == b"SEEDED\n"
    assert fake_target.read_bytes() == b"published"
    assert not (tmp_path / "seed" / ".legacy.sqlite3.staged").exists()


@pytest.mark.parametrize("existing_kind", ("file", "symlink"))
def test_seed_publish_does_not_remove_existing_database(tmp_path: Path, existing_kind: str) -> None:
    source = SEED.read_text()
    publish_python = re.search(r"PUBLISH_CODE = r'''(.*?)'''", source, re.DOTALL)
    assert publish_python is not None
    publish_python = publish_python.group(1)
    target_path = tmp_path / "stock_probs.sqlite3"
    staging_path = Path(f"{target_path}.seed-staging")
    staging_path.write_bytes(b"staged")
    actual_path = tmp_path / "existing.sqlite3"
    if existing_kind == "file":
        target_path.write_bytes(b"existing")
    else:
        actual_path.write_bytes(b"existing")
        target_path.symlink_to(actual_path)

    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", publish_python, str(target_path)],
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    if existing_kind == "file":
        assert target_path.read_bytes() == b"existing"
    else:
        assert target_path.is_symlink()
        assert actual_path.read_bytes() == b"existing"
    assert not Path(f"{target_path}.seed-staging").exists()


def test_seed_copy_does_not_remove_existing_staging_file(tmp_path: Path) -> None:
    source = SEED.read_text()
    copy_python = re.search(r"COPY_CODE = r'''(.*?)'''", source, re.DOTALL)
    assert copy_python is not None
    copy_python = copy_python.group(1)
    source_path = tmp_path / "source.sqlite3"
    source_path.write_bytes(b"replacement")
    target_path = tmp_path / "stock_probs.sqlite3"
    staging_path = Path(f"{target_path}.seed-staging")
    staging_path.write_bytes(b"existing-stage")

    copy_python = copy_python.replace("/seed/legacy.sqlite3", str(source_path))
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", copy_python, str(target_path)],
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert staging_path.read_bytes() == b"existing-stage"
    assert not target_path.exists()


def test_seed_refuses_running_app_before_upload(tmp_path: Path) -> None:
    identity, known_hosts = _connection_files(tmp_path)
    snapshot = tmp_path / "snapshot.sqlite3"
    snapshot_hash = _legacy_snapshot(snapshot)
    environment, log = _ssh_test_tools(tmp_path)
    environment.update(
        {
            "FAKE_IMAGE_ID": "sha256:" + "b" * 64,
            "FAKE_REVISION": "a" * 40,
            "FAKE_RUNNING_APP": "container-id",
        }
    )

    result = _run(
        SEED,
        [
            "--host",
            "203.0.113.10",
            "--identity-file",
            str(identity),
            "--known-hosts-file",
            str(known_hosts),
            "--snapshot",
            str(snapshot),
            "--snapshot-sha256",
            snapshot_hash,
            "--revision",
            "a" * 40,
            "--image-id",
            "sha256:" + "b" * 64,
        ],
        environment,
    )

    assert result.returncode != 0
    assert "production app container is running" in result.stderr
    assert not any(line.startswith("scp ") for line in log.read_text().splitlines())


@pytest.mark.parametrize("script", (CONFIGURE, SEED))
def test_operation_scripts_use_strict_ssh_and_fixed_destinations(script: Path) -> None:
    source = script.read_text()
    assert "StrictHostKeyChecking=yes" in source
    assert "IdentitiesOnly=yes" in source
    assert "ClearAllForwardings=yes" in source
    assert "eval " not in source
    assert "signalops" in source
