#!/usr/bin/env bash
# Install one Resend SMTP API key and recreate the fixed production app.
set -euo pipefail

readonly REMOTE_HOST="45.79.180.32"
readonly REMOTE_USER="signalops"
readonly REMOTE_TARGET="${REMOTE_USER}@${REMOTE_HOST}"
readonly DEFAULT_IDENTITY_FILE="${HOME}/.ssh/signal-ledger-operator-2026"
readonly DEFAULT_KNOWN_HOSTS_FILE="${XDG_CONFIG_HOME:-${HOME}/.config}/signal-ledger/credentials/linode-known-hosts"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly ROOT
REMOTE_HELPER="${ROOT}/infra/linode/smtp-credential-installer.py"
readonly REMOTE_HELPER

fail() {
  printf 'install-resend-smtp-key: %s\n' "$1" >&2
  exit 2
}

usage() {
  cat >&2 <<'EOF'
Usage: install-resend-smtp-key.sh --api-key-file FILE

The host, operator account, remote app.env, Compose file, runtime image reference, and
readiness URL are fixed. The API-key file must be a private regular file containing one
Resend key. For the local operator checkout only, set
SIGNAL_LEDGER_OPERATOR_IDENTITY_FILE or SIGNAL_LEDGER_KNOWN_HOSTS_FILE when the defaults
are not available.
EOF
}

api_key_file=""
while (($# > 0)); do
  case "$1" in
    --api-key-file)
      (($# >= 2)) || fail '--api-key-file requires a value'
      [[ -z "$api_key_file" ]] || fail '--api-key-file may be supplied once'
      api_key_file="$2"
      shift 2
      ;;
    --help|-h)
      (($# == 1)) || fail 'no extra arguments are accepted'
      usage
      exit 0
      ;;
    *)
      usage
      fail 'no host, user, command, URL, or remote path arguments are accepted'
      ;;
  esac
done

[[ -n "$api_key_file" ]] || {
  usage
  fail '--api-key-file is required'
}
[[ "$api_key_file" != *$'\n'* && "$api_key_file" != *$'\r'* ]] || \
  fail 'API-key file path is invalid'

identity_file="${SIGNAL_LEDGER_OPERATOR_IDENTITY_FILE:-$DEFAULT_IDENTITY_FILE}"
known_hosts_file="${SIGNAL_LEDGER_KNOWN_HOSTS_FILE:-$DEFAULT_KNOWN_HOSTS_FILE}"

# Match the fixed source gate used by the other operator helpers so command lookup and Git
# configuration cannot be redirected by the invoking environment.
export PATH=/usr/bin:/bin
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES
unset GIT_COMMON_DIR GIT_CONFIG GIT_CONFIG_COUNT GIT_CONFIG_PARAMETERS GIT_CONFIG_KEY_0 GIT_CONFIG_VALUE_0
unset GIT_SSH GIT_SSH_COMMAND GIT_PROXY_COMMAND GIT_ASKPASS SSH_ASKPASS GIT_SSL_NO_VERIFY
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_NOSYSTEM=1

require_private_file() {
  local path="$1"
  local label="$2"
  [[ -n "$path" && "$path" != *$'\n'* && "$path" != *$'\r'* ]] || \
    fail "$label path is invalid"
  [[ -f "$path" && ! -L "$path" ]] || fail "$label must be a regular non-symlink file"
  local mode
  mode="$(stat -c '%a' -- "$path" 2>/dev/null)" || fail "could not stat $label"
  (( (8#$mode & 077) == 0 )) || fail "$label must not be group/other-readable"
}

require_private_file "$identity_file" 'operator identity file'
require_private_file "$known_hosts_file" 'known-hosts file'
[[ -f "$REMOTE_HELPER" && ! -L "$REMOTE_HELPER" ]] || \
  fail 'remote installer must be a regular non-symlink file'
command -v python3 >/dev/null 2>&1 || fail 'python3 is required'
command -v ssh >/dev/null 2>&1 || fail 'ssh is required'
command -v ssh-keygen >/dev/null 2>&1 || fail 'ssh-keygen is required'
command -v base64 >/dev/null 2>&1 || fail 'base64 is required'

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

remote_python_base64="$(base64 < "$REMOTE_HELPER" | tr -d '\n')" || \
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
# Keep the remote shell argument quoted while transporting only a base64 literal. Python
# decodes and executes the fixed helper source; source quotes never become shell syntax.
# shellcheck disable=SC2029,SC2155
remote_command="/usr/bin/sudo -n -- /usr/bin/python3 -c 'import base64;exec(base64.b64decode(\"${remote_python_base64}\"))'"
readonly remote_command

validate_api_key_file() {
  # Validation is local-only and emits no key bytes. The validated file is then redirected
  # directly to the remote helper's stdin.
  /usr/bin/python3 "$REMOTE_HELPER" --validate-file "$api_key_file"
}

# The key is validated without placing its bytes in shell state, then redirected to the fixed
# helper's stdin. SSH output is suppressed so neither Docker diagnostics nor the secret can reach
# the terminal or a caller's log.
# shellcheck disable=SC2029
if ! validate_api_key_file >/dev/null 2>&1; then
  fail 'local SMTP API-key file is invalid'
fi
# shellcheck disable=SC2029
if ssh "${ssh_options[@]}" "$REMOTE_TARGET" "$remote_command" <"$api_key_file" >/dev/null 2>&1; then
  :
else
  ssh_status=$?
  if ((ssh_status == 3)); then
    fail 'SMTP update failed; the original app.env was restored and the fixed app passed readiness'
  fi
  fail 'fixed-host SMTP update failed; a private rollback artifact may be retained for recovery'
fi

printf 'Resend SMTP credential installed and the fixed production app passed readiness.\n'
