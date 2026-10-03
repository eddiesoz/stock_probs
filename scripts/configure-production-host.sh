#!/usr/bin/env bash
# shellcheck disable=SC2034
# Install operator-supplied production configuration on the fixed Signal Ledger host.
# This runs after Terraform/cloud-init and never enables the public tunnel.
set -euo pipefail

readonly REMOTE_USER="signalops"
readonly REMOTE_LOCK="/var/lib/signal-ledger/deploy.lock"
readonly REMOTE_APP_ENV="/etc/signal-ledger/app.env"
readonly REMOTE_TUNNEL_TOKEN="/etc/cloudflared/tunnel.token"
readonly REMOTE_APP_UPLOAD="/etc/signal-ledger/.app.env.upload"
readonly REMOTE_TUNNEL_UPLOAD="/etc/cloudflared/.tunnel.token.upload"
readonly REMOTE_APP_STAGE="/etc/signal-ledger/.app.env.staged"
readonly REMOTE_TUNNEL_STAGE="/etc/cloudflared/.tunnel.token.staged"
readonly TUNNEL_UNIT="signal-ledger-cloudflared.service"
readonly MAX_APP_ENV_BYTES=$((64 * 1024))
readonly MAX_TUNNEL_TOKEN_BYTES=16384
readonly PUBLIC_ORIGIN="https://ledger.jtmb.cc"
readonly GITHUB_REDIRECT_URI="https://ledger.jtmb.cc/api/v1/auth/github/callback"
readonly OWNER_GITHUB_ID="86915618"

fail() {
  printf 'configure-production-host: %s\n' "$1" >&2
  exit 2
}

usage() {
  cat >&2 <<'EOF'
Usage:
  configure-production-host.sh --host IPV4 --identity-file FILE --known-hosts-file FILE \
    --app-env-file FILE --tunnel-token-file FILE

  configure-production-host.sh --host IPV4 --identity-file FILE --known-hosts-file FILE \
    --generate-app-env-file FILE --github-client-id-file FILE \
    --github-client-secret-file FILE --tunnel-token-file FILE

The app and tunnel files must be regular local files with no group/other permissions.
The remote host and all destination paths are fixed. The tunnel remains disabled.
EOF
}

host=""
identity_file=""
known_hosts_file=""
app_env_file=""
tunnel_token_file=""
generated_app_env_file=""
github_client_id_file=""
github_client_secret_file=""

