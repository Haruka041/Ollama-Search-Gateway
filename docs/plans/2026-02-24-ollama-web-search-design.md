# Ollama Web Search 后端设计文档

**目标**：实现独立 FastAPI 服务，提供多节点 Ollama Web Search 代理、API Key 管理与限流统计。

## 1. 架构

- API 层（FastAPI）
  - `/web-search`：对外搜索代理
  - `/keys/*`：Key 管理与统计
  - `/nodes/*`：Ollama 节点管理
  - `/health`、`/stats`：健康与观测
- 领域层
  - `NodePool`：多节点负载、健康检查、故障摘除
  - `APIKeyManager`：批量导入、去重、CRUD、限流、统计
- 基础设施
  - `httpx.AsyncClient`：上游调用与流式转发
  - 后台健康检查任务：周期探活节点

## 2. 关键机制

1. 负载均衡：支持 `round-robin` 与 `least-connections`。
2. 健康检查：探测失败累积，超过阈值摘除；后续探活成功自动恢复。
3. Key 限流：按 key 的每分钟请求上限（纯内存窗口计数）。
4. 重试：非流式请求在节点失败时自动切换节点重试。
5. 流式代理：使用 `httpx` streaming + `StreamingResponse` 透传。

## 3. 数据模型（内存）

- `NodeState`：`id/base_url/healthy/fail_count/active_connections/total_requests/total_failures/last_error/last_checked_at`
- `APIKeyState`：`id/key/note/enabled/created_at/updated_at/total_requests/total_failures/last_used_at/window_epoch_minute/window_count`

## 4. 错误处理

- 无可用节点：503
- 无可用 Key 或限流：429/503
- 上游错误：透传状态码与错误摘要

## 5. 非目标

- 本次不做持久化（重启丢失状态），后续可升级 JSON/SQLite。
- 本次不做鉴权网关（建议部署时由反向代理增加认证）。
