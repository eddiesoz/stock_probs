#!/usr/bin/env bash
# Install the reviewed Compose file on the fixed host without changing running services.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly COMPOSE_SOURCE="$ROOT/compose.production.yaml"
readonly EXPECTED_REPOSITORY="https://github.com/eddiesoz/stock_probs.git"
readonly MAIN_BRANCH="main"
readonly REMOTE_HOST="45.79.180.32"
readonly REMOTE_USER="signalops"
readonly REMOTE_TARGET="${REMOTE_USER}@${REMOTE_HOST}"
readonly DEFAULT_IDENTITY_FILE="${HOME}/.ssh/signal-ledger-operator-2026"
readonly DEFAULT_KNOWN_HOSTS_FILE="${XDG_CONFIG_HOME:-${HOME}/.config}/signal-ledger/credentials/linode-known-hosts"

fail() {
  printf 'update-host-compose: %s\n' "$1" >&2
  exit 2
}

usage() {
  cat >&2 <<'EOF'
Usage: update-host-compose.sh --reviewed-revision SHA --compose-sha256 SHA256

The repository, host, operator account, target path, and remote command are fixed. The
worktree must be clean and exactly match origin/main. Supply the reviewed commit SHA and
the SHA-256 of its tracked compose.production.yaml file. For the local operator checkout
only, set SIGNAL_LEDGER_OPERATOR_IDENTITY_FILE or SIGNAL_LEDGER_KNOWN_HOSTS_FILE when the
defaults are not available.
EOF
}

