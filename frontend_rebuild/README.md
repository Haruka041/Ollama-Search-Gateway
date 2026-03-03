# Ollama Search Gateway Console

这个目录是面向 `backend/main.py` 的正式前端控制台。

## 已覆盖功能

- 管理员登录（`/api/auth/login`）
- 鉴权检查（`/api/auth/me`）
- 总览（`/api/health` + `/api/stats`）
- 节点管理（`/api/nodes`）
- API Key 管理（`/api/keys` + `/api/keys/import`）
- 代理请求测试（`/api/web-search`、`/api/chat`、`/v1/chat/completions`）
- 日志查看（`/api/logs`）

## 本地开发

```bash
cd frontend_rebuild
npm install
npm run dev
```

默认开发地址：`http://127.0.0.1:3000`

## 打包

```bash
npm run build
```

输出目录：`frontend_rebuild/dist`
