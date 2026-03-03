import { useEffect, useState } from "react";
import { BackendApi } from "../lib/api";
import type { HealthPayload, StatsPayload } from "../lib/types";

interface DashboardPageProps {
  api: BackendApi;
}

function StatCard({ title, value, hint }: { title: string; value: string | number; hint?: string }) {
  return (
    <section className="stat-card">
      <p>{title}</p>
      <h3>{value}</h3>
      {hint ? <span>{hint}</span> : null}
    </section>
  );
}

export function DashboardPage({ api }: DashboardPageProps) {
  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [stats, setStats] = useState<StatsPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const nodeSummary = health?.nodes ?? health?.node_pool;
  const keySummary = health?.keys ?? health?.key_pool;

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const [h, s] = await Promise.all([api.health(), api.stats()]);
      setHealth(h);
      setStats(s);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  return (
    <div className="page">
      <header className="page-header">
        <h2>系统总览</h2>
        <button type="button" onClick={load} disabled={loading}>
          {loading ? "刷新中..." : "刷新"}
        </button>
      </header>

      {error ? <p className="error-text">{error}</p> : null}

      <div className="grid-cards">
        <StatCard title="服务状态" value={health?.status ?? "-"} hint={health?.service ?? health?.timestamp ?? ""} />
        <StatCard
          title="节点健康"
          value={`${nodeSummary?.healthy ?? 0}/${nodeSummary?.total ?? 0}`}
          hint={`启用 ${nodeSummary?.enabled ?? 0}`}
        />
        <StatCard
          title="Key 健康"
          value={`${keySummary?.healthy ?? 0}/${keySummary?.total ?? 0}`}
          hint={`启用 ${keySummary?.enabled ?? 0}`}
        />
        <StatCard title="Key 总请求" value={keySummary?.total_requests ?? 0} />
        <StatCard title="Key 总失败" value={keySummary?.total_failures ?? 0} />
        <StatCard title="当前节点连接数" value={stats ? stats.nodes.reduce((acc, n) => acc + n.active_connections, 0) : 0} />
      </div>

      <section className="panel">
        <h3>节点快照</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>URL</th>
                <th>启用</th>
                <th>健康</th>
                <th>活跃连接</th>
                <th>请求数</th>
                <th>失败数</th>
              </tr>
            </thead>
            <tbody>
              {(stats?.nodes ?? []).map((node) => (
                <tr key={node.id}>
                  <td>{node.base_url}</td>
                  <td>{node.enabled ? "是" : "否"}</td>
                  <td>{node.healthy ? "健康" : "异常"}</td>
                  <td>{node.active_connections}</td>
                  <td>{node.total_requests}</td>
                  <td>{node.total_failures}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
