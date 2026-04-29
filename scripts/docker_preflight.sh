#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/infrastructure/docker-compose.yml}"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/infrastructure/.env}"

print_compose=0
if [[ "${1:-}" == "--print-compose" ]]; then
  print_compose=1
fi

detect_compose() {
  if command -v docker-compose >/dev/null 2>&1; then
    printf "docker-compose\n"
    return 0
  fi

  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    printf "docker compose\n"
    return 0
  fi

  return 1
}

fail() {
  printf "[docker-preflight] %s\n" "$*" >&2
}

if compose_cmd="$(detect_compose)"; then
  if [[ "$print_compose" -eq 1 ]]; then
    printf "%s\n" "$compose_cmd"
    exit 0
  fi
else
  fail "Docker Compose is required. Install either the Docker Compose plugin ('docker compose') or the legacy 'docker-compose' binary."
  fail "Then re-run 'make docker-preflight' to verify the local setup."
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  fail "Docker CLI is required but was not found in PATH."
  fail "Install Docker Desktop or Docker Engine, then re-run 'make docker-preflight'."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  fail "Docker is installed, but the daemon is not reachable."
  fail "Start Docker Desktop or the Docker service, then re-run 'make docker-preflight'."
  exit 1
fi

if [[ ! -f "$COMPOSE_FILE" ]]; then
  fail "Compose file not found: $COMPOSE_FILE"
  fail "Run this target from the repository root or set COMPOSE_FILE to the correct path."
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  fail "Compose env file not found: $ENV_FILE"
  fail "Create infrastructure/.env or set ENV_FILE to the env file used by your stack."
  exit 1
fi

printf "[docker-preflight] ok: using %s\n" "$compose_cmd"
