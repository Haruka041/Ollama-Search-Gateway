from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator
from urllib.parse import urlparse

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field


# =========================
# Settings
# =========================


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _split_csv(text: str | None) -> list[str]:
    raw = (text or "").replace("\n", ",")
    parts = [x.strip().rstrip("/") for x in raw.split(",") if x.strip()]
    if not parts:
        return ["https://ollama.com"]
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _split_list(text: str | None, default: list[str]) -> list[str]:
    raw = (text or "").replace("\n", ",")
    parts = [x.strip().rstrip("/") for x in raw.split(",") if x.strip()]
    if not parts:
        return default
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _normalize_api_key(raw: str) -> str:
    key = (raw or "").strip().strip('"').strip("'")
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return key


def _sanitize_log_detail(text: str) -> str:
    out = (text or "")
    out = re.sub(r"(?i)bearer\s+[a-z0-9._\-]+", "Bearer ***", out)
    out = re.sub(r"sk-[a-zA-Z0-9_\-]{8,}", "sk-***", out)
    out = re.sub(r"([A-Za-z0-9_\-]{24,})", "***", out)
    return out[:2000]


class Settings(BaseModel):
    ollama_nodes: list[str] = Field(default_factory=lambda: _split_csv(os.getenv("OLLAMA_NODES")))
    web_search_path: str = (os.getenv("WEB_SEARCH_PATH", "/api/web_search") or "/api/web_search").strip()
    chat_path: str = (os.getenv("CHAT_PATH", "/api/chat") or "/api/chat").strip()
    health_path: str = (os.getenv("HEALTH_PATH", "/api/tags") or "/api/tags").strip()
    request_timeout_seconds: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
    retry_attempts: int = int(os.getenv("RETRY_ATTEMPTS", "3"))
    node_failure_threshold: int = int(os.getenv("NODE_FAILURE_THRESHOLD", "3"))
    key_failure_threshold: int = int(os.getenv("KEY_FAILURE_THRESHOLD", "2"))
    key_cooldown_seconds: int = int(os.getenv("KEY_COOLDOWN_SECONDS", "60"))
    health_interval_seconds: int = int(os.getenv("HEALTH_INTERVAL_SECONDS", "15"))
    allow_no_api_key: bool = _parse_bool(os.getenv("ALLOW_NO_API_KEY"), default=False)

    admin_username: str = (os.getenv("ADMIN_USERNAME", "admin") or "admin").strip()
    admin_password: str = (os.getenv("ADMIN_PASSWORD", "") or "")
    admin_password_hash: str = (os.getenv("ADMIN_PASSWORD_HASH", "") or "").strip()
    jwt_secret: str = (os.getenv("JWT_SECRET", "") or "").strip()
    jwt_expire_minutes: int = max(1, int(os.getenv("JWT_EXPIRE_MINUTES", "120")))
    searx_compat_username: str = (os.getenv("SEARX_COMPAT_USERNAME", "") or "").strip()
    searx_compat_password: str = (os.getenv("SEARX_COMPAT_PASSWORD", "") or "")
    searx_compat_password_hash: str = (os.getenv("SEARX_COMPAT_PASSWORD_HASH", "") or "").strip()

    state_dir: str = (os.getenv("STATE_DIR", "/data") or "/data").strip()
    keys_store_file: str = (os.getenv("KEYS_STORE_FILE", "keys.json") or "keys.json").strip()
    nodes_store_file: str = (os.getenv("NODES_STORE_FILE", "nodes.json") or "nodes.json").strip()
    searx_compat_store_file: str = (os.getenv("SEARX_COMPAT_STORE_FILE", "searx_compat.json") or "searx_compat.json").strip()

    log_buffer_size: int = int(os.getenv("LOG_BUFFER_SIZE", "300"))
    cors_allow_origins: list[str] = Field(
        default_factory=lambda: _split_list(
            os.getenv("CORS_ALLOW_ORIGINS"),
            [
                "http://127.0.0.1:13000",
                "http://localhost:13000",
                "http://127.0.0.1:3000",
                "http://localhost:3000",
                "http://127.0.0.1:8080",
                "http://localhost:8080",
            ],
        )
    )
    cors_allow_origin_regex: str | None = (os.getenv("CORS_ALLOW_ORIGIN_REGEX", "") or "").strip() or None

    @property
    def keys_store_path(self) -> Path:
        return Path(self.state_dir) / self.keys_store_file

    @property
    def nodes_store_path(self) -> Path:
        return Path(self.state_dir) / self.nodes_store_file

    @property
    def searx_compat_store_path(self) -> Path:
        return Path(self.state_dir) / self.searx_compat_store_file


SETTINGS = Settings()


# =========================
# Errors & trace
# =========================


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = int(status_code)
        self.code = (code or "error").strip() or "error"
        self.message = (message or "").strip() or "unknown_error"
        super().__init__(self.message)


def _get_trace_id(request: Request | None) -> str:
    if request is None:
        return str(uuid.uuid4())
    value = getattr(getattr(request, "state", None), "trace_id", None)
    return value or str(uuid.uuid4())


def _error_payload(code: str, message: str, trace_id: str) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "trace_id": trace_id,
        }
    }


def _error_response(status_code: int, code: str, message: str, trace_id: str) -> JSONResponse:
    resp = JSONResponse(status_code=status_code, content=_error_payload(code, message, trace_id))
    resp.headers["x-trace-id"] = trace_id
    return resp


def _normalize_http_error(detail: Any, status_code: int) -> tuple[str, str]:
    if isinstance(detail, dict):
        code = str(detail.get("code") or f"http_{status_code}")
        message = str(detail.get("message") or code)
        return code, message
    if isinstance(detail, str):
        code = detail if re.fullmatch(r"[a-zA-Z0-9_\-.]+", detail) else f"http_{status_code}"
        return code, detail
    return f"http_{status_code}", str(detail or "http_error")


# =========================
# Event logs
# =========================


@dataclass
class EventLogEntry:
    ts: float
    level: str
    event: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.ts)),
            "level": self.level,
            "event": self.event,
            "detail": self.detail,
        }


class EventLog:
    def __init__(self, max_len: int = 300) -> None:
        self._items: deque[EventLogEntry] = deque(maxlen=max(50, max_len))
        self._lock = asyncio.Lock()

    async def add(self, level: str, event: str, detail: str) -> None:
        async with self._lock:
            self._items.append(
                EventLogEntry(
                    ts=time.time(),
                    level=level.upper(),
                    event=event[:80],
                    detail=_sanitize_log_detail((detail or "")[:2000]),
                )
            )

    async def list(self, limit: int = 100) -> list[dict[str, Any]]:
        cap = max(1, min(500, int(limit)))
        async with self._lock:
            return [x.to_dict() for x in list(self._items)[-cap:]][::-1]


# =========================
# Node pool
# =========================


@dataclass
class NodeState:
    id: str
    base_url: str
    enabled: bool = True
    healthy: bool = True
    active_connections: int = 0
    fail_count: int = 0
    total_requests: int = 0
    total_failures: int = 0
    last_error: str | None = None
    last_checked_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "base_url": self.base_url,
            "enabled": self.enabled,
            "healthy": self.healthy,
            "active_connections": self.active_connections,
            "fail_count": self.fail_count,
            "total_requests": self.total_requests,
            "total_failures": self.total_failures,
            "last_error": self.last_error,
            "last_checked_at": (
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.last_checked_at)) if self.last_checked_at else None
            ),
        }

    def to_store(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "base_url": self.base_url,
            "enabled": self.enabled,
        }


