import type { ReactNode } from "react";

export type AppTab = "dashboard" | "nodes" | "keys" | "proxy" | "logs" | "settings";

interface LayoutProps {
  username: string;
  activeTab: AppTab;
  onTabChange: (tab: AppTab) => void;
  onLogout: () => void;
  children: ReactNode;
}

const tabs: Array<{ id: AppTab; label: string }> = [
  { id: "dashboard", label: "总览" },
  { id: "nodes", label: "节点" },
  { id: "keys", label: "Keys" },
  { id: "proxy", label: "请求测试" },
  { id: "logs", label: "运行日志" },
  { id: "settings", label: "设置" },
];

export function Layout({ username, activeTab, onTabChange, onLogout, children }: LayoutProps) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <p className="brand-kicker">OSG</p>
          <h1>Gateway Console</h1>
          <p className="brand-subtitle">Ollama Search Gateway 管理台</p>
        </div>

        <nav className="nav">
          {tabs.map((tab) => (
            <button
              type="button"
              key={tab.id}
              className={`nav-item ${activeTab === tab.id ? "is-active" : ""}`}
              onClick={() => onTabChange(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <p className="user-chip">管理员: {username}</p>
          <button className="danger-btn" type="button" onClick={onLogout}>
            退出登录
          </button>
        </div>
      </aside>

      <main className="main-panel">{children}</main>
    </div>
  );
}
