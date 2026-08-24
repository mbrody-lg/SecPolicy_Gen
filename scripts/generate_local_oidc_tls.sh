#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CERT_DIR="$ROOT_DIR/infrastructure/.local-certs"

mkdir -p "$CERT_DIR"
if [[ -s "$CERT_DIR/ca.crt" && -s "$CERT_DIR/ca.key" && \
      -s "$CERT_DIR/identity.crt" && -s "$CERT_DIR/identity.key" && \
      -s "$CERT_DIR/context-edge.crt" && -s "$CERT_DIR/context-edge.key" ]]; then
  exit 0
fi

openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 365 \
  -subj "/CN=SecPolicyGen Local Development CA" \
  -keyout "$CERT_DIR/ca.key" \
  -out "$CERT_DIR/ca.crt"
issue_certificate() {
  local name=$1
  local common_name=$2
  local sans=$3

  openssl req -newkey rsa:3072 -sha256 -nodes \
    -subj "/CN=$common_name" \
    -addext "subjectAltName=$sans" \
    -keyout "$CERT_DIR/$name.key" \
    -out "$CERT_DIR/$name.csr"
  printf '%s\n' "subjectAltName=$sans" 'extendedKeyUsage=serverAuth' \
    > "$CERT_DIR/$name.ext"
  openssl x509 -req -sha256 -days 365 \
    -in "$CERT_DIR/$name.csr" \
    -CA "$CERT_DIR/ca.crt" \
    -CAkey "$CERT_DIR/ca.key" \
    -CAcreateserial \
    -extfile "$CERT_DIR/$name.ext" \
    -out "$CERT_DIR/$name.crt"
}

issue_certificate identity identity.test "DNS:identity.test,DNS:localhost,IP:127.0.0.1"
issue_certificate context-edge context-agent.test "DNS:context-agent.test,DNS:localhost,IP:127.0.0.1"
chmod 600 "$CERT_DIR"/*.key

echo "Generated local OIDC TLS material in infrastructure/.local-certs"
