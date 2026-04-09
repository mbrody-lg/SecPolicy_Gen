#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INFRA_DIR="${ROOT_DIR}/infrastructure"
INFRA_ENV_FILE="${INFRA_DIR}/.env"
COMPOSE_FILE="${INFRA_DIR}/docker-compose.yml"
CASE_FILE="${1:-${ROOT_DIR}/migration/golden-contexts/case-01-healthcare-clinic.json}"
OUTPUT_FILE="${2:-${ROOT_DIR}/migration/phase1-legacy-output.json}"
MOCK_MODE="${LEGACY_PHASE1_MOCK:-1}"
KEEP_STACK="${LEGACY_PHASE1_KEEP_STACK:-0}"

CONTEXT_CONTAINER="context_agent_web"
POLICY_CONTAINER="policy_agent_service"
VALIDATOR_CONTAINER="validator_agent_service"
POLICY_CONTAINER_CONFIG="/config/policy_agent.yaml"
POLICY_CONTAINER_SOURCE_CONFIG="/policy-agent/app/config/policy_agent.yaml"
POLICY_MOCK_CONFIG="/policy-agent/app/config/examples/policy_agent.example.mock.yaml"

TMP_ENV_FILE=""
TMP_ENV_TEMP_CREATED=0
TMP_BACKUP_DIR=""
STACK_STARTED=0

log() {
  printf "[phase1-legacy] %s\n" "$*"
}

if command -v docker-compose >/dev/null 2>&1; then
  DOCKER_COMPOSE_CMD=(docker-compose)
elif docker compose version >/dev/null 2>&1; then
  DOCKER_COMPOSE_CMD=(docker compose)
else
  echo "docker-compose (or docker compose) is required."
  exit 1
fi

cleanup() {
  if [[ -n "$TMP_BACKUP_DIR" && -d "$TMP_BACKUP_DIR" ]]; then
    if docker inspect "$CONTEXT_CONTAINER" >/dev/null 2>&1; then
      if [[ -f "$TMP_BACKUP_DIR/context_agent.yaml" ]]; then
        docker cp "$TMP_BACKUP_DIR/context_agent.yaml" "$CONTEXT_CONTAINER:/context-agent/app/config/context_agent.yaml" || true
      fi
      if [[ -f "$TMP_BACKUP_DIR/policy_agent.yaml" ]]; then
        docker exec "$POLICY_CONTAINER" mkdir -p /config || true
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
  fi
}

trap cleanup EXIT

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

if [[ ! -f "$CASE_FILE" ]]; then
  echo "Golden case not found: $CASE_FILE"
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT_FILE")"

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

log "starting docker stack"
"${DOCKER_COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" --env-file "$TMP_ENV_FILE" up --build -d
STACK_STARTED=1

log "waiting for services"
wait_for_http "http://localhost:5003/"
wait_for_http "http://localhost:5002/generate_policy"
wait_for_http "http://localhost:5001/validate-policy"

log "clearing service state"
docker exec -i "$CONTEXT_CONTAINER" python - <<'PY'
from pymongo import MongoClient

client = MongoClient("mongo", 27017)
client.contextdb.contexts.delete_many({})
client.contextdb.interactions.delete_many({})
client.policydb.policies.delete_many({})
client.validatordb.validations.delete_many({})
PY

if [[ "$MOCK_MODE" == "1" || "$MOCK_MODE" == "true" ]]; then
  TMP_BACKUP_DIR="$(mktemp -d)"
  docker cp "$CONTEXT_CONTAINER:/context-agent/app/config/context_agent.yaml" "$TMP_BACKUP_DIR/context_agent.yaml"
  if ! docker cp "$POLICY_CONTAINER:$POLICY_CONTAINER_CONFIG" "$TMP_BACKUP_DIR/policy_agent.yaml"; then
    docker cp "$POLICY_CONTAINER:$POLICY_CONTAINER_SOURCE_CONFIG" "$TMP_BACKUP_DIR/policy_agent.yaml"
  fi
  docker cp "$VALIDATOR_CONTAINER:/validator-agent/app/config/validator_agent.yaml" "$TMP_BACKUP_DIR/validator_agent.yaml"
  log "using mock configs for deterministic legacy capture"
  docker exec "$CONTEXT_CONTAINER" cp /context-agent/app/config/examples/context_agent.example.mock.yaml /context-agent/app/config/context_agent.yaml
  docker exec "$POLICY_CONTAINER" sh -lc "mkdir -p /config && cp $POLICY_MOCK_CONFIG $POLICY_CONTAINER_CONFIG"
  docker exec "$VALIDATOR_CONTAINER" cp /validator-agent/app/config/examples/validator_agent.example.mock.yaml /validator-agent/app/config/validator_agent.yaml
