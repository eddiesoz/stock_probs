#!/usr/bin/env bash
# Resolve only the lock-installed official MCP binary; opencode.json supplies security flags.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$ROOT/.tools/node/bin:$PATH"
exec "$ROOT/tools/browser/node_modules/.bin/playwright-mcp" "$@"