class NodePool:
    def __init__(self, nodes: list[str], failure_threshold: int = 3) -> None:
        self._nodes: dict[str, NodeState] = {}
        self._lock = asyncio.Lock()
        self._rr_cursor = 0
        self._failure_threshold = max(1, int(failure_threshold))
        for url in nodes:
            self._add_no_lock(url)

    def _add_no_lock(self, base_url: str, node_id: str | None = None, enabled: bool = True) -> NodeState:
        base_url = base_url.strip().rstrip("/")
        for n in self._nodes.values():
            if n.base_url == base_url:
                n.enabled = enabled
                return n
        node = NodeState(id=node_id or str(uuid.uuid4()), base_url=base_url, enabled=enabled)
        self._nodes[node.id] = node
        return node

    async def load_from_store(self, rows: list[dict[str, Any]]) -> None:
        async with self._lock:
            self._nodes.clear()
            for row in rows:
                base_url = str(row.get("base_url", "")).strip().rstrip("/")
                if not base_url:
                    continue
                node_id = str(row.get("id") or str(uuid.uuid4()))
                enabled = bool(row.get("enabled", True))
                self._add_no_lock(base_url, node_id=node_id, enabled=enabled)

    async def add(self, base_url: str, enabled: bool = True) -> NodeState:
        async with self._lock:
            node = self._add_no_lock(base_url, enabled=enabled)
            return node

    async def update(self, node_id: str, *, base_url: str | None = None, enabled: bool | None = None) -> NodeState:
        async with self._lock:
            node = self._nodes.get(node_id)
            if not node:
                raise KeyError("node_not_found")
            if base_url is not None:
                target = base_url.strip().rstrip("/")
                for n in self._nodes.values():
                    if n.id != node_id and n.base_url == target:
                        raise ValueError("node_base_url_duplicate")
                node.base_url = target
            if enabled is not None:
                node.enabled = bool(enabled)
            return node

    async def remove(self, node_id: str) -> bool:
        async with self._lock:
            return self._nodes.pop(node_id, None) is not None

    async def list(self) -> list[dict[str, Any]]:
        async with self._lock:
            return [n.to_dict() for n in self._nodes.values()]

    async def store_rows(self) -> list[dict[str, Any]]:
        async with self._lock:
            return [n.to_store() for n in self._nodes.values()]

    async def acquire(self, excluded_node_ids: set[str]) -> NodeState:
        async with self._lock:
            candidates = [
                n for n in self._nodes.values() if n.enabled and n.healthy and n.id not in excluded_node_ids
            ]
            if not candidates:
                raise RuntimeError("no_available_nodes")
            candidates.sort(key=lambda x: x.base_url)
            idx = self._rr_cursor % len(candidates)
            node = candidates[idx]
            self._rr_cursor = (self._rr_cursor + 1) % max(1, len(candidates))
            node.active_connections += 1
            node.total_requests += 1
            return node

    async def release_success(self, node_id: str) -> None:
        async with self._lock:
            node = self._nodes.get(node_id)
            if not node:
                return
            node.active_connections = max(0, node.active_connections - 1)
            node.fail_count = 0
            node.healthy = True
            node.last_error = None

    async def release_failure(self, node_id: str, error: str) -> None:
        async with self._lock:
            node = self._nodes.get(node_id)
            if not node:
                return
            node.active_connections = max(0, node.active_connections - 1)
            node.total_failures += 1
            node.fail_count += 1
            node.last_error = (error or "unknown")[:300]
            if node.fail_count >= self._failure_threshold:
                node.healthy = False

    async def probe_once(self, client: httpx.AsyncClient, health_path: str, timeout_s: float) -> None:
        async with self._lock:
            nodes = list(self._nodes.values())
        for node in nodes:
            if not node.enabled:
                continue
            url = f"{node.base_url}{health_path}"
            ok = False
            err = None
            try:
                resp = await client.get(url, timeout=timeout_s)
                ok = 200 <= resp.status_code < 500
                if not ok:
                    err = f"health_http_{resp.status_code}"
            except Exception as exc:  # noqa: BLE001
                err = f"health_exc:{exc.__class__.__name__}"

            async with self._lock:
                current = self._nodes.get(node.id)
                if not current:
                    continue
                current.last_checked_at = time.time()
                if ok:
                    current.healthy = True
                    current.fail_count = 0
                    current.last_error = None
                else:
                    current.fail_count += 1
                    current.last_error = err
                    if current.fail_count >= self._failure_threshold:
                        current.healthy = False


# =========================
# API key pool
# =========================


@dataclass
class APIKeyState:
    id: str
    key: str
    enabled: bool = True
    created_at: float = 0
    updated_at: float = 0
    total_requests: int = 0
    total_failures: int = 0
    fail_count: int = 0
    healthy: bool = True
    cooldown_until: float | None = None
    last_error: str | None = None
    last_used_at: float | None = None

    def masked(self) -> str:
        if len(self.key) <= 8:
            return "*" * len(self.key)
        return f"{self.key[:4]}***{self.key[-4:]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "key": self.masked(),
            "enabled": self.enabled,
            "healthy": self.healthy,
            "total_requests": self.total_requests,
            "total_failures": self.total_failures,
            "fail_count": self.fail_count,
            "last_error": self.last_error,
            "cooldown_until": (
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.cooldown_until)) if self.cooldown_until else None
            ),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.created_at)),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.updated_at)),
            "last_used_at": (
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.last_used_at)) if self.last_used_at else None
            ),
        }

    def to_store(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "key": self.key,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "total_requests": self.total_requests,
            "total_failures": self.total_failures,
            "fail_count": self.fail_count,
            "healthy": self.healthy,
            "cooldown_until": self.cooldown_until,
            "last_error": self.last_error,
            "last_used_at": self.last_used_at,
        }


