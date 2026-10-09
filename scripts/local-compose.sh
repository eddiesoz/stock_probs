#!/usr/bin/env bash
# Route local image builds through the fixed Buildx policy before Compose starts the service.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if (( $# == 0 )); then
  printf 'Usage: %s up [Compose options] | build | <non-build Compose command>\n' "$0" >&2
  exit 2
fi

COMMAND="$1"
shift

if [[ "$COMMAND" == "build" ]]; then
  if (( $# != 0 )); then
    printf 'The bounded local image build accepts no service overrides.\n' >&2
    exit 2
  fi
  exec /usr/bin/python3 "$ROOT/scripts/bounded_docker_build.py" --local-image-build
fi

if [[ "$COMMAND" == "up" ]]; then
  BUILD_REQUESTED="false"
  COMPOSE_ARGS=()
  for ARG in "$@"; do
    if [[ "$ARG" == "--build" ]]; then
      BUILD_REQUESTED="true"
    else
      COMPOSE_ARGS+=("$ARG")
    fi
  done
  if [[ "$BUILD_REQUESTED" == "true" ]]; then
    BUILD_RESULT="$(/usr/bin/python3 "$ROOT/scripts/bounded_docker_build.py" --local-image-build)"
    export STOCK_PROBS_LOCAL_IMAGE="$(BUILD_RESULT="$BUILD_RESULT" /usr/bin/python3 -c 'import json, os; value=json.loads(os.environ["BUILD_RESULT"]); tag=value.get("tag"); assert isinstance(tag, str); print(tag)')"
  else
    CURRENT_RESULT="$(/usr/bin/python3 "$ROOT/scripts/bounded_docker_build.py" --local-current-image)"
    export STOCK_PROBS_LOCAL_IMAGE="$(CURRENT_RESULT="$CURRENT_RESULT" /usr/bin/python3 -c 'import json, os; value=json.loads(os.environ["CURRENT_RESULT"]); tag=value.get("tag"); assert isinstance(tag, str); print(tag)')"
  fi
  exec docker compose --project-directory "$ROOT" --file "$ROOT/compose.yaml" \
    up "${COMPOSE_ARGS[@]}"
fi

for ARG in "$@"; do
  if [[ "$ARG" == "--build" ]]; then
    printf 'Build requests are supported only for the bounded local up/build commands.\n' >&2
    exit 2
  fi
done

if [[ -z "${STOCK_PROBS_LOCAL_IMAGE:-}" ]]; then
  STOCK_PROBS_LOCAL_IMAGE="stock-probs:local"
fi
export STOCK_PROBS_LOCAL_IMAGE
exec docker compose --project-directory "$ROOT" --file "$ROOT/compose.yaml" \
  "$COMMAND" "$@"
