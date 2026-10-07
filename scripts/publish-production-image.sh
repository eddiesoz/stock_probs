#!/usr/bin/env bash
# Publish only a clean, reviewed main revision. The default release transport uploads a locally
# built OCI archive to an immutable GitHub Release; the Linode helper verifies its hash and image
# ID before loading it. GHCR remains available as an explicit compatibility transport.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
IMAGE_REPOSITORY="ghcr.io/jtmb/signal-ledger"
RELEASE_REPOSITORY="eddiesoz/stock_probs"
MAX_ARCHIVE_BYTES=$((512 * 1024 * 1024))
PUBLISH_MODE="${SIGNAL_LEDGER_IMAGE_PUBLISH_MODE:-release}"
REVISION="$(git rev-parse --verify HEAD)"
if [[ ! "$REVISION" =~ ^[0-9a-f]{40}$ ]]; then
  printf 'HEAD is not an exact commit SHA.\n' >&2
  exit 2
fi
if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  printf 'The source tree must be clean before publishing.\n' >&2
  exit 2
fi
REMOTE_MAIN="$(git ls-remote origin refs/heads/main | awk '{print $1}')"
if [[ "$REMOTE_MAIN" != "$REVISION" ]]; then
  printf 'origin/main must match the reviewed local revision.\n' >&2
  exit 2
fi

if [[ "$PUBLISH_MODE" == "release" ]]; then
  command -v gh >/dev/null || {
    printf 'The GitHub CLI is required for release publication.\n' >&2
    exit 4
  }
  RELEASE_TAG="signal-ledger-${REVISION}"
  ARCHIVE_NAME="signal-ledger-image-${REVISION}.tar.gz"
  RECOVERY_ARCHIVE_NAME="signal-ledger-recovery-${REVISION}.tar.gz"
  PAIR_MANIFEST_NAME="signal-ledger-pair-${REVISION}.json"
  if gh release view "$RELEASE_TAG" --repo "$RELEASE_REPOSITORY" >/dev/null 2>&1; then
    printf 'The revision release already exists; immutable release publication refuses reuse.\n' >&2
    exit 4
  fi
elif [[ "$PUBLISH_MODE" != "ghcr" ]]; then
  printf 'SIGNAL_LEDGER_IMAGE_PUBLISH_MODE must be release or ghcr.\n' >&2
  exit 2
fi

TEMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEMP_ROOT"' EXIT
IMAGE_TAG="$IMAGE_REPOSITORY:sha-$REVISION"
if [[ "$PUBLISH_MODE" == "release" ]]; then
  CANDIDATE_CONTEXT="$TEMP_ROOT/candidate-context"
  SOURCE_CONTEXT_SHA256="$(python3 - "$CANDIDATE_CONTEXT" <<'PY'
import importlib.util
import sys
from pathlib import Path

module_path = Path("scripts/rehearse_schema13.py")
spec = importlib.util.spec_from_file_location("schema13_rehearsal", module_path)
if spec is None or spec.loader is None:
    raise SystemExit("the fixed source-context filter is unavailable")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
