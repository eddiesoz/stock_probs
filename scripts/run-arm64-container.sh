#!/usr/bin/env bash
# Container entrypoint: install locked ARM64 dependencies, then run the package/runtime smoke.
set -euo pipefail

printf 'execution_label=emulated ARM64 via OCI/QEMU; not native or physical ARM64 performance evidence\n'
mkdir -p /opt/stock-probs-deps/home /opt/stock-probs-deps/python
python -m pip install --disable-pip-version-check --no-cache-dir \
  --target /opt/stock-probs-deps/python --requirement /workspace/requirements.lock
export PYTHONPATH="/opt/stock-probs-deps/python"
export STOCK_PROBS_DEPENDENCY_PATH="$PYTHONPATH"
exec python /workspace/scripts/package_smoke.py \
  --artifact-dir /artifacts/package --expected-machine aarch64
