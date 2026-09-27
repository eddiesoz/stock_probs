#!/usr/bin/env bash
set -euo pipefail

# The endpoint and account are fixed so this helper cannot be redirected to an
# arbitrary Cloudflare API URL. The response and request config are temporary,
# mode 0600 files and are removed before the helper exits.
readonly CLOUDFLARE_ACCOUNT_ID="f4c09c14a6618297f411e9ee75305013"
readonly CLOUDFLARE_API_BASE="https://api.cloudflare.com/client/v4"

usage() {
  printf 'Usage: %s TUNNEL_ID OUTPUT_FILE\n' "$0" >&2
}

fail() {
  printf 'fetch-tunnel-token: %s\n' "$1" >&2
  exit 1
}

if [[ $# -ne 2 ]]; then
  usage
  exit 2
fi

tunnel_id=$1
output_file=$2

[[ "$tunnel_id" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$ ]] || fail "TUNNEL_ID must be a UUID"
[[ -n "$output_file" && "$output_file" != *$'\n'* && "$output_file" != *$'\r'* ]] || fail "OUTPUT_FILE must be a non-empty path"
[[ -n "${CLOUDFLARE_API_TOKEN:-}" ]] || fail "CLOUDFLARE_API_TOKEN is not set"
[[ "$CLOUDFLARE_API_TOKEN" != *$'\n'* && "$CLOUDFLARE_API_TOKEN" != *$'\r'* && "$CLOUDFLARE_API_TOKEN" != *'"'* && "$CLOUDFLARE_API_TOKEN" != *'\\'* ]] || fail "CLOUDFLARE_API_TOKEN contains unsupported control or quote characters"
command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v jq >/dev/null 2>&1 || fail "jq is required"

output_dir=$(dirname -- "$output_file")
[[ -d "$output_dir" ]] || fail "output directory does not exist"
if [[ -e "$output_file" || -L "$output_file" ]]; then
  [[ -f "$output_file" && ! -L "$output_file" ]] || fail "OUTPUT_FILE must be a regular file, not a symlink"
fi

umask 077
response_file=$(mktemp "${TMPDIR:-/tmp}/signal-ledger-cloudflare-response.XXXXXX")
request_config=$(mktemp "${TMPDIR:-/tmp}/signal-ledger-cloudflare-request.XXXXXX")
staged_file=$(mktemp "$output_dir/.signal-ledger-tunnel-token.XXXXXX")
trap 'rm -f -- "$response_file" "$request_config" "$staged_file"' EXIT
chmod 0600 "$response_file" "$request_config" "$staged_file"

printf 'silent\nshow-error\nfail\nproto = "=https"\nheader = "Authorization: Bearer %s"\nheader = "Accept: application/json"\n' \
  "$CLOUDFLARE_API_TOKEN" >"$request_config"

curl --config "$request_config" \
  --output "$response_file" \
  "$CLOUDFLARE_API_BASE/accounts/$CLOUDFLARE_ACCOUNT_ID/cfd_tunnel/$tunnel_id/token" \
  >/dev/null 2>/dev/null || fail "Cloudflare API request failed"

jq -er 'if .success == true and (.result | type) == "string" and (.result | length) > 0 then .result else error("unexpected Cloudflare response") end' \
  "$response_file" >"$staged_file" || fail "Cloudflare API returned no tunnel token"

chmod 0600 "$staged_file"
mv -f -- "$staged_file" "$output_file"