while (($# > 0)); do
  case "$1" in
    --host)
      (($# >= 2)) || fail '--host requires a value'
      host="$2"
      shift 2
      ;;
    --identity-file)
      (($# >= 2)) || fail '--identity-file requires a path'
      identity_file="$2"
      shift 2
      ;;
    --known-hosts-file)
      (($# >= 2)) || fail '--known-hosts-file requires a path'
      known_hosts_file="$2"
      shift 2
      ;;
    --app-env-file)
      (($# >= 2)) || fail '--app-env-file requires a path'
      app_env_file="$2"
      shift 2
      ;;
    --tunnel-token-file)
      (($# >= 2)) || fail '--tunnel-token-file requires a path'
      tunnel_token_file="$2"
      shift 2
      ;;
    --generate-app-env-file)
      (($# >= 2)) || fail '--generate-app-env-file requires a path'
      generated_app_env_file="$2"
      shift 2
      ;;
    --github-client-id-file)
      (($# >= 2)) || fail '--github-client-id-file requires a path'
      github_client_id_file="$2"
      shift 2
      ;;
    --github-client-secret-file)
      (($# >= 2)) || fail '--github-client-secret-file requires a path'
      github_client_secret_file="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      usage
      fail "unknown option: $1"
      ;;
  esac
done

[[ "$host" =~ ^[0-9]+(\.[0-9]+){3}$ ]] || fail '--host must be an IPv4 address'
IFS=. read -r octet_a octet_b octet_c octet_d <<< "$host"
for octet in "$octet_a" "$octet_b" "$octet_c" "$octet_d"; do
  [[ "$octet" =~ ^[0-9]{1,3}$ ]] && ((10#$octet <= 255)) || fail '--host contains an invalid IPv4 octet'
done

[[ -n "$identity_file" ]] || fail '--identity-file is required'
[[ -n "$known_hosts_file" ]] || fail '--known-hosts-file is required'
[[ -n "$tunnel_token_file" ]] || fail '--tunnel-token-file is required'
if [[ -n "$generated_app_env_file" ]]; then
  [[ -z "$app_env_file" ]] || fail '--app-env-file cannot be combined with --generate-app-env-file'
  [[ -n "$github_client_id_file" ]] || fail '--github-client-id-file is required when generating app.env'
  [[ -n "$github_client_secret_file" ]] || fail '--github-client-secret-file is required when generating app.env'
else
  [[ -n "$app_env_file" ]] || fail '--app-env-file is required'
  [[ -z "$github_client_id_file" && -z "$github_client_secret_file" ]] || \
    fail 'OAuth client files require --generate-app-env-file'
fi

require_private_file() {
  local path="$1"
  local label="$2"
  [[ -n "$path" && "$path" != *$'\n'* && "$path" != *$'\r'* ]] || fail "$label path is invalid"
  [[ -L "$path" || ! -f "$path" ]] && fail "$label must be a regular non-symlink file"
  local mode
  mode="$(stat -c '%a' -- "$path")" || fail "could not stat $label"
  (( (8#$mode & 077) == 0 )) || fail "$label must not be group/other-readable"
}

require_private_file "$identity_file" 'SSH identity file'
require_private_file "$known_hosts_file" 'known-hosts file'
require_private_file "$tunnel_token_file" 'tunnel token file'

if [[ -n "$generated_app_env_file" ]]; then
  [[ "$generated_app_env_file" != *$'\n'* && "$generated_app_env_file" != *$'\r'* ]] || \
    fail 'generated app.env path is invalid'
  [[ ! -e "$generated_app_env_file" && ! -L "$generated_app_env_file" ]] || \
    fail 'generated app.env destination already exists'
  require_private_file "$github_client_id_file" 'GitHub client ID file'
  require_private_file "$github_client_secret_file" 'GitHub client secret file'
  command -v python3 >/dev/null 2>&1 || fail 'python3 is required'
  python3 - "$github_client_id_file" "$github_client_secret_file" "$generated_app_env_file" \
    "$PUBLIC_ORIGIN" "$GITHUB_REDIRECT_URI" "$OWNER_GITHUB_ID" <<'PY'
from __future__ import annotations

import os
import secrets
import stat
import sys
from pathlib import Path

client_id_path = Path(sys.argv[1])
client_secret_path = Path(sys.argv[2])
destination = sys.argv[3]
origin = sys.argv[4]
redirect_uri = sys.argv[5]
owner_id = sys.argv[6]

def read_private_value(path: Path, label: str) -> str:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise SystemExit(f"{label}_file_invalid") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise SystemExit(f"{label}_file_invalid")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            value = stream.read(513)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(value) > 512:
        raise SystemExit(f"{label}_value_too_large")
    if value.endswith(b"\n"):
        value = value[:-1]
    if not value or any(byte < 0x21 or byte > 0x7E for byte in value):
        raise SystemExit(f"{label}_value_invalid")
    return value.decode("ascii")

client_id = read_private_value(client_id_path, "github_client_id")
client_secret = read_private_value(client_secret_path, "github_client_secret")
dotenv_safe_bytes = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
if any(byte not in dotenv_safe_bytes for byte in client_id.encode("ascii")):
    raise SystemExit("github_client_id_value_invalid")
if any(byte not in dotenv_safe_bytes for byte in client_secret.encode("ascii")):
    raise SystemExit("github_client_secret_value_invalid")
if len(client_id) > 200 or len(client_secret) > 512:
    raise SystemExit("github_client_value_too_large")
if not owner_id.isdigit() or not origin.startswith("https://"):
    raise SystemExit("fixed_production_identity_invalid")

parent = Path(destination).parent
if not parent.is_dir() or parent.is_symlink():
    raise SystemExit("generated_app_env_parent_invalid")
if Path(destination).exists() or Path(destination).is_symlink():
    raise SystemExit("generated_app_env_exists")

content = (
    "STOCK_PROBS_AUTH_MODE=github\n"
    f"STOCK_PROBS_PUBLIC_ORIGIN={origin}\n"
    "STOCK_PROBS_AUTH_COOKIE_SECURE=1\n"
    f"STOCK_PROBS_AUTH_SESSION_SECRET={secrets.token_urlsafe(48)}\n"
    f"STOCK_PROBS_GITHUB_CLIENT_ID={client_id}\n"
    f"STOCK_PROBS_GITHUB_CLIENT_SECRET={client_secret}\n"
    f"STOCK_PROBS_GITHUB_REDIRECT_URI={redirect_uri}\n"
    f"STOCK_PROBS_OWNER_GITHUB_ID={owner_id}\n"
    # Host-published requests arrive from the dedicated Compose bridge gateway. Keep the
    # generated operator settings aligned with compose.production.yaml's fixed IPAM contract.
    "STOCK_PROBS_TRUSTED_PROXY_HOSTS=127.0.0.1,::1,localhost,172.30.219.1\n"
)
destination_path = Path(destination)
temporary = destination_path.with_name(f".{destination_path.name}.staging-{secrets.token_hex(8)}")
descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
try:
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content.encode("ascii"))
        stream.flush()
        os.fsync(stream.fileno())
    try:
        # A hard link gives the generated file an atomic name without replacing a file that
        # appeared after the initial destination check.
        os.link(temporary, destination_path)
    except FileExistsError as exc:
        raise SystemExit("generated_app_env_exists") from exc
finally:
    try:
        temporary.unlink()
    except FileNotFoundError:
        pass
PY
  app_env_file="$generated_app_env_file"
fi

require_private_file "$app_env_file" 'app.env file'

file_size() {
  stat -c '%s' -- "$1"
}

app_env_size="$(file_size "$app_env_file")" || fail 'could not determine app.env size'
(( app_env_size > 0 && app_env_size <= MAX_APP_ENV_BYTES )) || \
  fail 'app.env size is outside the bounded range'

tunnel_token_size="$(file_size "$tunnel_token_file")" || fail 'could not determine tunnel token size'
(( tunnel_token_size > 0 && tunnel_token_size <= MAX_TUNNEL_TOKEN_BYTES )) || \
  fail 'tunnel token size is outside the bounded range'
# Cloudflare returns the token as one line. Allow its final newline, but reject controls that
# could turn a credential upload into a second record or an unexpected shell input.
if ! python3 - "$tunnel_token_file" <<'PY'
from pathlib import Path
import sys

value = Path(sys.argv[1]).read_bytes()
if value.endswith(b"\n"):
    value = value[:-1]
if not value or b"\n" in value or b"\r" in value or b"\x00" in value:
    raise SystemExit(1)
PY
then
  fail 'tunnel token must contain one line with no control bytes and an optional final newline'
fi

command -v ssh >/dev/null 2>&1 || fail 'ssh is required'
command -v sha256sum >/dev/null 2>&1 || fail 'sha256sum is required'
command -v python3 >/dev/null 2>&1 || fail 'python3 is required'

readonly remote_target="${REMOTE_USER}@${host}"
readonly ssh_options=(
  -T
  -o BatchMode=yes
  -o StrictHostKeyChecking=yes
  -o IdentitiesOnly=yes
  -o ClearAllForwardings=yes
  -o ConnectTimeout=10
  -o UserKnownHostsFile="$known_hosts_file"
  -i "$identity_file"
)
remote_ssh() {
  # The command is a repository-owned Python helper. User values are sent as bounded binary input
  # or validated hexadecimal arguments, never as shell syntax or remote paths.
  ssh "${ssh_options[@]}" "$remote_target" "$1"
}

read -r -d '' remote_config_python <<'PY' || true
import fcntl
import hashlib
import os
import stat
import struct
import subprocess
import sys

TRANSACTION_NAME = "signal-ledger-configure-transaction"
LOCK_FILE = "/var/lib/signal-ledger/deploy.lock"
APP_ENV = "/etc/signal-ledger/app.env"
TUNNEL_TOKEN = "/etc/cloudflared/tunnel.token"
APP_UPLOAD = "/etc/signal-ledger/.app.env.upload"
TUNNEL_UPLOAD = "/etc/cloudflared/.tunnel.token.upload"
APP_STAGE = "/etc/signal-ledger/.app.env.staged"
TUNNEL_STAGE = "/etc/cloudflared/.tunnel.token.staged"
TUNNEL_UNIT = "signal-ledger-cloudflared.service"
MAX_APP_BYTES = 64 * 1024
MAX_TOKEN_BYTES = 16 * 1024

owned_paths = []


def fail(message):
    raise SystemExit(message)


def run(argv):
    try:
        subprocess.run(argv, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("remote_command_failed") from exc


def status(argv):
    try:
        return subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    except OSError as exc:
        raise RuntimeError("remote_command_failed") from exc


def read_exact(size):
    chunks = []
    remaining = size
    while remaining:
        chunk = sys.stdin.buffer.read(min(remaining, 1024 * 1024))
        if not chunk:
            fail("input_truncated")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_blob(limit):
    (size,) = struct.unpack("!Q", read_exact(8))
    if not 0 < size <= limit:
        fail("input_size_invalid")
    return read_exact(size)


def reject_symlink(path):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode):
        fail("destination_symlink")


def require_absent(path):
    try:
        os.lstat(path)
    except FileNotFoundError:
        return
    fail("staging_path_exists")


def write_owned(path, value):
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    owned_paths.append(path)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        raise


def move_to_stage(source, stage):
    require_absent(stage)
    # Link-then-unlink keeps a concurrent stale stage from being overwritten between the
    # absence check and publication. Both paths are on the fixed root-owned filesystem.
    os.link(source, stage, follow_symlinks=False)
    owned_paths.append(stage)
    os.unlink(source)
    owned_paths.remove(source)


def publish(stage, destination, uid, gid):
    reject_symlink(destination)
    os.chown(stage, uid, gid)
    os.chmod(stage, 0o600)
    os.replace(stage, destination)
    owned_paths.remove(stage)


def digest(path):
    value = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def verify_tunnel_closed():
    if status(["/usr/bin/systemctl", "is-enabled", "--quiet", TUNNEL_UNIT]) == 0:
        fail("tunnel_enabled")
    if status(["/usr/bin/systemctl", "is-active", "--quiet", TUNNEL_UNIT]) == 0:
        fail("tunnel_active")


def operation(app_value, token_value):
    if not os.path.isdir(os.path.dirname(APP_ENV)) or not os.path.isdir(os.path.dirname(TUNNEL_TOKEN)):
        fail("configuration_directory_missing")
    run(["/usr/bin/systemctl", "cat", TUNNEL_UNIT])
    # Close the public route while the lock is held, before any credential bytes are written.
    run(["/usr/bin/systemctl", "disable", "--now", TUNNEL_UNIT])
    verify_tunnel_closed()

    write_owned(APP_UPLOAD, app_value)
    move_to_stage(APP_UPLOAD, APP_STAGE)
    publish(APP_STAGE, APP_ENV, 0, 0)

    write_owned(TUNNEL_UPLOAD, token_value)
    move_to_stage(TUNNEL_UPLOAD, TUNNEL_STAGE)
    import pwd

    cloudflared = pwd.getpwnam("cloudflared")
    publish(TUNNEL_STAGE, TUNNEL_TOKEN, cloudflared.pw_uid, cloudflared.pw_gid)

    expected_app = hashlib.sha256(app_value).hexdigest()
    expected_token = hashlib.sha256(token_value).hexdigest()
    if digest(APP_ENV) != expected_app or digest(TUNNEL_TOKEN) != expected_token:
        fail("remote_hash_mismatch")
    verify_tunnel_closed()


def main():
    lock_descriptor = None
    acquired = False
    try:
        lock_descriptor = os.open(
            LOCK_FILE, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o640
        )
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SystemExit("deployment_busy") from exc
        acquired = True
        app_value = read_blob(MAX_APP_BYTES)
        token_value = read_blob(MAX_TOKEN_BYTES)
        operation(app_value, token_value)
        sys.stdout.write("CONFIGURED\n")
    except SystemExit:
        raise
    except Exception as exc:
        raise SystemExit("remote_operation_failed") from exc
    finally:
        for path in reversed(owned_paths):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
        if lock_descriptor is not None:
            if acquired:
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            os.close(lock_descriptor)


main()
PY
remote_config_command="$(printf '%q ' /usr/bin/python3 -c "$remote_config_python")"

send_config_payload() {
  python3 - "$app_env_file" "$tunnel_token_file" <<'PY'
import os
import stat
import struct
import sys

for name in sys.argv[1:]:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size <= 0:
            raise SystemExit("local_upload_file_invalid")
        sys.stdout.buffer.write(struct.pack("!Q", info.st_size))
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            while block := stream.read(1024 * 1024):
                sys.stdout.buffer.write(block)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
sys.stdout.buffer.flush()
PY
}

remote_result="$(send_config_payload | remote_ssh "sudo -n $remote_config_command")" || \
  fail 'remote configuration transaction failed'
[[ "$remote_result" == 'CONFIGURED' ]] || fail 'remote configuration transaction was not confirmed'
printf 'Production host configuration installed; the Cloudflare tunnel remains disabled.\n'