class APIKeyPool:
    def __init__(self, failure_threshold: int = 2, cooldown_seconds: int = 60) -> None:
        self._keys: dict[str, APIKeyState] = {}
        self._by_key: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._rr_cursor = 0
        self._failure_threshold = max(1, int(failure_threshold))
        self._cooldown_seconds = max(10, int(cooldown_seconds))

    async def load_from_store(self, rows: list[dict[str, Any]]) -> None:
        async with self._lock:
            self._keys.clear()
            self._by_key.clear()
            for row in rows:
                key = _normalize_api_key(str(row.get("key", "")))
                if not key:
                    continue
                item = APIKeyState(
                    id=str(row.get("id") or str(uuid.uuid4())),
                    key=key,
                    enabled=bool(row.get("enabled", True)),
                    created_at=float(row.get("created_at") or time.time()),
                    updated_at=float(row.get("updated_at") or time.time()),
                    total_requests=int(row.get("total_requests") or 0),
                    total_failures=int(row.get("total_failures") or 0),
                    fail_count=int(row.get("fail_count") or 0),
                    healthy=bool(row.get("healthy", True)),
                    cooldown_until=float(row.get("cooldown_until")) if row.get("cooldown_until") else None,
                    last_error=str(row.get("last_error")) if row.get("last_error") else None,
                    last_used_at=float(row.get("last_used_at")) if row.get("last_used_at") else None,
                )
                if key in self._by_key:
                    continue
                self._keys[item.id] = item
                self._by_key[key] = item.id

    async def list(self) -> list[dict[str, Any]]:
        async with self._lock:
            return [k.to_dict() for k in self._keys.values()]

    async def store_rows(self) -> list[dict[str, Any]]:
        async with self._lock:
            return [k.to_store() for k in self._keys.values()]

    def _recover_if_due(self, item: APIKeyState) -> None:
        if item.healthy:
            return
        if item.cooldown_until is not None and time.time() >= item.cooldown_until:
            item.healthy = True
            item.fail_count = 0
            item.cooldown_until = None
            item.last_error = None
            item.updated_at = time.time()

    async def create(self, raw_key: str, enabled: bool = True) -> APIKeyState:
        key = _normalize_api_key(raw_key)
        if not key:
            raise ValueError("invalid_key")

        async with self._lock:
            if key in self._by_key:
                raise ValueError("duplicate_key")
            ts = time.time()
            item = APIKeyState(id=str(uuid.uuid4()), key=key, enabled=enabled, created_at=ts, updated_at=ts)
            self._keys[item.id] = item
            self._by_key[key] = item.id
            return item

    async def update(self, key_id: str, *, raw_key: str | None = None, enabled: bool | None = None) -> APIKeyState:
        async with self._lock:
            item = self._keys.get(key_id)
            if not item:
                raise KeyError("key_not_found")

            if raw_key is not None:
                key = _normalize_api_key(raw_key)
                if not key:
                    raise ValueError("invalid_key")
                existing_id = self._by_key.get(key)
                if existing_id and existing_id != key_id:
                    raise ValueError("duplicate_key")
                if key != item.key:
                    self._by_key.pop(item.key, None)
                    item.key = key
                    self._by_key[key] = key_id

            if enabled is not None:
                item.enabled = bool(enabled)

            item.updated_at = time.time()
            return item

    async def toggle(self, key_id: str) -> APIKeyState:
        async with self._lock:
            item = self._keys.get(key_id)
            if not item:
                raise KeyError("key_not_found")
            item.enabled = not item.enabled
            item.updated_at = time.time()
            return item

    async def delete(self, key_id: str) -> bool:
        async with self._lock:
            item = self._keys.pop(key_id, None)
            if not item:
                return False
            self._by_key.pop(item.key, None)
            return True

    async def import_lines(self, lines: list[str]) -> dict[str, Any]:
        added = 0
        duplicates = 0
        invalid = 0
        duplicate_line_numbers: list[int] = []
        invalid_line_numbers: list[int] = []
        batch_seen: set[str] = set()

        async with self._lock:
            for line_no, raw in enumerate(lines, start=1):
                key = _normalize_api_key(raw)
                if not key:
                    invalid += 1
                    invalid_line_numbers.append(line_no)
                    continue

                if key in batch_seen or key in self._by_key:
                    duplicates += 1
                    duplicate_line_numbers.append(line_no)
                    continue

                batch_seen.add(key)
                ts = time.time()
                item = APIKeyState(id=str(uuid.uuid4()), key=key, created_at=ts, updated_at=ts)
                self._keys[item.id] = item
                self._by_key[key] = item.id
                added += 1

        return {
            "added": added,
            "duplicates": duplicates,
            "invalid": invalid,
            "duplicate_line_numbers": duplicate_line_numbers,
            "invalid_line_numbers": invalid_line_numbers,
        }

    async def acquire(self, excluded_key_ids: set[str], requested_key_id: str | None = None) -> APIKeyState | None:
        async with self._lock:
            if requested_key_id:
                item = self._keys.get(requested_key_id)
                if not item or not item.enabled or item.id in excluded_key_ids:
                    raise RuntimeError("requested_key_unavailable")
                self._recover_if_due(item)
                if not item.healthy:
                    raise RuntimeError("requested_key_circuit_open")
                item.total_requests += 1
                item.last_used_at = time.time()
                item.updated_at = time.time()
                return item

            candidates: list[APIKeyState] = []
            for item in self._keys.values():
                if not item.enabled or item.id in excluded_key_ids:
                    continue
                self._recover_if_due(item)
                if item.healthy:
                    candidates.append(item)

            if not candidates:
                return None

            candidates.sort(key=lambda x: x.created_at)
            idx = self._rr_cursor % len(candidates)
            item = candidates[idx]
            self._rr_cursor = (self._rr_cursor + 1) % max(1, len(candidates))
            item.total_requests += 1
            item.last_used_at = time.time()
            item.updated_at = time.time()
            return item

    async def mark_success(self, key_id: str) -> None:
        async with self._lock:
            item = self._keys.get(key_id)
            if not item:
                return
            item.fail_count = 0
            item.healthy = True
            item.cooldown_until = None
            item.last_error = None
            item.updated_at = time.time()

    async def mark_failure(self, key_id: str, error: str) -> None:
        async with self._lock:
            item = self._keys.get(key_id)
            if not item:
                return
            item.total_failures += 1
            item.fail_count += 1
            item.last_error = (error or "unknown")[:300]
            if item.fail_count >= self._failure_threshold:
                item.healthy = False
                item.cooldown_until = time.time() + self._cooldown_seconds
            item.updated_at = time.time()


# =========================
# Auth
# =========================


@dataclass
class AdminClaims:
    username: str
    exp: int
    iat: int
    jti: str | None = None


def _validate_security_settings() -> None:
    if not SETTINGS.admin_password_hash and not SETTINGS.admin_password:
        raise RuntimeError("ADMIN_PASSWORD_HASH or ADMIN_PASSWORD is required")
    if not SETTINGS.jwt_secret:
        raise RuntimeError("JWT_SECRET is required")
    if SETTINGS.searx_compat_username and not SETTINGS.searx_compat_password_hash and not SETTINGS.searx_compat_password:
        raise RuntimeError(
            "SEARX_COMPAT_PASSWORD_HASH or SEARX_COMPAT_PASSWORD is required when SEARX_COMPAT_USERNAME is set"
        )


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padded = value + "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


def _jwt_sign(signing_input: bytes, secret: str) -> str:
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return _b64url_encode(sig)


def _jwt_encode(payload: dict[str, Any], secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_part = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_part = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_part}.{payload_part}".encode("utf-8")
    sig_part = _jwt_sign(signing_input, secret)
    return f"{header_part}.{payload_part}.{sig_part}"


def _jwt_decode(token: str, secret: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("invalid_token_format")

    header_part, payload_part, sig_part = parts
    signing_input = f"{header_part}.{payload_part}".encode("utf-8")
    expected = _jwt_sign(signing_input, secret)
    if not hmac.compare_digest(expected, sig_part):
        raise ValueError("invalid_token_signature")

    try:
        payload = json.loads(_b64url_decode(payload_part))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("invalid_token_payload") from exc

    exp = int(payload.get("exp") or 0)
    if not exp or time.time() >= exp:
        raise ValueError("token_expired")
    return payload


def _verify_password_hash(password_plain: str, password_hash: str) -> bool:
    pwd = password_plain or ""
    saved = (password_hash or "").strip()
    if not saved:
        return False

    # 1) sha256$<digest_hex>
    # 2) sha256$<salt>$<digest_hex> with digest = sha256((salt + password).encode())
    if saved.startswith("sha256$"):
        parts = saved.split("$")
        if len(parts) == 2:
            digest = hashlib.sha256(pwd.encode("utf-8")).hexdigest()
            return hmac.compare_digest(digest, parts[1])
        if len(parts) == 3:
            digest = hashlib.sha256(f"{parts[1]}{pwd}".encode("utf-8")).hexdigest()
            return hmac.compare_digest(digest, parts[2])
        return False

    # django-style: pbkdf2_sha256$<iterations>$<salt>$<hash_base64>
    if saved.startswith("pbkdf2_sha256$"):
        parts = saved.split("$")
        if len(parts) != 4:
            return False
        _, iter_text, salt, expected = parts
        try:
            iterations = int(iter_text)
        except ValueError:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), salt.encode("utf-8"), iterations)
        candidate_b64 = base64.b64encode(digest).decode("utf-8").strip()
        candidate_hex = digest.hex()
        return hmac.compare_digest(candidate_b64, expected) or hmac.compare_digest(candidate_hex, expected)

    # fallback: treat as plain sha256 hex
    digest = hashlib.sha256(pwd.encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, saved)


def _hash_password_sha256(password_plain: str) -> str:
    digest = hashlib.sha256((password_plain or "").encode("utf-8")).hexdigest()
    return f"sha256${digest}"


def _verify_password_input(password_plain: str, password_hash: str, password_raw: str) -> bool:
    # Prefer hash verification when provided.
    if (password_hash or "").strip():
        return _verify_password_hash(password_plain, password_hash)
    return hmac.compare_digest(password_plain or "", password_raw or "")


async def _get_searx_compat_credentials() -> tuple[str, str, str]:
    async with searx_compat_lock:
        username = str(searx_compat_state.get("username") or "").strip()
        password_hash = str(searx_compat_state.get("password_hash") or "").strip()
        password_raw = str(searx_compat_state.get("password") or "")
    return username, password_hash, password_raw


async def _set_searx_compat_credentials(username: str, password_hash: str, password_raw: str = "") -> None:
    async with searx_compat_lock:
        searx_compat_state["username"] = (username or "").strip()
        searx_compat_state["password_hash"] = (password_hash or "").strip()
        searx_compat_state["password"] = password_raw or ""


async def _persist_searx_compat_settings() -> None:
    username, password_hash, _password_raw = await _get_searx_compat_credentials()
    await _save_json(
        SETTINGS.searx_compat_store_path,
        {
            "username": username,
            "password_hash": password_hash,
        },
    )


