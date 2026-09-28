#!/usr/bin/env bash
# shellcheck disable=SC2034
# Seed the empty production volume with one verified legacy SQLite snapshot.
# The app container must not be running; the copied database remains owned by UID 10001.
set -euo pipefail

readonly REMOTE_USER="signalops"
readonly REMOTE_LOCK="/var/lib/signal-ledger/deploy.lock"
readonly REMOTE_VOLUME="signal-ledger_signal-ledger-data"
readonly REMOTE_DB="/data/stock_probs.sqlite3"
readonly REMOTE_SEED_DIR="/var/lib/signal-ledger/seed"
readonly REMOTE_SEED="/var/lib/signal-ledger/seed/legacy.sqlite3"
readonly REMOTE_SEED_STAGE="/var/lib/signal-ledger/seed/.legacy.sqlite3.staged"
readonly LEGACY_SCHEMA_VERSION=6
readonly MAX_SNAPSHOT_BYTES=$((512 * 1024 * 1024))

fail() {
  printf 'seed-production-data: %s\n' "$1" >&2
  exit 2
}

usage() {
  cat >&2 <<'EOF'
Usage:
  seed-production-data.sh --host IPV4 --identity-file FILE --known-hosts-file FILE \
    --snapshot FILE --snapshot-sha256 SHA256 --revision COMMIT_SHA \
    --image-id sha256:IMAGE_ID

The snapshot must be a regular private file containing the legacy schema-6 database.
The image, Docker volume, container state, and target database are checked remotely before
the one-time copy. The app is not started by this command.
EOF
}

