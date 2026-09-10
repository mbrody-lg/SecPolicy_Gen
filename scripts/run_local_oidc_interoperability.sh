#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-}"
if [[ "$MODE" != "http" && "$MODE" != "https" ]]; then
  echo "usage: $0 <http|https>" >&2
  exit 2
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

bash scripts/generate_local_oidc_tls.sh
read -r -a COMPOSE <<< "$(scripts/docker_preflight.sh --print-compose)"
COMPOSE_ARGS=(
  -f infrastructure/docker-compose.yml
  -f infrastructure/docker-compose.local-oidc.yml
  --env-file infrastructure/.env
  --profile local-oidc
  --profile local-oidc-https
)
SCHEME="$MODE"
PORT=8080
if [[ "$MODE" == "https" ]]; then
  PORT=8443
  export OIDC_ALLOW_INSECURE_HTTP=false
else
  export OIDC_ALLOW_INSECURE_HTTP=true
fi
ISSUER="$SCHEME://identity.test:$PORT/realms/secpolicygen"
REDIRECT_URI="https://context-agent.test/auth/callback"
export LOCAL_OIDC_HOSTNAME="$SCHEME://identity.test:$PORT"
export LOCAL_OIDC_CERT_UID="$(id -u)"
export OIDC_ISSUER_URL="$ISSUER"
export OIDC_REDIRECT_URI="$REDIRECT_URI"
export TRUSTED_HOSTS="localhost,127.0.0.1,context-agent,context-agent.test,identity.test"
export SESSION_COOKIE_SECURE=true
certificate_spki() {
  openssl x509 -in "$1" -pubkey -noout |
    openssl pkey -pubin -outform der |
    openssl dgst -sha256 -binary |
    openssl base64
}
LOCAL_OIDC_CERT_SPKI="$(certificate_spki infrastructure/.local-certs/identity.crt),$(certificate_spki infrastructure/.local-certs/context-edge.crt)"

fetch_discovery() {
  if [[ "$MODE" == "https" ]]; then
    curl --silent --fail --resolve "identity.test:$PORT:127.0.0.1" \
      --cacert infrastructure/.local-certs/ca.crt \
      "$ISSUER/.well-known/openid-configuration" >/dev/null
  else
    curl --silent --fail --resolve "identity.test:$PORT:127.0.0.1" \
      "$ISSUER/.well-known/openid-configuration" >/dev/null
  fi
}

echo "[local-oidc] starting $MODE issuer"
  "${COMPOSE[@]}" "${COMPOSE_ARGS[@]}" \
  up -d --force-recreate identity
  "${COMPOSE[@]}" "${COMPOSE_ARGS[@]}" \
  up --build -d context-agent
if [[ "$MODE" == "https" ]]; then
  "${COMPOSE[@]}" "${COMPOSE_ARGS[@]}" up -d context-edge
fi

for _ in $(seq 1 90); do
  if fetch_discovery; then
    break
  fi
  sleep 2
done
fetch_discovery

if [[ "$MODE" == "https" ]]; then
  for _ in $(seq 1 30); do
    if curl --silent --fail --resolve "context-agent.test:5443:127.0.0.1" \
      --cacert infrastructure/.local-certs/ca.crt \
      "https://context-agent.test:5443/health" >/dev/null; then
      break
    fi
    sleep 1
  done
  curl --silent --fail --resolve "context-agent.test:5443:127.0.0.1" \
    --cacert infrastructure/.local-certs/ca.crt \
    "https://context-agent.test:5443/health" >/dev/null
fi

for _ in $(seq 1 60); do
  health_status="$(docker inspect --format='{{.State.Health.Status}}' context_agent_web 2>/dev/null || true)"
  [[ "$health_status" == "healthy" ]] && break
  sleep 2
done
if [[ "${health_status:-}" != "healthy" ]]; then
  docker logs --tail 100 context_agent_web >&2
  exit 1
fi

docker exec context_agent_web python manage_identity.py \
  --issuer "$ISSUER" \
  --subject 11111111-1111-1111-1111-111111111111 \
  --organization-id local-development \
  --organization-name "SecPolicyGen Local Organization" \
  --role admin

echo "[local-oidc] running browser login against $MODE issuer"
"${COMPOSE[@]}" "${COMPOSE_ARGS[@]}" --profile test run --rm \
  -e CONTEXT_BROWSER_BASE_URL=https://context-agent.test \
  -e LOCAL_OIDC_CERT_SPKI="$LOCAL_OIDC_CERT_SPKI" \
  context-browser-tests sh -c \
  'cp /etc/secpolicygen/local-oidc-ca.crt /usr/local/share/ca-certificates/secpolicygen-local.crt && update-ca-certificates >/dev/null && /opt/browser-tests/node_modules/.bin/playwright test oidc-interoperability.spec.js --project chromium-desktop'

echo "[local-oidc] $MODE interoperability passed"
