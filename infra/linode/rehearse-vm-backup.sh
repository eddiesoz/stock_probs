#!/usr/bin/env bash
# Rehearse a fixed Linode backup restore against a disposable same-spec instance.
# The default path is read-only. Creation and deletion require explicit confirmation.
set -euo pipefail

readonly API_ROOT="https://api.linode.com/v4"
readonly SOURCE_LINODE_ID=106817202
readonly SNAPSHOT_ID=385239936
readonly LEGACY_LINODE_ID=97934478
readonly FIREWALL_ID=177236117
readonly EXPECTED_REGION="us-east"
readonly EXPECTED_TYPE="g6-nanode-1"
readonly TARGET_LABEL="signal-ledger-backup-rehearsal-385239936"
readonly RESUME_TARGET_ID=106825234
readonly CONFIRMATION="REHEARSE-SIGNAL-LEDGER-SNAPSHOT-385239936"
readonly REMOTE_USER="signalops"
# Fixed nonsecret cloud-init metadata. It preserves the host keys restored from the snapshot;
# the empty key-generation list prevents cloud-init from creating replacement keys on first boot.
readonly RESTORE_USER_DATA_B64="I2Nsb3VkLWNvbmZpZwpzc2hfZGVsZXRla2V5czogZmFsc2UKc3NoX2dlbmtleXR5cGVzOiBbXQo="
readonly MAX_API_RESPONSE_BYTES=$((2 * 1024 * 1024))
readonly MAX_TOKEN_BYTES=512
readonly MAX_REMOTE_OUTPUT_BYTES=65536
readonly MAX_WAIT_ATTEMPTS=90
readonly MAX_RESTORE_WAIT_ATTEMPTS=180
readonly WAIT_SECONDS=5
readonly MAX_KEYSCAN_ATTEMPTS=12
readonly KEYSCAN_WAIT_SECONDS=5

TOKEN_FILE=""
OPERATOR_IPV4_CIDR="${SIGNAL_LEDGER_OPERATOR_IPV4_CIDR:-${TF_VAR_operator_ipv4_cidr:-}}"
IDENTITY_FILE=""
KNOWN_HOSTS_FILE=""
RECEIPT_FILE=""
EXECUTE=false
RESUME_EXISTING=false
CONFIRM=""
TMP_DIR=""
TARGET_ID=""
TARGET_DELETED=false
API_LAST_STATUS=""

fail() {
  printf 'vm-backup-rehearsal: %s\n' "$1" >&2
  exit 2
}

usage() {
  cat <<'EOF'
Usage:
  rehearse-vm-backup.sh --token-file FILE --operator-ipv4-cidr OPERATOR_IPV4/32
  rehearse-vm-backup.sh --token-file FILE --operator-ipv4-cidr OPERATOR_IPV4/32 --execute \
    --identity-file FILE --known-hosts-file FILE \
    --confirm REHEARSE-SIGNAL-LEDGER-SNAPSHOT-385239936 [--receipt-file FILE]
  rehearse-vm-backup.sh --token-file FILE --operator-ipv4-cidr OPERATOR_IPV4/32 --execute \
    --resume-existing --identity-file FILE --known-hosts-file FILE \
    --confirm REHEARSE-SIGNAL-LEDGER-SNAPSHOT-385239936 [--receipt-file FILE]

The default mode performs fixed-target, read-only API checks only. Execute mode creates one
  disposable Linode from backup 385239936, attaches firewall 177236117, verifies the copied
  application volume/database and disabled Cloudflare unit over the fixed operator SSH boundary,
  then deletes that newly-created instance after successful verification. Source Linode 106817202
  and legacy Linode 97934478 are never deletion targets. A failed verification leaves the
  disposable instance in place for inspection and prints only its numeric ID.

The --resume-existing execute mode resumes only the fixed disposable instance 106825234 after a
restore timeout; it validates the fixed label/spec/status before any boot or deletion and never
accepts an instance ID argument.

No API root, instance ID, backup ID, firewall ID, label, endpoint, remote command, or remote path
is caller-configurable. Token and SSH files must be private regular files.
EOF
}

