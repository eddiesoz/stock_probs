#!/usr/bin/env bash
# Capture orchestration stays separate from the app and reuses the pinned browser/runtime launchers.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[[ "$#" -eq 0 ]] || { printf 'usage: %s\n' "$0" >&2; exit 2; }
[[ -x "$ROOT/.dev-venv/bin/python" ]] || { printf 'missing developer environment: run scripts/bootstrap.sh\n' >&2; exit 1; }
[[ -f "$ROOT/tools/browser/node_modules/playwright/index.js" ]] || { printf 'missing pinned Playwright: run scripts/install-node.sh\n' >&2; exit 1; }

exec node "$ROOT/tools/walkthrough/capture.js"
