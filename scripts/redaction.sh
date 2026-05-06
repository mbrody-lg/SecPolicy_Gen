#!/usr/bin/env bash

SENSITIVE_ENV_NAMES=(
  FLASK_SECRET_KEY
  MONGO_URI
  OPENAI_API_KEY
  MISTRAL_API_KEY
)

_escape_sed_literal() {
  printf "%s" "$1" | sed -e 's/[\/&]/\\&/g'
}

redact_sensitive_output() {
  local expression=""
  local name value escaped_value

  for name in "${SENSITIVE_ENV_NAMES[@]}"; do
    value="${!name:-}"
    if [[ -n "$value" ]]; then
      escaped_value="$(_escape_sed_literal "$value")"
      expression="${expression}s/${escaped_value}/[REDACTED:${name}]/g;"
    fi
  done

  expression="${expression}s/(OPENAI_API_KEY|MISTRAL_API_KEY|FLASK_SECRET_KEY|MONGO_URI)=([^[:space:]]+)/\\1=[REDACTED]/g;"
  expression="${expression}s/(openai_api_key|mistral_api_key|flask_secret_key|mongo_uri)[\"':= ]+[^,\"'[:space:]}]+/\\1=[REDACTED]/Ig;"

  sed -E "$expression"
}
