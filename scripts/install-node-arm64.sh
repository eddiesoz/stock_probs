#!/usr/bin/env bash
# Install a pinned official Node archive locally after checking an embedded release checksum.
set -euo pipefail

NODE_VERSION="22.19.0"
ARCH="$(uname -m)"
case "$ARCH" in
  aarch64|arm64)
    NODE_ARCH="arm64"
    NODE_SHA256="0b2d9f564b6594222a62c82e1df2efe119dd4a4aff29644f4dd325bf360b6bcc"
    ;;
  x86_64|amd64)
    NODE_ARCH="x64"
    NODE_SHA256="c0649af18e6a24f6fe5535a3e86b341dd49a8e71117c8b68bde973ef834f16f2"
    ;;
  *) printf 'Unsupported Node architecture: %s\n' "$ARCH" >&2; exit 2 ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="$ROOT/.tools/node"
if [[ -x "$INSTALL_DIR/bin/node" ]]; then
  if [[ "$("$INSTALL_DIR/bin/node" --version)" == "v${NODE_VERSION}" ]]; then
    "$INSTALL_DIR/bin/node" --version
    exit 0
  fi
  printf 'Existing local Node is not v%s; remove .tools/node before setup.\n' "$NODE_VERSION" >&2
  exit 2
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
ARCHIVE="node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz"
BASE_URL="https://nodejs.org/dist/v${NODE_VERSION}"
curl --fail --location --retry 3 --connect-timeout 10 --max-time 120 \
  --output "$TMP_DIR/$ARCHIVE" "$BASE_URL/$ARCHIVE"
printf '%s  %s\n' "$NODE_SHA256" "$TMP_DIR/$ARCHIVE" | sha256sum --check --strict -
mkdir -p "$ROOT/.tools"
tar -xJf "$TMP_DIR/$ARCHIVE" -C "$TMP_DIR"
mv "$TMP_DIR/node-v${NODE_VERSION}-linux-${NODE_ARCH}" "$INSTALL_DIR"
"$INSTALL_DIR/bin/node" --version
