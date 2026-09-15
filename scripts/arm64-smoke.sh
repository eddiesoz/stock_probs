#!/usr/bin/env bash
# Prefer native ARM64; otherwise use bounded explicit QEMU and label every result as emulated.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST_ARCH="$(uname -m)"
REVISION="$(git -C "$ROOT" rev-parse --verify HEAD)"
TASK_ID="${STOCK_PROBS_TASK_ID:-M01}"
if [[ ! "$TASK_ID" =~ ^(M0[0-9]|EXP-M09|R-M0[0-9]-[1-9][0-9]*)$ ]]; then
  printf 'STOCK_PROBS_TASK_ID must be an M00-M09, EXP-M09, or R-M##-<n> identifier.\n' >&2
  exit 2
fi
TASK_SLUG="$(printf '%s' "$TASK_ID" | tr '[:upper:]' '[:lower:]')"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
RUN_DIR="${STOCK_PROBS_ARM64_EVIDENCE_DIR:-$ROOT/test-results/arm64/$TASK_ID-$STAMP}"
RECORD="$RUN_DIR/evidence.json"
COMPOSE_FILE="$ROOT/scripts/compose.arm64.yml"
PROJECT="stock-probs-$TASK_SLUG-arm64-$(id -u)"
LOCK_FILE="${XDG_RUNTIME_DIR:-/tmp}/stock-probs-$TASK_SLUG-arm64-$(id -u).lock"
mkdir -p "$RUN_DIR"
RESULT="Unavailable"
EXECUTION_LABEL=""
EXIT_CODE="0"
REASON=""
QEMU_VERSION="not used"
COMPOSE_ACTIVE="false"
BINFMT_OWNED="false"
IMAGES_OWNED="false"
CROSS_ARCH_RESULT="Not requested for this task."
TASK_BINFMT_MARKER="$ROOT/.tools/qemu-arm64/$TASK_SLUG-binfmt-owned"
ARM64_PORT="$(PYTHONPATH="$ROOT" python3 -c 'from scripts.package_smoke import _free_port; print(_free_port())')"
ARM64_IMAGE="stock-probs-$TASK_SLUG-arm64-runtime:$STAMP"
ARM64_FRONTEND_IMAGE="stock-probs-$TASK_SLUG-arm64-frontend:$STAMP"
ARM_CHECKS=()
BROWSER_RESULT="Unavailable"
export STOCK_PROBS_ARM64_PORT="$ARM64_PORT"
export STOCK_PROBS_ARM64_IMAGE="$ARM64_IMAGE"
export STOCK_PROBS_ARM64_FRONTEND_IMAGE="$ARM64_FRONTEND_IMAGE"

add_check() {
  ARM_CHECKS+=("$1")
}

wait_for_readiness() {
  PYTHONPATH="$ROOT" python3 -c \
    'import sys; from scripts.package_smoke import _wait_for_json; _wait_for_json(f"http://127.0.0.1:{sys.argv[1]}/api/v1/readiness", "ready", None, timeout=45)' \
    "$ARM64_PORT"
}

