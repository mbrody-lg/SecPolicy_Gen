#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="${AGENT_CONFIG_DIR:-$ROOT_DIR/runtime/agent-config}"

require_file() {
  local path=$1
  if [[ ! -f "$path" ]]; then
    printf "Missing required external agent config: %s\n" "$path" >&2
    printf "Run: scripts/bootstrap_agent_config.sh\n" >&2
    exit 1
  fi
}

require_file "$CONFIG_DIR/context_agent.yaml"
require_file "$CONFIG_DIR/context_questions.yaml"
require_file "$CONFIG_DIR/policy_agent.yaml"
require_file "$CONFIG_DIR/validator_agent.yaml"

docker run --rm \
  -v "$ROOT_DIR:/repo:ro" \
  -v "$CONFIG_DIR:/agent-config:ro" \
  -w /repo/context-agent \
  infrastructure-context-agent \
  python -c "from app.agents.factory import load_agent_config; import yaml; load_agent_config('/agent-config/context_agent.yaml'); data=yaml.safe_load(open('/agent-config/context_questions.yaml', encoding='utf-8')); assert isinstance(data.get('questions'), list) and data['questions']"

docker run --rm \
  -v "$ROOT_DIR:/repo:ro" \
  -v "$CONFIG_DIR:/agent-config:ro" \
  -w /repo/policy-agent \
  infrastructure-policy-agent \
  python -c "from app.agents.factory import load_agent_config; config=load_agent_config('/agent-config/policy_agent.yaml'); assert isinstance(config.get('roles'), list) and config['roles']"

docker run --rm \
  -v "$ROOT_DIR:/repo:ro" \
  -v "$CONFIG_DIR:/agent-config:ro" \
  -w /repo/validator-agent \
  infrastructure-validator-agent \
  python -c "from app.agents.factory import load_agent_config; config=load_agent_config('/agent-config/validator_agent.yaml'); assert isinstance(config.get('roles'), list) and config['roles']"

printf "[agent-config] contracts validated: %s\n" "$CONFIG_DIR"
