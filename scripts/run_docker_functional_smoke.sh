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
PYTHON_BIN="${PYTHON_BIN:-python3}"

declare -a SERVICE_PROBE_DEFINITIONS=(
  "context-agent|http://localhost:5003"
  "policy-agent|http://localhost:5002"
  "validator-agent|http://localhost:5001"
)

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

wait_for_http_200() {
  local url=$1
  local attempts=0
  local max_attempts=60
  local delay=2
  local code=""

  while (( attempts < max_attempts )); do
    code="$(curl -sS -o /dev/null -w "%{http_code}" "$url" || echo 000)"
    if [[ "$code" == "200" ]]; then
      log "ready: $url"
      return 0
    fi
    attempts=$((attempts + 1))
    sleep "$delay"
  done

  log "timeout waiting for $url to return 200"
  return 1
}

assert_response_header_present() {
  local headers_file=$1
  local header_name=$2

  if ! grep -qi "^${header_name}:" "$headers_file"; then
    log "missing required response header $header_name"
    return 1
  fi
}

assert_json_status_equals() {
  local body_file=$1
  local expected_status=$2
  local label=$3

  "$PYTHON_BIN" - "$body_file" "$expected_status" "$label" <<'PY'
import json
import sys

body_path, expected, label = sys.argv[1:4]
with open(body_path, encoding="utf-8") as handle:
    payload = json.load(handle)

actual = payload.get("status")
if actual != expected:
    raise SystemExit(f"{label} returned status={actual!r}, expected {expected!r}")
PY
}

probe_service_health_and_ready() {
  local service_name=$1
  local base_url=$2
  local health_headers ready_headers health_body ready_body health_code ready_code

  health_headers="$(mktemp)"
  ready_headers="$(mktemp)"
  health_body="$(mktemp)"
  ready_body="$(mktemp)"

  health_code="$(curl -sS -D "$health_headers" -o "$health_body" -w "%{http_code}" "$base_url/health" || echo 000)"
  if [[ "$health_code" != "200" ]]; then
    log "$service_name /health returned HTTP $health_code"
    rm -f "$health_headers" "$ready_headers" "$health_body" "$ready_body"
    return 1
  fi
  assert_response_header_present "$health_headers" "X-Correlation-ID"

  wait_for_http_200 "$base_url/ready"
  ready_code="$(curl -sS -D "$ready_headers" -o "$ready_body" -w "%{http_code}" "$base_url/ready" || echo 000)"
  if [[ "$ready_code" != "200" ]]; then
    log "$service_name /ready returned HTTP $ready_code"
    rm -f "$health_headers" "$ready_headers" "$health_body" "$ready_body"
    return 1
  fi
  assert_response_header_present "$ready_headers" "X-Correlation-ID"
  assert_json_status_equals "$ready_body" "ready" "$service_name /ready"

  log "$service_name probes validated (/health + /ready)"
  rm -f "$health_headers" "$ready_headers" "$health_body" "$ready_body"
}

