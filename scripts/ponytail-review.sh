#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'usage: %s <task-boundary> <new-report-path>\n' "${0##*/}" >&2
}

[[ $# -eq 2 ]] || { usage; exit 64; }
boundary=$1
[[ "$boundary" =~ ^(M0[0-9]|EXP-M0[0-9]|ASTRA-FINAL|EXP-FINAL|R-M0[0-9]-[0-9]+|R-ASTRA-[0-9]+)(-[A-Za-z0-9._-]+)?$ ]] || {
  printf 'invalid task boundary: %s\n' "$boundary" >&2
  exit 64
}

repo_root=$(git rev-parse --show-toplevel)
report=$(realpath -m -- "$2")
case "$report" in
  "$repo_root"/*) ;;
  *) printf 'report path must stay inside %s\n' "$repo_root" >&2; exit 64 ;;
esac
[[ ! -e "$report" && ! -L "$report" ]] || {
  printf 'refusing to replace existing report: %s\n' "$report" >&2
  exit 73
}
report_dir=$(dirname -- "$report")
[[ -d "$report_dir" && ! -L "$report_dir" ]] || {
  printf 'report parent must be an existing non-symlink directory: %s\n' "$report_dir" >&2
  exit 73
}

command -v opencode >/dev/null
command -v timeout >/dev/null
command -v install >/dev/null
command -v jq >/dev/null
command -v stat >/dev/null

# OpenCode 1.18.31 documents auth.json as its credential store. Its documented
# environment interface has no whole-store auth override, so bridge only that
# file rather than exposing credential contents in an environment variable.
parent_data_home=${XDG_DATA_HOME:-${HOME:-}/.local/share}
case "$parent_data_home" in
  /*) ;;
  *) printf 'OpenCode data directory must be absolute\n' >&2; exit 77 ;;
esac
parent_auth="$parent_data_home/opencode/auth.json"
[[ -e "$parent_auth" ]] || {
  printf 'OpenCode auth store is missing; refusing isolated review\n' >&2
  exit 77
}
[[ ! -L "$parent_auth" && -f "$parent_auth" ]] || {
  printf 'OpenCode auth store must be a non-symlink regular file\n' >&2
  exit 77
}
auth_metadata=$(stat --format='%u:%a' -- "$parent_auth") || {
  printf 'could not verify OpenCode auth store metadata\n' >&2
  exit 77
}
auth_owner=${auth_metadata%%:*}
auth_mode=${auth_metadata#*:}
[[ "$auth_owner" == "$(id -u)" && ( "$auth_mode" == 600 || "$auth_mode" == 400 ) ]] || {
  printf 'OpenCode auth store must be owned by the current user with mode 600 or 400\n' >&2
  exit 77
}

umask 077
temp_base=$(realpath -e -- "${TMPDIR:-/tmp}")
[[ -d "$temp_base" ]] || { printf 'temporary directory is unavailable\n' >&2; exit 73; }
sandbox=$(mktemp -d "$temp_base/stock-probs-ponytail.XXXXXX")
sanitized=''
cleanup() {
  rm -rf -- "$sandbox"
  [[ -z "$sanitized" ]] || rm -f -- "$sanitized"
}
trap cleanup EXIT
mkdir -m 700 "$sandbox/home" "$sandbox/config" "$sandbox/data" "$sandbox/cache" \
  "$sandbox/state" "$sandbox/runtime" "$sandbox/tmp"
mkdir -m 700 "$sandbox/data/opencode"
isolated_auth="$sandbox/data/opencode/auth.json"
install -m 600 -- "$parent_auth" "$isolated_auth"
[[ ! -L "$isolated_auth" && -f "$isolated_auth" \
  && "$(stat --format='%u:%a' -- "$isolated_auth")" == "$(id -u):600" ]] || {
  printf 'could not create safe isolated OpenCode auth store\n' >&2
  exit 77
}
raw="$sandbox/raw"
provider_error="$sandbox/provider-error"
structured_text="$sandbox/structured-text"
# wc reports only line counts; allowing that read-only query avoids a denied
# inventory command without exposing source text or permitting mutation.
readonly_review_config='{"agent":{"LUNA MAX QA":{"model":"openai/gpt-5.6-luna","variant":"max","permission":{"*":"deny","read":{"*":"allow","*.env*":"deny","**/*credential*":"deny","**/*secret*":"deny"},"edit":"deny","write":"deny","glob":"allow","grep":"allow","bash":{"*":"deny","git diff*":"allow","git rev-parse*":"allow","git status*":"allow","wc -l":"allow","wc -l *":"allow"},"task":"deny","skill":{"*":"deny","ponytail-review":"allow"}}}}}'
review_prompt='Return only canonical plain text: path:Lstart[-end]: tag: claim (tag is delete, stdlib, native, yagni, or shrink), or exactly Lean already. Ship. when there are no findings. Do not use Markdown or backticks anywhere, including around identifiers.'
parent_rg="${XDG_CACHE_HOME:-$HOME/.cache}/opencode/bin/rg"
if [[ -f "$parent_rg" && -x "$parent_rg" && ! -L "$parent_rg" ]]; then
  mkdir -m 700 -p "$sandbox/cache/opencode/bin"
  install -m 700 "$parent_rg" "$sandbox/cache/opencode/bin/rg"
fi

run_isolated() (
  export HOME="$sandbox/home"
  export XDG_CONFIG_HOME="$sandbox/config"
  export XDG_DATA_HOME="$sandbox/data"
  export XDG_CACHE_HOME="$sandbox/cache"
  export XDG_STATE_HOME="$sandbox/state"
  export XDG_RUNTIME_DIR="$sandbox/runtime"
  export TMPDIR="$sandbox/tmp"
  export OPENCODE_CONFIG_CONTENT="$readonly_review_config"
  unset OPENCODE_AUTH_CONTENT OPENCODE_CONFIG OPENCODE_CONFIG_DIR OPENCODE_DB \
    OPENCODE_TEST_HOME OPENCODE_ZED_DB
  cd -- "$repo_root"
  "$@"
)

version_raw="$sandbox/version"
version_status=0
(
  ulimit -f 2048
  run_isolated opencode --version
) >"$version_raw" 2>&1 || version_status=$?
installed_version=$(<"$version_raw")
[[ $version_status -eq 0 && "$installed_version" == "1.18.31" ]] || {
  printf 'opencode 1.18.31 is required\n' >&2
  exit 69
}

# A fresh process is intentional: project plugins and profiles are loaded only at startup.
# Both streams stay in the private sandbox. Only stdout is the JSON event stream;
# stderr may contain provider diagnostics and must never enter the report parser.
provider_status=0
(
  # OpenCode's isolated state can exceed 2 MiB; 64 MiB still bounds both state and captures.
  ulimit -f 65536
  run_isolated timeout --signal=TERM --kill-after=10s 300s \
    opencode run --dir "$repo_root" --agent 'LUNA MAX QA' \
    --command ponytail-review --format json "$review_prompt"
) >"$raw" 2>"$provider_error" || provider_status=$?

# JSON mode keeps progress, source excerpts, and tool output private while giving
# the sanitizer an explicit event boundary instead of terminal-rendered text.
parse_status=0
jq -r '
  if type != "object" then error("invalid event")
  elif .type == "text" then
    if ((.part | type) == "object" and (.part.text | type) == "string")
    then .part.text
    else error("invalid text event")
    end
  else empty
  end
' "$raw" >"$structured_text" 2>"$sandbox/json-error" || parse_status=$?
provider_event=0
unknown_event=0
if [[ $parse_status -eq 0 ]]; then
  jq -s -e 'any(.[]; .type == "error")' "$raw" >/dev/null 2>&1 && provider_event=1
  jq -s -e 'any(.[]; .type == "error" and .error.name? == "UnknownError")' \
    "$raw" >/dev/null 2>&1 && unknown_event=1
fi

if [[ $provider_status -ne 0 || $provider_event -eq 1 ]]; then
  provider_ref="provider-exit-$provider_status"
  failure_status=$provider_status
  [[ $failure_status -ne 0 ]] || failure_status=69
  if [[ $provider_status -eq 124 ]]; then
    provider_ref='provider-timeout-300s'
  elif [[ $unknown_event -eq 1 ]]; then
    provider_ref="provider-unknown-error-exit-$provider_status"
  elif [[ $provider_event -eq 1 ]]; then
    provider_ref="provider-error-event-exit-$provider_status"
  fi
  printf 'ponytail review provider failed (ref=%s); no report retained\n' \
    "$provider_ref" >&2
  exit "$failure_status"
fi

[[ $parse_status -eq 0 ]] || {
  printf 'review returned invalid structured output; no report retained\n' >&2
  exit 65
}

outcomes=0
sanitized=$(mktemp "$report_dir/.ponytail-review.XXXXXX")
backtick=$'\x60'
em_dash=$'\u2014'
sensitive_line() {
  local value=$1
  local lower=${value,,}
  local private_key='-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----'
  local aws='(^|[^A-Z0-9])(AKIA|ASIA)[A-Z0-9]{16}([^A-Z0-9]|$)'
  local github='(^|[^A-Za-z0-9_])(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{20,})'
  local bearer='(^|[^a-z0-9_])bearer[[:space:]]+[A-Za-z0-9._~+/=-]{20,}'
  local credential_url='https?://[^[:space:]/:]+:[^[:space:]/@]+@'
  local webhook='https?://[^[:space:]]*(hooks\.slack\.com/services|/api/webhooks?/|/webhooks?/)[^[:space:]]*'
  local assignment="(^|[^a-z0-9_])[a-z_][a-z0-9_]*(secret|token|password|credential|api_?key|access_?key|private_?key|_key)[a-z0-9_]*[\"']?[[:space:]]*[:=][[:space:]]*[\"']?[A-Za-z0-9._~+/=-]{20,}"

  [[ "$value" =~ $private_key || "$value" =~ $aws || "$value" =~ $github \
    || "$lower" =~ $bearer || "$lower" =~ $credential_url \
    || "$lower" =~ $webhook || "$lower" =~ $assignment ]]
}

raw_diff_body() {
  local body=$1
  local diff='^(diff[[:space:]]+--git|index[[:space:]]+[[:xdigit:]]+\.\.[[:xdigit:]]+|@@([[:space:]]|$)|---[[:space:]]|\+\+\+[[:space:]]|[+-])'
  [[ "$body" =~ $diff ]]
}

finding_pattern='^(L[0-9]+(-[0-9]+)?|([A-Za-z0-9_.-][A-Za-z0-9_./-]*):L?[0-9]+(-[0-9]+)?):[[:space:]](delete|stdlib|native|yagni|shrink):[[:space:]](.+)$'

{
  printf 'scope: overengineering only\ncommand: /ponytail-review\nboundary: %s\n' "$boundary"
  while IFS= read -r line; do
    line=${line//$'\r'/}
    candidate=${line//"$backtick"/}
    candidate=${candidate//" ${em_dash} "/': '}
    body=''
    outcome=0
    if [[ "$candidate" == 'Lean already. Ship.' ]]; then
      outcome=1
    elif [[ "$candidate" =~ ^net:[[:space:]]-[0-9]+[[:space:]]lines[[:space:]]possible\.$ ]] \
      || [[ "$candidate" =~ ^Net[[:space:]]removable:[[:space:]]~[0-9]+[[:space:]]lines\.$ ]]; then
      :
    elif [[ "$candidate" =~ $finding_pattern ]]; then
      body=${BASH_REMATCH[6]}
      outcome=1
    else
      continue
    fi
    if ! sensitive_line "$candidate" \
      && { [[ -z "$body" ]] || ! raw_diff_body "$body"; }; then
      printf '%s\n' "${candidate:0:4096}"
      outcomes=$((outcomes + outcome))
    fi
  done <"$structured_text"
} >"$sanitized"

[[ $outcomes -gt 0 ]] || {
  printf 'review returned no allowlisted Ponytail result lines; no report retained\n' >&2
  exit 65
}
[[ $(wc -c <"$sanitized") -le 65536 ]] || {
  printf 'sanitized report exceeded 65536 bytes\n' >&2
  exit 65
}
mv -- "$sanitized" "$report"
printf 'retained sanitized report: %s\n' "$report"
