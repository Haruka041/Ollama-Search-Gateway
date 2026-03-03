import { useMemo, useState } from "react";
import { BackendApi } from "../lib/api";
import { JsonView } from "../components/JsonView";

interface ProxyPageProps {
  api: BackendApi;
}

type ProxyMode = "web-search" | "chat" | "openai";

const templates: Record<ProxyMode, string> = {
  "web-search": JSON.stringify(
    {
      query: "latest ollama web search news",
      max_results: 5,
      stream: false,
    },
    null,
    2,
  ),
  chat: JSON.stringify(
    {
      model: "qwen2.5",
      messages: [{ role: "user", content: "你好，介绍一下你自己" }],
      stream: false,
    },
    null,
    2,
  ),
  openai: JSON.stringify(
    {
      model: "qwen2.5",
      messages: [{ role: "user", content: "查一下今天 AI 领域的新闻" }],
      use_web_search: true,
      stream: false,
    },
    null,
    2,
  ),
};

function endpointByMode(mode: ProxyMode): string {
  if (mode === "web-search") return "/api/web-search";
  if (mode === "chat") return "/api/chat";
  return "/v1/chat/completions";
}

export function ProxyPage({ api }: ProxyPageProps) {
  const [mode, setMode] = useState<ProxyMode>("web-search");
  const [payloadText, setPayloadText] = useState(templates["web-search"]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<unknown>(null);
  const [streamText, setStreamText] = useState("");

  const endpoint = useMemo(() => endpointByMode(mode), [mode]);

  const switchMode = (next: ProxyMode) => {
    setMode(next);
    setPayloadText(templates[next]);
    setResult(null);
    setStreamText("");
    setError("");
  };

  const send = async () => {
    let payload: Record<string, unknown>;
    setError("");
    setResult(null);
    setStreamText("");
    try {
      payload = JSON.parse(payloadText) as Record<string, unknown>;
    } catch {
      setError("JSON 解析失败，请检查请求体格式。");
      return;
    }

    setRunning(true);
    try {
      if (payload.stream === true) {
        await api.postStream(endpoint, payload, (chunk) => {
          setStreamText((prev) => prev + chunk);
        });
      } else {
        const data = await api.postJson(endpoint, payload);
        setResult(data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "请求失败");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="page">
      <header className="page-header">
        <h2>代理请求测试</h2>
        <span className="muted">当前端点: {endpoint}</span>
      </header>

      <section className="panel">
        <div className="action-row">
          <button type="button" onClick={() => switchMode("web-search")} className={mode === "web-search" ? "is-primary" : ""}>
            Web Search
          </button>
          <button type="button" onClick={() => switchMode("chat")} className={mode === "chat" ? "is-primary" : ""}>
            Chat
          </button>
          <button type="button" onClick={() => switchMode("openai")} className={mode === "openai" ? "is-primary" : ""}>
            OpenAI 兼容
          </button>
        </div>

        <textarea
          rows={14}
          value={payloadText}
          onChange={(e) => setPayloadText(e.target.value)}
          spellCheck={false}
        />

        <div className="action-row">
          <button type="button" onClick={send} disabled={running}>
            {running ? "请求中..." : "发送请求"}
          </button>
          <button type="button" onClick={() => setPayloadText(templates[mode])} disabled={running}>
            重置模板
          </button>
        </div>
      </section>

      {error ? <p className="error-text">{error}</p> : null}

      {streamText ? (
        <section className="panel">
          <h3>流式输出</h3>
          <pre className="json-view">{streamText}</pre>
        </section>
      ) : null}

      {result !== null ? (
        <section className="panel">
          <h3>响应结果</h3>
          <JsonView data={result} />
        </section>
      ) : null}
    </div>
  );
}

