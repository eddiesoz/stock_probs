#!/usr/bin/env bash
# Build and stage the pinned frontend export through one fail-closed entry point.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NODE_BIN="$ROOT/.tools/node/bin"

"$ROOT/scripts/install-node.sh"
PATH="$NODE_BIN:$PATH" "$NODE_BIN/npm" --prefix "$ROOT/frontend" ci
PATH="$NODE_BIN:$PATH" "$NODE_BIN/npm" --prefix "$ROOT/frontend" run typecheck
PATH="$NODE_BIN:$PATH" "$NODE_BIN/npm" --prefix "$ROOT/frontend" test
PATH="$NODE_BIN:$PATH" "$NODE_BIN/npm" --prefix "$ROOT/frontend" run build
"$ROOT/.dev-venv/bin/python" "$ROOT/scripts/build_frontend.py"
[[ -f "$ROOT/src/stock_probs/static/next/index.html" ]]
[[ -f "$ROOT/src/stock_probs/static/next/api-docs.html" ]]
compgen -G "$ROOT/src/stock_probs/static/next/_next/static/chunks/*.js" >/dev/null