digest = module._candidate_context(Path.cwd(), Path(sys.argv[1]))
print(digest)
PY
)"
  if [[ ! "$SOURCE_CONTEXT_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'The filtered production source context was not verifiable.\n' >&2
    exit 3
  fi
  docker build --memory 1280m --memory-swap 2048m \
    --build-arg "REVISION=$REVISION" --tag "$IMAGE_TAG" "$CANDIDATE_CONTEXT"
else
  docker build --memory 1280m --memory-swap 2048m \
    --build-arg "REVISION=$REVISION" --tag "$IMAGE_TAG" .
fi
IMAGE_REVISION="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$IMAGE_TAG")"
if [[ "$IMAGE_REVISION" != "$REVISION" ]]; then
  printf 'The built image is missing the reviewed revision label.\n' >&2
  exit 3
fi

IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$IMAGE_TAG")"
IMAGE_PLATFORM="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$IMAGE_TAG")"
if [[ ! "$IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ || "$IMAGE_PLATFORM" != "linux/amd64" ]]; then
  printf 'The built image must be a Linux amd64 image with a complete image ID.\n' >&2
  exit 3
fi
if [[ "$PUBLISH_MODE" == "ghcr" ]]; then
  IMAGE_SCHEMA="$(docker run --rm --pull never --network none --read-only \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,size=16m \
    --cap-drop ALL --security-opt no-new-privileges --entrypoint python "$IMAGE_ID" \
    -c 'from stock_probs.repository import SCHEMA_VERSION; print(SCHEMA_VERSION)')"
  if [[ "$IMAGE_SCHEMA" =~ ^[0-9]+$ ]] && (( IMAGE_SCHEMA >= 13 )); then
    printf 'Schema-13 releases require the reviewed candidate/recovery GitHub release pair.\n' >&2
    exit 4
  fi
fi

ARCHIVE_PATH="$TEMP_ROOT/image.tar.gz"
if [[ "$PUBLISH_MODE" == "release" ]]; then
  PAIR_ROOT="$TEMP_ROOT/release-pair"
  mkdir -m 700 "$PAIR_ROOT"
  REHEARSAL_RECEIPT="$TEMP_ROOT/schema13-rehearsal.json"
  python3 scripts/rehearse_schema13.py \
    --candidate-image-id "$IMAGE_ID" \
    --expected-candidate-context-sha256 "$SOURCE_CONTEXT_SHA256" \
    --candidate-revision "$REVISION" \
    --release-artifact-directory "$PAIR_ROOT" \
    --receipt "$REHEARSAL_RECEIPT" >/dev/null
  ARCHIVE_PATH="$PAIR_ROOT/$ARCHIVE_NAME"
else
  docker save "$IMAGE_TAG" | gzip -n -9 > "$ARCHIVE_PATH"
fi
ARCHIVE_SIZE="$(stat -c '%s' "$ARCHIVE_PATH")"
if [[ ! "$ARCHIVE_SIZE" =~ ^[0-9]+$ ]] || (( ARCHIVE_SIZE == 0 || ARCHIVE_SIZE > MAX_ARCHIVE_BYTES )); then
  printf 'The image archive exceeded the bounded release size.\n' >&2
  exit 4
fi
  # A production image is assembled from allowlisted source trees. Refuse obvious credential
  # material in metadata, layer paths, or layer bytes before publishing the immutable asset.
  IMAGE_METADATA="$(docker image inspect --format '{{json .Config.Env}} {{json .Config.Labels}}' "$IMAGE_TAG")"
  if grep -aEi -- '-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|AKIA[0-9A-Z]{16}|AWS_SECRET_ACCESS_KEY=|SIGNAL_LEDGER_.*SECRET=' <<< "$IMAGE_METADATA" >/dev/null; then
    printf 'The image metadata contains credential-like material.\n' >&2
    exit 4
  fi
  # Public CA bundles (for example /usr/lib/ssl/cert.pem) are required at runtime.  Match
  # private-key and credential filenames instead of treating every certificate extension as a
  # secret; the byte scan below still rejects embedded private-key markers and known tokens.
  SECRET_PATH_PATTERN='(^|/)(\.env($|\.)|\.aws($|/)|\.ssh($|/)|auth\.json$|credentials?(\.json)?$|.*(id_(rsa|dsa|ecdsa|ed25519)|private[-_.]?key|secret[-_.]?key|client[-_.]?key|server[-_.]?key|token[-_.]?file|access[-_.]?token)([^/]*)$|.*\.(p12|pfx|key)$)'
  # Require key payload bytes after a PEM marker. Public crypto libraries may contain marker
  # constants in source code; a marker followed by base64 key material remains a secret.
  SECRET_BYTES_PATTERN='-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\t\n\r ]*[A-Za-z0-9+/=]{32,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|AKIA[0-9A-Z]{16}|AWS_SECRET_ACCESS_KEY=|SIGNAL_LEDGER_.*SECRET='
  # Runtime state belongs on the persistent data volume. Reject database, backup, and SQLite
  # sidecar names in every layer so a local data tree cannot be published accidentally.
  DATA_PATH_PATTERN='(^|/)[^/]*\.(?:db|sqlite3?|spbackup)(?:-(?:wal|shm|journal))?(?:/|$)'
  mapfile -t LAYER_MEMBERS < <(tar -tzf "$ARCHIVE_PATH" | awk '$0 ~ /(^|\/)layer\.tar$/ { print }')
  if (( ${#LAYER_MEMBERS[@]} == 0 )); then
    # Modern Docker/containerd image stores emit an OCI archive whose manifest names compressed
    # blobs rather than legacy */layer.tar members. Parse the single-image manifest and allow
    # only the two Docker save layer-member forms; arbitrary archive paths never reach tar.
    MANIFEST_PATH="$TEMP_ROOT/manifest.json"
    LAYER_MEMBER_LIST="$TEMP_ROOT/layer-members.txt"
    if ! tar -xOzf "$ARCHIVE_PATH" manifest.json > "$MANIFEST_PATH"; then
      printf 'The image archive did not contain a readable image manifest.\n' >&2
      exit 4
    fi
    if ! python3 - "$MANIFEST_PATH" > "$LAYER_MEMBER_LIST" <<'PY'
import json
import re
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)
    if not isinstance(manifest, list) or len(manifest) != 1:
        raise ValueError("expected one saved image")
    if not isinstance(manifest[0], dict):
        raise ValueError("invalid saved image entry")
    layers = manifest[0].get("Layers")
    if not isinstance(layers, list) or not layers:
        raise ValueError("missing image layers")
    for member in layers:
        if not isinstance(member, str) or (
            re.fullmatch(r"(?:[^/]+/)*layer\.tar", member) is None
            and re.fullmatch(r"blobs/sha256/[0-9a-f]{64}", member) is None
        ):
            raise ValueError("invalid layer member")
        print(member)
except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
    raise SystemExit(1) from exc
PY
    then
      printf 'The image archive contained invalid image layers.\n' >&2
      exit 4
    fi
    mapfile -t LAYER_MEMBERS < "$LAYER_MEMBER_LIST"
  fi
  if (( ${#LAYER_MEMBERS[@]} == 0 )); then
    printf 'The image archive did not contain a Docker layer.\n' >&2
    exit 4
  fi
  LAYER_INDEX=0
  for LAYER_MEMBER in "${LAYER_MEMBERS[@]}"; do
    LAYER_BYTES="$TEMP_ROOT/layer-bytes-${LAYER_INDEX}.tar"
    if ! tar -xOzf "$ARCHIVE_PATH" "$LAYER_MEMBER" > "$LAYER_BYTES"; then
      printf 'The image archive contained an unreadable Docker layer.\n' >&2
      exit 4
    fi
    LAYER_SIZE="$(stat -c '%s' "$LAYER_BYTES")"
    if [[ ! "$LAYER_SIZE" =~ ^[0-9]+$ ]] || (( LAYER_SIZE > MAX_ARCHIVE_BYTES )); then
      printf 'The image archive contained an oversized Docker layer.\n' >&2
      exit 4
    fi
    # Scan the tar member itself and each uncompressed file stream. This catches private-key
    # markers inside OCI gzip-compressed layers, while bounding all reads to fixed-size chunks.
    if python3 - "$LAYER_BYTES" "$SECRET_PATH_PATTERN" "$SECRET_BYTES_PATTERN" "$DATA_PATH_PATTERN" <<'PY'
import re
import sys
import tarfile

layer_path, path_expression, bytes_expression, data_path_expression = sys.argv[1:]
try:
    path_pattern = re.compile(path_expression, re.IGNORECASE)
    bytes_pattern = re.compile(bytes_expression.encode())
    data_path_pattern = re.compile(data_path_expression, re.IGNORECASE)
    with tarfile.open(layer_path, mode="r:*") as layer:
        for member in layer:
            if data_path_pattern.search(member.name):
                raise SystemExit(13)
            if path_pattern.search(member.name):
                raise SystemExit(10)
            if not member.isreg():
                continue
            stream = layer.extractfile(member)
            if stream is None:
                continue
            previous = b""
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                candidate = previous + chunk
                if bytes_pattern.search(candidate):
                    raise SystemExit(11)
                previous = candidate[-256:]
except (OSError, re.error, tarfile.TarError) as exc:
    raise SystemExit(12) from exc
PY
    then
      :
    else
      SCAN_STATUS=$?
      case "$SCAN_STATUS" in
        13) printf 'The image archive contains a database or backup path.\n' >&2 ;;
        10) printf 'The image archive contains a credential-like path.\n' >&2 ;;
        11) printf 'The image archive contains credential-like bytes.\n' >&2 ;;
        *) printf 'The image archive contained an unreadable Docker layer.\n' >&2 ;;
      esac
      exit 4
    fi
    rm -f "$LAYER_BYTES"
    ((LAYER_INDEX += 1))
  done
  ARCHIVE_SHA256="$(sha256sum "$ARCHIVE_PATH" | awk '{print $1}')"
if [[ ! "$ARCHIVE_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
  printf 'The image archive hash was unavailable.\n' >&2
  exit 4
fi
if [[ "$PUBLISH_MODE" == "release" ]]; then
  PAIR_FIELDS="$(python3 - "$REHEARSAL_RECEIPT" "$PAIR_ROOT" "$REVISION" <<'PY'
import json
import re
import sys
from pathlib import Path

receipt_path, pair_root_raw, revision = sys.argv[1:]
try:
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    pair = receipt["release_pair"]
    root = Path(pair_root_raw)
    fields = [
        pair["candidate_archive_name"],
        pair["candidate_archive_sha256"],
        str(pair["candidate_archive_size"]),
        pair["recovery_archive_name"],
        pair["recovery_archive_sha256"],
        str(pair["recovery_archive_size"]),
        pair["manifest_name"],
        pair["manifest_sha256"],
        receipt["candidate_image"]["id"],
        receipt["candidate_image"]["source_context_sha256"],
    ]
    if receipt.get("status") != "pass" or not isinstance(pair, dict):
        raise ValueError("invalid rehearsal receipt")
    if fields[0] != f"signal-ledger-image-{revision}.tar.gz":
        raise ValueError("candidate asset name mismatch")
    if fields[3] != f"signal-ledger-recovery-{revision}.tar.gz":
        raise ValueError("recovery asset name mismatch")
    if fields[6] != f"signal-ledger-pair-{revision}.json":
        raise ValueError("pair asset name mismatch")
    if any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in (fields[1], fields[7])):
        raise ValueError("invalid asset digest")
    if fields[2] != str((root / fields[0]).stat().st_size):
        raise ValueError("candidate asset size mismatch")
    if fields[5] != str((root / fields[3]).stat().st_size):
        raise ValueError("recovery asset size mismatch")
    print("\t".join(fields))
except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
    raise SystemExit("schema-13 pair receipt is invalid") from exc
PY
)"
  IFS=$'\t' read -r PAIR_CANDIDATE_NAME PAIR_CANDIDATE_SHA PAIR_CANDIDATE_SIZE \
    RECOVERY_ARCHIVE_NAME RECOVERY_ARCHIVE_SHA RECOVERY_ARCHIVE_SIZE PAIR_MANIFEST_NAME \
    PAIR_MANIFEST_SHA PAIR_CANDIDATE_IMAGE_ID PAIR_SOURCE_CONTEXT_SHA <<< "$PAIR_FIELDS"
  if [[ "$PAIR_CANDIDATE_NAME" != "$ARCHIVE_NAME" \
    || "$PAIR_CANDIDATE_SHA" != "$ARCHIVE_SHA256" \
    || "$PAIR_CANDIDATE_SIZE" != "$ARCHIVE_SIZE" \
    || "$PAIR_CANDIDATE_IMAGE_ID" != "$IMAGE_ID" \
    || "$PAIR_SOURCE_CONTEXT_SHA" != "$SOURCE_CONTEXT_SHA256" ]]; then
    printf 'The rehearsed candidate pair does not bind the built candidate archive.\n' >&2
    exit 4
  fi
  RECOVERY_ARCHIVE_PATH="$PAIR_ROOT/$RECOVERY_ARCHIVE_NAME"
  PAIR_MANIFEST_PATH="$PAIR_ROOT/$PAIR_MANIFEST_NAME"
  PAIR_MANIFEST_SIZE="$(stat -c '%s' "$PAIR_MANIFEST_PATH")"
  PAIR_MANIFEST_SHA_LOCAL="$(sha256sum "$PAIR_MANIFEST_PATH" | awk '{print $1}')"
  if [[ ! "$PAIR_MANIFEST_SIZE" =~ ^[0-9]+$ ]] \
    || (( PAIR_MANIFEST_SIZE == 0 || PAIR_MANIFEST_SIZE > 65536 )) \
    || [[ "$PAIR_MANIFEST_SHA_LOCAL" != "$PAIR_MANIFEST_SHA" ]]; then
    printf 'The local recovery-pair manifest failed its receipt identity.\n' >&2
    exit 4
  fi
  python3 scripts/verify-release-archive.py "$RECOVERY_ARCHIVE_PATH" \
    > "$TEMP_ROOT/recovery-archive-scan.json"
  python3 - "$TEMP_ROOT/recovery-archive-scan.json" "$PAIR_MANIFEST_PATH" \
    "$RECOVERY_ARCHIVE_SHA" "$RECOVERY_ARCHIVE_SIZE" <<'PY'
import json
import sys
from pathlib import Path

scan_path, manifest_path, expected_digest, expected_size = sys.argv[1:]
try:
    scan = json.loads(Path(scan_path).read_text(encoding="utf-8"))
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    recovery = manifest["recovery"]
    if (
        scan.get("status") != "pass"
        or scan.get("archive_sha256") != expected_digest
        or scan.get("archive_size") != int(expected_size)
        or recovery.get("archive_sha256") != expected_digest
        or recovery.get("archive_size") != int(expected_size)
        or recovery.get("assistant_enabled") is not False
    ):
        raise ValueError("recovery archive verification mismatch")
except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
    raise SystemExit("recovery image archive failed verification") from exc
PY
  if ! docker load --input "$RECOVERY_ARCHIVE_PATH" >/dev/null; then
    printf 'The rehearsed recovery image archive could not be loaded.\n' >&2
    exit 4
  fi
  RECOVERY_IMAGE_ID="$(python3 - "$PAIR_MANIFEST_PATH" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(manifest["recovery"]["image_id"])
PY
)"
  RECOVERY_REVISION="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$RECOVERY_IMAGE_ID")"
  RECOVERY_PLATFORM="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$RECOVERY_IMAGE_ID")"
  RECOVERY_METADATA="$(docker image inspect --format '{{json .Config.Env}} {{json .Config.Labels}}' "$RECOVERY_IMAGE_ID")"
  if grep -aEi -- '-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|AKIA[0-9A-Z]{16}|AWS_SECRET_ACCESS_KEY=|SIGNAL_LEDGER_.*SECRET=' <<< "$RECOVERY_METADATA" >/dev/null; then
    printf 'The recovery image metadata contains credential-like material.\n' >&2
    exit 4
  fi
  RECOVERY_CONFIG="$(docker image inspect --format '{{json .Config.Entrypoint}}|{{json .Config.Cmd}}' "$RECOVERY_IMAGE_ID")"
  if [[ "$RECOVERY_REVISION" != "$REVISION" || "$RECOVERY_PLATFORM" != "linux/amd64" ]] \
    || ! python3 - "$RECOVERY_CONFIG" <<'PY'
