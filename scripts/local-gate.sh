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
if [[ ! "$TASK_ID" =~ ^(M0[0-9]|EXP-M0[0-9]|ASTRA-FINAL|EXP-FINAL|R-M0[0-9]-[1-9][0-9]*|R-ASTRA-[0-9]+)$ ]]; then
  printf 'TASK_ID must be an M00-M09, EXP-M00-EXP-M09, R-M##-<n>, R-ASTRA-<n>, ASTRA-FINAL, or EXP-FINAL identifier.\n' >&2
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
DOC_GATE_TIMEOUT_SECONDS="${DOC_GATE_TIMEOUT_SECONDS:-30}"
COMPLETED_CHECKS=()
EXPECTED_CHECKS=()

set_expected_profile_checks() {
  EXPECTED_CHECKS=()
  if [[ -d "$ROOT/docs" ]]; then
    EXPECTED_CHECKS+=("documentation-completeness")
  else
    EXPECTED_CHECKS+=("documentation-completeness-skipped-no-docs")
  fi
  if [[ -f "$ROOT/frontend/package-lock.json" ]]; then
    EXPECTED_CHECKS+=("frontend-npm-ci-typecheck-build-test-stage")
  fi
  case "$PROFILE" in
    check)
      EXPECTED_CHECKS+=("python-checks")
      ;;
    m01)
      EXPECTED_CHECKS+=("package" "python-checks")
      ;;
    m02)
      EXPECTED_CHECKS+=("package" "python-checks" "browser" "playwright-mcp")
      ;;
    m03)
      EXPECTED_CHECKS+=(
        "package" "python-checks" "browser" "playwright-mcp" "arm64-functional-package-runtime"
      )
      ;;
    m04)
      EXPECTED_CHECKS+=(
        "native-package" "python-checks" "responsive-browser-visual-accessibility"
        "playwright-mcp" "arm64-native-or-explicitly-emulated-package-runtime"
      )
      ;;
    m06)
      EXPECTED_CHECKS+=(
        "native-package" "python-checks" "responsive-browser-visual-accessibility"
        "playwright-mcp" "arm64-native-or-explicitly-emulated-package-runtime"
        "mandatory-native-performance"
      )
      ;;
    m09)
      EXPECTED_CHECKS+=(
        "native-package" "python-checks" "responsive-browser-visual-accessibility-theme-news"
        "playwright-mcp" "arm64-native-or-explicitly-emulated-package-runtime"
        "mandatory-native-m09-performance"
      )
      ;;
    release)
      EXPECTED_CHECKS+=(
        "package" "python-checks" "browser" "playwright-mcp"
        "release-migration-backup" "mandatory-native-performance"
      )
      ;;
  esac
}

profile_completion_status() {
  if (( ${#COMPLETED_CHECKS[@]} != ${#EXPECTED_CHECKS[@]} )); then
    printf 'Local gate cannot pass: profile %s completed %d/%d required checks.\n' \
      "$PROFILE" "${#COMPLETED_CHECKS[@]}" "${#EXPECTED_CHECKS[@]}" >&2
    return 1
  fi
  local index
  for index in "${!EXPECTED_CHECKS[@]}"; do
    if [[ "${COMPLETED_CHECKS[$index]}" != "${EXPECTED_CHECKS[$index]}" ]]; then
      printf 'Local gate cannot pass: profile %s check %d was %s; expected %s.\n' \
        "$PROFILE" "$((index + 1))" "${COMPLETED_CHECKS[$index]}" "${EXPECTED_CHECKS[$index]}" >&2
      return 1
    fi
  done
  return 0
}

write_record() {
  local result="$1"
  local exit_code="$2"
  python3 - "$RECORD" "$result" "$exit_code" "$TASK_ID" "$REVISION" "$DIRTY" \
    "$NATIVE_ARCH" "$STARTED_UTC" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$RUN_DIR" \
    "$PROFILE" "$(IFS=,; printf '%s' "${COMPLETED_CHECKS[*]}")" \
    "$(IFS=,; printf '%s' "${EXPECTED_CHECKS[*]}")" "$COMPLETION_STATUS" <<'PY'
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
    expected_checks,
    completion_status,
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
    "expected_checks": [item for item in expected_checks.split(",") if item],
    "completion_contract_satisfied": completion_status == "true",
    "result": result,
    "exit_code": int(exit_code),
    "artifacts": ["evidence.json", *artifacts],
}
Path(record).write_text(json.dumps(payload, indent=2) + "\n")
Path(record).chmod(0o600)
PY
}

on_exit() {
  local exit_code="$?"
  local completion_ok
  local result
  trap - EXIT
  trap '' INT TERM HUP
  set +e
  if profile_completion_status; then
    COMPLETION_STATUS="true"
    completion_ok=0
  else
    COMPLETION_STATUS="false"
    completion_ok=1
  fi
  if (( exit_code == 0 )); then
    if (( completion_ok == 0 )); then
      result="Pass"
    else
      result="Fail"
      exit_code=1
    fi
  else
    result="Fail"
  fi
  if ! write_record "$result" "$exit_code"; then
    printf 'Local gate failed to write terminal evidence; forcing a nonzero exit.\n' >&2
    exit 1
  fi
  printf 'Local gate evidence: %s\n' "$RECORD"
  exit "$exit_code"
}
set_expected_profile_checks
trap on_exit EXIT

on_signal() {
  local signal_name="$1"
  local signal_status="$2"
  trap - INT TERM HUP
  printf 'Local gate interrupted by SIG%s; recording failure.\n' "$signal_name" >&2
  exit "$signal_status"
}
trap 'on_signal INT 130' INT
trap 'on_signal TERM 143' TERM
trap 'on_signal HUP 129' HUP

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

run_documentation_completeness() {
  if [[ ! -d "$ROOT/docs" ]]; then
    printf 'Documentation completeness: skipped (docs directory is absent).\n'
    COMPLETED_CHECKS+=("documentation-completeness-skipped-no-docs")
    return 0
  fi
  if [[ ! -f "$ROOT/documentation-map.json" || ! -f "$ROOT/scripts/check-doc-coverage.py" ]]; then
    printf 'Documentation completeness: checker or map is missing.\n' >&2
    return 1
  fi
  if ! [[ "$DOC_GATE_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] || (( DOC_GATE_TIMEOUT_SECONDS > 300 )); then
    printf 'DOC_GATE_TIMEOUT_SECONDS must be an integer from 1 to 300.\n' >&2
    return 2
  fi
  command -v timeout >/dev/null 2>&1 || {
    printf 'Documentation completeness: timeout is unavailable.\n' >&2
    return 1
  }
  timeout --foreground --kill-after=5s "${DOC_GATE_TIMEOUT_SECONDS}s" \
    "$PYTHON" "$ROOT/scripts/check-doc-coverage.py" \
    --root "$ROOT" --map "$ROOT/documentation-map.json"
  COMPLETED_CHECKS+=("documentation-completeness")
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
run_documentation_completeness
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
