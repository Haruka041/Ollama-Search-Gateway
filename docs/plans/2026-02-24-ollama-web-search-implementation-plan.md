# Ollama Web Search Backend Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a standalone FastAPI backend for Ollama web-search proxy with multi-node load balancing, API key management, rate limiting, and streaming support.

**Architecture:** Implement a single-service FastAPI app with in-memory managers: NodePool for node routing/health and APIKeyManager for key lifecycle/rate-limit/stats. `/web-search` proxies requests with failover retries and optional streaming passthrough.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, Pydantic, httpx

---

### Task 1: Scaffold project files

**Files:**
- Create: `backend/main.py`
- Create: `backend/requirements.txt`
- Create: `backend/README.md`

**Step 1:** Create FastAPI entrypoint with startup/shutdown hooks.

**Step 2:** Add dependency manifest.

**Step 3:** Add README run instructions.

### Task 2: Implement NodePool and health checks

**Files:**
- Modify: `backend/main.py`

**Step 1:** Add `NodeState` model and thread-safe/async-safe node manager.

**Step 2:** Implement `round-robin` and `least-connections` selection.

**Step 3:** Implement periodic health checker and failure-based ejection.

### Task 3: Implement API key manager and rate limiting

**Files:**
- Modify: `backend/main.py`

**Step 1:** Add key CRUD and bulk import parser (line-based dedupe).

**Step 2:** Add per-key minute window limiter and usage stats.

**Step 3:** Add key management endpoints.

### Task 4: Implement web-search proxy

**Files:**
- Modify: `backend/main.py`

**Step 1:** Add `/web-search` non-stream path with retry/failover.

**Step 2:** Add streaming passthrough with pre-yield retry.

**Step 3:** Add robust error responses and request validation.

### Task 5: Verification

**Files:**
- N/A

**Step 1:** Run `python3 -m py_compile backend/main.py`.

**Step 2:** Start server and run smoke curl tests for `/health`, `/keys/import`, `/web-search`.

**Step 3:** Document curl examples in README.
