#!/usr/bin/env bash
# Enable the already-reviewed owner-only Cloudflare canary on the fixed host.
set -euo pipefail

terraform_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly TERRAFORM_DIR="$terraform_dir"
readonly REMOTE_HOST="45.79.180.32"
readonly REMOTE_USER="signalops"
readonly TUNNEL_UNIT="signal-ledger-cloudflared.service"
readonly HOSTNAME="ledger.jtmb.cc"
readonly ORIGIN_SERVICE="http://127.0.0.1:8000"
readonly CACHE_RULESET_NAME="Signal Ledger cache bypass"
readonly TUNNEL_NAME="signal-ledger"
readonly ACCOUNT_ID="f4c09c14a6618297f411e9ee75305013"
readonly ZONE_ID="53092409b9e2a417c3af37656b48ce64"
readonly DEFAULT_IDENTITY_FILE="${HOME}/.ssh/signal-ledger-operator-2026"
readonly DEFAULT_KNOWN_HOSTS_FILE="${XDG_CONFIG_HOME:-${HOME}/.config}/signal-ledger/credentials/linode-known-hosts"
readonly DEFAULT_OWNER_EMAIL_FILE="${XDG_CONFIG_HOME:-${HOME}/.config}/signal-ledger/credentials/owner-email"
readonly DEFAULT_TERRAFORM_ROOT="${XDG_CONFIG_HOME:-${HOME}/.config}/signal-ledger/terraform/cloudflare"
readonly DEFAULT_STATE_FILE="$DEFAULT_TERRAFORM_ROOT/terraform.tfstate"
readonly DEFAULT_TF_DATA_DIR="$DEFAULT_TERRAFORM_ROOT/data"

fail() {
  printf 'enable-canary: %s\n' "$1" >&2
  exit 2
}

