import { useEffect, useState } from "react";
import { BackendApi } from "../lib/api";
import type { LogItem } from "../lib/types";

interface LogsPageProps {
  api: BackendApi;
}

export function LogsPage({ api }: LogsPageProps) {
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [limit, setLimit] = useState(100);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const resp = await api.logs(limit);
      setLogs(resp.logs);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载日志失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [limit]);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = window.setInterval(() => {
      void load();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [autoRefresh, limit]);

  return (
    <div className="page">
      <header className="page-header">
        <h2>运行日志</h2>
        <div className="action-row">
          <label className="inline-text">
            limit
            <input
              value={limit}
              type="number"
              min={1}
              max={500}
              onChange={(e) => setLimit(Number(e.target.value || 100))}
            />
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            自动刷新(3s)
          </label>
          <button type="button" onClick={load} disabled={loading}>
            {loading ? "刷新中..." : "手动刷新"}
          </button>
        </div>
      </header>

      {error ? <p className="error-text">{error}</p> : null}

      <section className="panel">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>时间</th>
                <th>级别</th>
                <th>事件</th>
                <th>详情</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log, index) => (
                <tr key={`${log.ts}-${index}`}>
                  <td>{log.time}</td>
                  <td>{log.level}</td>
                  <td>{log.event}</td>
                  <td>{log.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

