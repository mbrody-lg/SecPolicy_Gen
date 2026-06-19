#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "${RUN_REAL_PROVIDER_TESTS:-0}" != "1" && "${RUN_REAL_PROVIDER_TESTS:-}" != "true" ]]; then
  echo "RUN_REAL_PROVIDER_TESTS=1 is required for Context Agent live-provider smoke." >&2
  exit 2
fi

make docker-preflight
read -r -a DOCKER_COMPOSE_CMD <<< "$(scripts/docker_preflight.sh --print-compose)"

OUTPUT_HOST_PATH="${CONTEXT_LIVE_PROVIDER_SMOKE_OUTPUT:-migration/context-live-provider-smoke.json}"
case "$OUTPUT_HOST_PATH" in
  migration/*) OUTPUT_CONTAINER_PATH="/$OUTPUT_HOST_PATH" ;;
  *)
    echo "CONTEXT_LIVE_PROVIDER_SMOKE_OUTPUT must stay under migration/." >&2
    exit 2
    ;;
esac
mkdir -p "$(dirname "$OUTPUT_HOST_PATH")"

"${DOCKER_COMPOSE_CMD[@]}" -f infrastructure/docker-compose.yml --env-file infrastructure/.env up -d context-agent

for _ in $(seq 1 60); do
  health_status="$(docker inspect --format='{{.State.Health.Status}}' context_agent_web 2>/dev/null || true)"
  if [[ "$health_status" == "healthy" ]]; then
    break
  fi
  sleep 2
done
if [[ "${health_status:-}" != "healthy" ]]; then
  echo "context_agent_web did not become healthy; status=${health_status:-unknown}" >&2
  exit 1
fi

docker exec \
  -e RUN_REAL_PROVIDER_TESTS=1 \
  context_agent_web \
  python scripts/run_context_live_provider_smoke.py --output "$OUTPUT_CONTAINER_PATH"

python3 scripts/validate_context_live_provider_smoke_artifact.py "$OUTPUT_HOST_PATH"
echo "context live-provider smoke completed. Report: $OUTPUT_HOST_PATH"
