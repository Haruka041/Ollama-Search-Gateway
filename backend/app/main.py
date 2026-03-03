from fastapi import FastAPI

app = FastAPI(title="Ollama Web Search API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health")
def api_health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/search")
def search(q: str = "") -> dict[str, str]:
    """示例接口：后续可接入实际搜索逻辑。"""
    return {"query": q, "message": "search endpoint is ready"}