reviewed_revision=""
reviewed_compose_sha256=""
while (($# > 0)); do
  case "$1" in
    --reviewed-revision)
      (($# >= 2)) || fail '--reviewed-revision requires a value'
      [[ -z "$reviewed_revision" ]] || fail '--reviewed-revision may be supplied once'
      reviewed_revision="$2"
      shift 2
      ;;
    --compose-sha256)
      (($# >= 2)) || fail '--compose-sha256 requires a value'
      [[ -z "$reviewed_compose_sha256" ]] || fail '--compose-sha256 may be supplied once'
      reviewed_compose_sha256="$2"
      shift 2
      ;;
    --help|-h)
      (($# == 1)) || fail 'no extra arguments are accepted'
      usage
      exit 0
      ;;
    *)
      usage
      fail 'no command, host, URL, or path arguments are accepted'
      ;;
  esac
done

[[ "$reviewed_revision" =~ ^[0-9a-f]{40}$ ]] || \
  fail '--reviewed-revision must be a 40-character lowercase commit SHA'
[[ "$reviewed_compose_sha256" =~ ^[0-9a-f]{64}$ ]] || \
  fail '--compose-sha256 must be a 64-character lowercase SHA-256'

# Match Terraform's fixed source gate so environment-controlled Git settings cannot redirect
# repository, transport, configuration, or helper resolution.
export PATH=/usr/bin:/bin
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES
unset GIT_COMMON_DIR GIT_CONFIG GIT_CONFIG_COUNT GIT_CONFIG_PARAMETERS GIT_CONFIG_KEY_0 GIT_CONFIG_VALUE_0
unset GIT_SSH GIT_SSH_COMMAND GIT_PROXY_COMMAND GIT_ASKPASS SSH_ASKPASS GIT_SSL_NO_VERIFY
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_NOSYSTEM=1

[[ -f "$COMPOSE_SOURCE" && ! -L "$COMPOSE_SOURCE" ]] || \
  fail 'reviewed Compose source must be a regular non-symlink file'
command -v git >/dev/null 2>&1 || fail 'git is required'
command -v ssh >/dev/null 2>&1 || fail 'ssh is required'
command -v ssh-keygen >/dev/null 2>&1 || fail 'ssh-keygen is required'
command -v sha256sum >/dev/null 2>&1 || fail 'sha256sum is required'

head_revision="$(git -C "$ROOT" rev-parse --verify HEAD 2>/dev/null)" || \
  fail 'could not resolve the local source revision'
[[ "$head_revision" =~ ^[0-9a-f]{40}$ ]] || \
  fail 'local source revision is not a 40-character lowercase commit SHA'
[[ "$head_revision" == "$reviewed_revision" ]] || \
  fail 'local HEAD does not match the reviewed revision'

worktree_status="$(git -C "$ROOT" status --porcelain --untracked-files=normal 2>/dev/null)" || \
  fail 'could not inspect the local source tree'
[[ -z "$worktree_status" ]] || fail 'the source tree must be clean'

origin_url="$(git -C "$ROOT" remote get-url origin 2>/dev/null)" || \
  fail 'origin remote is missing'
[[ "$origin_url" == "$EXPECTED_REPOSITORY" ]] || \
  fail 'origin must be the exact Signal Ledger repository'

remote_main="$(
  cd /
  GIT_TERMINAL_PROMPT=0 git -C "$ROOT" ls-remote --exit-code --refs \
    "$EXPECTED_REPOSITORY" "refs/heads/$MAIN_BRANCH" 2>/dev/null \
    | awk 'NR == 1 { print $1 }'
)" || fail 'could not resolve the public origin/main revision'
[[ "$remote_main" =~ ^[0-9a-f]{40}$ ]] || \
  fail 'origin/main is not a 40-character lowercase commit SHA'
[[ "$head_revision" == "$remote_main" ]] || \
  fail 'local HEAD must exactly match origin/main'

tree_entry="$(git -C "$ROOT" ls-tree "$reviewed_revision" -- compose.production.yaml 2>/dev/null)" || \
  fail 'could not inspect the reviewed Compose source entry'
[[ "$tree_entry" == 100644\ blob\ *$'\t'compose.production.yaml ]] || \
  fail 'reviewed Compose source must be a tracked regular file'

compose_sha256="$(sha256sum "$COMPOSE_SOURCE" 2>/dev/null | awk '{print $1}')" || \
  fail 'could not hash the reviewed Compose source'
[[ "$compose_sha256" =~ ^[0-9a-f]{64}$ ]] || \
  fail 'reviewed Compose source checksum is invalid'
[[ "$compose_sha256" == "$reviewed_compose_sha256" ]] || \
  fail 'reviewed Compose source checksum does not match'

identity_file="${SIGNAL_LEDGER_OPERATOR_IDENTITY_FILE:-$DEFAULT_IDENTITY_FILE}"
known_hosts_file="${SIGNAL_LEDGER_KNOWN_HOSTS_FILE:-$DEFAULT_KNOWN_HOSTS_FILE}"

require_private_file() {
  local path="$1"
  local label="$2"
  [[ -n "$path" && "$path" != *$'\n'* && "$path" != *$'\r'* ]] || \
    fail "$label path is invalid"
  [[ -f "$path" && ! -L "$path" ]] || \
    fail "$label must be a regular non-symlink file"
  local mode
  mode="$(stat -c '%a' -- "$path" 2>/dev/null)" || fail "could not stat $label"
  (( (8#$mode & 077) == 0 )) || fail "$label must not be group/other-readable"
}

require_private_file "$identity_file" 'operator identity file'
require_private_file "$known_hosts_file" 'known-hosts file'

ssh-keygen -F "$REMOTE_HOST" -f "$known_hosts_file" >/dev/null 2>&1 || \
  fail 'known-hosts file has no pinned key for the fixed Signal Ledger host'
if ! awk -v fixed_host="$REMOTE_HOST" '
  /^[[:space:]]*(#|$)/ { next }
  {
    host_field = ($1 ~ /^@/ ? $2 : $1)
    count = split(host_field, host_names, ",")
    for (i = 1; i <= count; i++) {
      if (host_names[i] != fixed_host && host_names[i] != "[" fixed_host "]:22") {
        invalid = 1
      }
    }
    found = 1
  }
  END { exit (found && !invalid ? 0 : 1) }
' "$known_hosts_file"; then
  fail 'known-hosts file contains an entry outside the fixed Signal Ledger host'
fi

# The remote installer receives only the fixed Compose bytes on stdin and this validated digest.
# It takes the deploy helper's lock before target checks, uses no-follow opens, and atomically
# replaces the target without invoking Docker or systemd; services and tunnel keep running.
REMOTE_PYTHON="$(cat <<'PYTHON'
from __future__ import annotations

import fcntl
import hashlib
import os
import secrets
import stat
import sys
from grp import getgrnam

APP_DIRECTORY = "signal-ledger"
VAR_DIRECTORY = "var"
LIB_DIRECTORY = "lib"
STATE_DIRECTORY = "signal-ledger"
COMPOSE_NAME = "compose.production.yaml"
LOCK_NAME = "deploy.lock"
MAX_COMPOSE_BYTES = 1024 * 1024
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW


class InstallError(Exception):
    """Represent a safe, non-diagnostic installer failure."""


def _metadata_is(metadata: os.stat_result, *, uid: int, gid: int, mode: int) -> bool:
    return (
        stat.S_ISDIR(metadata.st_mode)
        and metadata.st_uid == uid
        and metadata.st_gid == gid
        and stat.S_IMODE(metadata.st_mode) == mode
    )


def _target_metadata(directory_fd: int) -> os.stat_result:
    try:
        metadata = os.stat(COMPOSE_NAME, dir_fd=directory_fd, follow_symlinks=False)
    except OSError as exc:
        raise InstallError from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o644
        or metadata.st_nlink != 1
    ):
        raise InstallError
    return metadata


def _target_signature(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_uid,
        metadata.st_gid,
        stat.S_IMODE(metadata.st_mode),
        metadata.st_nlink,
    )


def _write_all(descriptor: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise InstallError
        remaining = remaining[written:]


def install(expected_sha256: str) -> None:
    if len(expected_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in expected_sha256
    ):
        raise InstallError

    root_fd = var_fd = lib_fd = state_fd = lock_fd = opt_fd = app_fd = temp_fd = -1
    temp_name = ""
    try:
        root_fd = os.open("/", DIRECTORY_FLAGS)

        var_fd = os.open(VAR_DIRECTORY, DIRECTORY_FLAGS, dir_fd=root_fd)
        var_metadata = os.fstat(var_fd)
        if not _metadata_is(var_metadata, uid=0, gid=0, mode=0o755):
            raise InstallError
        lib_fd = os.open(LIB_DIRECTORY, DIRECTORY_FLAGS, dir_fd=var_fd)
        lib_metadata = os.fstat(lib_fd)
        if not _metadata_is(lib_metadata, uid=0, gid=0, mode=0o755):
            raise InstallError
        state_fd = os.open(STATE_DIRECTORY, DIRECTORY_FLAGS, dir_fd=lib_fd)
        deploy_gid = getgrnam("signal-ledger-deploy").gr_gid
        state_metadata = os.fstat(state_fd)
        if not _metadata_is(state_metadata, uid=0, gid=deploy_gid, mode=0o750):
            raise InstallError

        # Match the helper's root-owned, private lock and fail closed if a plan or deploy holds
        # it. No create/chmod path is allowed here because both tools must lock the same inode.
        lock_fd = os.open(LOCK_NAME, os.O_RDWR | os.O_NOFOLLOW, dir_fd=state_fd)
        lock_metadata = os.fstat(lock_fd)
        if (
            not stat.S_ISREG(lock_metadata.st_mode)
            or lock_metadata.st_uid != 0
            or lock_metadata.st_gid not in (0, deploy_gid)
            or stat.S_IMODE(lock_metadata.st_mode) not in (0o600, 0o640)
            or lock_metadata.st_nlink != 1
        ):
            raise InstallError
        lock_path_metadata = os.stat(LOCK_NAME, dir_fd=state_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(lock_path_metadata.st_mode)
            or lock_path_metadata.st_dev != lock_metadata.st_dev
            or lock_path_metadata.st_ino != lock_metadata.st_ino
        ):
            raise InstallError
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        opt_fd = os.open("opt", DIRECTORY_FLAGS, dir_fd=root_fd)
        opt_metadata = os.fstat(opt_fd)
        if not _metadata_is(opt_metadata, uid=0, gid=0, mode=0o755):
            raise InstallError

        app_fd = os.open(APP_DIRECTORY, DIRECTORY_FLAGS, dir_fd=opt_fd)
        app_metadata = os.fstat(app_fd)
        if not _metadata_is(app_metadata, uid=0, gid=deploy_gid, mode=0o750):
            raise InstallError

        before = _target_metadata(app_fd)
        before_signature = _target_signature(before)
        temp_name = f".compose.production.yaml.{secrets.token_hex(16)}.tmp"
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=app_fd,
        )

        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(0, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_COMPOSE_BYTES:
                raise InstallError
            digest.update(chunk)
            _write_all(temp_fd, chunk)
        if digest.hexdigest() != expected_sha256:
            raise InstallError

        os.fchown(temp_fd, 0, 0)
        os.fchmod(temp_fd, 0o644)
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = -1

        current = _target_metadata(app_fd)
        if _target_signature(current) != before_signature:
            raise InstallError
        os.replace(
            temp_name,
            COMPOSE_NAME,
            src_dir_fd=app_fd,
            dst_dir_fd=app_fd,
        )
        temp_name = ""
        os.fsync(app_fd)

        installed_fd = os.open(COMPOSE_NAME, FILE_FLAGS, dir_fd=app_fd)
        try:
            installed_metadata = os.fstat(installed_fd)
            if (
                not stat.S_ISREG(installed_metadata.st_mode)
                or installed_metadata.st_uid != 0
                or installed_metadata.st_gid != 0
                or stat.S_IMODE(installed_metadata.st_mode) != 0o644
                or installed_metadata.st_nlink != 1
            ):
                raise InstallError
            installed_digest = hashlib.sha256()
            installed_total = 0
            while True:
                chunk = os.read(installed_fd, 65536)
                if not chunk:
                    break
                installed_total += len(chunk)
                if installed_total > MAX_COMPOSE_BYTES:
                    raise InstallError
                installed_digest.update(chunk)
            if installed_digest.hexdigest() != expected_sha256:
                raise InstallError
        finally:
            os.close(installed_fd)
    except (OSError, InstallError, KeyError):
        if temp_name and app_fd >= 0:
            try:
                os.unlink(temp_name, dir_fd=app_fd)
            except OSError:
                pass
        raise InstallError from None
    finally:
        if lock_fd >= 0:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        for descriptor in (temp_fd, app_fd, opt_fd, state_fd, lib_fd, var_fd, root_fd):
            if descriptor >= 0:
                os.close(descriptor)


try:
    if len(sys.argv) != 2:
        raise InstallError
    install(sys.argv[1])
except InstallError:
    sys.stderr.write("compose_update_failed\n")
    raise SystemExit(2) from None
PYTHON
)"
remote_python_base64="$(printf '%s' "$REMOTE_PYTHON" | base64 | tr -d '\n')" || \
  fail 'could not prepare the fixed remote installer'
[[ "$remote_python_base64" =~ ^[A-Za-z0-9+/]+=*$ ]] || \
  fail 'fixed remote installer encoding is invalid'

readonly ssh_options=(
  -T
  -o BatchMode=yes
  -o StrictHostKeyChecking=yes
  -o IdentitiesOnly=yes
  -o ClearAllForwardings=yes
  -o ConnectTimeout=10
  -o UserKnownHostsFile="$known_hosts_file"
  -o GlobalKnownHostsFile=/dev/null
  -i "$identity_file"
)
readonly remote_command="/usr/bin/sudo -n -- /usr/bin/python3 -c \"\$(/usr/bin/printf '%s' '$remote_python_base64' | /usr/bin/base64 --decode)\" '$reviewed_compose_sha256'"

if ! ssh "${ssh_options[@]}" "$REMOTE_TARGET" "$remote_command" \
  <"$COMPOSE_SOURCE" >/dev/null 2>&1; then
  fail 'fixed-host Compose update failed; no service or tunnel action was requested'
fi

printf 'Reviewed Compose installed on the fixed host; current services and tunnel were not changed.\n'
