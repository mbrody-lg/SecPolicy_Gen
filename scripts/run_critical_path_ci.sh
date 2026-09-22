#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
METRICS_DIR="${CRITICAL_PATH_METRICS_DIR:-$ROOT_DIR/migration/critical-path}"
ENV_FILE="${CRITICAL_PATH_ENV_FILE:-$ROOT_DIR/infrastructure/.env.smoke.example}"
PROJECT_NAME="${CRITICAL_PATH_COMPOSE_PROJECT:-secpolicy-critical-path-ci}"
COMPOSE_OVERRIDE="${CRITICAL_PATH_COMPOSE_OVERRIDE:-$ROOT_DIR/infrastructure/docker-compose.critical-path.yml}"

mkdir -p "$METRICS_DIR"
started_at="$(date +%s)"
disk_before_kb="$(df -Pk "$ROOT_DIR" | awk 'NR == 2 {print $3}')"
status="failed"

write_metrics() {
  local exit_code=$1
  local finished_at disk_after_kb
  finished_at="$(date +%s)"
  disk_after_kb="$(df -Pk "$ROOT_DIR" | awk 'NR == 2 {print $3}')"
  printf '{\n  "status": "%s",\n  "exit_code": %d,\n  "total_seconds": %d,\n  "disk_used_before_kb": %d,\n  "disk_used_after_kb": %d,\n  "disk_delta_kb": %d\n}\n' \
    "$status" "$exit_code" "$((finished_at - started_at))" \
    "$disk_before_kb" "$disk_after_kb" "$((disk_after_kb - disk_before_kb))" \
    > "$METRICS_DIR/metrics.json"
}

finish() {
  local exit_code=$?
  write_metrics "$exit_code"
  exit "$exit_code"
}
trap finish EXIT

CRITICAL_PATH_ENV_FILE="$ENV_FILE" \
CRITICAL_PATH_COMPOSE_PROJECT="$PROJECT_NAME" \
CRITICAL_PATH_COMPOSE_OVERRIDE="$COMPOSE_OVERRIDE" \
CRITICAL_PATH_REMOVE_VOLUMES=1 \
  make -C "$ROOT_DIR" critical-path-validation
status="passed"