run_service_probe_validation() {
  local definition service_name base_url
  for definition in "${SERVICE_PROBE_DEFINITIONS[@]}"; do
    service_name=${definition%%|*}
    base_url=${definition#*|}
    probe_service_health_and_ready "$service_name" "$base_url"
  done
}

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required for functional smoke tests."
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required for functional smoke tests."
  exit 1
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "$PYTHON_BIN is required for functional smoke tests."
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

log "waiting for services to accept HTTP traffic"
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

log "validating health and readiness probes for all services"
run_service_probe_validation

log "loading golden fixtures into context-agent"
docker exec "$CONTEXT_CONTAINER" python generate_context_from_yaml.py "$GOLDEN_DIR"

RESULT_FILE="$ROOT_DIR/migration/functional-smoke-result.json"
ERROR_FILE="$ROOT_DIR/migration/functional-smoke-error.log"
mkdir -p "$(dirname "$RESULT_FILE")"
: > "$ERROR_FILE"

log "running full context -> policy -> validation pipeline and collecting evidence"
if ! docker exec -i "$CONTEXT_CONTAINER" python - > "$RESULT_FILE" 2> "$ERROR_FILE" <<'PY'
import json
import time
from uuid import uuid4
from datetime import datetime, timezone
from bson import ObjectId
from pymongo import MongoClient
from app import create_app, mongo
import requests

app = create_app()
app.app_context().push()

SERVICE_ENDPOINTS = {
    "context-agent": "http://localhost:5000",
    "policy-agent": "http://policy-agent:5000",
    "validator-agent": "http://validator-agent:5000",
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def probe_service(base_url):
    checks = {}
    for path in ("/health", "/ready"):
        try:
            response = requests.get(f"{base_url}{path}", timeout=15)
            payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else {}
            checks[path[1:]] = {
                "status_code": response.status_code,
                "correlation_id": response.headers.get("X-Correlation-ID"),
                "payload_status": payload.get("status") if isinstance(payload, dict) else None,
            }
        except Exception as exc:  # pragma: no cover - smoke-only diagnostics
            checks[path[1:]] = {
                "status_code": 0,
                "correlation_id": None,
                "payload_status": None,
                "error": str(exc),
            }
    return checks


def lookup_diagnostics(correlation_id):
    deadline = time.time() + 10
    last_result = {
        "status_code": 0,
        "header_correlation_id": None,
        "document_correlation_id": None,
        "pipeline_status": None,
        "has_policy_hop": False,
        "has_validator_hop": False,
    }

    while time.time() < deadline:
        try:
            diagnostics_response = requests.get(
                f"http://localhost:5000/diagnostics/{correlation_id}",
                headers={"X-Correlation-ID": correlation_id},
                timeout=30,
            )
            last_result["status_code"] = diagnostics_response.status_code
            last_result["header_correlation_id"] = diagnostics_response.headers.get("X-Correlation-ID")
            diagnostics_payload = diagnostics_response.json() if diagnostics_response.headers.get("Content-Type", "").startswith("application/json") else {}
            if isinstance(diagnostics_payload, dict):
                last_result["document_correlation_id"] = diagnostics_payload.get("correlation_id")
                last_result["pipeline_status"] = diagnostics_payload.get("status")
                hops = diagnostics_payload.get("hops", [])
                last_result["has_policy_hop"] = any(hop.get("target_service") == "policy-agent" for hop in hops)
                last_result["has_validator_hop"] = any(hop.get("target_service") == "validator-agent" for hop in hops)
            if last_result["status_code"] == 200 and last_result["pipeline_status"] == "completed":
                break
        except Exception as exc:  # pragma: no cover - smoke-only diagnostics
            last_result["error"] = str(exc)
        time.sleep(0.5)

    return last_result


service_checks = {
    service_name: probe_service(base_url)
    for service_name, base_url in SERVICE_ENDPOINTS.items()
}
preflight_failures = []
for service_name, checks in service_checks.items():
    for check_name, check in checks.items():
        if check["status_code"] != 200:
            preflight_failures.append(f"{service_name}:{check_name}:status:{check['status_code']}")
        if not check.get("correlation_id"):
            preflight_failures.append(f"{service_name}:{check_name}:missing_correlation_id")
        if check_name == "ready" and check.get("payload_status") != "ready":
            preflight_failures.append(f"{service_name}:{check_name}:payload_status:{check.get('payload_status')}")

context_ids = [str(doc["_id"]) for doc in mongo.db.contexts.find({}, {"_id": 1})]
status_by_context = {}
observability_by_context = {}

for context_id in context_ids:
    correlation_id = f"smoke-{context_id}-{uuid4().hex[:8]}"
    try:
        response = requests.post(
            f"http://localhost:5000/context/{context_id}/generate_policy",
            headers={"X-Correlation-ID": correlation_id},
            allow_redirects=False,
            timeout=120,
        )
        generate_status = response.status_code
        response_correlation_id = response.headers.get("X-Correlation-ID")
    except Exception as exc:
        generate_status = 0
        response_correlation_id = None
        observability_by_context[context_id] = {
            "requested_correlation_id": correlation_id,
            "generate_response_correlation_id": response_correlation_id,
            "error": str(exc),
        }

    status_by_context[context_id] = generate_status
    observability_by_context.setdefault(context_id, {})
    observability_by_context[context_id].update(
        {
            "requested_correlation_id": correlation_id,
            "generate_response_correlation_id": response_correlation_id,
        }
    )
    observability_by_context[context_id].update(lookup_diagnostics(correlation_id))

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
    observability = observability_by_context.get(context_id, {})
    if generate_status not in (200, 302):
        reasons.append(f"generate_status:{generate_status}")
    if observability.get("generate_response_correlation_id") != observability.get("requested_correlation_id"):
        reasons.append("missing_or_mismatched_response_correlation_id")
    if observability.get("status_code") != 200:
        reasons.append(f"diagnostics_status:{observability.get('status_code')}")
    if observability.get("header_correlation_id") != observability.get("requested_correlation_id"):
        reasons.append("missing_or_mismatched_diagnostics_header_correlation_id")
    if observability.get("document_correlation_id") != observability.get("requested_correlation_id"):
        reasons.append("missing_or_mismatched_diagnostics_correlation_id")
    if observability.get("pipeline_status") != "completed":
        reasons.append(f"diagnostics_pipeline_status:{observability.get('pipeline_status')}")
    if not observability.get("has_policy_hop"):
        reasons.append("missing_policy_hop")
    if not observability.get("has_validator_hop"):
        reasons.append("missing_validator_hop")
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
        "pipeline_time": utc_now(),
        "failure_reasons": reasons,
        "observability": observability,
    })

if not context_ids:
    failed = [{"context_id": "n/a", "reasons": ["no_contexts_loaded"]}]

result = {
    "smoke_timestamp": utc_now(),
    "total_contexts": len(context_ids),
    "service_checks": service_checks,
    "preflight_failures": preflight_failures,
    "failed_contexts": failed,
    "summary": summary,
}

if preflight_failures:
    if not failed:
        failed.append({"context_id": "preflight", "reasons": preflight_failures})
    else:
        failed.insert(0, {"context_id": "preflight", "reasons": preflight_failures})

print(json.dumps(result, indent=2))

if failed:
    raise SystemExit(1)
PY
then
  echo "functional smoke pipeline failed. See $RESULT_FILE and $ERROR_FILE"
  exit 1
fi

echo "functional smoke completed. Report: $RESULT_FILE"