while (($# > 0)); do
  case "$1" in
    --token-file)
      (($# >= 2)) || fail '--token-file requires a path'
      TOKEN_FILE="$2"
      shift 2
      ;;
    --operator-ipv4-cidr)
      (($# >= 2)) || fail '--operator-ipv4-cidr requires a /32 value'
      OPERATOR_IPV4_CIDR="$2"
      shift 2
      ;;
    --identity-file)
      (($# >= 2)) || fail '--identity-file requires a path'
      IDENTITY_FILE="$2"
      shift 2
      ;;
    --known-hosts-file)
      (($# >= 2)) || fail '--known-hosts-file requires a path'
      KNOWN_HOSTS_FILE="$2"
      shift 2
      ;;
    --receipt-file)
      (($# >= 2)) || fail '--receipt-file requires a path'
      RECEIPT_FILE="$2"
      shift 2
      ;;
    --confirm)
      (($# >= 2)) || fail '--confirm requires the fixed rehearsal string'
      CONFIRM="$2"
      shift 2
      ;;
    --execute)
      EXECUTE=true
      shift
      ;;
    --resume-existing)
      RESUME_EXISTING=true
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      usage >&2
      fail "unknown option: $1"
      ;;
  esac
done

[[ -n "$TOKEN_FILE" ]] || fail '--token-file is required'
[[ -n "$OPERATOR_IPV4_CIDR" ]] || \
  fail '--operator-ipv4-cidr is required (use the same nonsecret Terraform input as operator_ipv4_cidr)'
python3 - "$OPERATOR_IPV4_CIDR" <<'PY'
from __future__ import annotations

import ipaddress
import sys

value = sys.argv[1]
try:
    address = ipaddress.ip_interface(value)
except ValueError as exc:
    raise SystemExit("operator_ipv4_cidr_invalid") from exc
if address.version != 4 or address.network.prefixlen != 32 or str(address) != value:
    raise SystemExit("operator_ipv4_cidr_invalid")
PY

require_private_file() {
  local path="$1"
  local label="$2"
  [[ -n "$path" && "$path" != *$'\n'* && "$path" != *$'\r'* ]] || fail "$label path is invalid"
  [[ -L "$path" || ! -f "$path" ]] && fail "$label must be a regular non-symlink file"
  local mode
  mode="$(stat -c '%a' -- "$path")" || fail "could not stat $label"
  [[ "$mode" =~ ^[0-7]+$ ]] || fail "$label permissions could not be read"
  (( (8#$mode & 077) == 0 )) || fail "$label must not be group/other-readable"
}

require_private_file "$TOKEN_FILE" 'Linode token file'
token_size="$(stat -c '%s' -- "$TOKEN_FILE")" || fail 'could not determine token file size'
(( token_size > 0 && token_size <= MAX_TOKEN_BYTES )) || fail 'token file is outside the bounded range'

# Emit the token only to the pipe consumed by curl --config -; it never enters argv or logs.
token_config() {
  python3 - "$TOKEN_FILE" <<'PY'
from __future__ import annotations

import re
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("token_file_invalid")
    value = path.read_bytes()
except (OSError, ValueError) as exc:
    raise SystemExit(str(exc)) from exc
if value.endswith(b"\n"):
    value = value[:-1]
if not value or len(value) > 512 or re.fullmatch(rb"[A-Za-z0-9._~+/=-]+", value) is None:
    raise SystemExit("token_file_invalid")
token = value.decode("ascii")
sys.stdout.write(f'header = "Authorization: Bearer {token}"\n')
sys.stdout.write('header = "Accept: application/json"\n')
PY
}

if [[ "$EXECUTE" == true ]]; then
  [[ "$CONFIRM" == "$CONFIRMATION" ]] || fail "exact confirmation $CONFIRMATION is required"
  [[ -n "$IDENTITY_FILE" ]] || fail '--identity-file is required with --execute'
  [[ -n "$KNOWN_HOSTS_FILE" ]] || fail '--known-hosts-file is required with --execute'
  require_private_file "$IDENTITY_FILE" 'SSH identity file'
  require_private_file "$KNOWN_HOSTS_FILE" 'known-hosts file'
else
  [[ -z "$CONFIRM" ]] || fail '--confirm requires --execute'
  [[ -z "$IDENTITY_FILE" ]] || fail '--identity-file requires --execute'
  [[ -z "$KNOWN_HOSTS_FILE" ]] || fail '--known-hosts-file requires --execute'
  [[ -z "$RECEIPT_FILE" ]] || fail '--receipt-file requires --execute'
  [[ "$RESUME_EXISTING" == false ]] || fail '--resume-existing requires --execute'
fi

if [[ -n "$RECEIPT_FILE" ]]; then
  [[ "$RECEIPT_FILE" != *$'\n'* && "$RECEIPT_FILE" != *$'\r'* ]] || fail 'receipt path is invalid'
  [[ ! -e "$RECEIPT_FILE" && ! -L "$RECEIPT_FILE" ]] || fail 'receipt destination already exists'
  receipt_parent="$(dirname -- "$RECEIPT_FILE")"
  [[ -d "$receipt_parent" && ! -L "$receipt_parent" ]] || fail 'receipt parent must be a directory'
fi

command -v curl >/dev/null 2>&1 || fail 'curl is required'
command -v python3 >/dev/null 2>&1 || fail 'python3 is required'

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/signal-ledger-vm-rehearsal.XXXXXX")" || fail 'could not create temporary directory'
chmod 700 "$TMP_DIR"
trap 'if [[ -n "$TARGET_ID" && "$TARGET_DELETED" != true ]]; then printf '\''vm-backup-rehearsal: disposable instance retained for inspection: %s\n'\'' "$TARGET_ID" >&2; fi; rm -rf -- "$TMP_DIR"' EXIT

api_request() {
  local method="$1"
  local path="$2"
  local output="$3"
  local body="${4:-}"
  local allow_not_found="${5:-false}"
  local status
  local -a curl_arguments=(
    --silent
    --show-error
    --proto '=https'
    --tlsv1.2
    --connect-timeout 10
    --max-time 30
    --max-filesize "$MAX_API_RESPONSE_BYTES"
    --request "$method"
    --url "$API_ROOT$path"
    --header 'Accept: application/json'
    --output "$output"
    --write-out '%{http_code}'
  )
  if [[ -n "$body" ]]; then
    curl_arguments+=(--header 'Content-Type: application/json' --data-binary "$body")
  fi
  if ! status="$(token_config | curl --config - "${curl_arguments[@]}")"; then
    fail "Linode API request failed for fixed path $path"
  fi
  [[ "$status" =~ ^[0-9]{3}$ ]] || fail "Linode API returned an invalid status for $path"
  API_LAST_STATUS="$status"
  if [[ "$status" != 2?? && ! ( "$allow_not_found" == true && "$status" == 404 ) ]]; then
    fail "Linode API returned HTTP $status for fixed path $path"
  fi
}

assert_source_instance() {
  local response="$1"
  python3 - "$response" "$SOURCE_LINODE_ID" "$EXPECTED_REGION" "$EXPECTED_TYPE" <<'PY'
from __future__ import annotations

import ipaddress
import json
import sys

path, expected_id, expected_region, expected_type = sys.argv[1:]
try:
    value = json.loads(open(path, encoding="utf-8").read())
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit("source_response_invalid") from exc
if not isinstance(value, dict) or value.get("id") != int(expected_id):
    raise SystemExit("source_identity_invalid")
if value.get("region") != expected_region or value.get("type") != expected_type:
    raise SystemExit("source_spec_invalid")
addresses = value.get("ipv4")
if not isinstance(addresses, list) or not addresses:
    raise SystemExit("source_address_missing")
try:
    address = ipaddress.ip_address(addresses[0])
except ValueError as exc:
    raise SystemExit("source_address_invalid") from exc
if address.version != 4 or address.is_unspecified or address.is_loopback:
    raise SystemExit("source_address_invalid")
print(address)
PY
}

assert_backup() {
  local response="$1"
  python3 - "$response" "$SNAPSHOT_ID" "$EXPECTED_REGION" <<'PY'
from __future__ import annotations

import json
import sys

path, expected_id, expected_region = sys.argv[1:]
try:
    value = json.loads(open(path, encoding="utf-8").read())
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit("backup_response_invalid") from exc
if not isinstance(value, dict) or value.get("id") != int(expected_id):
    raise SystemExit("backup_identity_invalid")
if value.get("type") != "snapshot" or value.get("status") != "successful":
    raise SystemExit("backup_not_successful")
if value.get("available") is not True or value.get("region") != expected_region:
    raise SystemExit("backup_unavailable_or_wrong_region")
PY
}

assert_firewall() {
  local response="$1"
  python3 - "$response" "$FIREWALL_ID" "$OPERATOR_IPV4_CIDR" <<'PY'
from __future__ import annotations

import json
import sys

path, expected_id, operator_cidr = sys.argv[1:]
try:
    value = json.loads(open(path, encoding="utf-8").read())
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit("firewall_response_invalid") from exc
if not isinstance(value, dict) or value.get("id") != int(expected_id):
    raise SystemExit("firewall_identity_invalid")
if value.get("status") != "enabled":
    raise SystemExit("firewall_not_enabled")
rules = value.get("rules")
if not isinstance(rules, dict) or rules.get("inbound_policy") != "DROP":
    raise SystemExit("firewall_inbound_policy_invalid")
inbound = rules.get("inbound")
if not isinstance(inbound, list) or len(inbound) != 1:
    raise SystemExit("firewall_rules_invalid")
rule = inbound[0]
if not isinstance(rule, dict) or rule.get("action") != "ACCEPT":
    raise SystemExit("firewall_ssh_rule_missing_or_duplicated")
addresses = rule.get("addresses")
if not isinstance(addresses, dict):
    raise SystemExit("firewall_address_shape_invalid")
ipv4 = addresses.get("ipv4")
if not isinstance(ipv4, list):
    raise SystemExit("firewall_address_shape_invalid")
if "ipv6" in addresses:
    ipv6 = addresses["ipv6"]
    if not isinstance(ipv6, list):
        raise SystemExit("firewall_address_shape_invalid")
else:
    ipv6 = []
if ipv6:
    raise SystemExit("firewall_ipv6_inbound")
if ipv4 != [operator_cidr]:
    raise SystemExit("firewall_operator_cidr_mismatch")
if rule.get("protocol") != "TCP" or rule.get("ports") != "22":
    raise SystemExit("firewall_allows_non_ssh_inbound")
PY
}

assert_label_available() {
  local response="$1"
  python3 - "$response" "$TARGET_LABEL" <<'PY'
from __future__ import annotations

import json
import sys

path, label = sys.argv[1:]
try:
    value = json.loads(open(path, encoding="utf-8").read())
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit("instances_response_invalid") from exc
if not isinstance(value, dict) or not isinstance(value.get("data"), list):
    raise SystemExit("instances_response_invalid")
if value.get("pages", 1) != 1:
    raise SystemExit("instances_page_truncated")
for instance in value["data"]:
    if isinstance(instance, dict) and instance.get("label") == label:
        raise SystemExit("rehearsal_label_already_exists")
PY
}

assert_created_instance() {
  local response="$1"
  python3 - "$response" "$SOURCE_LINODE_ID" "$LEGACY_LINODE_ID" "$TARGET_LABEL" "$EXPECTED_REGION" "$EXPECTED_TYPE" <<'PY'
from __future__ import annotations

import json
import sys

path, source_id, legacy_id, expected_label, expected_region, expected_type = sys.argv[1:]
try:
    value = json.loads(open(path, encoding="utf-8").read())
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit("create_response_invalid") from exc
if not isinstance(value, dict):
    raise SystemExit("create_response_invalid")
identifier = value.get("id")
if type(identifier) is not int or identifier <= 0:
    raise SystemExit("created_instance_id_invalid")
if identifier in {int(source_id), int(legacy_id)}:
    raise SystemExit("created_instance_is_protected")
if value.get("label") != expected_label or value.get("region") != expected_region:
    raise SystemExit("created_instance_identity_invalid")
if value.get("type") != expected_type:
    raise SystemExit("created_instance_spec_invalid")
print(identifier)
PY
}

assert_target_instance() {
  local response="$1"
  local expected_id="$2"
  python3 - "$response" "$expected_id" "$TARGET_LABEL" "$EXPECTED_REGION" "$EXPECTED_TYPE" <<'PY'
from __future__ import annotations

import ipaddress
import json
import sys

path, expected_id, expected_label, expected_region, expected_type = sys.argv[1:]
try:
    value = json.loads(open(path, encoding="utf-8").read())
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit("target_response_invalid") from exc
if not isinstance(value, dict) or value.get("id") != int(expected_id):
    raise SystemExit("target_identity_invalid")
if value.get("label") != expected_label or value.get("region") != expected_region:
    raise SystemExit("target_identity_invalid")
if value.get("type") != expected_type:
    raise SystemExit("target_spec_invalid")
if value.get("status") != "running":
    raise SystemExit("target_not_running")
addresses = value.get("ipv4")
if not isinstance(addresses, list) or not addresses:
    raise SystemExit("target_address_missing")
try:
    address = ipaddress.ip_address(addresses[0])
except ValueError as exc:
    raise SystemExit("target_address_invalid") from exc
if address.version != 4 or address.is_unspecified or address.is_loopback:
    raise SystemExit("target_address_invalid")
print(address)
PY
}

assert_target_restore_state() {
  local response="$1"
  local expected_id="$2"
  python3 - "$response" "$expected_id" "$TARGET_LABEL" "$EXPECTED_REGION" "$EXPECTED_TYPE" <<'PY'
from __future__ import annotations

import ipaddress
import json
import sys

path, expected_id, expected_label, expected_region, expected_type = sys.argv[1:]
try:
    value = json.loads(open(path, encoding="utf-8").read())
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit("target_response_invalid") from exc
if not isinstance(value, dict) or value.get("id") != int(expected_id):
    raise SystemExit("target_identity_invalid")
if value.get("label") != expected_label or value.get("region") != expected_region:
    raise SystemExit("target_identity_invalid")
if value.get("type") != expected_type:
    raise SystemExit("target_spec_invalid")
status = value.get("status")
if status not in {"offline", "running"}:
    raise SystemExit("target_restore_not_complete")
if status == "running":
    addresses = value.get("ipv4")
    if not isinstance(addresses, list) or not addresses:
        raise SystemExit("target_address_missing")
    try:
        address = ipaddress.ip_address(addresses[0])
    except ValueError as exc:
        raise SystemExit("target_address_invalid") from exc
    if address.version != 4 or address.is_unspecified or address.is_loopback:
        raise SystemExit("target_address_invalid")
    print(f"running {address}")
else:
    print("offline")
PY
}

assert_resume_target() {
  local response="$1"
  local expected_id="$2"
  python3 - "$response" "$expected_id" "$TARGET_LABEL" "$EXPECTED_REGION" "$EXPECTED_TYPE" <<'PY'
from __future__ import annotations

import ipaddress
import json
import sys

path, expected_id, expected_label, expected_region, expected_type = sys.argv[1:]
try:
    value = json.loads(open(path, encoding="utf-8").read())
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit("resume_target_response_invalid") from exc
if not isinstance(value, dict) or value.get("id") != int(expected_id):
    raise SystemExit("resume_target_identity_invalid")
if value.get("label") != expected_label or value.get("region") != expected_region:
    raise SystemExit("resume_target_identity_invalid")
if value.get("type") != expected_type:
    raise SystemExit("resume_target_spec_invalid")
status = value.get("status")
if status not in {"restoring", "offline", "running"}:
    raise SystemExit("resume_target_status_invalid")
if status == "running":
    addresses = value.get("ipv4")
    if not isinstance(addresses, list) or not addresses:
        raise SystemExit("resume_target_address_missing")
    try:
        address = ipaddress.ip_address(addresses[0])
    except ValueError as exc:
        raise SystemExit("resume_target_address_invalid") from exc
    if address.version != 4 or address.is_unspecified or address.is_loopback:
        raise SystemExit("resume_target_address_invalid")
    print(f"running {address}")
else:
    print(status)
PY
}

assert_firewall_attached() {
  local response="$1"
  python3 - "$response" "$FIREWALL_ID" <<'PY'
from __future__ import annotations

import json
import sys

path, firewall_id = sys.argv[1:]
try:
    value = json.loads(open(path, encoding="utf-8").read())
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit("attached_firewall_response_invalid") from exc
if not isinstance(value, dict) or not isinstance(value.get("data"), list):
    raise SystemExit("attached_firewall_response_invalid")
if not any(isinstance(item, dict) and item.get("id") == int(firewall_id) for item in value["data"]):
    raise SystemExit("fixed_firewall_not_attached")
PY
}

read -r -d '' REMOTE_VERIFY_PY <<'PY' || true
from __future__ import annotations

import hashlib
import json
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

VOLUME = "signal-ledger_signal-ledger-data"
DATABASE_NAME = "stock_probs.sqlite3"
COMPOSE_PATH = "/opt/signal-ledger/compose.production.yaml"
APP_ENV_PATH = "/etc/signal-ledger/app.env"
TUNNEL_UNIT = "signal-ledger-cloudflared.service"


def run(arguments: list[str], limit: int = 4096) -> str:
    result = subprocess.run(
        arguments,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if result.returncode != 0 or len(result.stdout) > limit:
        raise SystemExit("remote_command_failed")
    return result.stdout.strip()


def regular_file(path: Path, maximum: int) -> None:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise SystemExit("remote_path_invalid")
    if info.st_size <= 0 or info.st_size > maximum:
        raise SystemExit("remote_file_size_invalid")
    return None


def logical_database_hash(database: sqlite3.Connection) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    for line in database.iterdump():
        encoded = (line + "\n").encode("utf-8")
        size += len(encoded)
        if size > 512 * 1024 * 1024:
            raise SystemExit("remote_logical_database_too_large")
        digest.update(encoded)
    return digest.hexdigest(), size


def inactive(action: str) -> bool:
    result = subprocess.run(
        ["/usr/bin/systemctl", action, "--quiet", TUNNEL_UNIT],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode != 0


try:
    mountpoint_lines = run(
        ["/usr/bin/docker", "volume", "inspect", "--format", "{{.Mountpoint}}", VOLUME]
    ).splitlines()
    if len(mountpoint_lines) != 1:
        raise SystemExit("remote_volume_invalid")
    mountpoint = Path(mountpoint_lines[0])
    if not mountpoint.is_absolute() or not str(mountpoint).startswith("/var/lib/docker/volumes/"):
        raise SystemExit("remote_volume_invalid")
    database_path = mountpoint / DATABASE_NAME
    regular_file(database_path, 512 * 1024 * 1024)
    # A read-only SQLite transaction sees the main database and any adjacent WAL pages as one
    # consistent snapshot. Hashing the canonical logical dump avoids claiming equality from the
    # main file alone when a writer has not checkpointed its WAL yet.
    database = sqlite3.connect(f"file:{quote(str(database_path))}?mode=ro", uri=True, timeout=5.0)
    try:
        database.execute("PRAGMA query_only = ON")
        database.execute("PRAGMA busy_timeout = 5000")
        database.execute("BEGIN")
        integrity = database.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key = database.execute("PRAGMA foreign_key_check").fetchone()
        schema = database.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
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
        database_digest, logical_database_size = logical_database_hash(database)
    finally:
        database.rollback()
        database.close()
    compose_path = Path(COMPOSE_PATH)
    regular_file(compose_path, 512 * 1024)
    compose_bytes = compose_path.read_bytes()
    app_env_info = Path(APP_ENV_PATH).lstat()
    if stat.S_ISLNK(app_env_info.st_mode) or not stat.S_ISREG(app_env_info.st_mode):
        raise SystemExit("remote_app_env_invalid")
    if app_env_info.st_size <= 0 or app_env_info.st_size > 64 * 1024:
        raise SystemExit("remote_app_env_size_invalid")
    if app_env_info.st_mode & 0o077:
        raise SystemExit("remote_app_env_permissions")
    if b"127.0.0.1:8000:8000" not in compose_bytes or b"0.0.0.0:8000" in compose_bytes:
        raise SystemExit("remote_compose_not_loopback_only")
    if integrity != "ok" or foreign_key is not None or not isinstance(schema, int):
        raise SystemExit("remote_database_integrity_failed")
    record = {
        "logical_database_sha256": database_digest,
        "logical_database_size": logical_database_size,
        "compose_sha256": hashlib.sha256(compose_bytes).hexdigest(),
        "schema_version": schema,
        "counts": counts,
        "loopback_only": True,
        "tunnel_enabled": not inactive("is-enabled"),
        "tunnel_active": not inactive("is-active"),
    }
except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
    raise SystemExit("remote_verification_failed") from exc

sys.stdout.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
PY
REMOTE_VERIFY_COMMAND="$(printf '%q ' /usr/bin/sudo -n /usr/bin/python3 -c "$REMOTE_VERIFY_PY")"

ssh_options() {
  printf '%s\n' \
    -T \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=yes \
    -o IdentitiesOnly=yes \
    -o ClearAllForwardings=yes \
    -o ConnectTimeout=10 \
    -o UserKnownHostsFile="$1" \
    -i "$IDENTITY_FILE"
}

remote_verify() {
  local address="$1"
  local known_hosts="$2"
  local output="$3"
  local remote_target="${REMOTE_USER}@${address}"
  local -a options
  mapfile -t options < <(ssh_options "$known_hosts")
  local remote_output
  # The fixed Python verifier is intentionally quoted as one remote shell command.
  # shellcheck disable=SC2029
  if ! remote_output="$(ssh "${options[@]}" "$remote_target" "$REMOTE_VERIFY_COMMAND")"; then
    return 1
  fi
  (( ${#remote_output} > 0 && ${#remote_output} <= MAX_REMOTE_OUTPUT_BYTES )) || return 1
  printf '%s\n' "$remote_output" > "$output"
  python3 - "$output" <<'PY'
from __future__ import annotations

import json
import re
import sys

try:
    lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
    value = json.loads(lines[0]) if len(lines) == 1 else None
except (OSError, UnicodeDecodeError, json.JSONDecodeError):
    value = None
if not isinstance(value, dict):
    raise SystemExit("remote_record_invalid")
if re.fullmatch(r"[0-9a-f]{64}", value.get("logical_database_sha256", "")) is None:
    raise SystemExit("remote_database_hash_invalid")
if type(value.get("logical_database_size")) is not int or not 0 < value["logical_database_size"] <= 512 * 1024 * 1024:
    raise SystemExit("remote_logical_database_size_invalid")
if re.fullmatch(r"[0-9a-f]{64}", value.get("compose_sha256", "")) is None:
    raise SystemExit("remote_compose_hash_invalid")
if type(value.get("schema_version")) is not int or value["schema_version"] < 1:
    raise SystemExit("remote_schema_invalid")
counts = value.get("counts")
required = {"events", "runs", "inputs", "results", "outcomes", "holdings", "watchlist"}
if not isinstance(counts, dict) or set(counts) != required:
    raise SystemExit("remote_counts_invalid")
if any(type(counts[key]) is not int or counts[key] < 0 for key in counts):
    raise SystemExit("remote_counts_invalid")
if value.get("loopback_only") is not True:
    raise SystemExit("remote_security_state_invalid")
if type(value.get("tunnel_enabled")) is not bool or type(value.get("tunnel_active")) is not bool:
    raise SystemExit("remote_security_state_invalid")
PY
}

source_response="$TMP_DIR/source.json"
backup_response="$TMP_DIR/backup.json"
firewall_response="$TMP_DIR/firewall.json"
instances_response="$TMP_DIR/instances.json"
api_request GET "/linode/instances/$SOURCE_LINODE_ID" "$source_response"
SOURCE_IP="$(assert_source_instance "$source_response")" || \
  fail 'source Linode did not match the fixed same-spec target'
api_request GET "/linode/instances/$SOURCE_LINODE_ID/backups/$SNAPSHOT_ID" "$backup_response"
assert_backup "$backup_response" || fail 'the fixed snapshot is not a successful available backup'
api_request GET "/networking/firewalls/$FIREWALL_ID" "$firewall_response"
assert_firewall "$firewall_response" || fail 'the fixed firewall is not a closed SSH-only policy'
if [[ "$RESUME_EXISTING" != true ]]; then
  api_request GET "/linode/instances?page_size=500" "$instances_response"
  assert_label_available "$instances_response" || fail 'the fixed rehearsal label is not available'
fi

if [[ "$EXECUTE" != true ]]; then
  printf 'Read-only rehearsal checks passed for source %s, snapshot %s, firewall %s; no Linode was created.\n' \
    "$SOURCE_LINODE_ID" "$SNAPSHOT_ID" "$FIREWALL_ID"
  exit 0
fi

command -v ssh >/dev/null 2>&1 || fail 'ssh is required with --execute'
command -v ssh-keygen >/dev/null 2>&1 || fail 'ssh-keygen is required with --execute'
command -v ssh-keyscan >/dev/null 2>&1 || fail 'ssh-keyscan is required with --execute'

source_remote="$TMP_DIR/source-remote.json"
if ! remote_verify "$SOURCE_IP" "$KNOWN_HOSTS_FILE" "$source_remote"; then
  fail 'source SSH verification failed; no rehearsal instance was created'
fi

if [[ "$RESUME_EXISTING" == true ]]; then
  TARGET_ID="$RESUME_TARGET_ID"
else
  target_body="{\"backup_id\":385239936,\"label\":\"signal-ledger-backup-rehearsal-385239936\",\"region\":\"us-east\",\"type\":\"g6-nanode-1\",\"backups_enabled\":true,\"disk_encryption\":\"enabled\",\"booted\":false,\"firewall_id\":177236117,\"metadata\":{\"user_data\":\"$RESTORE_USER_DATA_B64\"}}"
  create_response="$TMP_DIR/create.json"
  api_request POST "/linode/instances" "$create_response" "$target_body"
  TARGET_ID="$(assert_created_instance "$create_response")" || fail 'Linode API returned an unsafe rehearsal instance'
fi

target_response="$TMP_DIR/target.json"
TARGET_IP=""
TARGET_STATUS=""
for _attempt in $(seq 1 "$MAX_RESTORE_WAIT_ATTEMPTS"); do
  api_request GET "/linode/instances/$TARGET_ID" "$target_response"
  if [[ "$RESUME_EXISTING" == true ]]; then
    target_state="$(assert_resume_target "$target_response" "$TARGET_ID")" || \
      fail 'fixed resume target identity or status validation failed'
    if [[ "$target_state" == offline || "$target_state" == running* ]]; then
      TARGET_STATUS="${target_state%% *}"
      if [[ "$TARGET_STATUS" == running ]]; then
        TARGET_IP="${target_state#* }"
      fi
      break
    fi
  elif target_state="$(assert_target_restore_state "$target_response" "$TARGET_ID" 2>/dev/null)"; then
    TARGET_STATUS="${target_state%% *}"
    if [[ "$TARGET_STATUS" == running ]]; then
      TARGET_IP="${target_state#* }"
    fi
    break
  fi
  sleep "$WAIT_SECONDS"
done
[[ -n "$TARGET_STATUS" ]] || fail 'disposable Linode restore did not reach offline or running state in time'

# Check the attachment before any explicit boot. The create request includes the fixed
# firewall ID, but this read-back prevents booting a clone with an unexpected attachment.
attached_response="$TMP_DIR/attached-firewalls-before-boot.json"
api_request GET "/linode/instances/$TARGET_ID/firewalls" "$attached_response"
assert_firewall_attached "$attached_response" || \
  fail 'the disposable Linode is not attached to firewall 177236117'

if [[ "$TARGET_STATUS" == offline ]]; then
  # Linode can finish restoring a snapshot in the offline state. Boot only the instance
  # returned by the fixed create request, then continue through the normal running gate.
  boot_response="$TMP_DIR/boot.json"
  api_request POST "/linode/instances/$TARGET_ID/boot" "$boot_response"
  for _attempt in $(seq 1 "$MAX_WAIT_ATTEMPTS"); do
    api_request GET "/linode/instances/$TARGET_ID" "$target_response"
    if TARGET_IP="$(assert_target_instance "$target_response" "$TARGET_ID" 2>/dev/null)"; then
      break
    fi
    sleep "$WAIT_SECONDS"
  done
fi
[[ -n "$TARGET_IP" ]] || fail 'disposable Linode did not reach the fixed running state in time'

# Re-read after a boot when the restore completed offline, so the SSH boundary is checked on
# the running instance as well.
if [[ "$TARGET_STATUS" == offline ]]; then
  attached_response="$TMP_DIR/attached-firewalls-after-boot.json"
  api_request GET "/linode/instances/$TARGET_ID/firewalls" "$attached_response"
  assert_firewall_attached "$attached_response" || \
    fail 'the running disposable Linode is not attached to firewall 177236117'
fi

# A backup clone is expected to carry the source SSH host keys. Compare the new address's
# observed keys with the operator-trusted source entry before connecting; never use TOFU.
source_key_material="$TMP_DIR/source-key-material"
target_keyscan="$TMP_DIR/target-keyscan"
target_known_hosts="$TMP_DIR/target-known-hosts"
ssh-keygen -F "$SOURCE_IP" -f "$KNOWN_HOSTS_FILE" 2>/dev/null |
  awk 'NF >= 3 && $2 ~ /^(ssh-|ecdsa-|sk-)/ { print $2 "\t" $3 }' | sort -u > "$source_key_material"
[[ -s "$source_key_material" ]] || fail 'trusted known-hosts file has no source host key'
: > "$target_known_hosts"
for _attempt in $(seq 1 "$MAX_KEYSCAN_ATTEMPTS"); do
  if ssh-keyscan -T 10 -4 "$TARGET_IP" 2>/dev/null |
    awk 'NF >= 3 && $2 ~ /^(ssh-|ecdsa-|sk-)/ { print $2 "\t" $3 }' | sort -u > "$target_keyscan" &&
    [[ -s "$target_keyscan" ]] &&
    comm -12 "$source_key_material" "$target_keyscan" | awk -F '\t' -v host="$TARGET_IP" \
      '{ print host " " $1 " " $2 }' > "$target_known_hosts" &&
    [[ -s "$target_known_hosts" ]]; then
    break
  fi
  if ((_attempt < MAX_KEYSCAN_ATTEMPTS)); then
    sleep "$KEYSCAN_WAIT_SECONDS"
  fi
done
[[ -s "$target_known_hosts" ]] || fail 'disposable host key did not match the trusted source key'
chmod 600 "$target_known_hosts"

target_remote="$TMP_DIR/target-remote.json"
verified=false
for _attempt in $(seq 1 "$MAX_WAIT_ATTEMPTS"); do
  if remote_verify "$TARGET_IP" "$target_known_hosts" "$target_remote"; then
    verified=true
    break
  fi
  sleep "$WAIT_SECONDS"
done
[[ "$verified" == true ]] || fail 'disposable host did not pass the fixed SSH/application verification'

python3 - "$source_remote" "$target_remote" <<'PY'
from __future__ import annotations

import json
import sys

try:
    source = json.loads(open(sys.argv[1], encoding="utf-8").read())
    target = json.loads(open(sys.argv[2], encoding="utf-8").read())
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit("remote_record_invalid") from exc
if source["logical_database_sha256"] != target["logical_database_sha256"]:
    raise SystemExit("restored_database_hash_mismatch")
if source["logical_database_size"] != target["logical_database_size"]:
    raise SystemExit("restored_database_size_mismatch")
if source["compose_sha256"] != target["compose_sha256"]:
    raise SystemExit("restored_compose_hash_mismatch")
if source["schema_version"] != target["schema_version"] or source["counts"] != target["counts"]:
    raise SystemExit("restored_database_metadata_mismatch")
if target["tunnel_enabled"] or target["tunnel_active"]:
    raise SystemExit("restored_tunnel_not_closed")
if target["loopback_only"] is not True:
    raise SystemExit("restored_compose_not_loopback_only")
PY

delete_response="$TMP_DIR/delete.json"
api_request DELETE "/linode/instances/$TARGET_ID" "$delete_response"
for _attempt in $(seq 1 12); do
  api_request GET "/linode/instances/$TARGET_ID" "$TMP_DIR/delete-check.json" "" true || true
  [[ "$API_LAST_STATUS" == 404 ]] && break
  sleep "$WAIT_SECONDS"
done
[[ "$API_LAST_STATUS" == 404 ]] || fail 'Linode API did not confirm deletion of the disposable instance'
TARGET_DELETED=true

if [[ -n "$RECEIPT_FILE" ]]; then
  python3 - "$RECEIPT_FILE" "$TARGET_ID" "$SNAPSHOT_ID" "$FIREWALL_ID" "$source_remote" <<'PY'
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

destination = Path(sys.argv[1])
if destination.exists() or destination.is_symlink():
    raise SystemExit("receipt_destination_exists")
parent = destination.parent
if not parent.is_dir() or parent.is_symlink():
    raise SystemExit("receipt_parent_invalid")
source = json.loads(Path(sys.argv[5]).read_text(encoding="utf-8"))
record = {
    "kind": "linode_vm_backup_rehearsal",
    "result": "Pass",
    "source_linode_id": 106817202,
    "rehearsal_instance_id": int(sys.argv[2]),
    "snapshot_id": int(sys.argv[3]),
    "firewall_id": int(sys.argv[4]),
    "rehearsal_instance_deleted": True,
    "logical_database_sha256": source["logical_database_sha256"],
    "logical_database_size": source["logical_database_size"],
    "compose_sha256": source["compose_sha256"],
    "schema_version": source["schema_version"],
    "counts": source["counts"],
}
encoded = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
try:
    with os.fdopen(descriptor, "wb") as stream:
        descriptor = -1
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
finally:
    if descriptor >= 0:
        os.close(descriptor)
PY
fi

printf 'Backup recovery rehearsal passed; disposable instance %s was deleted after verification.\n' "$TARGET_ID"