host=""
identity_file=""
known_hosts_file=""
snapshot_file=""
snapshot_sha256=""
revision=""
image_id=""

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
    --snapshot)
      (($# >= 2)) || fail '--snapshot requires a path'
      snapshot_file="$2"
      shift 2
      ;;
    --snapshot-sha256)
      (($# >= 2)) || fail '--snapshot-sha256 requires a value'
      snapshot_sha256="$2"
      shift 2
      ;;
    --revision)
      (($# >= 2)) || fail '--revision requires a value'
      revision="$2"
      shift 2
      ;;
    --image-id)
      (($# >= 2)) || fail '--image-id requires a value'
      image_id="$2"
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

[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || fail '--revision must be a lowercase 40-character commit SHA'
[[ "$snapshot_sha256" =~ ^[0-9a-f]{64}$ ]] || fail '--snapshot-sha256 must be a lowercase SHA-256'
[[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || fail '--image-id must be a full sha256 image ID'
[[ -n "$identity_file" ]] || fail '--identity-file is required'
[[ -n "$known_hosts_file" ]] || fail '--known-hosts-file is required'
[[ -n "$snapshot_file" ]] || fail '--snapshot is required'

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
require_private_file "$snapshot_file" 'snapshot file'

snapshot_size="$(stat -c '%s' -- "$snapshot_file")" || fail 'could not determine snapshot size'
(( snapshot_size > 0 && snapshot_size <= MAX_SNAPSHOT_BYTES )) || \
  fail 'snapshot size is outside the bounded range'

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
  # Commands are repository-owned constants. User inputs are restricted to hex values and are
  # inserted only into the immutable image ID; no caller-supplied command or path is accepted.
  ssh "${ssh_options[@]}" "$remote_target" "$1"
}

# Validate the local database before opening any SSH connection. The output is a small count
# record, never database content; the same record is required from the remote volume later.
snapshot_metadata="$(python3 - "$snapshot_file" "$snapshot_sha256" "$LEGACY_SCHEMA_VERSION" <<'PY'
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

path = Path(sys.argv[1])
expected_hash = sys.argv[2]
expected_schema = int(sys.argv[3])

try:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != expected_hash:
        raise ValueError("snapshot_hash_mismatch")

    database = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True)
    try:
        database.execute("PRAGMA query_only = ON")
        if database.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("snapshot_integrity_failed")
        if database.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("snapshot_foreign_key_check_failed")
        schema = database.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
        if schema != expected_schema:
            raise ValueError("snapshot_schema_unexpected")
        counts = {
            "events": database.execute("SELECT count(*) FROM search_events").fetchone()[0],
            "runs": database.execute("SELECT count(*) FROM forecast_runs").fetchone()[0],
            "inputs": database.execute("SELECT count(*) FROM forecast_inputs").fetchone()[0],
            "results": database.execute("SELECT count(*) FROM forecast_results").fetchone()[0],
            "outcomes": database.execute("SELECT count(*) FROM outcomes").fetchone()[0],
            "holdings": database.execute(
                "SELECT count(*) FROM instrument_list_items WHERE kind = 'portfolio'"
            ).fetchone()[0],
            "watchlist": database.execute(
                "SELECT count(*) FROM instrument_list_items WHERE kind = 'watchlist'"
            ).fetchone()[0],
        }
    finally:
        database.close()
except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
    raise SystemExit(str(exc))

print(json.dumps({"sha256": digest.hexdigest(), "schema": schema, **counts}, sort_keys=True))
PY
)" || fail 'local snapshot verification failed'

expected_remote_metadata="$(python3 - "$snapshot_metadata" <<'PY'
import json
import sys

record = json.loads(sys.argv[1])
fields = ("sha256", "events", "runs", "inputs", "results", "outcomes", "holdings", "watchlist")
print("|".join([str(record["sha256"]), "ok", str(record["schema"])] + [str(record[field]) for field in fields[1:]]))
PY
)" || fail 'could not prepare expected snapshot metadata'

read -r -d '' remote_seed_python <<'PY' || true
import fcntl
import os
import stat
import struct
import subprocess
import sys

TRANSACTION_NAME = "signal-ledger-seed-transaction"
LOCK_FILE = "/var/lib/signal-ledger/deploy.lock"
VOLUME = "signal-ledger_signal-ledger-data"
DATABASE = "/data/stock_probs.sqlite3"
SEED_DIR = "/var/lib/signal-ledger/seed"
SEED_FINAL = "/var/lib/signal-ledger/seed/legacy.sqlite3"
SEED_STAGE = "/var/lib/signal-ledger/seed/.legacy.sqlite3.staged"
MAX_SNAPSHOT_BYTES = 512 * 1024 * 1024
owned_paths = []
phase = "start"

VERIFY_CODE = r'''
import hashlib
import sqlite3
import sys
path = sys.argv[1]
digest = hashlib.sha256()
stream = open(path, "rb")
for block in iter(lambda: stream.read(1024 * 1024), b""):
    digest.update(block)
stream.close()
# The mounted snapshot is immutable and its container directory is read-only;
# immutable=1 prevents SQLite from requiring WAL sidecar writes for verification.
database = sqlite3.connect("file:" + path + "?mode=ro&immutable=1", uri=True)
integrity = database.execute("PRAGMA integrity_check").fetchone()[0]
foreign_key = database.execute("PRAGMA foreign_key_check").fetchone()
if foreign_key is not None:
    raise SystemExit("foreign_key_check_failed")
schema = database.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
events = database.execute("SELECT count(*) FROM search_events").fetchone()[0]
runs = database.execute("SELECT count(*) FROM forecast_runs").fetchone()[0]
inputs = database.execute("SELECT count(*) FROM forecast_inputs").fetchone()[0]
results = database.execute("SELECT count(*) FROM forecast_results").fetchone()[0]
outcomes = database.execute("SELECT count(*) FROM outcomes").fetchone()[0]
holdings = database.execute("SELECT count(*) FROM instrument_list_items WHERE kind = char(112,111,114,116,102,111,108,105,111)").fetchone()[0]
watchlist = database.execute("SELECT count(*) FROM instrument_list_items WHERE kind = char(119,97,116,99,104,108,105,115,116)").fetchone()[0]
print(digest.hexdigest() + "|" + integrity + "|" + str(schema) + "|" + "|".join(str(value) for value in (events, runs, inputs, results, outcomes, holdings, watchlist)))
'''

COPY_CODE = r'''
import atexit
import os
import shutil
import sys
source = "/seed/legacy.sqlite3"
target = sys.argv[1]
temporary = target + ".seed-staging"
descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_WRONLY, 0o600)
completed = [False]
atexit.register(lambda: (not completed[0]) and os.path.lexists(temporary) and os.unlink(temporary))
stream = os.fdopen(descriptor, "wb")
source_stream = open(source, "rb")
shutil.copyfileobj(source_stream, stream, 1024 * 1024)
source_stream.close()
stream.flush()
os.fsync(stream.fileno())
stream.close()
completed[0] = True
'''

PUBLISH_CODE = r'''
import atexit
import os
import sys
target = sys.argv[1]
temporary = target + ".seed-staging"
linked = [False]


def cleanup():
    if linked[0]:
        try:
            os.unlink(target)
        except FileNotFoundError:
            pass
    if os.path.lexists(temporary):
        os.unlink(temporary)


atexit.register(cleanup)
os.link(temporary, target)
linked[0] = True
os.unlink(temporary)
linked[0] = False
'''

CLEANUP_CODE = r'''
import os
import sys
target = sys.argv[1]
temporary = target + ".seed-staging"
if os.path.lexists(temporary):
    os.unlink(temporary)
'''


def fail(message):
    raise SystemExit(message)


def run(argv):
    try:
        return subprocess.run(argv, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("remote_command_failed") from exc


def capture(argv):
    try:
        result = subprocess.run(argv, check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("remote_command_failed") from exc
    return result.stdout.decode("utf-8", "strict").strip()


def status(argv):
    try:
        return subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).returncode
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


def stream_snapshot(path):
    (size,) = struct.unpack("!Q", read_exact(8))
    if not 0 < size <= MAX_SNAPSHOT_BYTES:
        fail("snapshot_size_invalid")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    owned_paths.append(path)
    try:
        with os.fdopen(descriptor, "wb") as output:
            remaining = size
            while remaining:
                block = read_exact(min(remaining, 1024 * 1024))
                output.write(block)
                remaining -= len(block)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        raise
    os.chown(path, 10001, 10001)
    os.chmod(path, 0o400)


def sandbox():
    return [
        "/usr/bin/docker",
        "run",
        "--rm",
        "--pull=never",
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "32",
        "--memory",
        "256m",
        "--cpus",
        "0.5",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=8m",
        "--user",
        "10001:10001",
    ]


def require_seed_dir():
    try:
        info = os.lstat(SEED_DIR)
    except FileNotFoundError:
        os.mkdir(SEED_DIR, 0o700)
        return
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail("seed_directory_invalid")


def require_seed_paths_absent():
    for path in (SEED_FINAL, SEED_STAGE):
        try:
            os.lstat(path)
        except FileNotFoundError:
            continue
        fail("seed_path_exists")


def require_target_absent(image_id):
    target_code = "import os,sys; target=sys.argv[1]; sys.exit(1 if os.path.lexists(target) or os.path.lexists(target+'.seed-staging') else 0)"
    command = sandbox() + ["--volume", VOLUME + ":/data", image_id, "python", "-c", target_code, DATABASE]
    if status(command) != 0:
        fail("database_target_exists")


def verify_stage(image_id, expected):
    command = sandbox() + [
        "--mount",
        "type=bind,src=" + SEED_STAGE + ",dst=/seed/legacy.sqlite3,readonly",
        image_id,
        "python",
        "-c",
        VERIFY_CODE,
        "/seed/legacy.sqlite3",
    ]
    if capture(command) != expected:
        fail("staged_database_verification_failed")


def copy_to_volume(image_id):
    command = sandbox() + [
        "--mount",
        "type=bind,src=" + SEED_STAGE + ",dst=/seed/legacy.sqlite3,readonly",
        "--volume",
        VOLUME + ":/data",
        image_id,
        "python",
        "-c",
        COPY_CODE,
        DATABASE,
    ]
    run(command)


def verify_volume_staging(image_id, expected):
    command = sandbox() + [
        "--volume",
        VOLUME + ":/data:ro",
        image_id,
        "python",
        "-c",
        VERIFY_CODE,
        DATABASE + ".seed-staging",
    ]
    if capture(command) != expected:
        fail("volume_staging_verification_failed")


def publish_volume(image_id):
    command = sandbox() + [
        "--volume",
        VOLUME + ":/data",
        image_id,
        "python",
        "-c",
        PUBLISH_CODE,
        DATABASE,
    ]
    run(command)


def cleanup_volume_staging(image_id):
    command = sandbox() + [
        "--volume",
        VOLUME + ":/data",
        image_id,
        "python",
        "-c",
        CLEANUP_CODE,
        DATABASE,
    ]
    try:
        subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def operation(revision, image_id, expected):
    global phase
    phase = "validate"
    parts = expected.split("|")
    if len(parts) != 10 or parts[1] != "ok":
        fail("expected_metadata_invalid")
    image_record = capture([
        "/usr/bin/docker",
        "image",
        "inspect",
        "--format",
        "{{.Id}}|{{index .Config.Labels \"org.opencontainers.image.revision\"}}",
        image_id,
    ])
    if image_record != image_id + "|" + revision:
        fail("image_identity_mismatch")
    phase = "container_state"
    running = capture([
        "/usr/bin/docker",
        "ps",
        "--filter",
        "label=com.docker.compose.project=signal-ledger",
        "--filter",
        "label=com.docker.compose.service=app",
        "--format",
        "{{.ID}}",
    ])
    if running:
        fail("production_app_running")
    phase = "volume"
    if status(["/usr/bin/docker", "volume", "inspect", VOLUME]) != 0:
        run(["/usr/bin/docker", "volume", "create", VOLUME])
    phase = "target"
    require_target_absent(image_id)
    require_seed_dir()
    require_seed_paths_absent()
    phase = "upload"
    stream_snapshot(SEED_STAGE)
    phase = "verify_upload"
    verify_stage(image_id, expected)
    volume_staging_created = True
    try:
        phase = "copy"
        copy_to_volume(image_id)
        phase = "verify_volume"
        verify_volume_staging(image_id, expected)
        os.unlink(SEED_STAGE)
        owned_paths.remove(SEED_STAGE)
        phase = "publish"
        publish_volume(image_id)
        volume_staging_created = False
    finally:
        if volume_staging_created:
            cleanup_volume_staging(image_id)


def main():
    revision = sys.argv[1]
    image_id = sys.argv[2]
    expected = sys.argv[3]
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
        operation(revision, image_id, expected)
        sys.stdout.write("SEEDED\n")
    except SystemExit:
        raise
    except Exception as exc:
        raise SystemExit(f"remote_seed_transaction_failed:{phase}") from exc
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
remote_seed_command="$(printf '%q ' /usr/bin/python3 -c "$remote_seed_python" "$revision" "$image_id" "$expected_remote_metadata")"
send_seed_payload() {
  python3 - "$snapshot_file" <<'PY'
import os
import stat
import struct
import sys

descriptor = os.open(sys.argv[1], os.O_RDONLY | os.O_NOFOLLOW)
try:
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size <= 0:
        raise SystemExit("local_snapshot_file_invalid")
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

remote_result="$(send_seed_payload | remote_ssh "sudo -n $remote_seed_command")" || \
  fail 'remote seed transaction failed'
[[ "$remote_result" == 'SEEDED' ]] || fail 'remote seed transaction was not confirmed'
printf 'Legacy snapshot seeded into the reviewed image volume; the app remains stopped.\n'
