# OWS Backend (FastAPI)

任务ID：OWS-BE-01

## 功能
- 多 Ollama 节点 round-robin 调度
- 节点失败自动切换下一节点（含超时与重试）
- API Key 批量导入（一行一个，自动 trim + 去重）
- Key 启停与使用统计
- `/api/search` 代理 Ollama Web Search（兼容 stream true/false）

## 启动
```bash
cd /mnt/512/openclaw-workspace/ollama-web-search/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 可选配置
export OLLAMA_NODES="https://ollama.com,https://your-backup-node.example.com"
export WEB_SEARCH_PATH="/api/web_search"
export HEALTH_PATH="/api/tags"
export REQUEST_TIMEOUT_SECONDS="20"
export RETRY_ATTEMPTS="5"
export NODE_FAILURE_THRESHOLD="2"
export HEALTH_INTERVAL_SECONDS="15"
export ALLOW_NO_API_KEY="0"
export SEARX_COMPAT_USERNAME="searx-user"
export SEARX_COMPAT_PASSWORD="change-me"
export SEARX_COMPAT_PASSWORD_HASH="sha256$<your_password_sha256_hex>"

uvicorn main:app --host 0.0.0.0 --port 8000
```

## 接口
- `GET /health`
- `GET /api/health`
- `GET /api/nodes`
- `POST /api/nodes`
- `PUT /api/nodes/{id}`
- `DELETE /api/nodes/{id}`
- `POST /api/keys/import`（支持 `text/plain`、`application/json`、json lines）
- `GET /api/keys`
- `PATCH /api/keys/{id}/toggle`
- `DELETE /api/keys/{id}`
- `GET /api/settings/searx-compat`
- `PUT /api/settings/searx-compat`
- `POST /api/search`
- `GET /search`（SearxNG 兼容）
- `POST /search`（SearxNG 兼容）

## 最小测试命令

### 1) 健康检查
```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/api/health
```

### 2) 导入 key（text/plain）
```bash
cat <<'EOF' | curl -s -X POST http://127.0.0.1:8000/api/keys/import \
  -H 'Content-Type: text/plain' --data-binary @-
sk-key-1
sk-key-2
sk-key-1

EOF
```

### 3) 导入 key（json）
```bash
curl -s -X POST http://127.0.0.1:8000/api/keys/import \
  -H 'Content-Type: application/json' \
  -d '{"keys":["sk-a","sk-b","sk-a"]}'
```

### 4) 列出 key
```bash
curl -s http://127.0.0.1:8000/api/keys
```

### 5) 搜索（非流式）
```bash
curl -s -X POST http://127.0.0.1:8000/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"what is ollama?","max_results":5,"stream":false}'
```

### 6) 搜索（流式）
```bash
curl -N -X POST http://127.0.0.1:8000/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"latest ollama web search news","max_results":5,"stream":true}'
```

### 7) SearxNG 兼容接口（可选独立 Basic Auth）

如果设置了 `SEARX_COMPAT_USERNAME`，则 `/search` 会要求 Basic Auth，且账号与后台管理 JWT 登录完全分离。

```bash
# 先生成密码哈希（示例密码: change-me）
python - <<'PY'
import hashlib
pwd = "change-me"
print("sha256$" + hashlib.sha256(pwd.encode()).hexdigest())
PY

# 调用兼容接口
curl -s "http://127.0.0.1:8000/search?q=llm&format=json" \
  -u "searx-user:change-me"
```

## 说明
- 当前实现为纯内存状态：服务重启后 key 列表、统计、节点健康状态会重置。
- `/api/search` 对请求体采用透传策略（除 `api_key_id` 和 `timeout_seconds` 外），兼容 Ollama Web Search 的 `query/max_results/stream` 参数扩展。
- `/search` 的 Basic Auth 为可选。未设置 `SEARX_COMPAT_USERNAME` 时保持开放；设置后需配置 `SEARX_COMPAT_PASSWORD` 或 `SEARX_COMPAT_PASSWORD_HASH`（若两者都设置，优先哈希）。
- 管理台可通过 `PUT /api/settings/searx-compat` 在线修改 Searx 兼容鉴权（仅保存哈希，不保存明文密码），配置持久化到 `${STATE_DIR}/${SEARX_COMPAT_STORE_FILE:-searx_compat.json}`。
