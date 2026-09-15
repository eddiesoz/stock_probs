#!/usr/bin/env bash
# Run the fail-closed local gate directly and retain revision/architecture/result evidence.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TASK_ID="${TASK_ID:-M01}"
PROFILE="${1:-m01}"
if (( $# > 1 )) || [[ ! "$PROFILE" =~ ^(m01|m02|m03|m04|m06|m09|check|release)$ ]]; then
  printf 'Usage: %s [m01|m02|m03|m04|m06|m09|check|release]\n' "${0##*/}" >&2
  exit 2
fi
if [[ ! "$TASK_ID" =~ ^(M0[0-9]|R-M0[0-9]-[1-9][0-9]*)$ ]]; then
  printf 'TASK_ID must be an M00-M09 or R-M##-<n> identifier.\n' >&2
  exit 2
fi

STARTED_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
RUN_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NATIVE_ARCH="$(uname -m)"
REVISION="$(git -C "$ROOT" rev-parse --verify HEAD)"
if [[ -n "$(git -C "$ROOT" status --porcelain=v1 --untracked-files=normal)" ]]; then
  DIRTY="true"
else
  DIRTY="false"
fi
RUN_DIR="$ROOT/test-results/local-gates/${TASK_ID}-${RUN_STAMP}"
RECORD="$RUN_DIR/evidence.json"
mkdir -p "$RUN_DIR/python"
export STOCK_PROBS_PACKAGE_ARTIFACT_DIR="$RUN_DIR/package"
export STOCK_PROBS_REVISION="$REVISION"
export STOCK_PROBS_DATA_DIR="$RUN_DIR/runtime"
export STOCK_PROBS_BROWSER_ARTIFACT_DIR="$RUN_DIR/browser"
export STOCK_PROBS_BROWSER_RUNTIME="$RUN_DIR/browser-runtime"
export STOCK_PROBS_TASK_ID="$TASK_ID"
PYTHON="$ROOT/.dev-venv/bin/python"
NODE_BIN="$ROOT/.tools/node/bin"
COMPLETED_CHECKS=()

write_record() {
  local result="$1"
  local exit_code="$2"
  python3 - "$RECORD" "$result" "$exit_code" "$TASK_ID" "$REVISION" "$DIRTY" \
    "$NATIVE_ARCH" "$STARTED_UTC" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$RUN_DIR" \
    "$PROFILE" "$(IFS=,; printf '%s' "${COMPLETED_CHECKS[*]}")" <<'PY'
import json
import sys
from pathlib import Path

(
    record,
    result,
    exit_code,
    task,
    revision,
    dirty,
    architecture,
    started,
    finished,
    run_dir,
    profile,
    completed_checks,
) = sys.argv[1:]
run_path = Path(run_dir)
artifacts = sorted(
    str(path.relative_to(run_path)) for path in run_path.rglob("*") if path.is_file()
)
payload = {
    "task": task,
    "revision": revision,
    "working_tree_dirty": dirty == "true",
    "native_architecture": architecture,
    "execution_label": f"native {architecture}",
    "started_utc": started,
    "finished_utc": finished,
    "command": ["./scripts/local-gate.sh", profile],
    "profile": profile,
    "completed_checks": [item for item in completed_checks.split(",") if item],
    "result": result,
    "exit_code": int(exit_code),
    "artifacts": ["evidence.json", *artifacts],
}
Path(record).write_text(json.dumps(payload, indent=2) + "\n")
PY
}

on_exit() {
  local exit_code="$?"
  trap - EXIT
  set +e
  if (( exit_code == 0 )); then
    write_record "Pass" "$exit_code"
  else
    write_record "Fail" "$exit_code"
  fi
  printf 'Local gate evidence: %s\n' "$RECORD"
  exit "$exit_code"
}
trap on_exit EXIT

run_check() {
  "$PYTHON" -m ruff check src tests scripts
  "$PYTHON" -m mypy src/stock_probs/backup.py src/stock_probs/cli.py
  "$PYTHON" -m compileall -q src tests scripts
  bash -n scripts/*.sh
  "$PYTHON" scripts/comment_audit.py
  "$PYTHON" -m pytest -m "not live" --cov=stock_probs --cov-report=term-missing \
    --cov-fail-under=85 --junitxml="$RUN_DIR/python/junit.xml"
  "$PYTHON" -m ruff check --select S --ignore S101 src tests scripts
  "$PYTHON" -m pytest tests/test_repository_backup.py tests/test_backup_cli.py -q
}

run_package() {
  "$PYTHON" scripts/package_smoke.py
}

run_browser() {
  "$ROOT/scripts/install-node.sh"
  PATH="$NODE_BIN:$PATH" "$NODE_BIN/npm" --prefix "$ROOT/tools/browser" ci
  local port
  port="$($PYTHON -c \
    'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
  PATH="$NODE_BIN:$PATH" STOCK_PROBS_BROWSER_PORT="$port" \
    "$NODE_BIN/npm" --prefix "$ROOT/tools/browser" test
}

run_mcp() {
  PATH="$NODE_BIN:$PATH" "$NODE_BIN/node" "$ROOT/tools/browser/mcp-smoke.js"
}

run_ponytail_precondition() {
  # A gate verifies the pinned review interface once without self-performing the independent review.
  command -v opencode >/dev/null
  command -v timeout >/dev/null
  [[ -x "$ROOT/scripts/ponytail-review.sh" ]]
  [[ -f "$ROOT/tools/ponytail/PROVENANCE.md" ]]
  [[ "$(opencode --version)" == "1.18.30" ]]
  PATH="$NODE_BIN:$PATH" "$NODE_BIN/node" "$ROOT/tools/ponytail/smoke.mjs"
}

run_arm64() {
  # Keep the architecture receipt inside this gate's evidence tree while the ARM helper
  # independently labels native versus emulated execution and any hardware limitation.
  STOCK_PROBS_ARM64_EVIDENCE_DIR="$RUN_DIR/arm64" "$ROOT/scripts/arm64-smoke.sh"
}

run_performance() {
  # Performance is intentionally native-host only. The harness writes an explicit Unavailable
  # ARM64 row on this x86 gate and never delegates resource measurements to QEMU/OCI.
  STOCK_PROBS_PERFORMANCE_ARTIFACT_DIR="$RUN_DIR/performance" \
    "$PYTHON" "$ROOT/scripts/performance_harness.py" --profile "$PROFILE"
}

require_performance_acceptance() {
  local reviewer="${PERFORMANCE_REVIEWER:-}"
  local normalized
  normalized="$(printf '%s' "$reviewer" | tr '[:lower:] -' '[:upper:]__')"
  if [[ ${#reviewer} -lt 3 || "$normalized" =~ (PENDING|PLACEHOLDER|TODO|TBD|UNKNOWN|UNAVAILABLE|N/A) ]]; then
    printf 'PERFORMANCE_REVIEWER must name a non-placeholder independent reviewer for %s.\n' "$PROFILE" >&2
    return 2
  fi
  if [[ "$PROFILE" == "release" && "$DIRTY" == "true" ]]; then
    printf 'Release performance requires a clean committed working tree.\n' >&2
    return 2
  fi
}

printf 'task=%s revision=%s dirty=%s native_arch=%s profile=%s\n' \
  "$TASK_ID" "$REVISION" "$DIRTY" "$NATIVE_ARCH" "$PROFILE"
printf 'Local scripts are authoritative only with independent review; no external pipeline is used.\n'
"$ROOT/scripts/bootstrap.sh"
cd "$ROOT"
if [[ -f "$ROOT/frontend/package-lock.json" ]]; then
  "$ROOT/scripts/build-frontend.sh"
  COMPLETED_CHECKS+=("frontend-npm-ci-typecheck-build-test-stage")
fi

case "$PROFILE" in
  check)
    run_check
    COMPLETED_CHECKS+=("python-checks")
    ;;
  m01)
    run_package
    COMPLETED_CHECKS+=("package")
    run_check
    COMPLETED_CHECKS+=("python-checks")
    ;;
  m02)
    run_package
    COMPLETED_CHECKS+=("package")
    run_check
    COMPLETED_CHECKS+=("python-checks")
    run_browser
    COMPLETED_CHECKS+=("browser")
    run_mcp
    COMPLETED_CHECKS+=("playwright-mcp")
    ;;
  m03)
    run_package
    COMPLETED_CHECKS+=("package")
    run_check
    COMPLETED_CHECKS+=("python-checks")
    run_browser
    COMPLETED_CHECKS+=("browser")
    run_mcp
    COMPLETED_CHECKS+=("playwright-mcp")
    run_arm64
    COMPLETED_CHECKS+=("arm64-functional-package-runtime")
    ;;
  m04)
    run_package
    COMPLETED_CHECKS+=("native-package")
    run_check
    COMPLETED_CHECKS+=("python-checks")
    run_browser
    COMPLETED_CHECKS+=("responsive-browser-visual-accessibility")
    run_mcp
    COMPLETED_CHECKS+=("playwright-mcp")
    run_arm64
    COMPLETED_CHECKS+=("arm64-native-or-explicitly-emulated-package-runtime")
    ;;
  m06)
    require_performance_acceptance
    run_ponytail_precondition
    COMPLETED_CHECKS+=("ponytail-review-interface-available-not-invoked")
    run_package
    COMPLETED_CHECKS+=("native-package")
    run_check
    COMPLETED_CHECKS+=("python-checks")
    run_browser
    COMPLETED_CHECKS+=("responsive-browser-visual-accessibility")
    run_mcp
    COMPLETED_CHECKS+=("playwright-mcp")
    run_arm64
    COMPLETED_CHECKS+=("arm64-native-or-explicitly-emulated-package-runtime")
    run_performance
    COMPLETED_CHECKS+=("mandatory-native-performance")
    ;;
  m09)
    require_performance_acceptance
    run_ponytail_precondition
    COMPLETED_CHECKS+=("ponytail-review-interface-available-not-invoked")
    run_package
    COMPLETED_CHECKS+=("native-package")
    run_check
    COMPLETED_CHECKS+=("python-checks")
    run_browser
    COMPLETED_CHECKS+=("responsive-browser-visual-accessibility-theme-news")
    run_mcp
    COMPLETED_CHECKS+=("playwright-mcp")
    run_arm64
    COMPLETED_CHECKS+=("arm64-native-or-explicitly-emulated-package-runtime")
    run_performance
    COMPLETED_CHECKS+=("mandatory-native-m09-performance")
    ;;
  release)
    require_performance_acceptance
    run_ponytail_precondition
    COMPLETED_CHECKS+=("ponytail-review-interface-available-not-invoked")
    run_package
    COMPLETED_CHECKS+=("package")
    run_check
    COMPLETED_CHECKS+=("python-checks")
    run_browser
    COMPLETED_CHECKS+=("browser")
    run_mcp
    COMPLETED_CHECKS+=("playwright-mcp")
    "$PYTHON" -m stock_probs.cli migrate
    "$PYTHON" -m pytest tests/test_backup_cli.py -q
    COMPLETED_CHECKS+=("release-migration-backup")
    run_performance
    COMPLETED_CHECKS+=("mandatory-native-performance")
    ;;
esac
