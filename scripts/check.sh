#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PUBLIC_PORT="${PUBLIC_PORT:-8080}"
if [[ -f .env ]]; then
  ENV_PUBLIC_PORT=$(grep -E '^PUBLIC_PORT=' .env | tail -n1 | cut -d'=' -f2- || true)
  if [[ -n "${ENV_PUBLIC_PORT:-}" ]]; then
    PUBLIC_PORT="$ENV_PUBLIC_PORT"
  fi
fi

BASE_URL="http://127.0.0.1:${PUBLIC_PORT}"

echo "[CHECK] compose ps"
docker compose ps || true

echo "[CHECK] GET ${BASE_URL}/healthz"
curl -fsS "${BASE_URL}/healthz" && echo

echo "[CHECK] GET ${BASE_URL}/api/health"
curl -fsS "${BASE_URL}/api/health" && echo

echo "[CHECK] POST ${BASE_URL}/api/web-search"
curl -fsS "${BASE_URL}/api/web-search" \
  -H 'Content-Type: application/json' \
  -d '{"query":"docker compose health check","max_results":3,"stream":false}' | head -c 400

echo

echo "[OK] 基础验收完成"