else
  log "using existing service configs"
fi

log "loading single golden case"
docker exec "$CONTEXT_CONTAINER" mkdir -p /tmp/phase1-case
docker cp "$CASE_FILE" "$CONTEXT_CONTAINER:/tmp/phase1-case/input.json"
docker exec "$CONTEXT_CONTAINER" python generate_context_from_yaml.py /tmp/phase1-case

log "running legacy pipeline and capturing comparable JSON"
docker exec -i "$CONTEXT_CONTAINER" python - "$CASE_FILE" > "$OUTPUT_FILE" <<'PY'
import json
import sys
from pathlib import Path
from datetime import datetime
from bson import ObjectId
from pymongo import MongoClient
import requests
from app import create_app, mongo

case_file = Path(sys.argv[1]).resolve()
case_data = json.loads(case_file.read_text(encoding="utf-8"))

app = create_app()
app.app_context().push()

context_doc = mongo.db.contexts.find_one(sort=[("created_at", -1)])
if not context_doc:
    raise SystemExit("No context loaded.")

context_id = str(context_doc["_id"])
response = requests.post(
    f"http://localhost:5000/context/{context_id}/generate_policy",
    allow_redirects=False,
    timeout=120,
)

client = MongoClient("mongo", 27017)
context_db = client.contextdb
policy_db = client.policydb
validator_db = client.validatordb

validated = context_db.interactions.find_one(
    {"context_id": ObjectId(context_id), "question_id": "validated_policy"},
    sort=[("timestamp", -1)],
)
policy_doc = policy_db.policies.find_one({"context_id": context_id}, sort=[("generated_at", -1)])
if not policy_doc:
    policy_doc = context_db.policies.find_one({"context_id": context_id}, sort=[("generated_at", -1)])
validation_doc = validator_db.validations.find_one({"context_id": context_id}, sort=[("timestamp", -1)])
if not validation_doc:
    validation_doc = context_db.validations.find_one({"context_id": context_id}, sort=[("timestamp", -1)])

result = {
    "case_id": case_data.get("case_id"),
    "scenario": case_data.get("scenario"),
    "strategy_id": case_data.get("strategy_id"),
    "context_id": context_id,
    "language": (policy_doc or {}).get("language", context_doc.get("language", "en")),
    "policy_text": (validated or {}).get("answer", (policy_doc or {}).get("policy_text", "")),
    "structured_plan": (policy_doc or {}).get("structured_plan", []),
    "generated_at": (
        (policy_doc or {}).get("generated_at").isoformat()
        if (policy_doc or {}).get("generated_at") is not None
        else datetime.utcnow().isoformat() + "Z"
    ),
    "policy_agent_version": (policy_doc or {}).get("policy_agent_version", ""),
    "status": (validated or {}).get("status", (validation_doc or {}).get("final_decision", "review")),
    "reasons": (
        ((validation_doc or {}).get("evaluator_result") or {}).get("reasons", [])
        if isinstance((validation_doc or {}).get("evaluator_result"), dict)
        else []
    ),
    "recommendations": (validated or {}).get("recommendations", []),
    "legacy_meta": {
        "generate_status": response.status_code,
        "validation_rounds": 0 if not validation_doc else 1 + len((validation_doc.get("all_rounds") or [])),
        "validation_found": validation_doc is not None,
        "validated_policy_found": validated is not None,
        "source_case_file": str(case_file),
    },
}

print(json.dumps(result, indent=2))
PY

log "legacy comparable output saved to $OUTPUT_FILE"
