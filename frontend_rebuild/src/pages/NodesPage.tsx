import { useEffect, useState } from "react";
import { BackendApi } from "../lib/api";
import type { NodeItem } from "../lib/types";

interface NodesPageProps {
  api: BackendApi;
}

export function NodesPage({ api }: NodesPageProps) {
  const [nodes, setNodes] = useState<NodeItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [newUrl, setNewUrl] = useState("");
  const [newEnabled, setNewEnabled] = useState(true);
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const resp = await api.listNodes();
      setNodes(resp.nodes);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载节点失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const addNode = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!newUrl.trim()) return;
    setSaving(true);
    setError("");
    try {
      await api.addNode({ base_url: newUrl.trim(), enabled: newEnabled });
      setNewUrl("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "新增节点失败");
    } finally {
      setSaving(false);
    }
  };

  const toggleEnabled = async (node: NodeItem) => {
    setSaving(true);
    setError("");
    try {
      await api.updateNode(node.id, { enabled: !node.enabled });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新节点失败");
    } finally {
      setSaving(false);
    }
  };

  const updateUrl = async (node: NodeItem) => {
    const url = window.prompt("输入新的节点 URL", node.base_url);
    if (!url || url.trim() === node.base_url) return;
    setSaving(true);
    setError("");
    try {
      await api.updateNode(node.id, { base_url: url.trim() });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新 URL 失败");
    } finally {
      setSaving(false);
    }
  };

  const removeNode = async (node: NodeItem) => {
    if (!window.confirm(`确认删除节点 ${node.base_url} ?`)) return;
    setSaving(true);
    setError("");
    try {
      await api.deleteNode(node.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除节点失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page">
      <header className="page-header">
        <h2>节点管理</h2>
        <button type="button" onClick={load} disabled={loading || saving}>
          {loading ? "刷新中..." : "刷新"}
        </button>
      </header>

      <section className="panel">
        <h3>新增节点</h3>
        <form className="inline-form" onSubmit={addNode}>
          <input
            value={newUrl}
            onChange={(e) => setNewUrl(e.target.value)}
            placeholder="https://ollama.com"
          />
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={newEnabled}
              onChange={(e) => setNewEnabled(e.target.checked)}
            />
            启用
          </label>
          <button type="submit" disabled={saving}>
            {saving ? "提交中..." : "添加"}
          </button>
        </form>
      </section>

      {error ? <p className="error-text">{error}</p> : null}

      <section className="panel">
        <h3>节点列表</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>URL</th>
                <th>启用</th>
                <th>健康</th>
                <th>请求</th>
                <th>失败</th>
                <th>最近错误</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {nodes.map((node) => (
                <tr key={node.id}>
                  <td>{node.base_url}</td>
                  <td>{node.enabled ? "是" : "否"}</td>
                  <td>{node.healthy ? "健康" : "异常"}</td>
                  <td>{node.total_requests}</td>
                  <td>{node.total_failures}</td>
                  <td>{node.last_error || "-"}</td>
                  <td>
                    <div className="action-row">
                      <button type="button" onClick={() => toggleEnabled(node)} disabled={saving}>
                        {node.enabled ? "禁用" : "启用"}
                      </button>
                      <button type="button" onClick={() => updateUrl(node)} disabled={saving}>
                        改 URL
                      </button>
                      <button type="button" onClick={() => removeNode(node)} disabled={saving}>
                        删除
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

