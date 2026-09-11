#!/usr/bin/env bash
# Reset port-scoped browser state so concurrent local QA runs cannot share audit records.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${STOCK_PROBS_BROWSER_PORT:-8765}"
if [[ ! "$PORT" =~ ^[0-9]+$ ]] || (( 10#$PORT < 1 || 10#$PORT > 65535 )); then
  printf 'STOCK_PROBS_BROWSER_PORT must be between 1 and 65535.\n' >&2
  exit 2
fi
RUNTIME="${STOCK_PROBS_BROWSER_RUNTIME:-$ROOT/tools/browser/test-results/runtime-$PORT}"
rm -rf "$RUNTIME"
export STOCK_PROBS_DATA_DIR="$RUNTIME"
export STOCK_PROBS_PROVIDER="fixture"
export STOCK_PROBS_FIXTURE_NOW="2025-01-10T17:03:00+00:00"
exec "$ROOT/.dev-venv/bin/python" -m stock_probs.cli serve --host 127.0.0.1 --port "$PORT"
