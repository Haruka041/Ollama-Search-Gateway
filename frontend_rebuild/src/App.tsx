import { useEffect, useMemo, useState } from "react";
import { BackendApi } from "./lib/api";
import type { SessionState } from "./lib/types";
import { Layout, type AppTab } from "./components/Layout";
import { LoginPage } from "./pages/LoginPage";
import { DashboardPage } from "./pages/DashboardPage";
import { NodesPage } from "./pages/NodesPage";
import { KeysPage } from "./pages/KeysPage";
import { ProxyPage } from "./pages/ProxyPage";
import { LogsPage } from "./pages/LogsPage";
import { SettingsPage } from "./pages/SettingsPage";

const SESSION_STORAGE_KEY = "ows_rebuild_session";

function loadSession(): SessionState | null {
  try {
    const raw = localStorage.getItem(SESSION_STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as SessionState;
  } catch {
    return null;
  }
}

function saveSession(session: SessionState | null): void {
  if (!session) {
    localStorage.removeItem(SESSION_STORAGE_KEY);
    return;
  }
  localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
}

export default function App() {
  const [session, setSession] = useState<SessionState | null>(() => loadSession());
  const [activeTab, setActiveTab] = useState<AppTab>("dashboard");
  const [authError, setAuthError] = useState("");
  const [checkingSession, setCheckingSession] = useState<boolean>(() => Boolean(loadSession()));

  const api = useMemo(() => {
    if (!session) return null;
    return new BackendApi(session);
  }, [session]);

  const handleLoginSuccess = (next: SessionState) => {
    saveSession(next);
    setSession(next);
    setActiveTab("dashboard");
    setAuthError("");
    setCheckingSession(false);
  };

  const handleLogout = () => {
    saveSession(null);
    setSession(null);
    setAuthError("");
    setCheckingSession(false);
  };

  useEffect(() => {
    if (!api || !session) {
      setCheckingSession(false);
      return;
    }

    let canceled = false;
    setCheckingSession(true);
    void api
      .me()
      .then(() => {
        if (!canceled) {
          setAuthError("");
          setCheckingSession(false);
        }
      })
      .catch((err: unknown) => {
        if (canceled) return;
        const message = err instanceof Error ? err.message : "登录状态已失效，请重新登录";
        setAuthError(message);
        saveSession(null);
        setSession(null);
        setCheckingSession(false);
      });

    return () => {
      canceled = true;
    };
  }, [api, session]);

  const renderTab = () => {
    if (!api) return null;
    if (activeTab === "dashboard") return <DashboardPage api={api} />;
    if (activeTab === "nodes") return <NodesPage api={api} />;
    if (activeTab === "keys") return <KeysPage api={api} />;
    if (activeTab === "proxy") return <ProxyPage api={api} />;
    if (activeTab === "settings") return <SettingsPage api={api} />;
    return <LogsPage api={api} />;
  };

  if (!session || !api) {
    return <LoginPage onLoginSuccess={handleLoginSuccess} />;
  }

  if (checkingSession) {
    return (
      <div className="login-screen">
        <div className="login-card">
          <h1>校验登录状态...</h1>
          <p className="muted">正在验证 JWT 是否有效</p>
        </div>
      </div>
    );
  }

  return (
    <>
      {authError ? <p className="error-banner">{authError}</p> : null}
      <Layout username={session.username} activeTab={activeTab} onTabChange={setActiveTab} onLogout={handleLogout}>
        {renderTab()}
      </Layout>
    </>
  );
}
