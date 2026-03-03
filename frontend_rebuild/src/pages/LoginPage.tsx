import { useState } from "react";
import { BackendApi, detectDefaultBaseUrl } from "../lib/api";
import type { SessionState } from "../lib/types";

interface LoginPageProps {
  onLoginSuccess: (session: SessionState) => void;
}

export function LoginPage({ onLoginSuccess }: LoginPageProps) {
  const [baseUrl, setBaseUrl] = useState(detectDefaultBaseUrl());
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!baseUrl.trim() || !username.trim() || !password.trim()) {
      setError("请完整填写地址、用户名和密码。");
      return;
    }

    setSubmitting(true);
    setError("");
    try {
      const loginResp = await BackendApi.login(baseUrl, username.trim(), password);
      const session: SessionState = {
        baseUrl: baseUrl.trim(),
        token: loginResp.access_token,
        username: loginResp.admin.username,
      };

      const api = new BackendApi(session);
      const profile = await api.me();
      session.exp = profile.exp;
      onLoginSuccess(session);
    } catch (err) {
      const message = err instanceof Error ? err.message : "登录失败";
      setError(message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-screen">
      <div className="login-card">
        <p className="badge">Ollama Search Gateway</p>
        <h1>Gateway Console</h1>
        <p className="muted">连接后端控制面（`/api/auth/login` + Bearer JWT）</p>
        <form className="form" onSubmit={handleSubmit}>
          <label>
            <span>后端地址</span>
            <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="http://127.0.0.1:8080" />
          </label>
          <label>
            <span>管理员用户名</span>
            <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="admin" />
          </label>
          <label>
            <span>管理员密码</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="输入 ADMIN_PASSWORD_HASH 对应明文密码"
            />
          </label>
          {error ? <p className="error-text">{error}</p> : null}
          <button type="submit" disabled={submitting}>
            {submitting ? "登录中..." : "进入控制台"}
          </button>
        </form>
      </div>
    </div>
  );
}
