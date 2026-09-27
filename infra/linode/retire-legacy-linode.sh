#!/usr/bin/env bash
# Retire only the historical host after independently recorded cutover evidence.
set -euo pipefail

OLD_INSTANCE_ID=97934478
API_ROOT="https://api.linode.com/v4/linode/instances"
CONFIRMATION="DELETE-LEGACY-97934478"
EXECUTE=false
REPLACEMENT_ID=""
BACKUP_RECEIPT=""
MIGRATION_RECEIPT=""
CANARY_RECEIPT=""
CONFIRM=""

usage() {
  cat <<'EOF'
Usage:
  retire-legacy-linode.sh --replacement-id ID \
    --backup-receipt FILE --migration-receipt FILE --canary-receipt FILE \
    --confirm DELETE-LEGACY-97934478 [--execute]

The receipts must record a passing backup/recovery rehearsal, data migration,
and owner-only canary for a replacement whose ID differs from 97934478.
Without --execute this command validates evidence only. With --execute,
LINODE_TOKEN is used for fixed API calls; it is never printed.
EOF
}

fail() {
  printf 'legacy retirement refused: %s\n' "$1" >&2
  exit 2
}

while (($# > 0)); do
  case "$1" in
    --replacement-id) (($# >= 2)) || fail '--replacement-id requires a value'; REPLACEMENT_ID="$2"; shift 2 ;;
    --backup-receipt) (($# >= 2)) || fail '--backup-receipt requires a path'; BACKUP_RECEIPT="$2"; shift 2 ;;
    --migration-receipt) (($# >= 2)) || fail '--migration-receipt requires a path'; MIGRATION_RECEIPT="$2"; shift 2 ;;
    --canary-receipt) (($# >= 2)) || fail '--canary-receipt requires a path'; CANARY_RECEIPT="$2"; shift 2 ;;
    --confirm) (($# >= 2)) || fail '--confirm requires the fixed confirmation string'; CONFIRM="$2"; shift 2 ;;
    --execute) EXECUTE=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) fail "unknown option: $1" ;;
  esac
done

[[ "$REPLACEMENT_ID" =~ ^[0-9]+$ ]] || fail 'replacement ID must be a positive integer'
(( REPLACEMENT_ID > 0 && REPLACEMENT_ID != OLD_INSTANCE_ID )) || \
  fail 'replacement ID must differ from legacy instance 97934478'
[[ "$CONFIRM" == "$CONFIRMATION" ]] || fail "exact confirmation $CONFIRMATION is required"
[[ -n "$BACKUP_RECEIPT" && -n "$MIGRATION_RECEIPT" && -n "$CANARY_RECEIPT" ]] || \
  fail 'all three evidence receipts are required'

# Receipt validation is local and strict. Each artifact must be distinct, bounded, and tied to
# the same replacement instance before any remote API request is considered.
python3 - "$REPLACEMENT_ID" "$BACKUP_RECEIPT" "$MIGRATION_RECEIPT" "$CANARY_RECEIPT" <<'PY'
from __future__ import annotations

import json
import re
import stat
import sys
from pathlib import Path

old_id = 97934478
replacement_id = int(sys.argv[1])
receipts = (
    (Path(sys.argv[2]), "backup_recovery"),
    (Path(sys.argv[3]), "data_migration"),
    (Path(sys.argv[4]), "owner_canary"),
)
seen_inodes: set[tuple[int, int]] = set()
sha256 = re.compile(r"^[0-9a-f]{64}$")
required = {
    "backup_recovery": {"backup_verified": True, "recovery_rehearsed": True, "backup_sha256": sha256, "recovery_rehearsal_id": str},
    "data_migration": {"migration_completed": True, "source_database_sha256": sha256, "target_database_sha256": sha256, "migration_id": str},
    "owner_canary": {"canary_passed": True, "canary_id": str, "public_route_open": False},
}

for path, kind in receipts:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise SystemExit(f"receipt unavailable: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SystemExit(f"receipt must be a regular non-symlink file: {path}")
    if metadata.st_size == 0 or metadata.st_size > 64 * 1024:
        raise SystemExit(f"receipt size is outside the bounded range: {path}")
    inode = (metadata.st_dev, metadata.st_ino)
    if inode in seen_inodes:
        raise SystemExit("the three receipts must be distinct files")
    seen_inodes.add(inode)
    try:
        with path.open("rb") as stream:
            record = json.load(stream)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"receipt is not valid JSON: {path}") from exc
    if not isinstance(record, dict):
        raise SystemExit(f"receipt root must be an object: {path}")
    if record.get("kind") != kind or record.get("result") != "Pass":
        raise SystemExit(f"receipt does not pass its required scope: {path}")
    if record.get("legacy_instance_id") != old_id:
        raise SystemExit(f"receipt names an unexpected legacy instance: {path}")
    if record.get("replacement_instance_id") != replacement_id:
        raise SystemExit(f"receipt names a different replacement instance: {path}")
    if not isinstance(record.get("receipt_id"), str) or not record["receipt_id"].strip():
        raise SystemExit(f"receipt_id is required: {path}")
    for field, expected in required[kind].items():
        value = record.get(field)
        if isinstance(expected, re.Pattern):
            if not isinstance(value, str) or expected.fullmatch(value) is None:
                raise SystemExit(f"{field} is invalid in receipt: {path}")
        elif expected is str:
            if not isinstance(value, str) or not value.strip():
                raise SystemExit(f"{field} is required in receipt: {path}")
        elif value is not expected:
            raise SystemExit(f"{field} is not proven in receipt: {path}")
PY

if [[ "$EXECUTE" != true ]]; then
  printf 'Evidence accepted for replacement %s; deletion not requested.\n' "$REPLACEMENT_ID"
  exit 0
fi

[[ -n "${LINODE_TOKEN:-}" ]] || fail 'LINODE_TOKEN is required for API retirement'
if [[ ! "$LINODE_TOKEN" =~ ^[A-Za-z0-9._~+/=-]{1,512}$ ]]; then
  fail 'LINODE_TOKEN must be a bounded single-line token with safe header characters'
fi
command -v curl >/dev/null || fail 'curl is required for API retirement'
command -v python3 >/dev/null || fail 'python3 is required for API retirement'
API_TMP="$(mktemp -d /tmp/signal-ledger-retire.XXXXXX)"
trap 'rm -rf -- "$API_TMP"' EXIT

api_curl() {
  # Keep the token in the pipe-fed curl configuration instead of exposing it in argv.
  printf 'header = "Authorization: Bearer %s"\nheader = "Accept: application/json"\n' \
    "$LINODE_TOKEN" |
    curl --silent --show-error --proto '=https' --tlsv1.2 \
      --connect-timeout 10 --max-time 30 --config - "$@"
}

api_get() {
  local instance_id="$1"
  local output_path="$2"
  local status
  status="$(api_curl --output "$output_path" --write-out '%{http_code}' \
    "$API_ROOT/$instance_id")" || fail "Linode API lookup failed for fixed instance $instance_id"
  [[ "$status" == 200 ]] || fail "Linode API lookup returned HTTP $status for fixed instance $instance_id"
}

api_get "$OLD_INSTANCE_ID" "$API_TMP/legacy.json"
api_get "$REPLACEMENT_ID" "$API_TMP/replacement.json"
python3 - "$API_TMP/legacy.json" "$API_TMP/replacement.json" "$REPLACEMENT_ID" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    legacy = json.load(stream)
with open(sys.argv[2], encoding="utf-8") as stream:
    replacement = json.load(stream)
if legacy.get("id") != 97934478:
    raise SystemExit("the fixed legacy API response did not identify 97934478")
if replacement.get("id") != int(sys.argv[3]):
    raise SystemExit("the replacement API response did not identify the requested instance")
PY

delete_status="$(api_curl --request DELETE --output /dev/null --write-out '%{http_code}' \
  "$API_ROOT/$OLD_INSTANCE_ID")" || \
  fail 'Linode API deletion request failed'
[[ "$delete_status" == 200 || "$delete_status" == 202 || "$delete_status" == 204 ]] || \
  fail "Linode API deletion returned unexpected HTTP $delete_status"
printf 'Linode API accepted retirement of legacy %s; replacement %s was checked first.\n' \
  "$OLD_INSTANCE_ID" "$REPLACEMENT_ID"
