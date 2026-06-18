#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

FIXTURE_PATH="${CONTEXT_BROWSER_FIXTURE_HOST_PATH:-migration/context-browser-smoke.json}"
COMPOSE_FILE="infrastructure/docker-compose.yml"
ENV_FILE="infrastructure/.env"

make docker-preflight
read -r -a DOCKER_COMPOSE_CMD <<< "$(scripts/docker_preflight.sh --print-compose)"

mkdir -p "$(dirname "$FIXTURE_PATH")"

echo "[context-browser] ensuring Context Agent test stack is running"
"${DOCKER_COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d context-agent
for _ in $(seq 1 60); do
  health_status="$(docker inspect --format='{{.State.Health.Status}}' context_agent_web 2>/dev/null || true)"
  if [[ "$health_status" == "healthy" ]]; then
    break
  fi
  sleep 2
done
if [[ "${health_status:-}" != "healthy" ]]; then
  echo "[context-browser] context_agent_web did not become healthy; status=${health_status:-unknown}" >&2
  exit 1
fi

echo "[context-browser] seeding deterministic context workflow fixtures"
docker exec context_agent_web python scripts/seed_browser_smoke_contexts.py > "$FIXTURE_PATH"

echo "[context-browser] running Playwright release-gate smoke in Docker"
"${DOCKER_COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" --env-file "$ENV_FILE" --profile test run --rm \
  -e CONTEXT_BROWSER_FIXTURE_PATH="/repo/$FIXTURE_PATH" \
  context-browser-tests