import json
import sys

try:
    entrypoint_raw, command_raw = sys.argv[1].split("|", 1)
    entrypoint = json.loads(entrypoint_raw)
    command = json.loads(command_raw)
except (ValueError, json.JSONDecodeError):
    raise SystemExit(1)
if entrypoint != ["python", "-m", "stock_probs.recovery_supervisor"] or command != [
    "serve",
    "--host",
    "0.0.0.0",
    "--port",
    "8000",
    "--allow-non-loopback",
]:
    raise SystemExit(1)
PY
  then
    printf 'The recovery image identity or fixed app-only entrypoint failed verification.\n' >&2
    exit 4
  fi
  RECOVERY_SCHEMA="$(docker run --rm --pull never --network none --read-only \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,size=16m \
    --cap-drop ALL --security-opt no-new-privileges --entrypoint python "$RECOVERY_IMAGE_ID" \
    -c 'from stock_probs.repository import SCHEMA_VERSION; print(SCHEMA_VERSION)')"
  if [[ "$RECOVERY_SCHEMA" != "13" ]]; then
    printf 'The recovery image does not support the required schema.\n' >&2
    exit 4
  fi
  python3 scripts/verify-release-archive.py "$RECOVERY_ARCHIVE_PATH" \
    > "$TEMP_ROOT/recovery-archive-scan-final.json"
  RECOVERY_ARCHIVE_SHA_VERIFIED="$(sha256sum "$RECOVERY_ARCHIVE_PATH" | awk '{print $1}')"
  if [[ "$RECOVERY_ARCHIVE_SHA_VERIFIED" != "$RECOVERY_ARCHIVE_SHA" ]]; then
    printf 'The recovery archive failed its pair digest.\n' >&2
    exit 4
  fi
  gh release create "$RELEASE_TAG" "$ARCHIVE_PATH" "$RECOVERY_ARCHIVE_PATH" "$PAIR_MANIFEST_PATH" \
    --repo "$RELEASE_REPOSITORY" \
    --target "$REVISION" \
    --title "Signal Ledger ${REVISION}" \
    --notes "Reviewed Linux amd64 candidate and schema-13 recovery pair for ${REVISION}." \
    --latest=false >/dev/null
  # Re-download the immutable asset and load it after publication. This proves the GitHub asset
  # bytes and image identity still match the locally reviewed archive before returning success.
  VERIFY_ROOT="$TEMP_ROOT/published"
  mkdir -m 700 "$VERIFY_ROOT"
  if ! gh release download "$RELEASE_TAG" \
    --repo "$RELEASE_REPOSITORY" \
    --dir "$VERIFY_ROOT" \
    --clobber >/dev/null; then
    printf 'The published release pair could not be downloaded for verification.\n' >&2
    exit 4
  fi
  for asset in "$ARCHIVE_NAME $ARCHIVE_SHA256 $ARCHIVE_SIZE" \
    "$RECOVERY_ARCHIVE_NAME $RECOVERY_ARCHIVE_SHA $RECOVERY_ARCHIVE_SIZE" \
    "$PAIR_MANIFEST_NAME $PAIR_MANIFEST_SHA $PAIR_MANIFEST_SIZE"; do
    read -r asset_name expected_sha expected_size <<< "$asset"
    downloaded_asset="$VERIFY_ROOT/$asset_name"
    if [[ ! -f "$downloaded_asset" || -L "$downloaded_asset" ]]; then
      printf 'A published release-pair asset was not a regular file.\n' >&2
      exit 4
    fi
    actual_size="$(stat -c '%s' "$downloaded_asset")"
    actual_sha="$(sha256sum "$downloaded_asset" | awk '{print $1}')"
    if [[ "$actual_size" != "$expected_size" || "$actual_sha" != "$expected_sha" ]]; then
      printf 'A published release-pair asset failed size or SHA-256 verification.\n' >&2
      exit 4
    fi
  done
  DOWNLOADED_ARCHIVE="$VERIFY_ROOT/$ARCHIVE_NAME"
  if ! docker load --input "$DOWNLOADED_ARCHIVE" >/dev/null; then
    printf 'The published image asset could not be loaded for verification.\n' >&2
    exit 4
  fi
  DOWNLOADED_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$IMAGE_TAG")"
  DOWNLOADED_REVISION="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$IMAGE_TAG")"
  DOWNLOADED_PLATFORM="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$IMAGE_TAG")"
  if [[ "$DOWNLOADED_IMAGE_ID" != "$IMAGE_ID" || "$DOWNLOADED_REVISION" != "$REVISION" \
    || "$DOWNLOADED_PLATFORM" != "$IMAGE_PLATFORM" ]]; then
    printf 'The published image asset failed image identity verification.\n' >&2
    exit 4
  fi
  DOWNLOADED_RECOVERY="$VERIFY_ROOT/$RECOVERY_ARCHIVE_NAME"
  if ! docker load --input "$DOWNLOADED_RECOVERY" >/dev/null; then
    printf 'The published recovery archive could not be loaded for verification.\n' >&2
    exit 4
  fi
  DOWNLOADED_RECOVERY_ID="$(docker image inspect --format '{{.Id}}' "$RECOVERY_IMAGE_ID")"
  DOWNLOADED_RECOVERY_REVISION="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$RECOVERY_IMAGE_ID")"
  DOWNLOADED_RECOVERY_PLATFORM="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$RECOVERY_IMAGE_ID")"
  if [[ "$DOWNLOADED_RECOVERY_ID" != "$RECOVERY_IMAGE_ID" \
    || "$DOWNLOADED_RECOVERY_REVISION" != "$REVISION" \
    || "$DOWNLOADED_RECOVERY_PLATFORM" != "linux/amd64" ]]; then
    printf 'The published recovery archive failed image identity verification.\n' >&2
    exit 4
  fi
  printf '{"transport":"github_release","repository":"%s","release_tag":"%s","archive_name":"%s","revision":"%s","archive_sha256":"%s","image_id":"%s","platform":"%s","archive_size":%s,"pair_manifest_name":"%s","pair_manifest_sha256":"%s","recovery_archive_name":"%s","recovery_archive_sha256":"%s","recovery_image_id":"%s","recovery_platform":"%s","recovery_schema_version":13}\n' \
    "$RELEASE_REPOSITORY" "$RELEASE_TAG" "$ARCHIVE_NAME" "$REVISION" \
    "$ARCHIVE_SHA256" "$IMAGE_ID" "$IMAGE_PLATFORM" "$ARCHIVE_SIZE" \
    "$PAIR_MANIFEST_NAME" "$PAIR_MANIFEST_SHA" "$RECOVERY_ARCHIVE_NAME" \
    "$RECOVERY_ARCHIVE_SHA" "$RECOVERY_IMAGE_ID" "$DOWNLOADED_RECOVERY_PLATFORM"
  exit 0
fi

# Capture registry output to extract the immutable manifest digest without logging an auth
# token or trusting a mutable tag as the release identity.
if ! PUSH_OUTPUT="$(docker push "$IMAGE_TAG" 2>&1)"; then
  printf 'GHCR push failed; check Docker registry authentication and package permissions.\n' >&2
  exit 4
fi
IMAGE_DIGEST="$(awk '/digest: sha256:/ { for (i = 1; i <= NF; i++) if ($i == "digest:") print $(i+1) }' <<< "$PUSH_OUTPUT" | tail -n 1)"
if [[ ! "$IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  printf 'GHCR did not return a usable manifest digest.\n' >&2
  exit 4
fi
IMAGE_REF="$IMAGE_REPOSITORY@$IMAGE_DIGEST"
docker pull --quiet "$IMAGE_REF" >/dev/null
PULLED_REVISION="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$IMAGE_REF")"
if [[ "$PULLED_REVISION" != "$REVISION" ]]; then
  printf 'The registry digest does not carry the reviewed revision.\n' >&2
  exit 4
fi
printf '{"revision":"%s","image_digest":"%s","image_ref":"%s"}\n' \
  "$REVISION" "${IMAGE_DIGEST#sha256:}" "$IMAGE_REF"
