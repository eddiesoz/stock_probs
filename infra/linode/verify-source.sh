#!/usr/bin/env bash
set -euo pipefail

# Terraform's external data source invokes this fixed, local gate during plan and apply. It
# accepts the reviewed SHA and, for the apply-time check, one RFC3339 nonce; repository, command,
# path, and URL inputs are intentionally not configurable by Terraform variables or the MCP client.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXPECTED_REPOSITORY="https://github.com/eddiesoz/stock_probs.git"

# Do not let caller-controlled Git environment settings redirect repository, configuration,
# transport, or helper resolution. The gate intentionally uses only the checkout and public URL
# above.
export PATH=/usr/bin:/bin
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES
unset GIT_COMMON_DIR GIT_CONFIG GIT_CONFIG_COUNT GIT_CONFIG_PARAMETERS GIT_CONFIG_KEY_0 GIT_CONFIG_VALUE_0
unset GIT_SSH GIT_SSH_COMMAND GIT_PROXY_COMMAND GIT_ASKPASS SSH_ASKPASS GIT_SSL_NO_VERIFY
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_NOSYSTEM=1

fail() {
  printf 'Terraform source gate: %s\n' "$1" >&2
  exit 1
}

query_json="$(cat)" || fail "could not read the query"
reviewed_revision="$(
  python3 -c '
import datetime
import json
import re
import sys

try:
    payload = json.load(sys.stdin)
except (json.JSONDecodeError, TypeError):
    raise SystemExit("invalid JSON query")

allowed_keys = (
    {"reviewed_revision"},
    {"reviewed_revision", "apply_nonce"},
)
if not isinstance(payload, dict) or set(payload) not in allowed_keys:
    raise SystemExit("query must contain reviewed_revision and optional apply_nonce")

revision = payload["reviewed_revision"]
if not isinstance(revision, str) or len(revision) != 40:
    raise SystemExit("reviewed_revision must be a 40-character lowercase SHA")
if any(character not in "0123456789abcdef" for character in revision):
    raise SystemExit("reviewed_revision must be a 40-character lowercase SHA")

if "apply_nonce" in payload:
    nonce = payload["apply_nonce"]
    if not isinstance(nonce, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})",
        nonce,
    ):
        raise SystemExit("apply_nonce must be an RFC3339 timestamp")
    try:
        parsed_nonce = datetime.datetime.fromisoformat(nonce.replace("Z", "+00:00"))
    except ValueError:
        raise SystemExit("apply_nonce must be an RFC3339 timestamp")
    if parsed_nonce.tzinfo is None:
        raise SystemExit("apply_nonce must include a timezone")
print(revision)
' <<<"$query_json"
)" || fail "the query must contain a valid reviewed_revision and optional RFC3339 apply_nonce"

head_revision="$(git -C "$ROOT" rev-parse --verify HEAD 2>/dev/null)" \
  || fail "could not resolve HEAD"
[[ "$head_revision" =~ ^[0-9a-f]{40}$ ]] \
  || fail "HEAD is not a 40-character lowercase commit SHA"

worktree_status="$(git -C "$ROOT" status --porcelain --untracked-files=normal 2>/dev/null)" \
  || fail "could not inspect the worktree"
[[ -z "$worktree_status" ]] \
  || fail "the source tree must be clean"

origin_url="$(git -C "$ROOT" remote get-url origin 2>/dev/null)" \
  || fail "origin remote is missing"
[[ "$origin_url" == "$EXPECTED_REPOSITORY" ]] \
  || fail "origin must be the exact Signal Ledger repository"

remote_main="$(
  cd /
  GIT_TERMINAL_PROMPT=0 git ls-remote --exit-code --refs "$EXPECTED_REPOSITORY" refs/heads/main 2>/dev/null \
    | awk 'NR == 1 { print $1 }'
)" || fail "could not resolve the public origin/main revision"
[[ "$remote_main" =~ ^[0-9a-f]{40}$ ]] \
  || fail "origin/main is not a 40-character lowercase commit SHA"
[[ "$head_revision" == "$remote_main" ]] \
  || fail "HEAD must exactly match origin/main"
[[ "$reviewed_revision" == "$head_revision" ]] \
  || fail "reviewed_revision must exactly match HEAD"

setup_path="$ROOT/scripts/setup-production-host.sh"
compose_path="$ROOT/compose.production.yaml"
helper_path="$ROOT/scripts/production-deploy-helper.py"
for source_path in "$setup_path" "$compose_path" "$helper_path"; do
  [[ -f "$source_path" && ! -L "$source_path" ]] \
    || fail "reviewed source files must be regular files"
done

setup_sha256="$(sha256sum "$setup_path" | awk '{ print $1 }')"
compose_sha256="$(sha256sum "$compose_path" | awk '{ print $1 }')"
helper_sha256="$(sha256sum "$helper_path" | awk '{ print $1 }')"
for source_sha256 in "$setup_sha256" "$compose_sha256" "$helper_sha256"; do
  [[ "$source_sha256" =~ ^[0-9a-f]{64}$ ]] \
    || fail "could not compute a source SHA-256"
done

python3 - "$reviewed_revision" "$remote_main" "$setup_sha256" "$compose_sha256" "$helper_sha256" <<'PY'
import json
import sys

print(
    json.dumps(
        {
            "reviewed_revision": sys.argv[1],
            "remote_main": sys.argv[2],
            "source_setup_sha256": sys.argv[3],
            "source_compose_sha256": sys.argv[4],
            "source_helper_sha256": sys.argv[5],
        },
        sort_keys=True,
    )
)
PY
