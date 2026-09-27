#!/usr/bin/env bash
# Verify or install this repository's versioned Git hooks.
#
# Verification is the default.  --apply changes only this clone's local
# core.hooksPath setting and the mode of the checked-in hook; it never writes a
# global Git configuration or copies files into .git/hooks.
set -euo pipefail

APPLY=0
MODE_SET=0
HOOKS_PATH=".githooks"
HOOK="$HOOKS_PATH/pre-push"

usage() {
  printf 'Usage: %s [--verify-only|--apply]\n' "${0##*/}"
}

while (( $# > 0 )); do
  case "$1" in
    --apply)
      (( MODE_SET == 0 )) || { usage >&2; exit 2; }
      APPLY=1
      MODE_SET=1
      shift
      ;;
    --verify-only)
      (( MODE_SET == 0 )) || { usage >&2; exit 2; }
      MODE_SET=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)"; then
  printf 'ERROR: not inside a Git work tree\n' >&2
  exit 2
fi

ok() { printf 'OK: %s\n' "$*"; }
fail() { printf 'MISSING/FAILED: %s\n' "$*" >&2; }

status=0
if [[ ! -f "$REPO_ROOT/$HOOK" ]]; then
  fail "hook source missing: $REPO_ROOT/$HOOK"
  exit 1
fi

if (( APPLY == 1 )); then
  chmod 0755 "$REPO_ROOT/$HOOK"
  git -C "$REPO_ROOT" config core.hooksPath "$HOOKS_PATH"
  ok "core.hooksPath -> $HOOKS_PATH"
fi

configured="$(git -C "$REPO_ROOT" config --get core.hooksPath || true)"
if [[ "$configured" == "$HOOKS_PATH" ]]; then
  ok "core.hooksPath is $HOOKS_PATH"
else
  fail "core.hooksPath is '${configured:-unset}'; run $0 --apply"
  status=1
fi

if [[ -x "$REPO_ROOT/$HOOK" ]]; then
  ok "$HOOK is executable"
else
  fail "$HOOK is not executable; run $0 --apply"
  status=1
fi

if (( status == 0 )); then
  printf 'Repository-local documentation gate hook is active for this clone.\n'
else
  printf 'Repository-local documentation gate hook is not active; no files were installed.\n' >&2
fi
exit "$status"
