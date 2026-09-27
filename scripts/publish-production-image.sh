#!/usr/bin/env bash
# Publish only a clean, reviewed main revision. The Linode helper pulls the returned digest;
# this script never builds on the VM or accepts an alternate registry or image name.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
IMAGE_REPOSITORY="ghcr.io/jtmb/signal-ledger"
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