usage() {
  cat >&2 <<'EOF'
Usage: enable-canary.sh

The host, SSH account, remote command, public hostname, Terraform state location, and
Cloudflare resources are fixed. For the local operator checkout only, set
SIGNAL_LEDGER_OPERATOR_IDENTITY_FILE, SIGNAL_LEDGER_KNOWN_HOSTS_FILE,
SIGNAL_LEDGER_OWNER_EMAIL_FILE, SIGNAL_LEDGER_CLOUDFLARE_STATE_FILE,
SIGNAL_LEDGER_CLOUDFLARE_TF_DATA_DIR, or SIGNAL_LEDGER_TERRAFORM_BIN when the private
local defaults are not available. The owner email file must contain exactly one valid
email address and remain private. The
Cloudflare API token must be supplied in CLOUDFLARE_API_TOKEN; it is never accepted
as a command-line argument.
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
owner_email_file="${SIGNAL_LEDGER_OWNER_EMAIL_FILE:-$DEFAULT_OWNER_EMAIL_FILE}"
state_file="${SIGNAL_LEDGER_CLOUDFLARE_STATE_FILE:-$DEFAULT_STATE_FILE}"
tf_data_dir="${SIGNAL_LEDGER_CLOUDFLARE_TF_DATA_DIR:-$DEFAULT_TF_DATA_DIR}"

require_private_file() {
  local path="$1"
  local label="$2"
  [[ -n "$path" && "$path" != *$'\n'* && "$path" != *$'\r'* ]] || fail "$label path is invalid"
  [[ -f "$path" && ! -L "$path" ]] || fail "$label must be a regular non-symlink file"
  local mode
  mode="$(stat -c '%a' -- "$path")" || fail "could not stat $label"
  (( (8#$mode & 077) == 0 )) || fail "$label must not be group/other-readable"
}

require_private_file "$identity_file" 'SSH identity file'
require_private_file "$known_hosts_file" 'known-hosts file'
require_private_file "$owner_email_file" 'owner email file'
require_private_file "$state_file" 'Terraform state file'

owner_email_lines=()
mapfile -t owner_email_lines <"$owner_email_file" || fail 'could not read owner email file'
(( ${#owner_email_lines[@]} == 1 )) || fail 'owner email file must contain exactly one line'
owner_email="${owner_email_lines[0]}"
[[ "$owner_email" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$ ]] || \
  fail 'owner email file must contain a valid email address'

[[ -d "$TERRAFORM_DIR" && ! -L "$TERRAFORM_DIR" ]] || \
  fail 'Terraform workdir must be the repository Cloudflare module'
[[ -d "$tf_data_dir" && ! -L "$tf_data_dir" ]] || \
  fail 'Terraform data directory must be an existing private directory'
tf_data_mode="$(stat -c '%a' -- "$tf_data_dir")" || fail 'could not stat Terraform data directory'
(( (8#$tf_data_mode & 077) == 0 )) || \
  fail 'Terraform data directory must not be group/other-readable'

[[ -n "${CLOUDFLARE_API_TOKEN:-}" ]] || fail 'CLOUDFLARE_API_TOKEN is required'
[[ "$CLOUDFLARE_API_TOKEN" != *$'\n'* && "$CLOUDFLARE_API_TOKEN" != *$'\r'* ]] || \
  fail 'CLOUDFLARE_API_TOKEN must be a single-line value'

command -v ssh >/dev/null 2>&1 || fail 'ssh is required'
command -v ssh-keygen >/dev/null 2>&1 || fail 'ssh-keygen is required'
command -v python3 >/dev/null 2>&1 || fail 'python3 is required'

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

terraform_bin="${SIGNAL_LEDGER_TERRAFORM_BIN:-}"
if [[ -z "$terraform_bin" ]]; then
  terraform_bin="$(command -v terraform 2>/dev/null || true)"
fi
[[ -n "$terraform_bin" && -x "$terraform_bin" ]] || fail 'Terraform is required to verify the applied canary state'

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/signal-ledger-canary.XXXXXX")"
trap 'rm -rf -- "$tmp_dir"' EXIT
chmod 0700 "$tmp_dir"
state_json="$tmp_dir/state.json"
refresh_log="$tmp_dir/provider-refresh-plan.log"

# A full plan is intentionally required immediately before inspecting the state so Terraform
# refreshes every managed object through the provider and catches both remote drift and config
# changes. The provider token is inherited from the environment rather than placed in argv or
# the log. Exit 2 means the refreshed plan has changes; both it and provider errors block startup.
set +e
(
  export TF_DATA_DIR="$tf_data_dir"
  export TF_VAR_owner_email="$owner_email"
  "$terraform_bin" -chdir="$TERRAFORM_DIR" plan \
    -detailed-exitcode \
    -input=false \
    -no-color \
    -lock-timeout=30s \
    -state="$state_file" \
    "-var=account_id=$ACCOUNT_ID" \
    "-var=zone_id=$ZONE_ID" \
    '-var=zone_name=jtmb.cc' \
    "-var=tunnel_name=$TUNNEL_NAME" \
    "-var=hostname=$HOSTNAME" \
    '-var=exposure_mode=canary' \
    '-var=public_invited_confirmation=' \
    >"$refresh_log" 2>&1
)
refresh_status=$?
set -e
if [[ "$refresh_status" -ne 0 ]]; then
  fail 'Cloudflare provider-refreshed plan failed or detected drift'
fi

if ! (
  export TF_DATA_DIR="$tf_data_dir"
  "$terraform_bin" -chdir="$TERRAFORM_DIR" show -json "$state_file" >"$state_json" 2>/dev/null
); then
  fail 'Terraform could not read the Cloudflare state file'
fi
chmod 0600 "$state_json"

SIGNAL_LEDGER_CANARY_OWNER_EMAIL="$owner_email" python3 - "$state_json" "$HOSTNAME" \
  "$ORIGIN_SERVICE" \
  "$CACHE_RULESET_NAME" "$TUNNEL_NAME" "$ACCOUNT_ID" "$ZONE_ID" <<'PY'
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

(
    state_path,
    hostname,
    origin_service,
    cache_name,
    tunnel_name,
    account_id,
    zone_id,
) = sys.argv[1:]
owner_email = os.environ.get("SIGNAL_LEDGER_CANARY_OWNER_EMAIL", "")
if not owner_email:
    raise SystemExit("cloudflare_canary_unverified:missing_owner_email")

try:
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit("cloudflare_state_invalid") from exc


def fail(reason: str) -> None:
    raise SystemExit(f"cloudflare_canary_unverified:{reason}")


def resources(module: dict[str, object]):
    for resource in module.get("resources", []):
        if isinstance(resource, dict):
            yield resource
    for child in module.get("child_modules", []):
        if isinstance(child, dict):
            yield from resources(child)


values = state.get("values")
if not isinstance(values, dict):
    fail("missing_state_values")
root_module = values.get("root_module")
if not isinstance(root_module, dict):
    fail("missing_root_module")

by_address: dict[str, dict[str, object]] = {}
for resource in resources(root_module):
    address = resource.get("address")
    resource_values = resource.get("values")
    if isinstance(address, str) and isinstance(resource_values, dict):
        if address in by_address:
            fail("duplicate_resource")
        by_address[address] = resource_values


def resource(address: str) -> dict[str, object]:
    found = by_address.get(address)
    if found is None:
        fail(f"missing_{address}")
    return found


outputs = values.get("outputs")
if not isinstance(outputs, dict):
    fail("missing_outputs")
mode = outputs.get("exposure_mode", {}).get("value") if isinstance(outputs.get("exposure_mode"), dict) else None
public_hostname = outputs.get("public_hostname", {}).get("value") if isinstance(outputs.get("public_hostname"), dict) else None
if mode != "canary" or public_hostname != hostname:
    fail("exposure_mode_is_not_owner_canary")

access = resource("cloudflare_zero_trust_access_application.canary[0]")
if (
    access.get("type") != "self_hosted"
    or access.get("domain") != hostname
    or access.get("zone_id") != zone_id
):
    fail("access_application_identity")
destinations = access.get("destinations")
if not isinstance(destinations, list) or len(destinations) != 1 or not isinstance(destinations[0], dict):
    fail("access_destinations")
destination_uri = destinations[0].get("uri")
if destination_uri not in (hostname, f"https://{hostname}"):
    fail("access_destination_host")
policies = access.get("policies")
if not isinstance(policies, list) or len(policies) != 1 or not isinstance(policies[0], dict):
    fail("access_policy_count")
policy = policies[0]
if policy.get("decision") != "allow":
    fail("access_policy_decision")
includes = policy.get("include")
if not isinstance(includes, list) or len(includes) != 1 or not isinstance(includes[0], dict):
    fail("access_policy_include")
email_block = includes[0].get("email")
policy_email = email_block.get("email") if isinstance(email_block, dict) else email_block
if not isinstance(policy_email, str) or policy_email.strip().casefold() != owner_email.casefold():
    fail("access_policy_owner")
for key in ("exclude",):
    value = policy.get(key)
    if value not in (None, []):
        fail("access_policy_exclusion")

cache = resource("cloudflare_ruleset.signal_ledger_cache_bypass")
if (
    cache.get("name") != cache_name
    or cache.get("kind") != "zone"
    or cache.get("phase") != "http_request_cache_settings"
    or cache.get("zone_id") != zone_id
):
    fail("cache_ruleset_identity")
rules = cache.get("rules")
if not isinstance(rules, list) or len(rules) != 1 or not isinstance(rules[0], dict):
    fail("cache_rule_count")
rule = rules[0]
parameters = rule.get("action_parameters")
browser_ttl = parameters.get("browser_ttl") if isinstance(parameters, dict) else None
if (
    rule.get("action") != "set_cache_settings"
    or rule.get("enabled") is not True
    or rule.get("expression") != f'(http.host eq "{hostname}")'
    or not isinstance(parameters, dict)
    or parameters.get("cache") is not False
    or not isinstance(browser_ttl, dict)
    or browser_ttl.get("mode") != "bypass"
):
    fail("cache_bypass_rule")

tunnel = resource("cloudflare_zero_trust_tunnel_cloudflared.signal_ledger")
if (
    tunnel.get("name") != tunnel_name
    or tunnel.get("config_src") != "cloudflare"
    or tunnel.get("account_id") != account_id
):
    fail("tunnel_identity")
tunnel_id = tunnel.get("id")
if not isinstance(tunnel_id, str) or re.fullmatch(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}",
    tunnel_id,
) is None:
    fail("tunnel_id")
tunnel_output = outputs.get("tunnel_id")
if not isinstance(tunnel_output, dict) or tunnel_output.get("value") != tunnel_id:
    fail("tunnel_output_id")
tunnel_config_resource = resource("cloudflare_zero_trust_tunnel_cloudflared_config.signal_ledger")
if (
    tunnel_config_resource.get("account_id") != account_id
    or tunnel_config_resource.get("tunnel_id") != tunnel_id
):
    fail("tunnel_config_identity")
config = tunnel_config_resource.get("config")
if isinstance(config, str):
    try:
        config = json.loads(config)
    except json.JSONDecodeError as exc:
        raise SystemExit("cloudflare_canary_unverified:tunnel_config_json") from exc
if not isinstance(config, dict):
    fail("tunnel_config")
ingress = config.get("ingress")
if not isinstance(ingress, list) or len(ingress) != 2:
    fail("tunnel_ingress_count")
canary, terminal = ingress
if not isinstance(canary, dict) or not isinstance(terminal, dict):
    fail("tunnel_ingress_shape")
if (
    canary.get("hostname") != hostname
    or canary.get("service") != origin_service
    or canary.get("path") not in (None, "")
    or canary.get("origin_request") not in (None, {})
    or terminal.get("service") != "http_status:404"
    or terminal.get("hostname") not in (None, "")
    or terminal.get("path") not in (None, "")
):
    fail("tunnel_ingress")

dns = resource("cloudflare_dns_record.canary[0]")
content = dns.get("content")
if (
    dns.get("name") != hostname
    or dns.get("type") != "CNAME"
    or dns.get("zone_id") != zone_id
    or dns.get("proxied") is not True
    or not isinstance(content, str)
    or content != f"{tunnel_id}.cfargotunnel.com"
):
    fail("dns_canary_record")
PY

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

# Both invocations are fixed literals. No caller-controlled command, path, URL, or service name
# reaches the remote shell; the second call proves the first one left the unit active.
if ! ssh "${ssh_options[@]}" "$remote_target" \
  /usr/bin/sudo -n -- /usr/bin/systemctl enable --now "$TUNNEL_UNIT" >/dev/null 2>&1; then
  fail 'fixed host tunnel enable failed'
fi
if ! ssh "${ssh_options[@]}" "$remote_target" \
  /usr/bin/sudo -n -- /usr/bin/systemctl is-active --quiet "$TUNNEL_UNIT" >/dev/null 2>&1; then
  fail 'fixed host tunnel is not active after enable'
fi

printf 'Owner-only Cloudflare canary verified for %s; fixed host tunnel is active.\n' "$HOSTNAME"
