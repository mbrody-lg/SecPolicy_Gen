#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INFRA_DIR="$ROOT_DIR/infrastructure"
COMPOSE_FILE="${INFRA_DIR}/docker-compose.yml"
ENV_FILE="${MIGRATION_SMOKE_ENV_FILE:-$INFRA_DIR/.env}"
CHROMA_CONTAINER="${CHROMA_CONTAINER:-infrastructure-chroma-1}"
CHROMA_IMAGE="${CHROMA_IMAGE:-chromadb/chroma}"
BACKUP_FILE="${CHROMA_BACKUP_FILE:-$ROOT_DIR/.local-workspace/chroma-backups/rag-runtime.tar.gz}"

usage() {
  cat <<'EOF'
Usage: scripts/chroma_backup.sh <backup|restore>

Environment:
  CHROMA_BACKUP_FILE   Backup tar.gz path.
  CHROMA_CONTAINER     Chroma container name. Default: infrastructure-chroma-1
  CHROMA_IMAGE         Local image used for volume maintenance. Default: chromadb/chroma
EOF
}

if command -v docker-compose >/dev/null 2>&1; then
  DOCKER_COMPOSE_CMD=(docker-compose)
elif docker compose version >/dev/null 2>&1; then
  DOCKER_COMPOSE_CMD=(docker compose)
else
  echo "docker-compose (or docker compose) is required."
  exit 1
fi

action="${1:-}"
case "$action" in
  backup|restore) ;;
  *)
    usage
    exit 2
    ;;
esac

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing env file: $ENV_FILE"
  exit 1
fi

if ! docker inspect "$CHROMA_CONTAINER" >/dev/null 2>&1; then
  echo "Missing Chroma container: $CHROMA_CONTAINER"
  exit 1
fi

case "$action" in
  backup)
    mkdir -p "$(dirname "$BACKUP_FILE")"
    echo "Creating Chroma backup: $BACKUP_FILE"
    docker exec "$CHROMA_CONTAINER" tar -czf - -C /data . > "$BACKUP_FILE"
    ;;
  restore)
    if [[ ! -f "$BACKUP_FILE" ]]; then
      echo "Missing Chroma backup: $BACKUP_FILE"
      exit 1
    fi
    echo "Restoring Chroma backup: $BACKUP_FILE"
    "${DOCKER_COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" --env-file "$ENV_FILE" stop chroma >/dev/null
    docker run --rm --volumes-from "$CHROMA_CONTAINER" --entrypoint sh "$CHROMA_IMAGE" -lc \
      'find /data -mindepth 1 -maxdepth 1 -exec rm -rf {} +'
    docker run --rm --volumes-from "$CHROMA_CONTAINER" \
      -v "$(dirname "$BACKUP_FILE"):/backup:ro" \
      --entrypoint sh "$CHROMA_IMAGE" -lc \
      "tar -xzf /backup/$(basename "$BACKUP_FILE") -C /data"
    "${DOCKER_COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d chroma >/dev/null
    ;;
esac
