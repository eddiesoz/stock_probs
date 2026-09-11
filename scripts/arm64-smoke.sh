#!/usr/bin/env bash
# Prefer native ARM64; otherwise use bounded explicit QEMU and label every result as emulated.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST_ARCH="$(uname -m)"
REVISION="$(git -C "$ROOT" rev-parse --verify HEAD)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
RUN_DIR="$ROOT/test-results/arm64/M01-$STAMP"
RECORD="$RUN_DIR/evidence.json"
COMPOSE_FILE="$ROOT/scripts/compose.arm64.yml"
PROJECT="stock-probs-m01-arm64-$(id -u)"
LOCK_FILE="${XDG_RUNTIME_DIR:-/tmp}/stock-probs-m01-arm64-$(id -u).lock"
mkdir -p "$RUN_DIR"
RESULT="Unavailable"
EXECUTION_LABEL=""
EXIT_CODE="0"
REASON=""
QEMU_VERSION="not used"
COMPOSE_ACTIVE="false"
BINFMT_OWNED="false"
TASK_BINFMT_MARKER="$ROOT/.tools/qemu-arm64/task-binfmt-owned"

write_record() {
  ARM_RESULT="$RESULT" ARM_LABEL="$EXECUTION_LABEL" ARM_REASON="$REASON" \
    ARM_QEMU_VERSION="$QEMU_VERSION" python3 - \
    "$RECORD" "$REVISION" "$HOST_ARCH" "$STARTED" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$EXIT_CODE" "$RUN_DIR" <<'PY'
import json
import os
import sys
from pathlib import Path

record, revision, host_arch, started, finished, exit_code, run_dir = sys.argv[1:]
run_path = Path(run_dir)
payload = {
    "task": "M01",
    "revision": revision,
    "host_architecture": host_arch,
    "target_architecture": "aarch64",
    "execution_label": os.environ["ARM_LABEL"],
    "emulator": os.environ["ARM_QEMU_VERSION"],
    "result": os.environ["ARM_RESULT"],
    "reason": os.environ["ARM_REASON"],
    "exit_code": int(exit_code),
    "started_utc": started,
    "finished_utc": finished,
    "physical_arm64_performance": "Unavailable unless host_architecture is native ARM64",
    "artifacts": ["evidence.json", *sorted(
        str(path.relative_to(run_path)) for path in run_path.rglob("*") if path.is_file()
    )],
}
Path(record).write_text(json.dumps(payload, indent=2) + "\n")
PY
}

compose_down() {
  docker compose --project-name "$PROJECT" --file "$COMPOSE_FILE" \
    down --volumes --remove-orphans
}

cleanup_stale_projects() {
  local network project network_label attached
  local -a networks=()
  mapfile -t networks < <(
    docker network ls --filter 'name=^stock-probs-m01-arm64-' --format '{{.Name}}'
  )
  for network in "${networks[@]}"; do
    project="$(docker network inspect --format \
      '{{ index .Labels "com.docker.compose.project" }}' "$network")"
    network_label="$(docker network inspect --format \
      '{{ index .Labels "com.docker.compose.network" }}' "$network")"
    attached="$(docker network inspect --format '{{ len .Containers }}' "$network")"
    if [[ "$project" =~ ^stock-probs-m01-arm64-[a-zA-Z0-9_-]+$ ]] \
      && [[ "$network" == "${project}_default" ]] && [[ "$network_label" == "default" ]] \
      && [[ "$attached" == "0" ]]; then
      printf 'Removing verified stale M01 Compose project: %s\n' "$project"
      docker compose --project-name "$project" --file "$COMPOSE_FILE" \
        down --volumes --remove-orphans
    elif [[ "$project" != "$PROJECT" ]]; then
      printf 'Unavailable: refusing to remove unverified or active network %s.\n' "$network" >&2
      return 3
    fi
  done
}

on_exit() {
  local exit_code="$?"
  trap - EXIT
  set +e
  if [[ "$COMPOSE_ACTIVE" == "true" ]]; then
    local binfmt_cleanup_code="0"
    if [[ "$BINFMT_OWNED" == "true" ]]; then
      docker compose --project-name "$PROJECT" --file "$COMPOSE_FILE" \
        run --rm binfmt-unregister
      binfmt_cleanup_code="$?"
      if (( binfmt_cleanup_code == 0 )); then
        rm -f "$TASK_BINFMT_MARKER"
      fi
    fi
    compose_down
    local cleanup_code="$?"
    if (( (cleanup_code != 0 || binfmt_cleanup_code != 0) && exit_code == 0 )); then
      exit_code="4"
      RESULT="Fail"
      REASON="Task-owned binfmt or Compose resources could not be removed."
    fi
  fi
  if (( exit_code != 0 )) && [[ -z "$REASON" ]]; then
    REASON="A fail-closed ARM64 smoke command exited with status $exit_code."
  fi
  EXIT_CODE="$exit_code"
  write_record
  printf 'ARM64 smoke evidence: %s\n' "$RECORD"
  exit "$exit_code"
}
trap on_exit EXIT

