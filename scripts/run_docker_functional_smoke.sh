#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INFRA_DIR="$ROOT_DIR/infrastructure"
INFRA_ENV_FILE="${INFRA_DIR}/.env"
TMP_ENV_FILE=""
TMP_ENV_TEMP_CREATED=0
STACK_STARTED=0

CONTEXT_CONTAINER="context_agent_web"
POLICY_CONTAINER="policy_agent_service"
VALIDATOR_CONTAINER="validator_agent_service"
COMPOSE_FILE="${INFRA_DIR}/docker-compose.yml"
POLICY_MOCK_CONFIG="/policy-agent/app/config/examples/policy_agent.example.mock.yaml"
POLICY_CONTAINER_CONFIG=""
VALIDATOR_CONTAINER_CONFIG=""

MOCK_MODE="${MIGRATION_SMOKE_MOCK:-1}"
CLEAN_DB="${MIGRATION_SMOKE_CLEAN_DB:-1}"
KEEP_STACK="${MIGRATION_SMOKE_KEEP_STACK:-0}"
TMP_BACKUP_DIR=""
GOLDEN_DIR="${MIGRATION_SMOKE_GOLDEN_DIR:-/migration/golden-contexts}"

log() {
  printf "[functional-smoke] %s\n" "$*"
}

resolve_service_config_path() {
  local container_name=$1
  docker exec "$container_name" python -c "from app import create_app; app=create_app(); print(app.config['CONFIG_PATH'])"
}

if command -v docker-compose >/dev/null 2>&1; then
  DOCKER_COMPOSE_CMD=(docker-compose)
elif docker compose version >/dev/null 2>&1; then
  DOCKER_COMPOSE_CMD=(docker compose)
else
  echo "docker-compose (or docker compose) is required for functional smoke tests."
  exit 1
fi

restore_and_cleanup() {
  if [[ -n "$TMP_BACKUP_DIR" && -d "$TMP_BACKUP_DIR" ]]; then
    if docker inspect "$CONTEXT_CONTAINER" >/dev/null 2>&1; then
      if [[ -f "$TMP_BACKUP_DIR/context_agent.yaml" ]]; then
        docker cp "$TMP_BACKUP_DIR/context_agent.yaml" "$CONTEXT_CONTAINER:/context-agent/app/config/context_agent.yaml" || true
      fi
      if [[ -f "$TMP_BACKUP_DIR/policy_agent.yaml" ]]; then
        docker exec "$POLICY_CONTAINER" mkdir -p /config
        docker cp "$TMP_BACKUP_DIR/policy_agent.yaml" "$POLICY_CONTAINER:$POLICY_CONTAINER_CONFIG" || true
      fi
      if [[ -f "$TMP_BACKUP_DIR/validator_agent.yaml" ]]; then
        docker cp "$TMP_BACKUP_DIR/validator_agent.yaml" "$VALIDATOR_CONTAINER:/validator-agent/app/config/validator_agent.yaml" || true
      fi
    fi

    rm -rf "$TMP_BACKUP_DIR"
  fi

  if [[ "$TMP_ENV_TEMP_CREATED" -eq 1 && -n "$TMP_ENV_FILE" && -f "$TMP_ENV_FILE" ]]; then
    rm -f "$TMP_ENV_FILE"
  fi

  if [[ "$KEEP_STACK" == "1" || "$KEEP_STACK" == "true" ]]; then
    log "KEEP_STACK active: docker stack preserved"
    return
  fi

  if [[ "$STACK_STARTED" -eq 1 ]]; then
    log "stopping docker stack"
    "${DOCKER_COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" down -v --remove-orphans >/dev/null 2>&1 || true
    STACK_STARTED=0
  fi
}

trap 'restore_and_cleanup' EXIT

wait_for_http() {
  local url=$1
  local attempts=0
  local max_attempts=60
  local delay=2
  local code=""

  while (( attempts < max_attempts )); do
    code="$(curl -sS -o /dev/null -w "%{http_code}" "$url" || echo 000)"
    if [[ "$code" =~ ^[0-9]+$ ]] && (( code >= 200 && code < 500 )); then
      log "ready: $url"
      return 0
    fi
    attempts=$((attempts + 1))
    sleep "$delay"
  done

  log "timeout waiting for $url"
  return 1
}

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required for functional smoke tests."
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required for functional smoke tests."
  exit 1
fi

if [[ ! -f "$INFRA_ENV_FILE" ]]; then
  if [[ -f "$INFRA_DIR/.env.example" ]]; then
    TMP_ENV_FILE="$(mktemp)"
    TMP_ENV_TEMP_CREATED=1
    cp "$INFRA_DIR/.env.example" "$TMP_ENV_FILE"
    log "using ephemeral infrastructure env file from .env.example"
  else
    echo "Missing infrastructure/.env and .env.example"
    exit 1
  fi
else
  TMP_ENV_FILE="$INFRA_ENV_FILE"
fi

log "starting docker stack for functional smoke tests"
"${DOCKER_COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" --env-file "$TMP_ENV_FILE" up --build -d
STACK_STARTED=1

log "waiting for services"
wait_for_http "http://localhost:5003/"
wait_for_http "http://localhost:5002/generate_policy"
wait_for_http "http://localhost:5001/validate-policy"

if [[ "$GOLDEN_DIR" == "/migration/golden-contexts" ]]; then
  if ! docker exec "$CONTEXT_CONTAINER" test -d /migration/golden-contexts; then
    GOLDEN_DIR="/context-agent/app/config/examples/answers"
  fi
fi

