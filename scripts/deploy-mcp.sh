#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec uv run --offline --frozen --project tools/deploy_mcp python tools/deploy_mcp/server.py
