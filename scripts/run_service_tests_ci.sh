#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infrastructure/docker-compose.yml"
COMPOSE_OVERRIDE="$ROOT_DIR/infrastructure/docker-compose.service-tests.yml"
ENV_FILE="${SERVICE_TEST_ENV_FILE:-$ROOT_DIR/infrastructure/.env.smoke.example}"
METRICS_DIR="${SERVICE_TEST_METRICS_DIR:-$ROOT_DIR/migration/service-tests}"
HEALTH_TIMEOUT_SECONDS="${SERVICE_TEST_HEALTH_TIMEOUT_SECONDS:-180}"

service="${1:-}"
case "$service" in
  context-agent)
    target="context-tests"
    container_variable="CONTEXT_TEST_CONTAINER"
    ;;
  policy-agent)
    target="policy-tests"
    container_variable="POLICY_TEST_CONTAINER"
    ;;
  validator-agent)
    target="validator-tests"
    container_variable="VALIDATOR_TEST_CONTAINER"
    ;;
  *)
    echo "Usage: $0 {context-agent|policy-agent|validator-agent}" >&2
    exit 2
    ;;
esac

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing service-test env file: $ENV_FILE" >&2
  exit 1
fi
if [[ ! "$HEALTH_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  echo "SERVICE_TEST_HEALTH_TIMEOUT_SECONDS must be a positive integer" >&2
  exit 1
fi

compose_cmd="$("$ROOT_DIR/scripts/docker_preflight.sh" --print-compose)"
read -r -a compose_parts <<< "$compose_cmd"
project_name="secpolicy-service-tests-${service}"
compose=("${compose_parts[@]}" -p "$project_name" -f "$COMPOSE_FILE" -f "$COMPOSE_OVERRIDE" --env-file "$ENV_FILE")

mkdir -p "$METRICS_DIR"
started_at="$(date +%s)"
test_started_at=""
status="failed"

write_metrics() {
  local finished_at total_seconds test_seconds
  finished_at="$(date +%s)"
  total_seconds=$((finished_at - started_at))
  test_seconds=0
  if [[ -n "$test_started_at" ]]; then
    test_seconds=$((finished_at - test_started_at))
  fi
  printf '{\n  "service": "%s",\n  "status": "%s",\n  "total_seconds": %d,\n  "test_seconds": %d\n}\n' \
    "$service" "$status" "$total_seconds" "$test_seconds" \
    > "$METRICS_DIR/$service.json"
}

cleanup() {
  exit_code=$?
  if [[ "$exit_code" -ne 0 ]]; then
    "${compose[@]}" ps || true
    "${compose[@]}" logs --tail 200 "$service" || true
  fi
  "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  write_metrics
  exit "$exit_code"
}
trap cleanup EXIT

"$ROOT_DIR/scripts/bootstrap_agent_config.sh"
"${compose[@]}" up --build -d "$service"
container="$("${compose[@]}" ps -q "$service")"
if [[ -z "$container" ]]; then
  echo "Compose did not create a container for $service" >&2
  exit 1
fi

deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
while (( SECONDS < deadline )); do
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$container" 2>/dev/null || true)"
  if [[ "$health" == "healthy" ]]; then
    break
  fi
  if [[ "$health" == "unhealthy" ]]; then
    echo "$service became unhealthy" >&2
    exit 1
  fi
  sleep 2
done

if [[ "${health:-}" != "healthy" ]]; then
  echo "$service did not become healthy within ${HEALTH_TIMEOUT_SECONDS}s" >&2
  exit 1
fi

test_started_at="$(date +%s)"
make -C "$ROOT_DIR" "$target" "$container_variable=$container"
status="passed"