def _create_admin_token(username: str) -> str:
    now = int(time.time())
    exp = now + SETTINGS.jwt_expire_minutes * 60
    payload = {
        "sub": username,
        "username": username,
        "iat": now,
        "exp": exp,
        "jti": str(uuid.uuid4()),
    }
    return _jwt_encode(payload, SETTINGS.jwt_secret)


async def require_admin(request: Request) -> AdminClaims:
    auth = (request.headers.get("authorization") or "").strip()
    if not auth.lower().startswith("bearer "):
        await event_log.add("WARN", "auth_missing_bearer", f"path={request.url.path}")
        raise AppError(status_code=401, code="unauthorized", message="missing bearer token")

    token = auth[7:].strip()
    if not token:
        raise AppError(status_code=401, code="unauthorized", message="missing bearer token")

    try:
        payload = _jwt_decode(token, SETTINGS.jwt_secret)
    except ValueError as exc:
        await event_log.add("WARN", "auth_invalid_token", f"path={request.url.path}, reason={exc}")
        raise AppError(status_code=401, code="invalid_token", message=str(exc)) from exc

    username = str(payload.get("username") or payload.get("sub") or "").strip()
    if not username or username != SETTINGS.admin_username:
        await event_log.add("WARN", "auth_user_mismatch", f"path={request.url.path}, user={username}")
        raise AppError(status_code=401, code="invalid_token", message="token user mismatch")

    return AdminClaims(
        username=username,
        exp=int(payload.get("exp") or 0),
        iat=int(payload.get("iat") or 0),
        jti=str(payload.get("jti")) if payload.get("jti") else None,
    )


def _decode_basic_auth(auth_header: str) -> tuple[str, str] | None:
    text = (auth_header or "").strip()
    if not text.lower().startswith("basic "):
        return None
    encoded = text[6:].strip()
    if not encoded:
        return None
    try:
        raw = base64.b64decode(encoded, validate=True).decode("utf-8", errors="strict")
    except (binascii.Error, UnicodeDecodeError):
        return None
    if ":" not in raw:
        return None
    username, password = raw.split(":", 1)
    return username, password


async def require_searx_compat_auth(request: Request) -> None:
    username_cfg, password_hash_cfg, password_raw_cfg = await _get_searx_compat_credentials()

    # If no dedicated credentials are configured, keep compatibility endpoint open.
    if not username_cfg:
        return

    auth = (request.headers.get("authorization") or "").strip()
    decoded = _decode_basic_auth(auth)
    if not decoded:
        raise HTTPException(
            status_code=401,
            detail={"code": "basic_auth_required", "message": "basic auth required"},
            headers={"WWW-Authenticate": 'Basic realm="searx-compat", charset="UTF-8"'},
        )

    username, password = decoded
    username_ok = hmac.compare_digest(username, username_cfg)
    password_ok = _verify_password_input(password, password_hash_cfg, password_raw_cfg)
    if not username_ok or not password_ok:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_basic_credentials", "message": "invalid username or password"},
            headers={"WWW-Authenticate": 'Basic realm="searx-compat", charset="UTF-8"'},
        )


# =========================
# Persistence
# =========================


async def _load_json(path: Path) -> Any:
    if not path.exists():
        return None

    def _read() -> str:
        return path.read_text(encoding="utf-8")

    raw = await asyncio.to_thread(_read)
    if not raw.strip():
        return None
    return json.loads(raw)


async def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    def _write() -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    await asyncio.to_thread(_write)


# =========================
# Request models
# =========================


class NodeCreateRequest(BaseModel):
    base_url: str
    enabled: bool = True


class NodeUpdateRequest(BaseModel):
    base_url: str | None = None
    enabled: bool | None = None


class KeyCreateRequest(BaseModel):
    key: str
    enabled: bool = True


class KeyUpdateRequest(BaseModel):
    key: str | None = None
    enabled: bool | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class ProxyRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    stream: bool = False
    api_key_id: str | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)


class OpenAIChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str | None = None
    messages: list[Any] | None = None
    stream: bool = False
    api_key_id: str | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)


class SearxSearchRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    q: str | None = None
    query: str | None = None
    count: int | None = Field(default=None, gt=0)
    max_results: int | None = Field(default=None, gt=0)
    format: str | None = "json"


class SearxCompatSettingsUpdateRequest(BaseModel):
    enabled: bool = False
    username: str | None = None
    password: str | None = None


# =========================
# App
# =========================


app = FastAPI(title="Ollama Web Search Service", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=SETTINGS.cors_allow_origins,
    allow_origin_regex=SETTINGS.cors_allow_origin_regex,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-trace-id"],
)
event_log = EventLog(max_len=SETTINGS.log_buffer_size)
node_pool = NodePool(SETTINGS.ollama_nodes, failure_threshold=SETTINGS.node_failure_threshold)
key_pool = APIKeyPool(
    failure_threshold=SETTINGS.key_failure_threshold,
    cooldown_seconds=SETTINGS.key_cooldown_seconds,
)
state_lock = asyncio.Lock()
searx_compat_lock = asyncio.Lock()
searx_compat_state: dict[str, str] = {
    "username": SETTINGS.searx_compat_username,
    "password_hash": SETTINGS.searx_compat_password_hash,
    "password": SETTINGS.searx_compat_password,
}

# =============================================================================
# Static File Serving (for single-container deployment)
# =============================================================================
STATIC_DIR = Path(os.getenv("STATIC_DIR", "/app/static"))

def _is_static_request(path: str) -> bool:
    """Check if path looks like a static file request."""
    # Files with extensions (except .html which should be handled by SPA)
    if "." in Path(path).name:
        ext = Path(path).suffix.lower()
        if ext in {".js", ".css", ".map", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".webp", ".webm", ".mp4", ".mp3", ".json"}:
            return True
    return False


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    trace_id = (request.headers.get("x-trace-id") or "").strip() or str(uuid.uuid4())
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["x-trace-id"] = trace_id
    return response


@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    await event_log.add("WARN", "request_error", f"path={request.url.path}, code={exc.code}")
    return _error_response(exc.status_code, exc.code, exc.message, _get_trace_id(request))


@app.exception_handler(HTTPException)
async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    code, message = _normalize_http_error(exc.detail, exc.status_code)
    await event_log.add("WARN", "request_error", f"path={request.url.path}, code={code}")
    return _error_response(exc.status_code, code, message, _get_trace_id(request))


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    message = str(first.get("msg") or "request validation error")
    await event_log.add("WARN", "validation_error", f"path={request.url.path}, msg={message}")
    return _error_response(422, "validation_error", message, _get_trace_id(request))


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    await event_log.add("ERROR", "unhandled_exception", f"path={request.url.path}, type={exc.__class__.__name__}")
    return _error_response(500, "internal_error", "internal server error", _get_trace_id(request))


async def _persist_nodes() -> None:
    rows = await node_pool.store_rows()
    await _save_json(SETTINGS.nodes_store_path, rows)


async def _persist_keys() -> None:
    rows = await key_pool.store_rows()
    await _save_json(SETTINGS.keys_store_path, rows)


async def _load_state() -> None:
    async with state_lock:
        nodes_rows = await _load_json(SETTINGS.nodes_store_path)
        if isinstance(nodes_rows, list) and nodes_rows:
            await node_pool.load_from_store(nodes_rows)

        keys_rows = await _load_json(SETTINGS.keys_store_path)
        if isinstance(keys_rows, list) and keys_rows:
            await key_pool.load_from_store(keys_rows)

        searx_rows = await _load_json(SETTINGS.searx_compat_store_path)
        if isinstance(searx_rows, dict):
            username = str(searx_rows.get("username") or "").strip()
            password_hash = str(searx_rows.get("password_hash") or "").strip()
            if username and not password_hash:
                raise RuntimeError("invalid searx_compat settings: password_hash required when username is set")
            await _set_searx_compat_credentials(username, password_hash, "")


async def _health_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await node_pool.probe_once(app.state.http, SETTINGS.health_path, SETTINGS.request_timeout_seconds)
        except Exception as exc:  # noqa: BLE001
            await event_log.add("WARN", "health_probe_error", str(exc))
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(3, SETTINGS.health_interval_seconds))
        except asyncio.TimeoutError:
            continue


