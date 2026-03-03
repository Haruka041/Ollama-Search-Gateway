# Ollama Search Gateway

Ollama Search Gateway (OSG) 是一个 FastAPI 网关，提供：

- 多节点转发与健康探测
- API Key 池管理
- OpenAI 兼容接口
- SearxNG 兼容接口（`/search`）
- 内置管理前端（由同一个容器直接提供静态页面）

## 部署方式

## 1) 单容器（推荐）

```bash
docker run -d --name ollama-search-gateway \
  -p 8080:8080 \
  -e ADMIN_USERNAME=admin \
  -e ADMIN_PASSWORD='admin123' \
  -e JWT_SECRET='replace-with-a-long-random-secret' \
  -e OLLAMA_NODES='https://ollama.com' \
  -v ./runtime/backend-data:/data \
  ghcr.io/haruka041/ollama-search-gateway:latest
```

访问：

- 管理台：`http://<你的IP>:8080`
- 健康检查：`http://<你的IP>:8080/health`

> 服务监听 `0.0.0.0:8080`，公网访问还需要放行主机/云防火墙端口。
> 后端同时支持 `ADMIN_PASSWORD`（明文）和 `ADMIN_PASSWORD_HASH`（哈希），若两者都设置则优先使用哈希。

## 2) Docker Compose（使用 GHCR latest 镜像）

```bash
cp .env.example .env
docker compose -f docker-compose.ghcr.yml up -d
```

默认 compose 使用镜像：

- `ghcr.io/haruka041/ollama-search-gateway:latest`

## 默认登录

- 用户名：`admin`
- 默认密码：`admin123`

> 首次部署后请立即修改密码和 `JWT_SECRET`。

## 常用配置

| 变量 | 说明 | 默认 |
|---|---|---|
| `PUBLIC_PORT` | 宿主机暴露端口 | `8080` |
| `OLLAMA_NODES` | 上游节点（逗号分隔） | `https://ollama.com` |
| `WEB_SEARCH_PATH` | 搜索上游路径 | `/api/web_search` |
| `CHAT_PATH` | 聊天上游路径 | `/api/chat` |
| `ALLOW_NO_API_KEY` | 是否允许无 key 请求 | `false` |
| `ADMIN_USERNAME` | 管理员用户名 | `admin` |
| `ADMIN_PASSWORD` | 管理员明文密码（简单模式） | `admin123` |
| `ADMIN_PASSWORD_HASH` | 管理员密码哈希 | `sha256$...` |
| `JWT_SECRET` | JWT 签名密钥 | `replace-with-a-long-random-secret` |
| `SEARX_COMPAT_USERNAME` | `/search` 的 Basic Auth 用户名（可选） | 空 |
| `SEARX_COMPAT_PASSWORD` | `/search` 的 Basic Auth 明文密码（可选） | 空 |
| `SEARX_COMPAT_PASSWORD_HASH` | `/search` 的 Basic Auth 密码哈希（可选） | 空 |
| `SEARX_COMPAT_STORE_FILE` | Searx 兼容设置持久化文件 | `searx_compat.json` |

## 密码哈希生成

PowerShell:

```powershell
$pwd='your-password'
$hash=[BitConverter]::ToString(([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($pwd)))).Replace('-','').ToLower()
"sha256$$hash"
```

Python:

```bash
python - <<'PY'
import hashlib
pwd = "your-password"
print("sha256$" + hashlib.sha256(pwd.encode()).hexdigest())
PY
```

## API 兼容

- OpenAI 兼容：`POST /v1/chat/completions`
- Web Search：`POST /api/web-search` 或 `POST /api/search`
- Chat：`POST /api/chat`
- SearxNG 兼容：`GET /search` / `POST /search`

## SearxNG 客户端填写建议

- API URL：`http(s)://<域名>/search`
- Engines：可留空或 `google,bing,duckduckgo`
- Language：可留空或 `zh-CN`
- Username / Password：当你启用了 Searx 兼容鉴权时填写

## 自动构建与发布

仓库内置 GitHub Actions：

- 自动构建并推送 GHCR 镜像
- 自动创建 Release
- 版本号使用 **commit 时间**（UTC）：
  - 形如：`vYYYYMMDDHHMMSS`
  - 镜像标签：`latest` 和 `YYYYMMDDHHMMSS`

## 本地开发（源码）

```bash
docker compose -f docker-compose.dev.yml up -d --build
```
