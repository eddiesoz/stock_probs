#!/usr/bin/env bash
# Bootstrap the supported CPython without relying on system ensurepip or a native compiler.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_VERSION="3.11.15"
VENV="$ROOT/.dev-venv"

if ! command -v uv; then
  printf 'Unavailable: uv is required on PATH; no network installer is executed automatically.\n' >&2
  exit 3
fi

if [[ -e "$VENV" ]]; then
  if [[ ! -x "$VENV/bin/python" ]]; then
    printf 'Existing .dev-venv is incomplete; move it aside before bootstrap.\n' >&2
    exit 2
  fi
  OBSERVED="$($VENV/bin/python -c 'import platform; print(platform.python_version())')"
  if [[ "$OBSERVED" != "$PYTHON_VERSION" ]]; then
    printf 'Existing .dev-venv uses Python %s, expected exactly %s; move it aside first.\n' \
      "$OBSERVED" "$PYTHON_VERSION" >&2
    exit 2
  fi
else
  uv python install "$PYTHON_VERSION"
  uv venv --python "$PYTHON_VERSION" "$VENV"
fi

# uv installs wheels directly, so setup works even when the host Python has no ensurepip/compiler.
uv pip install --python "$VENV/bin/python" --requirement "$ROOT/requirements.lock"
uv pip install --python "$VENV/bin/python" --no-build-isolation --no-deps --editable "$ROOT"
"$VENV/bin/python" -c \
  'import platform; assert platform.python_version() == "3.11.15"; import stock_probs; print(stock_probs.__file__)'