@app.on_event("startup")
async def startup() -> None:
    _validate_security_settings()
    app.state.http = httpx.AsyncClient(timeout=SETTINGS.request_timeout_seconds)
    app.state.stop_event = asyncio.Event()
    await _load_state()
    app.state.health_task = asyncio.create_task(_health_loop(app.state.stop_event))
    await event_log.add("INFO", "startup", "service_started")


@app.on_event("shutdown")
async def shutdown() -> None:
    app.state.stop_event.set()
    app.state.health_task.cancel()
    try:
        await app.state.health_task
    except BaseException:
        pass
    await app.state.http.aclose()


# =========================
# Health & stats
# =========================


async def _health_payload() -> dict[str, Any]:
    nodes = await node_pool.list()
    keys = await key_pool.list()
    return {
        "status": "ok",
        "service": "ollama-web-search",
        "nodes": {
            "total": len(nodes),
            "enabled": sum(1 for n in nodes if n["enabled"]),
            "healthy": sum(1 for n in nodes if n["enabled"] and n["healthy"]),
        },
        "keys": {
            "total": len(keys),
            "enabled": sum(1 for k in keys if k["enabled"]),
            "healthy": sum(1 for k in keys if k["enabled"] and k["healthy"]),
            "total_requests": sum(int(k["total_requests"]) for k in keys),
            "total_failures": sum(int(k["total_failures"]) for k in keys),
        },
    }


@app.get("/health")
async def health_root() -> dict[str, Any]:
    return await _health_payload()


@app.get("/api/health")
async def health_api() -> dict[str, Any]:
    return await _health_payload()


@app.get("/api/stats")
async def stats_api(_admin: AdminClaims = Depends(require_admin)) -> dict[str, Any]:
    return {
        "health": await _health_payload(),
        "nodes": await node_pool.list(),
        "keys": await key_pool.list(),
    }


@app.get("/api/logs")
async def logs_api(limit: int = Query(default=100, ge=1, le=500), _admin: AdminClaims = Depends(require_admin)) -> dict[str, Any]:
    return {"logs": await event_log.list(limit)}


# =========================
# System settings APIs
# =========================


def _build_searx_compat_settings_payload(username: str, password_hash: str, password_raw: str = "") -> dict[str, Any]:
    enabled = bool(username and (password_hash or password_raw))
    return {
        "enabled": enabled,
        "username": username,
        "has_password": bool(password_hash or password_raw),
        "search_path": "/search",
    }


@app.get("/api/settings/searx-compat")
async def get_searx_compat_settings(_admin: AdminClaims = Depends(require_admin)) -> dict[str, Any]:
    username, password_hash, password_raw = await _get_searx_compat_credentials()
    return _build_searx_compat_settings_payload(username, password_hash, password_raw)


@app.put("/api/settings/searx-compat")
async def update_searx_compat_settings(
    req: SearxCompatSettingsUpdateRequest,
    _admin: AdminClaims = Depends(require_admin),
) -> dict[str, Any]:
    current_username, current_password_hash, current_password_raw = await _get_searx_compat_credentials()

    enabled = bool(req.enabled)
    username = (req.username or "").strip()
    password = req.password or ""

    if not enabled:
        next_username = ""
        next_password_hash = ""
        next_password_raw = ""
    else:
        if not username:
            raise AppError(400, "username_required", "username_required")
        if ":" in username:
            raise AppError(400, "invalid_username", "invalid_username")

        next_username = username
        next_password_hash = current_password_hash
        next_password_raw = current_password_raw

        if password:
            next_password_hash = _hash_password_sha256(password)
            next_password_raw = ""

        if not next_password_hash and not next_password_raw:
            raise AppError(400, "password_required", "password_required")

    await _set_searx_compat_credentials(next_username, next_password_hash, next_password_raw)
    await _persist_searx_compat_settings()

    await event_log.add(
        "INFO",
        "searx_compat_update",
        f"enabled={bool(next_username and (next_password_hash or next_password_raw))}, user_changed={current_username != next_username}",
    )
    return _build_searx_compat_settings_payload(next_username, next_password_hash, next_password_raw)


# =========================
# Auth APIs
# =========================


@app.post("/api/auth/login")
async def auth_login(req: LoginRequest, request: Request) -> dict[str, Any]:
    username = (req.username or "").strip()
    if username != SETTINGS.admin_username or not _verify_password_input(
        req.password,
        SETTINGS.admin_password_hash,
        SETTINGS.admin_password,
    ):
        await event_log.add("WARN", "auth_login_failed", f"path={request.url.path}, user={username}")
        raise AppError(401, "invalid_credentials", "invalid username or password")

    token = _create_admin_token(username)
    await event_log.add("INFO", "auth_login_success", f"path={request.url.path}, user={username}")
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": SETTINGS.jwt_expire_minutes * 60,
        "admin": {
            "username": username,
        },
    }


@app.get("/api/auth/me")
async def auth_me(claims: AdminClaims = Depends(require_admin)) -> dict[str, Any]:
    return {
        "username": claims.username,
        "exp": claims.exp,
        "iat": claims.iat,
    }


# =========================
# Node APIs
# =========================


@app.get("/api/nodes")
async def list_nodes(_admin: AdminClaims = Depends(require_admin)) -> dict[str, Any]:
    return {"nodes": await node_pool.list()}


@app.post("/api/nodes")
async def add_node(req: NodeCreateRequest, _admin: AdminClaims = Depends(require_admin)) -> dict[str, Any]:
    node = await node_pool.add(req.base_url, enabled=req.enabled)
    await _persist_nodes()
    await event_log.add("INFO", "node_add", node.base_url)
    return {"node": node.to_dict()}


@app.put("/api/nodes/{node_id}")
async def update_node(node_id: str, req: NodeUpdateRequest, _admin: AdminClaims = Depends(require_admin)) -> dict[str, Any]:
    try:
        node = await node_pool.update(node_id, base_url=req.base_url, enabled=req.enabled)
    except KeyError as exc:
        raise AppError(404, "node_not_found", "node_not_found") from exc
    except ValueError as exc:
        raise AppError(400, str(exc), str(exc)) from exc
    await _persist_nodes()
    await event_log.add("INFO", "node_update", f"{node_id}")
    return {"node": node.to_dict()}


@app.delete("/api/nodes/{node_id}")
async def delete_node(node_id: str, _admin: AdminClaims = Depends(require_admin)) -> dict[str, Any]:
    ok = await node_pool.remove(node_id)
    if not ok:
        raise AppError(404, "node_not_found", "node_not_found")
    await _persist_nodes()
    await event_log.add("INFO", "node_delete", node_id)
    return {"status": "deleted", "node_id": node_id}


# =========================
# Key APIs
# =========================


def _extract_lines_from_json_or_text(ctype: str, text: str) -> list[str]:
    if "application/json" not in ctype:
        return text.splitlines()

    try:
        data = json.loads(text or "{}")
    except Exception:  # noqa: BLE001
        return text.splitlines()

    if isinstance(data, str):
        return data.splitlines()

    if isinstance(data, list):
        out: list[str] = []
        for item in data:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict) and item.get("key") is not None:
                out.append(str(item.get("key")))
        return out

    if isinstance(data, dict):
        if isinstance(data.get("keys"), list):
            return [str(x) for x in data.get("keys")]
        if isinstance(data.get("keys_text"), str):
            return data.get("keys_text", "").splitlines()
        if isinstance(data.get("lines"), list):
            return [str(x) for x in data.get("lines")]

    return text.splitlines()


@app.get("/api/keys")
async def list_keys(_admin: AdminClaims = Depends(require_admin)) -> dict[str, Any]:
    return {"keys": await key_pool.list()}


@app.post("/api/keys")
async def create_key(req: KeyCreateRequest, _admin: AdminClaims = Depends(require_admin)) -> dict[str, Any]:
    try:
        item = await key_pool.create(req.key, enabled=req.enabled)
    except ValueError as exc:
        raise AppError(400, str(exc), str(exc)) from exc

    await _persist_keys()
    await event_log.add("INFO", "key_create", item.id)
    return {"key": item.to_dict()}


