#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "[INFO] 未检测到 .env，已由 .env.example 生成默认 .env"
fi

echo "[INFO] 启动生产栈（backend + frontend/nginx）..."
docker compose --env-file .env up -d --build

echo "[INFO] 运行健康检查..."
"$ROOT_DIR/scripts/check.sh"

echo "[DONE] 生产栈启动完成"
