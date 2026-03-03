import { useEffect, useState } from "react";
import { BackendApi } from "../lib/api";
import type { KeyItem } from "../lib/types";

interface KeysPageProps {
  api: BackendApi;
}

export function KeysPage({ api }: KeysPageProps) {
  const [keys, setKeys] = useState<KeyItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [newKey, setNewKey] = useState("");
  const [newEnabled, setNewEnabled] = useState(true);
  const [importText, setImportText] = useState("");
  const [error, setError] = useState("");
  const [importSummary, setImportSummary] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const resp = await api.listKeys();
      setKeys(resp.keys);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载 Key 列表失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const addKey = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!newKey.trim()) return;
    setSaving(true);
    setError("");
    setImportSummary("");
    try {
      await api.addKey({ key: newKey.trim(), enabled: newEnabled });
      setNewKey("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "新增 Key 失败");
    } finally {
      setSaving(false);
    }
  };

  const toggleKey = async (key: KeyItem) => {
    setSaving(true);
    setError("");
    try {
      await api.toggleKey(key.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "切换 Key 状态失败");
    } finally {
      setSaving(false);
    }
  };

  const deleteKey = async (key: KeyItem) => {
    if (!window.confirm(`确认删除 Key ${key.key} ?`)) return;
    setSaving(true);
    setError("");
    try {
      await api.deleteKey(key.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除 Key 失败");
    } finally {
      setSaving(false);
    }
  };

  const importKeys = async () => {
    if (!importText.trim()) return;
    setSaving(true);
    setError("");
    setImportSummary("");
    try {
      const result = await api.importKeys(importText);
      setImportSummary(
        `导入完成：received=${result.received} added=${result.added} duplicates=${result.duplicates} invalid=${result.invalid}`,
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "批量导入失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page">
      <header className="page-header">
        <h2>API Key 管理</h2>
        <button type="button" onClick={load} disabled={loading || saving}>
          {loading ? "刷新中..." : "刷新"}
        </button>
      </header>

      <section className="panel">
        <h3>新增 Key</h3>
        <form className="inline-form" onSubmit={addKey}>
          <input
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
            placeholder="sk-xxxx"
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

      <section className="panel">
        <h3>批量导入</h3>
        <textarea
          value={importText}
          onChange={(e) => setImportText(e.target.value)}
          rows={6}
          placeholder={"每行一个 Key\nsk-one\nsk-two"}
        />
        <div className="action-row">
          <button type="button" onClick={importKeys} disabled={saving}>
            {saving ? "导入中..." : "执行导入"}
          </button>
          <button type="button" onClick={() => setImportText("")} disabled={saving}>
            清空
          </button>
        </div>
        {importSummary ? <p className="info-text">{importSummary}</p> : null}
      </section>

      {error ? <p className="error-text">{error}</p> : null}

      <section className="panel">
        <h3>Key 列表</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Key(掩码)</th>
                <th>启用</th>
                <th>健康</th>
                <th>请求</th>
                <th>失败</th>
                <th>冷却到</th>
                <th>最后错误</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {keys.map((item) => (
                <tr key={item.id}>
                  <td>{item.key}</td>
                  <td>{item.enabled ? "是" : "否"}</td>
                  <td>{item.healthy ? "健康" : "熔断"}</td>
                  <td>{item.total_requests}</td>
                  <td>{item.total_failures}</td>
                  <td>{item.cooldown_until || "-"}</td>
                  <td>{item.last_error || "-"}</td>
                  <td>
                    <div className="action-row">
                      <button type="button" onClick={() => toggleKey(item)} disabled={saving}>
                        {item.enabled ? "禁用" : "启用"}
                      </button>
                      <button type="button" onClick={() => deleteKey(item)} disabled={saving}>
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