export STOCK_PROBS_REVISION="$REVISION"
if [[ "$HOST_ARCH" == "aarch64" || "$HOST_ARCH" == "arm64" ]]; then
  EXECUTION_LABEL="native ARM64; physical performance was not measured by this functional smoke"
  export STOCK_PROBS_EXECUTION_LABEL="$EXECUTION_LABEL"
  RESULT="Fail"
  "$ROOT/scripts/bootstrap.sh"
  "$ROOT/.dev-venv/bin/python" "$ROOT/scripts/package_smoke.py" \
    --artifact-dir "$RUN_DIR/package" --expected-machine aarch64
  RESULT="Pass"
  exit 0
fi

EXECUTION_LABEL="emulated ARM64 via explicit user-local QEMU/OCI; not native or physical ARM64 performance evidence"
export STOCK_PROBS_EXECUTION_LABEL="$EXECUTION_LABEL"
export STOCK_PROBS_ARM64_ARTIFACT_DIR="$RUN_DIR"
export STOCK_PROBS_CONTAINER_UID="$(id -u)"
export STOCK_PROBS_CONTAINER_GID="$(id -g)"
export STOCK_PROBS_QEMU_DIR="$ROOT/.tools/qemu-arm64"

if ! command -v docker; then
  REASON="Docker with Compose is required for emulated ARM64 verification."
  printf 'Unavailable: %s\n' "$REASON" >&2
  exit 3
fi
if ! command -v flock; then
  REASON="flock is required to serialize cleanup of the fixed task-owned Compose project."
  printf 'Unavailable: %s\n' "$REASON" >&2
  exit 3
fi
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  REASON="Another M01 ARM64 emulation owns the task Compose project."
  printf 'Unavailable: %s\n' "$REASON" >&2
  exit 3
fi

docker info
docker compose version
printf '%s\n' "$EXECUTION_LABEL"
mkdir -p "$STOCK_PROBS_QEMU_DIR"
COMPOSE_ACTIVE="true"
# A fixed, user-scoped project lets this command remove only its own stale network/volume.
cleanup_stale_projects
compose_down
timeout --signal=TERM --kill-after=5s 120s docker compose \
  --project-name "$PROJECT" --file "$COMPOSE_FILE" run --rm qemu-acquire
QEMU_VERSION="$($STOCK_PROBS_QEMU_DIR/qemu-aarch64-static --version)"

if [[ -e /proc/sys/fs/binfmt_misc/qemu-aarch64 && -e "$TASK_BINFMT_MARKER" ]]; then
  # An interrupted prior run left an explicitly marked handler; remove only that one before reuse.
  BINFMT_OWNED="true"
  docker compose --project-name "$PROJECT" --file "$COMPOSE_FILE" \
    run --rm binfmt-unregister
  rm -f "$TASK_BINFMT_MARKER"
  BINFMT_OWNED="false"
fi
if [[ ! -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ]]; then
  : > "$TASK_BINFMT_MARKER"
  BINFMT_OWNED="true"
  timeout --signal=TERM --kill-after=5s 120s docker compose \
    --project-name "$PROJECT" --file "$COMPOSE_FILE" run --rm binfmt-register
fi
timeout --signal=TERM --kill-after=5s 120s docker compose \
  --project-name "$PROJECT" --file "$COMPOSE_FILE" run --rm arm64-deps-init

if ! timeout --signal=TERM --kill-after=5s 120s docker compose \
  --project-name "$PROJECT" --file "$COMPOSE_FILE" run --rm \
  --entrypoint /usr/local/bin/python arm64-smoke \
  -c \
  'import platform; assert platform.machine() in {"aarch64", "arm64"}; print(platform.machine())'; then
  REASON="The pinned explicit QEMU helper could not execute the pinned ARM64 Python image."
  printf 'Unavailable: %s\n' "$REASON" >&2
  exit 3
fi

RESULT="Fail"
timeout --signal=TERM --kill-after=15s 900s docker compose \
  --project-name "$PROJECT" --file "$COMPOSE_FILE" run --rm arm64-smoke
RESULT="Pass"