@app.patch("/api/keys/{key_id}")
async def update_key(key_id: str, req: KeyUpdateRequest, _admin: AdminClaims = Depends(require_admin)) -> dict[str, Any]:
    try:
        item = await key_pool.update(key_id, raw_key=req.key, enabled=req.enabled)
    except KeyError as exc:
        raise AppError(404, "key_not_found", "key_not_found") from exc
    except ValueError as exc:
        raise AppError(400, str(exc), str(exc)) from exc

    await _persist_keys()
    await event_log.add("INFO", "key_update", key_id)
    return {"key": item.to_dict()}


@app.patch("/api/keys/{key_id}/toggle")
async def toggle_key(key_id: str, _admin: AdminClaims = Depends(require_admin)) -> dict[str, Any]:
    try:
        item = await key_pool.toggle(key_id)
    except KeyError as exc:
        raise AppError(404, "key_not_found", "key_not_found") from exc

    await _persist_keys()
    await event_log.add("INFO", "key_toggle", f"{key_id}:{item.enabled}")
    return {"key": item.to_dict()}


@app.delete("/api/keys/{key_id}")
async def delete_key(key_id: str, _admin: AdminClaims = Depends(require_admin)) -> dict[str, Any]:
    ok = await key_pool.delete(key_id)
    if not ok:
        raise AppError(404, "key_not_found", "key_not_found")
    await _persist_keys()
    await event_log.add("INFO", "key_delete", key_id)
    return {"status": "deleted", "key_id": key_id}


@app.post("/api/keys/import")
async def import_keys(request: Request, _admin: AdminClaims = Depends(require_admin)) -> dict[str, Any]:
    ctype = (request.headers.get("content-type") or "").lower()
    body = await request.body()
    text = body.decode("utf-8", errors="ignore")
    lines = _extract_lines_from_json_or_text(ctype, text)
    result = await key_pool.import_lines(lines)
    await _persist_keys()
    await event_log.add(
        "INFO",
        "key_import",
        json.dumps({"received": len(lines), "added": result["added"], "duplicates": result["duplicates"], "invalid": result["invalid"]}, ensure_ascii=False),
    )
    return {"status": "ok", "received": len(lines), **result}


# =========================
# Proxy
# =========================