write_record() {
  ARM_RESULT="$RESULT" ARM_LABEL="$EXECUTION_LABEL" ARM_REASON="$REASON" \
    ARM_CROSS_ARCH_RESULT="$CROSS_ARCH_RESULT" \
    ARM_QEMU_VERSION="$QEMU_VERSION" ARM_CHECKS="$(IFS=,; printf '%s' "${ARM_CHECKS[*]}")" \
    ARM_BROWSER_RESULT="$BROWSER_RESULT" python3 - \
    "$RECORD" "$REVISION" "$HOST_ARCH" "$STARTED" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$EXIT_CODE" "$RUN_DIR" "$TASK_ID" <<'PY'
import json
import os
import sys
from pathlib import Path

record, revision, host_arch, started, finished, exit_code, run_dir, task = sys.argv[1:]
run_path = Path(run_dir)
payload = {
    "task": task,
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
    "physical_arm64_performance": "Unavailable; this functional smoke does not measure performance.",
    "arm64_browser": "Unavailable; Chromium ran on the host only and is not ARM browser evidence.",
    "verified_scopes": [item for item in os.environ["ARM_CHECKS"].split(",") if item],
    "host_browser": {
        "result": os.environ["ARM_BROWSER_RESULT"],
        "host_architecture": host_arch,
        "backend_execution": os.environ["ARM_LABEL"],
        "scope": "primary functional journeys against the ARM64 backend; no performance claim",
    },
    "cross_architecture_restore": os.environ["ARM_CROSS_ARCH_RESULT"],
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
    docker network ls --filter "name=^$PROJECT" --format '{{.Name}}'
  )
  for network in "${networks[@]}"; do
    project="$(docker network inspect --format \
      '{{ index .Labels "com.docker.compose.project" }}' "$network")"
    network_label="$(docker network inspect --format \
      '{{ index .Labels "com.docker.compose.network" }}' "$network")"
    attached="$(docker network inspect --format '{{ len .Containers }}' "$network")"
    if [[ "$project" == "$PROJECT" ]] \
      && [[ "$network" == "${project}_default" ]] && [[ "$network_label" == "default" ]] \
      && [[ "$attached" == "0" ]]; then
      printf 'Removing verified stale %s Compose project: %s\n' "$TASK_ID" "$project"
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
  if [[ "$IMAGES_OWNED" == "true" ]]; then
    docker image rm "$ARM64_IMAGE" "$ARM64_FRONTEND_IMAGE" >/dev/null
    local image_cleanup_code="$?"
    if (( image_cleanup_code != 0 && exit_code == 0 )); then
      exit_code="4"
      RESULT="Fail"
      REASON="Task-owned ARM64 build images could not be removed."
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
export STOCK_PROBS_CONTAINER_UID="$(id -u)"
export STOCK_PROBS_CONTAINER_GID="$(id -g)"
export STOCK_PROBS_QEMU_DIR="$ROOT/.tools/qemu-arm64"
export STOCK_PROBS_ARM64_ARTIFACT_DIR="$RUN_DIR"

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
  REASON="Another $TASK_ID ARM64 emulation owns the task Compose project."
  printf 'Unavailable: %s\n' "$REASON" >&2
  exit 3
fi

docker info
docker compose version
COMPOSE_ACTIVE="true"
# A fixed, user-scoped project lets this command remove only its own stale network/volume.
cleanup_stale_projects
compose_down
mkdir -p "$STOCK_PROBS_QEMU_DIR"

if [[ "$HOST_ARCH" == "aarch64" || "$HOST_ARCH" == "arm64" ]]; then
  EXECUTION_LABEL="native ARM64; physical performance was not measured by this functional smoke"
  export STOCK_PROBS_EXECUTION_LABEL="$EXECUTION_LABEL"
  printf '%s\n' "$EXECUTION_LABEL"
  RESULT="Fail"
  "$ROOT/scripts/bootstrap.sh"
  "$ROOT/.dev-venv/bin/python" "$ROOT/scripts/package_smoke.py" \
    --artifact-dir "$RUN_DIR/package" --expected-machine aarch64
  add_check "native-arm64-wheel-package-runtime"
else
  EXECUTION_LABEL="emulated ARM64 via task-owned pinned QEMU/OCI; not native or physical ARM64 performance evidence"
  export STOCK_PROBS_EXECUTION_LABEL="$EXECUTION_LABEL"
  printf '%s\n' "$EXECUTION_LABEL"
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
if [[ -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ]]; then
  REASON="An external aarch64 binfmt handler prevents a task-owned pinned QEMU lifecycle."
  printf 'Unavailable: %s\n' "$REASON" >&2
  exit 3
fi
: > "$TASK_BINFMT_MARKER"
BINFMT_OWNED="true"
timeout --signal=TERM --kill-after=5s 120s docker compose \
  --project-name "$PROJECT" --file "$COMPOSE_FILE" run --rm binfmt-register
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
add_check "emulated-arm64-wheel-package-runtime"

fi

IMAGES_OWNED="true"
timeout --signal=TERM --kill-after=30s 1800s docker compose \
  --project-name "$PROJECT" --file "$COMPOSE_FILE" build --pull \
  arm64-frontend-builder arm64-app
add_check "dockerfile-arm64-frontend-and-production-build"

timeout --signal=TERM --kill-after=5s 120s docker compose \
  --project-name "$PROJECT" --file "$COMPOSE_FILE" run --rm --no-deps \
  --entrypoint /bin/sh arm64-frontend-builder -ec \
  'test "$(node -p process.arch)" = arm64 && test "$(cat .next/BUILD_ID)" = stock-probs && test -f out/index.html && test -f out/api-docs.html && test -d out/_next/static && printf "node_arch=%s\nbuild_id=%s\nexports=index.html,api-docs.html,_next/static\n" "$(node -p process.arch)" "$(cat .next/BUILD_ID)"' \
  > "$RUN_DIR/frontend-builder.txt"
add_check "node-process-arch-build-id-export"

timeout --signal=TERM --kill-after=5s 120s docker compose \
  --project-name "$PROJECT" --file "$COMPOSE_FILE" up --detach --no-deps arm64-app
timeout --signal=TERM --kill-after=5s 120s docker compose \
  --project-name "$PROJECT" --file "$COMPOSE_FILE" exec --no-TTY arm64-app \
  python -c 'import platform; assert platform.machine() in {"aarch64", "arm64"}; print(platform.machine())' \
  > "$RUN_DIR/python-machine.txt"
add_check "production-python-machine-aarch64"

python3 - "$ARM64_IMAGE" "$(docker compose --project-name "$PROJECT" --file "$COMPOSE_FILE" ps -q arm64-app)" "$RUN_DIR/container.json" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

image_name, container_id, output = sys.argv[1:]
image = json.loads(subprocess.check_output(["docker", "image", "inspect", image_name]))[0]
container = json.loads(subprocess.check_output(["docker", "inspect", container_id]))[0]
host = container["HostConfig"]
assert (image["Os"], image["Architecture"], image["Config"]["User"]) == (
    "linux", "arm64", "10001:10001"
)
assert host["ReadonlyRootfs"] is True
assert host["CapDrop"] == ["ALL"]
assert "no-new-privileges:true" in host["SecurityOpt"]
assert host["PidsLimit"] == 128
assert host["Memory"] == 768 * 1024 * 1024
assert host["NanoCpus"] == 1_000_000_000
assert host["LogConfig"]["Config"] == {"max-file": "3", "max-size": "10m"}
binding = host["PortBindings"]["8000/tcp"][0]
assert binding["HostIp"] == "127.0.0.1"
assert any(mount["Destination"] == "/data" and mount["Type"] == "volume" for mount in container["Mounts"])
summary = {
    "image": {"id": image["Id"], "os": image["Os"], "architecture": image["Architecture"], "user": image["Config"]["User"]},
    "container": {
        "read_only": host["ReadonlyRootfs"], "cap_drop": host["CapDrop"],
        "security_opt": host["SecurityOpt"], "pids_limit": host["PidsLimit"],
        "memory_bytes": host["Memory"], "nano_cpus": host["NanoCpus"],
        "logging": host["LogConfig"], "published_host": binding["HostIp"],
        "persistent_data_volume": True,
    },
}
Path(output).write_text(json.dumps(summary, indent=2) + "\n")
PY
add_check "production-image-platform-user-containment"

wait_for_readiness

"$ROOT/scripts/install-node.sh"
PATH="$ROOT/.tools/node/bin:$PATH" "$ROOT/.tools/node/bin/npm" --prefix "$ROOT/tools/browser" ci
PATH="$ROOT/.tools/node/bin:$PATH" \
  STOCK_PROBS_BROWSER_EXTERNAL=1 STOCK_PROBS_BROWSER_PORT="$ARM64_PORT" \
  STOCK_PROBS_BROWSER_BACKEND_EXECUTION="$EXECUTION_LABEL" \
  STOCK_PROBS_BROWSER_ARTIFACT_DIR="$RUN_DIR/host-browser" \
  "$ROOT/tools/browser/node_modules/.bin/playwright" test dashboard.spec.js \
  --config "$ROOT/tools/browser/playwright.config.js"
BROWSER_RESULT="Pass"
add_check "host-chromium-primary-journeys-arm64-backend"

python3 - "$ROOT" "$ARM64_PORT" "$RUN_DIR/runtime-before-restart.json" before <<'PY'
import json
import sys
from pathlib import Path

root, port, artifact, phase = sys.argv[1:]
sys.path.insert(0, root)
from scripts.package_smoke import _get, _runtime_resources

base = f"http://127.0.0.1:{port}"

assert json.loads(_get(base + "/api/v1/health", timeout=10)[0])["status"] == "ok"
assert json.loads(_get(base + "/api/v1/readiness", timeout=10)[0])["status"] == "ready"
resources = set()
for path, marker in (("/", b"Signal Ledger"), ("/api/v1/docs", b"Signal Ledger API")):
    page, headers = _get(base + path)
    assert marker in page and "default-src 'self'" in headers["content-security-policy"]
    resources.update(_runtime_resources(page.decode()))
for resource in resources:
    body, headers = _get(base + resource)
    assert body and headers["x-content-type-options"] == "nosniff"
forecast = json.loads(_get(
    base + "/api/v1/forecasts", method="POST", status=201, timeout=10,
    payload={"symbol": "ACDC", "asset_type": "stock"},
)[0])
event_id = forecast["event"]["id"]
history = json.loads(_get(base + "/api/v1/history?page_size=100", timeout=10)[0])
assert any(item["id"] == event_id for item in history["items"])
news = json.loads(_get(base + "/api/v1/news?symbol=ACDC&limit=5", timeout=10)[0])
assert news["symbol"] == "ACDC" and news["items"]
assert _get(base + "/api/v1/history-export.json", timeout=10)[0]
assert _get(base + "/api/v1/history-export.csv", timeout=10)[0]
backup = json.loads(_get(
    base + "/api/v1/operations/backups", method="POST", status=201, timeout=10,
    payload={"name": "arm64-runtime.spbackup"},
)[0])
assert backup["created"] is True
missing = json.loads(_get(base + "/assets/not-present.css", status=404, timeout=10)[0])
wrong_method = json.loads(_get(base + "/assets/app.js", method="POST", status=405, timeout=10)[0])
assert missing["error"]["code"] == "not_found"
assert wrong_method["error"]["code"] == "method_not_allowed"
Path(artifact).write_text(json.dumps({
    "phase": phase, "event_id": event_id, "history_total": history["total"],
    "news_items": len(news["items"]), "assets": sorted(resources),
    "backup_created": True, "safe_errors": [404, 405],
}, indent=2) + "\n")
PY
add_check "fixture-api-html-assets-backup-safe-errors"

timeout --signal=TERM --kill-after=5s 120s docker compose \
  --project-name "$PROJECT" --file "$COMPOSE_FILE" restart arm64-app
wait_for_readiness
PYTHONPATH="$ROOT" python3 - "$ARM64_PORT" "$RUN_DIR/runtime-before-restart.json" "$RUN_DIR/runtime-after-restart.json" <<'PY'
import json
import sys
from pathlib import Path

from scripts.package_smoke import _get

port, before_path, after_path = sys.argv[1:]
base = f"http://127.0.0.1:{port}"

before = json.loads(Path(before_path).read_text())
saved = json.loads(_get(base + f"/api/v1/history/{before['event_id']}", timeout=10)[0])
verified = json.loads(_get(
    base + "/api/v1/operations/restores", method="POST", timeout=10,
    payload={"name": "arm64-runtime.spbackup", "promote": False},
)[0])
assert saved["event"]["id"] == before["event_id"]
assert verified["verified"] is True and verified["promoted"] is False
Path(after_path).write_text(json.dumps({
    "event_id": before["event_id"], "history_persisted": True,
    "backup_persisted_and_verified": True,
}, indent=2) + "\n")
PY
add_check "restart-history-backup-persistence"

docker compose --project-name "$PROJECT" --file "$COMPOSE_FILE" \
  logs --no-color --tail 200 arm64-app > "$RUN_DIR/arm64-app.log"
if (( $(stat -c %s "$RUN_DIR/arm64-app.log") > 262144 )); then
  REASON="Bounded ARM64 application log excerpt exceeded 256 KiB."
  exit 1
fi
add_check "bounded-log-excerpt"

if [[ "$HOST_ARCH" != "aarch64" && "$HOST_ARCH" != "arm64" ]] \
  && [[ "$TASK_ID" == "M05" || "$TASK_ID" =~ ^R-M05- ]]; then
  CROSS_DIR="$RUN_DIR/cross-architecture"
  HOST_PYTHON="$ROOT/.dev-venv/bin/python"
  export STOCK_PROBS_EXECUTION_LABEL="native x86_64 producer; functional evidence only"
  "$HOST_PYTHON" "$ROOT/scripts/cross_arch_backup_restore.py" create \
    "$CROSS_DIR/x86-source" x86-source "$CROSS_DIR/x86-create.json" \
    "native x86_64 backup for emulated ARM64 restore"

  timeout --signal=TERM --kill-after=15s 300s docker compose \
    --project-name "$PROJECT" --file "$COMPOSE_FILE" run --rm \
    --entrypoint /usr/local/bin/python \
    -e PYTHONPATH=/workspace/src:/opt/stock-probs-deps/python arm64-smoke \
    /workspace/scripts/cross_arch_backup_restore.py restore \
    /artifacts/cross-architecture/arm64-restored x86-source \
    /artifacts/cross-architecture/x86-to-emulated-arm64.json \
    "native x86_64 backup restored on emulated ARM64" \
    --source /artifacts/cross-architecture/x86-source

  timeout --signal=TERM --kill-after=15s 300s docker compose \
    --project-name "$PROJECT" --file "$COMPOSE_FILE" run --rm \
    --entrypoint /usr/local/bin/python \
    -e PYTHONPATH=/workspace/src:/opt/stock-probs-deps/python arm64-smoke \
    /workspace/scripts/cross_arch_backup_restore.py create \
    /artifacts/cross-architecture/arm64-source arm64-source \
    /artifacts/cross-architecture/arm64-create.json \
    "emulated ARM64 backup for native x86_64 restore"

  export STOCK_PROBS_EXECUTION_LABEL="native x86_64 restorer; functional evidence only"
  "$HOST_PYTHON" "$ROOT/scripts/cross_arch_backup_restore.py" restore \
    "$CROSS_DIR/x86-restored" arm64-source "$CROSS_DIR/emulated-arm64-to-x86.json" \
    "emulated ARM64 backup restored on native x86_64" \
    --source "$CROSS_DIR/arm64-source"
  CROSS_ARCH_RESULT="Pass: both restore directions; ARM64 execution was emulated functional evidence."
fi
RESULT="Pass"