docker exec "$CONTEXT_CONTAINER" test -d "$GOLDEN_DIR"
log "loading golden fixtures from $GOLDEN_DIR"

if [[ "$CLEAN_DB" == "1" || "$CLEAN_DB" == "true" ]]; then
  log "clearing previous service state for deterministic run"
  docker exec -i "$CONTEXT_CONTAINER" python - <<'PY'
from pymongo import MongoClient

client = MongoClient("mongo", 27017)
client.contextdb.contexts.delete_many({})
client.contextdb.interactions.delete_many({})
client.policydb.policies.delete_many({})
client.validatordb.validations.delete_many({})
PY
fi

if [[ "$MOCK_MODE" == "1" || "$MOCK_MODE" == "true" ]]; then
  POLICY_CONTAINER_CONFIG="$(resolve_service_config_path "$POLICY_CONTAINER")"
  VALIDATOR_CONTAINER_CONFIG="$(resolve_service_config_path "$VALIDATOR_CONTAINER")"
  TMP_BACKUP_DIR="$(mktemp -d)"
  docker cp "$CONTEXT_CONTAINER:/context-agent/app/config/context_agent.yaml" "$TMP_BACKUP_DIR/context_agent.yaml"
  docker cp "$POLICY_CONTAINER:$POLICY_CONTAINER_CONFIG" "$TMP_BACKUP_DIR/policy_agent.yaml"
  docker cp "$VALIDATOR_CONTAINER:$VALIDATOR_CONTAINER_CONFIG" "$TMP_BACKUP_DIR/validator_agent.yaml"
  log "using mock agent configs for deterministic execution"
  docker exec "$CONTEXT_CONTAINER" cp /context-agent/app/config/examples/context_agent.example.mock.yaml /context-agent/app/config/context_agent.yaml
  docker exec "$POLICY_CONTAINER" sh -lc "mkdir -p \"$(dirname "$POLICY_CONTAINER_CONFIG")\" && cp \"$POLICY_MOCK_CONFIG\" \"$POLICY_CONTAINER_CONFIG\""
  docker exec "$VALIDATOR_CONTAINER" sh -lc "mkdir -p \"$(dirname "$VALIDATOR_CONTAINER_CONFIG")\" && cp /validator-agent/app/config/examples/validator_agent.example.mock.yaml \"$VALIDATOR_CONTAINER_CONFIG\""
else
  log "using existing service configs (requires production-like API keys for model calls)"
fi

log "loading golden fixtures into context-agent"
docker exec "$CONTEXT_CONTAINER" python generate_context_from_yaml.py "$GOLDEN_DIR"

RESULT_FILE="$ROOT_DIR/migration/functional-smoke-result.json"
mkdir -p "$(dirname "$RESULT_FILE")"

log "running full context -> policy -> validation pipeline and collecting evidence"
if ! docker exec -i "$CONTEXT_CONTAINER" python - > "$RESULT_FILE" <<'PY'
import json
from datetime import datetime
from bson import ObjectId
from pymongo import MongoClient
from app import create_app, mongo
import requests

app = create_app()
app.app_context().push()

context_ids = [str(doc["_id"]) for doc in mongo.db.contexts.find({}, {"_id": 1})]
status_by_context = {}

for context_id in context_ids:
    try:
        response = requests.post(
            f"http://localhost:5000/context/{context_id}/generate_policy",
            allow_redirects=False,
            timeout=120,
        )
        status_by_context[context_id] = response.status_code
    except Exception:
        status_by_context[context_id] = 0

client = MongoClient("mongo", 27017)
context_db = client.contextdb
policy_db = client.policydb
validator_db = client.validatordb
fallback_db = client.contextdb

summary = []
failed = []

for context_id in context_ids:
    context_oid = ObjectId(context_id)
    validated_count = context_db.interactions.count_documents({
        "context_id": context_oid,
        "question_id": "validated_policy",
    })
    policy_records = policy_db.policies.count_documents({"context_id": context_id})
    if policy_records == 0:
        policy_records = fallback_db.policies.count_documents({"context_id": context_id})

    validation_docs = list(
        validator_db.validations.find({"context_id": context_id}).sort("timestamp", -1)
    )
    if not validation_docs:
        validation_docs = list(
            fallback_db.validations.find({"context_id": context_id}).sort("timestamp", -1)
        )

    reasons = []
    generate_status = status_by_context.get(context_id, 0)
    if generate_status not in (200, 302):
        reasons.append(f"generate_status:{generate_status}")
    if validated_count == 0:
        reasons.append("missing_validated_policy")
    if policy_records == 0:
        reasons.append("missing_policy_record")

    if reasons:
        failed.append({"context_id": context_id, "reasons": reasons})

    summary.append({
        "context_id": context_id,
        "generate_status": generate_status,
        "validated_policy_records": validated_count,
        "policy_records": policy_records,
        "validation_rounds": len(validation_docs),
        "last_status": validation_docs[0].get("final_decision") if validation_docs else None,
        "pipeline_time": datetime.utcnow().isoformat() + "Z",
        "failure_reasons": reasons,
    })

if not context_ids:
    failed = [{"context_id": "n/a", "reasons": ["no_contexts_loaded"]}]

result = {
    "smoke_timestamp": datetime.utcnow().isoformat() + "Z",
    "total_contexts": len(context_ids),
    "failed_contexts": failed,
    "summary": summary,
}

print(json.dumps(result, indent=2))

if failed:
    raise SystemExit(1)
PY
then
  echo "functional smoke pipeline failed. See $RESULT_FILE"
  exit 1
fi

echo "functional smoke completed. Report: $RESULT_FILE"
