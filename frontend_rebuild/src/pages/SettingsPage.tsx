import { useEffect, useState } from "react";
import { BackendApi } from "../lib/api";
import type { SearxCompatSettings } from "../lib/types";

interface SettingsPageProps {
  api: BackendApi;
}

export function SettingsPage({ api }: SettingsPageProps) {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [hasPassword, setHasPassword] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    setSuccess("");
    try {
      const resp = await api.getSearxCompatSettings();
      applyState(resp);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载设置失败");
    } finally {
      setLoading(false);
    }
  };

  const applyState = (resp: SearxCompatSettings) => {
    setEnabled(resp.enabled);
    setUsername(resp.username || "");
    setHasPassword(resp.has_password);
    setPassword("");
  };

  useEffect(() => {
    void load();
  }, []);

  const save = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const resp = await api.updateSearxCompatSettings({
        enabled,
        username: enabled ? username.trim() : "",
        password: password.trim() || undefined,
      });
      applyState(resp);
      setSuccess("Searx 兼容鉴权设置已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page">
      <header className="page-header">
        <h2>系统设置</h2>
        <button type="button" onClick={load} disabled={loading || saving}>
          {loading ? "刷新中..." : "刷新"}
        </button>
      </header>

      <section className="panel">
        <h3>SearxNG 兼容鉴权</h3>
        <form className="form" onSubmit={save}>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              disabled={saving}
            />
            启用 /search Basic Auth（建议公网开启）
          </label>

          <label>
            <span>Username</span>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="searx-user"
              disabled={!enabled || saving}
            />
          </label>

          <label>
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={hasPassword ? "留空表示不修改密码" : "首次启用必须输入密码"}
              disabled={!enabled || saving}
            />
          </label>

          <p className="muted">
            当前状态: {enabled ? "已启用" : "未启用"}，密码状态: {hasPassword ? "已设置" : "未设置"}
          </p>

          <div className="action-row">
            <button type="submit" disabled={saving}>
              {saving ? "保存中..." : "保存设置"}
            </button>
          </div>
        </form>
      </section>

      {error ? <p className="error-text">{error}</p> : null}
      {success ? <p className="info-text">{success}</p> : null}

      <section className="panel">
        <h3>客户端填写说明</h3>
        <div className="settings-help">
          <p>
            <strong>API URL</strong>: {api.searchCompatUrl()}
          </p>
          <p>
            <strong>Engines</strong>: 可留空，或填写 <code>google,bing,duckduckgo</code>
          </p>
          <p>
            <strong>Language</strong>: 可留空，或填写 <code>zh-CN</code>
          </p>
          <p>
            <strong>Username / Password</strong>: 启用鉴权后填写本页设置的账号密码；未启用可留空
          </p>
        </div>
      </section>
    </div>
  );
}

