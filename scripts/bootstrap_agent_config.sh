#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="${AGENT_CONFIG_DIR:-$ROOT_DIR/runtime/agent-config}"

mkdir -p "$CONFIG_DIR"

copy_if_missing() {
  local source_path=$1
  local target_name=$2
  local target_path="$CONFIG_DIR/$target_name"

  if [[ -f "$target_path" ]]; then
    printf "[agent-config] preserved existing %s\n" "$target_path"
    return
  fi

  cp "$source_path" "$target_path"
  printf "[agent-config] created %s from %s\n" "$target_path" "$source_path"
}

copy_if_missing "$ROOT_DIR/context-agent/app/config/context_agent.yaml" "context_agent.yaml"
copy_if_missing "$ROOT_DIR/context-agent/app/config/context_questions.yaml" "context_questions.yaml"
copy_if_missing "$ROOT_DIR/policy-agent/app/config/policy_agent.yaml" "policy_agent.yaml"
copy_if_missing "$ROOT_DIR/validator-agent/app/config/validator_agent.yaml" "validator_agent.yaml"

printf "[agent-config] ready: %s\n" "$CONFIG_DIR"
