#!/usr/bin/env bash
# Publish only a clean, reviewed main revision. The default release transport uploads a locally
# built OCI archive to an immutable GitHub Release; the Linode helper verifies its hash and image
# ID before loading it. GHCR remains available as an explicit compatibility transport.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
IMAGE_REPOSITORY="ghcr.io/jtmb/signal-ledger"
RELEASE_REPOSITORY="eddiesoz/stock_probs"
RELEASE_TAG_PREFIX="signal-ledger-"
RELEASE_ARCHIVE_PREFIX="signal-ledger-image-"
RELEASE_ARCHIVE_SUFFIX=".tar.gz"
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

IMAGE_TAG="$IMAGE_REPOSITORY:sha-$REVISION"
docker build --memory 1280m --memory-swap 2048m \
  --build-arg "REVISION=$REVISION" --tag "$IMAGE_TAG" .
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

if [[ "$PUBLISH_MODE" == "release" ]]; then
  command -v gh >/dev/null || {
    printf 'The GitHub CLI is required for release publication.\n' >&2
    exit 4
  }
  RELEASE_TAG="${RELEASE_TAG_PREFIX}${REVISION}"
  ARCHIVE_NAME="${RELEASE_ARCHIVE_PREFIX}${REVISION}${RELEASE_ARCHIVE_SUFFIX}"
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
ARCHIVE_PATH="$TEMP_ROOT/image.tar.gz"
if [[ "$PUBLISH_MODE" == "release" ]]; then
  ARCHIVE_PATH="$TEMP_ROOT/$ARCHIVE_NAME"
fi
  docker save "$IMAGE_TAG" | gzip -n -9 > "$ARCHIVE_PATH"
  ARCHIVE_SIZE="$(stat -c '%s' "$ARCHIVE_PATH")"
  if [[ ! "$ARCHIVE_SIZE" =~ ^[0-9]+$ ]] || (( ARCHIVE_SIZE == 0 || ARCHIVE_SIZE > MAX_ARCHIVE_BYTES )); then
    printf 'The image archive exceeded the bounded release size.\n' >&2
    exit 4
  fi
  # A production image is assembled from allowlisted source trees. Refuse obvious credential
  # material in metadata, layer paths, or layer bytes before publishing the immutable asset.
  IMAGE_METADATA="$(docker image inspect --format '{{json .Config.Env}} {{json .Config.Labels}}' "$IMAGE_TAG")"
  if grep -aE -- '-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|AWS_SECRET_ACCESS_KEY=|SIGNAL_LEDGER_.*SECRET=' <<< "$IMAGE_METADATA" >/dev/null; then
    printf 'The image metadata contains credential-like material.\n' >&2
    exit 4
  fi
  # Public CA bundles (for example /usr/lib/ssl/cert.pem) are required at runtime.  Match
  # private-key and credential filenames instead of treating every certificate extension as a
  # secret; the byte scan below still rejects embedded private-key markers and known tokens.
  SECRET_PATH_PATTERN='(^|/)(\.env($|\.)|.*(id_(rsa|dsa|ecdsa|ed25519)|private[-_.]?key|secret[-_.]?key|client[-_.]?key|server[-_.]?key|token[-_.]?file)([^/]*)$|.*\.(p12|pfx|key)$)'
  # Require key payload bytes after a PEM marker. Public crypto libraries may contain marker
  # constants in source code; a marker followed by base64 key material remains a secret.
  SECRET_BYTES_PATTERN='-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\t\n\r ]*[A-Za-z0-9+/=]{32,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|AWS_SECRET_ACCESS_KEY=|SIGNAL_LEDGER_.*SECRET='
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
    path_pattern = re.compile(path_expression)
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
  gh release create "$RELEASE_TAG" "$ARCHIVE_PATH" \
    --repo "$RELEASE_REPOSITORY" \
    --target "$REVISION" \
    --title "Signal Ledger ${REVISION}" \
    --notes "Locally built Linux amd64 production image for ${REVISION}." \
    --latest=false >/dev/null
  # Re-download the immutable asset and load it after publication. This proves the GitHub asset
  # bytes and image identity still match the locally reviewed archive before returning success.
  VERIFY_ROOT="$TEMP_ROOT/published"
  mkdir -m 700 "$VERIFY_ROOT"
  if ! gh release download "$RELEASE_TAG" \
    --repo "$RELEASE_REPOSITORY" \
    --pattern "$ARCHIVE_NAME" \
    --dir "$VERIFY_ROOT" \
    --clobber >/dev/null; then
    printf 'The published image asset could not be downloaded for verification.\n' >&2
    exit 4
  fi
  DOWNLOADED_ARCHIVE="$VERIFY_ROOT/$ARCHIVE_NAME"
  if [[ ! -f "$DOWNLOADED_ARCHIVE" || -L "$DOWNLOADED_ARCHIVE" ]]; then
    printf 'The published image asset was not a regular file.\n' >&2
    exit 4
  fi
  DOWNLOADED_SIZE="$(stat -c '%s' "$DOWNLOADED_ARCHIVE")"
  DOWNLOADED_SHA256="$(sha256sum "$DOWNLOADED_ARCHIVE" | awk '{print $1}')"
  if [[ ! "$DOWNLOADED_SIZE" =~ ^[0-9]+$ ]] || (( DOWNLOADED_SIZE == 0 || DOWNLOADED_SIZE > MAX_ARCHIVE_BYTES )) \
    || [[ "$DOWNLOADED_SHA256" != "$ARCHIVE_SHA256" ]]; then
    printf 'The published image asset failed size or SHA-256 verification.\n' >&2
    exit 4
  fi
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
  printf '{"transport":"github_release","repository":"%s","release_tag":"%s","archive_name":"%s","revision":"%s","archive_sha256":"%s","image_id":"%s","platform":"%s","archive_size":%s}\n' \
    "$RELEASE_REPOSITORY" "$RELEASE_TAG" "$ARCHIVE_NAME" "$REVISION" \
    "$ARCHIVE_SHA256" "$IMAGE_ID" "$IMAGE_PLATFORM" "$ARCHIVE_SIZE"
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