def _build_headers(api_key: str | None) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream, text/plain, */*",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _is_retryable_status(status_code: int) -> bool:
    return status_code in {401, 403, 408, 409, 425, 429, 500, 502, 503, 504}


async def _choose_node_and_key(
    excluded_nodes: set[str],
    excluded_keys: set[str],
    requested_key_id: str | None,
    *,
    force_allow_no_key: bool = False,
) -> tuple[NodeState, APIKeyState | None]:
    node = await node_pool.acquire(excluded_nodes)
    key = await key_pool.acquire(excluded_keys, requested_key_id=requested_key_id)
    if key is None and not force_allow_no_key and not SETTINGS.allow_no_api_key:
        await node_pool.release_failure(node.id, "no_available_keys")
        raise RuntimeError("no_available_keys")
    return node, key


def _build_upstream_url(base_url: str, upstream_path: str, route_name: str) -> str:
    """
    Build upstream URL with a compatibility rule:
    - If web-search route uses default OWS path but node URL already ends with /search,
      treat node URL as the complete SearxNG endpoint.
    """
    base = (base_url or "").strip().rstrip("/")
    path = (upstream_path or "").strip()
    if not base:
        return path

    if path.startswith("http://") or path.startswith("https://"):
        return path

    parsed = urlparse(base)
    base_path = (parsed.path or "").rstrip("/")
    if (
        route_name in {"web_search", "openai_web_search"}
        and base_path.endswith("/search")
        and path in {"/api/web_search", "api/web_search"}
    ):
        return base

    if not path:
        return base

    if path.startswith("/"):
        return f"{base}{path}"
    return f"{base}/{path}"


def _is_searxng_mode(route_name: str, upstream_path: str, payload: dict[str, Any]) -> bool:
    if route_name not in {"web_search", "openai_web_search"}:
        return False

    backend_hint = str(payload.get("search_backend") or payload.get("backend") or "").strip().lower()
    if backend_hint in {"searxng", "searx"}:
        return True
    if bool(payload.get("use_searxng")):
        return True

    path = (upstream_path or "").strip().lower()
    if path.startswith("http://") or path.startswith("https://"):
        parsed = urlparse(path)
        path = (parsed.path or "").strip().lower()

    if path in {"search", "/search"} or path.endswith("/search"):
        return True
    return False


def _normalize_searx_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        parts = [str(x).strip() for x in value if str(x).strip()]
        return ",".join(parts) if parts else None
    text = str(value).strip()
    return text or None


def _build_searxng_params(payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query") or payload.get("q") or "").strip()
    if not query:
        raise AppError(400, "query_required", "query_required")

    params: dict[str, Any] = {"q": query, "format": str(payload.get("format") or "json")}

    if payload.get("max_results") is not None and payload.get("count") is None:
        try:
            params["count"] = int(payload.get("max_results"))
        except Exception:  # noqa: BLE001
            pass

    passthrough_map = {
        "count": "count",
        "engines": "engines",
        "categories": "categories",
        "language": "language",
        "time_range": "time_range",
        "pageno": "pageno",
        "safesearch": "safesearch",
    }
    for src, dst in passthrough_map.items():
        normalized = _normalize_searx_value(payload.get(src))
        if normalized is not None:
            params[dst] = normalized

    return params


async def _proxy_to_ollama(payload: dict[str, Any], upstream_path: str, route_name: str) -> Any:
    requested_key_id = payload.pop("api_key_id", None)
    timeout_seconds = float(payload.pop("timeout_seconds", SETTINGS.request_timeout_seconds))
    searxng_mode = _is_searxng_mode(route_name, upstream_path, payload)

    excluded_nodes: set[str] = set()
    excluded_keys: set[str] = set()
    attempts = max(1, SETTINGS.retry_attempts)
    last_error = "unknown"

    async def _stream_from_upstream(
        upstream: httpx.Response,
        node_id: str,
        key_id: str | None,
    ) -> AsyncGenerator[bytes, None]:
        ok = True
        try:
            async for chunk in upstream.aiter_bytes():
                if chunk:
                    yield chunk
        except Exception:  # noqa: BLE001
            ok = False
            raise
        finally:
            await upstream.aclose()
            if ok:
                await node_pool.release_success(node_id)
                if key_id:
                    await key_pool.mark_success(key_id)
            else:
                await node_pool.release_failure(node_id, "stream_interrupted")
                if key_id:
                    await key_pool.mark_failure(key_id, "stream_interrupted")

    for attempt in range(1, attempts + 1):
        node: NodeState | None = None
        key: APIKeyState | None = None
        try:
            node, key = await _choose_node_and_key(
                excluded_nodes,
                excluded_keys,
                requested_key_id,
                force_allow_no_key=searxng_mode,
            )
            headers = _build_headers(key.key if key else None)
            url = _build_upstream_url(node.base_url, upstream_path, route_name)

            if searxng_mode:
                params = _build_searxng_params(payload)
                searx_headers = {"Accept": "application/json"}
                if key:
                    searx_headers["Authorization"] = f"Bearer {key.key}"

                resp = await app.state.http.get(url, headers=searx_headers, params=params, timeout=timeout_seconds)
                if _is_retryable_status(resp.status_code):
                    excluded_nodes.add(node.id)
                    await node_pool.release_failure(node.id, f"http_{resp.status_code}")
                    if key:
                        excluded_keys.add(key.id)
                        await key_pool.mark_failure(key.id, f"http_{resp.status_code}")
                    last_error = resp.text[:300] or f"http_{resp.status_code}"
                    await event_log.add("WARN", f"{route_name}_retry", f"attempt={attempt}, status={resp.status_code}")
                    continue

                if resp.status_code >= 400:
                    await node_pool.release_failure(node.id, f"http_{resp.status_code}")
                    if key:
                        await key_pool.mark_failure(key.id, f"http_{resp.status_code}")
                    await event_log.add("ERROR", f"{route_name}_upstream_error", resp.text[:500])
                    raise AppError(status_code=resp.status_code, code="upstream_error", message=resp.text[:500])

                await node_pool.release_success(node.id)
                if key:
                    await key_pool.mark_success(key.id)
                await event_log.add("INFO", f"{route_name}_ok", f"attempt={attempt}, mode=searxng, node={node.base_url}")

                content_type = resp.headers.get("content-type", "application/json")
                if "json" in content_type:
                    return JSONResponse(status_code=resp.status_code, content=resp.json())
                return JSONResponse(status_code=resp.status_code, content={"text": resp.text})

            if payload.get("stream") is True:
                request_obj = app.state.http.build_request("POST", url, headers=headers, json=payload)
                upstream = await app.state.http.send(request_obj, stream=True, timeout=timeout_seconds)

                if _is_retryable_status(upstream.status_code):
                    raw = await upstream.aread()
                    await upstream.aclose()
                    excluded_nodes.add(node.id)
                    if key:
                        excluded_keys.add(key.id)
                        await key_pool.mark_failure(key.id, f"http_{upstream.status_code}")
                    await node_pool.release_failure(node.id, f"http_{upstream.status_code}")
                    last_error = raw.decode("utf-8", errors="ignore")[:300] or f"http_{upstream.status_code}"
                    await event_log.add("WARN", f"{route_name}_retry", f"attempt={attempt}, status={upstream.status_code}")
                    continue

                if upstream.status_code >= 400:
                    raw = await upstream.aread()
                    await upstream.aclose()
                    await node_pool.release_failure(node.id, f"http_{upstream.status_code}")
                    if key:
                        await key_pool.mark_failure(key.id, f"http_{upstream.status_code}")
                    detail = raw.decode("utf-8", errors="ignore")[:500]
                    await event_log.add("ERROR", f"{route_name}_upstream_error", detail)
                    raise AppError(status_code=upstream.status_code, code="upstream_error", message=detail)

                media_type = upstream.headers.get("content-type", "text/event-stream")
                await event_log.add("INFO", f"{route_name}_stream_ok", f"attempt={attempt}, node={node.base_url}")
                return StreamingResponse(
                    _stream_from_upstream(upstream, node.id, key.id if key else None),
                    media_type=media_type,
                )

            resp = await app.state.http.post(url, headers=headers, json=payload, timeout=timeout_seconds)
            if _is_retryable_status(resp.status_code):
                excluded_nodes.add(node.id)
                await node_pool.release_failure(node.id, f"http_{resp.status_code}")
                if key:
                    excluded_keys.add(key.id)
                    await key_pool.mark_failure(key.id, f"http_{resp.status_code}")
                last_error = resp.text[:300] or f"http_{resp.status_code}"
                await event_log.add("WARN", f"{route_name}_retry", f"attempt={attempt}, status={resp.status_code}")
                continue

            if resp.status_code >= 400:
                await node_pool.release_failure(node.id, f"http_{resp.status_code}")
                if key:
                    await key_pool.mark_failure(key.id, f"http_{resp.status_code}")
                await event_log.add("ERROR", f"{route_name}_upstream_error", resp.text[:500])
                raise AppError(status_code=resp.status_code, code="upstream_error", message=resp.text[:500])

            await node_pool.release_success(node.id)
            if key:
                await key_pool.mark_success(key.id)

            content_type = resp.headers.get("content-type", "application/json")
            await event_log.add("INFO", f"{route_name}_ok", f"attempt={attempt}, node={node.base_url}")
            if "json" in content_type:
                return JSONResponse(status_code=resp.status_code, content=resp.json())
            return JSONResponse(status_code=resp.status_code, content={"text": resp.text})

        except RuntimeError as exc:
            msg = str(exc)
            last_error = msg
            if msg in {
                "no_available_nodes",
                "no_available_keys",
                "requested_key_unavailable",
                "requested_key_circuit_open",
            }:
                break
            if node:
                await node_pool.release_failure(node.id, f"runtime:{msg}")
            if key:
                await key_pool.mark_failure(key.id, f"runtime:{msg}")
        except AppError:
            raise
        except httpx.HTTPError as exc:
            last_error = f"httpx:{exc.__class__.__name__}"
            if node:
                excluded_nodes.add(node.id)
                await node_pool.release_failure(node.id, last_error)
            if key:
                excluded_keys.add(key.id)
                await key_pool.mark_failure(key.id, last_error)
        except Exception as exc:  # noqa: BLE001
            last_error = f"exc:{exc.__class__.__name__}"
            if node:
                excluded_nodes.add(node.id)
                await node_pool.release_failure(node.id, last_error)
            if key:
                excluded_keys.add(key.id)
                await key_pool.mark_failure(key.id, last_error)

    await event_log.add("ERROR", f"{route_name}_failed", last_error)
    raise AppError(status_code=503, code="proxy_failed", message=f"proxy_failed:{last_error}")


def _extract_query_from_messages(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""

    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").lower()
        if role != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    t = str(item.get("type") or "")
                    if t in {"text", "input_text"} and item.get("text"):
                        parts.append(str(item.get("text")))
            if parts:
                return "\n".join(parts).strip()
    return ""


def _openai_tools_indicate_web_search(tools: Any) -> bool:
    if not isinstance(tools, list):
        return False
    for item in tools:
        if not isinstance(item, dict):
            continue
        tool_type = str(item.get("type") or "").lower()
        if tool_type in {"web_search", "web_search_preview"}:
            return True
    return False


def _build_openai_compatible_response(raw: Any, model: str | None) -> dict[str, Any]:
    if isinstance(raw, dict) and raw.get("object") == "chat.completion" and isinstance(raw.get("choices"), list):
        return raw

    content = ""
    if isinstance(raw, dict):
        if isinstance(raw.get("response"), str):
            content = raw.get("response") or ""
        elif isinstance(raw.get("text"), str):
            content = raw.get("text") or ""
        elif isinstance(raw.get("message"), dict) and isinstance(raw.get("message", {}).get("content"), str):
            content = str(raw.get("message", {}).get("content") or "")
        else:
            content = json.dumps(raw, ensure_ascii=False)
    elif isinstance(raw, str):
        content = raw
    else:
        content = json.dumps(raw, ensure_ascii=False)

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model or "unknown",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }
        ],
    }


def _looks_like_search_endpoint(path_or_url: str) -> bool:
    value = (path_or_url or "").strip().lower()
    if not value:
        return False
    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlparse(value)
        value = (parsed.path or "").strip().lower()
    return value in {"search", "/search"} or value.endswith("/search")


def _extract_proxy_payload(proxy_result: Any) -> Any:
    if isinstance(proxy_result, JSONResponse):
        try:
            text = (proxy_result.body or b"").decode("utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            return {}
        if not text:
            return {}
        try:
            return json.loads(text)
        except Exception:  # noqa: BLE001
            return {"text": text}
    if isinstance(proxy_result, (dict, list, str)):
        return proxy_result
    return {"text": str(proxy_result)}


def _pick_first_text(data: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
        elif isinstance(value, (int, float)):
            return str(value)
    return ""


def _normalize_searx_result_item(item: Any, idx: int) -> dict[str, Any] | None:
    if isinstance(item, str):
        text = item.strip()
        if not text:
            return None
        return {
            "title": f"Result {idx}",
            "url": "about:blank",
            "content": text,
            "engine": "gateway",
            "template": "default.html",
        }
    if not isinstance(item, dict):
        return None

    url = _pick_first_text(item, ["url", "link", "href", "source_url", "source"])
    title = _pick_first_text(item, ["title", "name", "headline"]) or (url or f"Result {idx}")
    content = _pick_first_text(item, ["content", "snippet", "description", "summary", "text", "response"])

    if not title and not url and not content:
        return None

    engine = _pick_first_text(item, ["engine", "provider", "source"]) or "gateway"
    template = _pick_first_text(item, ["template"]) or "default.html"

    normalized: dict[str, Any] = {
        "title": title or f"Result {idx}",
        "url": url or "about:blank",
        "content": content or "",
        "engine": engine,
        "template": template,
    }

    category = _pick_first_text(item, ["category"])
    if category:
        normalized["category"] = category

    score_val = item.get("score")
    if isinstance(score_val, (int, float)):
        normalized["score"] = float(score_val)

    published = _pick_first_text(item, ["publishedDate", "published_at", "published", "date", "created_at"])
    if published:
        normalized["publishedDate"] = published

    return normalized


def _build_searxng_compatible_response(raw: Any, query: str) -> dict[str, Any]:
    payload = raw if isinstance(raw, dict) else {}

    raw_results = None
    if isinstance(payload.get("results"), list):
        raw_results = payload.get("results")
    elif isinstance(payload.get("data"), list):
        raw_results = payload.get("data")
    elif isinstance(payload.get("items"), list):
        raw_results = payload.get("items")
    elif isinstance(raw, list):
        raw_results = raw
    else:
        raw_results = []

    normalized_results: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_results, start=1):
        normalized = _normalize_searx_result_item(item, idx)
        if normalized is not None:
            normalized_results.append(normalized)

    if not normalized_results:
        fallback = ""
        if isinstance(payload.get("response"), str):
            fallback = str(payload.get("response") or "").strip()
        elif isinstance(payload.get("text"), str):
            fallback = str(payload.get("text") or "").strip()
        elif isinstance(raw, str):
            fallback = raw.strip()

        if fallback:
            normalized_results.append(
                {
                    "title": "Answer",
                    "url": "about:blank",
                    "content": fallback,
                    "engine": "gateway",
                    "template": "default.html",
                }
            )

    number_of_results = payload.get("number_of_results")
    if not isinstance(number_of_results, int):
        number_of_results = len(normalized_results)

    answers = payload.get("answers") if isinstance(payload.get("answers"), list) else []
    corrections = payload.get("corrections") if isinstance(payload.get("corrections"), list) else []
    infoboxes = payload.get("infoboxes") if isinstance(payload.get("infoboxes"), list) else []
    suggestions = payload.get("suggestions") if isinstance(payload.get("suggestions"), list) else []
    unresponsive_engines = (
        payload.get("unresponsive_engines") if isinstance(payload.get("unresponsive_engines"), list) else []
    )

    return {
        "query": query,
        "number_of_results": number_of_results,
        "results": normalized_results,
        "answers": answers,
        "corrections": corrections,
        "infoboxes": infoboxes,
        "suggestions": suggestions,
        "unresponsive_engines": unresponsive_engines,
    }


def _prepare_searx_compat_proxy_payload(raw: dict[str, Any]) -> tuple[dict[str, Any], str]:
    query = str(raw.get("q") or raw.get("query") or "").strip()
    if not query:
        raise AppError(400, "query_required", "query_required")

    fmt = str(raw.get("format") or "json").strip().lower()
    if fmt and fmt != "json":
        raise AppError(400, "unsupported_format", "only json format is supported")

    count_raw = raw.get("count", raw.get("max_results", 10))
    try:
        max_results = int(count_raw)
    except Exception:  # noqa: BLE001
        max_results = 10
    max_results = max(1, min(50, max_results))

    proxy_payload: dict[str, Any] = {
        "query": query,
        "max_results": max_results,
        "stream": False,
    }

    if _looks_like_search_endpoint(SETTINGS.web_search_path):
        proxy_payload["search_backend"] = "searxng"
        proxy_payload["format"] = "json"
        for key in ["engines", "categories", "language", "time_range", "pageno", "safesearch"]:
            if raw.get(key) is not None:
                proxy_payload[key] = raw.get(key)
        proxy_payload["count"] = max_results

    return proxy_payload, query


async def _searx_compat_search(raw: dict[str, Any]) -> dict[str, Any]:
    proxy_payload, query = _prepare_searx_compat_proxy_payload(raw)
    proxied = await _proxy_to_ollama(proxy_payload, SETTINGS.web_search_path, route_name="web_search")
    raw_payload = _extract_proxy_payload(proxied)
    return _build_searxng_compatible_response(raw_payload, query=query)


@app.get("/search")
async def searxng_search_get(
    _auth: None = Depends(require_searx_compat_auth),
    q: str = Query(default="", alias="q"),
    format: str = Query(default="json", alias="format"),
    count: int | None = Query(default=None, ge=1, le=50, alias="count"),
    max_results: int | None = Query(default=None, ge=1, le=50, alias="max_results"),
    engines: str | None = Query(default=None, alias="engines"),
    categories: str | None = Query(default=None, alias="categories"),
    language: str | None = Query(default=None, alias="language"),
    time_range: str | None = Query(default=None, alias="time_range"),
    pageno: int | None = Query(default=None, ge=1, alias="pageno"),
    safesearch: int | None = Query(default=None, ge=0, le=2, alias="safesearch"),
) -> dict[str, Any]:
    await event_log.add("INFO", "searx_compat_request", "method=GET")
    raw = {
        "q": q,
        "format": format,
        "count": count,
        "max_results": max_results,
        "engines": engines,
        "categories": categories,
        "language": language,
        "time_range": time_range,
        "pageno": pageno,
        "safesearch": safesearch,
    }
    return await _searx_compat_search(raw)


@app.post("/search")
async def searxng_search_post(
    req: SearxSearchRequest,
    _auth: None = Depends(require_searx_compat_auth),
) -> dict[str, Any]:
    await event_log.add("INFO", "searx_compat_request", "method=POST")
    raw = req.model_dump(exclude_none=True)
    return await _searx_compat_search(raw)


@app.post("/api/web-search")
@app.post("/api/search")
async def api_web_search(req: ProxyRequest) -> Any:
    payload = req.model_dump(exclude_none=True)
    query = str(payload.get("query") or "").strip()
    if not query:
        raise AppError(400, "query_required", "query_required")
    await event_log.add("INFO", "web_search_request", f"stream={bool(payload.get('stream'))}")
    return await _proxy_to_ollama(payload, SETTINGS.web_search_path, route_name="web_search")


@app.post("/api/chat")
async def api_chat(req: ProxyRequest) -> Any:
    payload = req.model_dump(exclude_none=True)
    await event_log.add("INFO", "chat_request", f"stream={bool(payload.get('stream'))}")
    return await _proxy_to_ollama(payload, SETTINGS.chat_path, route_name="chat")


@app.post("/v1/chat/completions")
async def openai_chat_completions(req: OpenAIChatCompletionRequest) -> Any:
    payload = req.model_dump(exclude_none=True)
    use_web_search = bool(payload.get("query") or payload.get("web_search") or payload.get("use_web_search"))
    if not use_web_search:
        use_web_search = _openai_tools_indicate_web_search(payload.get("tools"))

    if use_web_search and not payload.get("query"):
        payload["query"] = _extract_query_from_messages(payload.get("messages"))

    if use_web_search:
        query = str(payload.get("query") or "").strip()
        if not query:
            raise AppError(400, "query_required", "query_required")
        await event_log.add("INFO", "openai_chat_request", f"mode=web_search, stream={bool(payload.get('stream'))}")
        return await _proxy_to_ollama(payload, SETTINGS.web_search_path, route_name="openai_web_search")

    await event_log.add("INFO", "openai_chat_request", f"mode=chat, stream={bool(payload.get('stream'))}")
    resp = await _proxy_to_ollama(payload, SETTINGS.chat_path, route_name="openai_chat")
    if isinstance(resp, StreamingResponse):
        return resp
    if isinstance(resp, JSONResponse):
        try:
            raw = json.loads(resp.body.decode("utf-8"))
        except Exception:  # noqa: BLE001
            raw = {"text": resp.body.decode("utf-8", errors="ignore")}
        mapped = _build_openai_compatible_response(raw, model=payload.get("model"))
        return JSONResponse(status_code=resp.status_code, content=mapped)
    return resp


# =============================================================================
# Static File Serving (SPA support for single-container deployment)
# =============================================================================

@app.get("/{full_path:path}", include_in_schema=False, response_model=None)
async def serve_spa(full_path: str, request: Request) -> Any:
    """
    Serve static files and SPA fallback.
    - API routes are handled by other route handlers
    - Static files (js, css, images, etc.) are served from STATIC_DIR
    - Everything else falls back to index.html for SPA routing
    """
    # Skip API routes
    if full_path.startswith("api/") or full_path.startswith("v1/"):
        return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": "Not found"}})

    # Check if requesting a static file
    if _is_static_request(full_path):
        file_path = STATIC_DIR / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)

    # SPA fallback: serve index.html for all other routes
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)

    return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": "Not found"}})


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
