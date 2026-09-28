#!/usr/bin/env bash
# Install the reviewed tunnel unit on the fixed host without starting the connector.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly UNIT_SOURCE="$script_dir/signal-ledger-cloudflared.service"
readonly REMOTE_HOST="45.79.180.32"
readonly REMOTE_USER="signalops"
readonly REMOTE_UNIT="/etc/systemd/system/signal-ledger-cloudflared.service"
readonly DEFAULT_IDENTITY_FILE="${HOME}/.ssh/signal-ledger-operator-2026"
readonly DEFAULT_KNOWN_HOSTS_FILE="${XDG_CONFIG_HOME:-${HOME}/.config}/signal-ledger/credentials/linode-known-hosts"

fail() {
  printf 'update-host-unit: %s\n' "$1" >&2
  exit 2
}

usage() {
  cat >&2 <<'EOF'
Usage: update-host-unit.sh

The host, SSH account, remote unit path, and remote commands are fixed. For the local
operator checkout only, set SIGNAL_LEDGER_OPERATOR_IDENTITY_FILE or
SIGNAL_LEDGER_KNOWN_HOSTS_FILE when the defaults are not available.
EOF
}

if (($# > 0)); then
  [[ "$#" -eq 1 && "$1" == "--help" ]] || {
    usage
    fail 'no command, host, URL, or path arguments are accepted'
  }
  usage
  exit 0
fi

identity_file="${SIGNAL_LEDGER_OPERATOR_IDENTITY_FILE:-$DEFAULT_IDENTITY_FILE}"
known_hosts_file="${SIGNAL_LEDGER_KNOWN_HOSTS_FILE:-$DEFAULT_KNOWN_HOSTS_FILE}"

require_private_file() {
  local path="$1"
  local label="$2"
  [[ -n "$path" && "$path" != *$'\n'* && "$path" != *$'\r'* ]] || fail "$label path is invalid"
  [[ -f "$path" && ! -L "$path" ]] || fail "$label must be a regular non-symlink file"
  local mode
  mode="$(stat -c '%a' -- "$path")" || fail "could not stat $label"
  (( (8#$mode & 077) == 0 )) || fail "$label must not be group/other-readable"
}

[[ -f "$UNIT_SOURCE" && ! -L "$UNIT_SOURCE" ]] || \
  fail 'reviewed Cloudflare Tunnel unit artifact is unavailable'
require_private_file "$identity_file" 'SSH identity file'
require_private_file "$known_hosts_file" 'known-hosts file'

command -v ssh >/dev/null 2>&1 || fail 'ssh is required'
command -v ssh-keygen >/dev/null 2>&1 || fail 'ssh-keygen is required'
command -v sha256sum >/dev/null 2>&1 || fail 'sha256sum is required'

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
  fail 'known-hosts file contains a host entry outside the fixed Signal Ledger host'
fi

unit_sha256="$(sha256sum "$UNIT_SOURCE" | awk '{print $1}')" || fail 'could not hash reviewed unit'
[[ "$unit_sha256" =~ ^[0-9a-f]{64}$ ]] || fail 'reviewed unit hash is invalid'

readonly remote_target="${REMOTE_USER}@${REMOTE_HOST}"
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

# The remote command and destination are fixed. The reviewed hash is validated above before it
# is inserted, and the unit bytes arrive on stdin so no user-controlled path or shell text is
# sent to the host. disable --now plus is-active proves the connector remains stopped.
remote_command="set -eu
/usr/bin/sudo -n -- /usr/bin/install -o root -g root -m 0644 /dev/stdin '$REMOTE_UNIT'
/usr/bin/sudo -n -- /usr/bin/systemctl daemon-reload
/usr/bin/sudo -n -- /usr/bin/systemctl disable --now signal-ledger-cloudflared.service
remote_sha256=\$(/usr/bin/sudo -n -- /usr/bin/sha256sum '$REMOTE_UNIT' | /usr/bin/awk '{print \$1}')
[ \"\$remote_sha256\" = '$unit_sha256' ]
if /usr/bin/sudo -n -- /usr/bin/systemctl is-active --quiet signal-ledger-cloudflared.service; then
  exit 1
fi"

if ! ssh "${ssh_options[@]}" "$remote_target" "$remote_command" <"$UNIT_SOURCE" >/dev/null 2>&1; then
  fail 'fixed host unit update failed or tunnel remained active'
fi

printf 'Reviewed Cloudflare Tunnel unit installed on the fixed host; service remains stopped.\n'
