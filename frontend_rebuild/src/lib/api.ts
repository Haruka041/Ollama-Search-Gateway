import type {
  AdminProfile,
  ApiErrorPayload,
  HealthPayload,
  KeyItem,
  LogItem,
  LoginResponse,
  NodeItem,
  SearxCompatSettings,
  SessionState,
  StatsPayload,
} from "./types";

export class ApiError extends Error {
  status: number;
  code: string;
  traceId: string;

  constructor(message: string, status: number, code = "request_failed", traceId = "") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.traceId = traceId;
  }
}

const jsonHeaders = {
  "Content-Type": "application/json",
};

function normalizeBaseUrl(raw: string): string {
  const value = raw.trim().replace(/\/+$/, "");
  if (!value) return "";
  if (/^https?:\/\//i.test(value)) return value;
  return `http://${value}`;
}

function resolveError(payload: unknown, status: number): ApiError {
  const p = (payload ?? {}) as ApiErrorPayload;
  const code = p.error?.code || `http_${status}`;
  const message = p.error?.message || "Request failed";
  const traceId = p.error?.trace_id || "";
  return new ApiError(message, status, code, traceId);
}

async function parseResponse<T>(resp: Response): Promise<T> {
  const contentType = resp.headers.get("content-type") || "";
  let payload: unknown;
  if (contentType.includes("application/json")) {
    payload = await resp.json().catch(() => ({}));
  } else {
    payload = await resp.text().catch(() => "");
  }

  if (!resp.ok) {
    throw resolveError(payload, resp.status);
  }

  return payload as T;
}

export class BackendApi {
  private baseUrl: string;
  private token: string;

  constructor(session: SessionState) {
    this.baseUrl = normalizeBaseUrl(session.baseUrl);
    this.token = session.token;
  }

  searchCompatUrl(): string {
    return `${this.baseUrl}/search`;
  }

  static async login(baseUrl: string, username: string, password: string): Promise<LoginResponse> {
    const normalizedBase = normalizeBaseUrl(baseUrl);
    const resp = await fetch(`${normalizedBase}/api/auth/login`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ username, password }),
    });
    return parseResponse<LoginResponse>(resp);
  }

  private async request<T>(
    path: string,
    init: RequestInit = {},
    options: { noAuth?: boolean } = {},
  ): Promise<T> {
    const headers: Record<string, string> = {
      ...jsonHeaders,
      ...(init.headers as Record<string, string>),
    };
    if (!options.noAuth) {
      headers.Authorization = `Bearer ${this.token}`;
    }

    const resp = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers,
    });
    return parseResponse<T>(resp);
  }

  me(): Promise<AdminProfile> {
    return this.request<AdminProfile>("/api/auth/me");
  }

  health(): Promise<HealthPayload> {
    return this.request<HealthPayload>("/api/health", {}, { noAuth: true });
  }

  stats(): Promise<StatsPayload> {
    return this.request<StatsPayload>("/api/stats");
  }

  listNodes(): Promise<{ nodes: NodeItem[] }> {
    return this.request<{ nodes: NodeItem[] }>("/api/nodes");
  }

  addNode(payload: { base_url: string; enabled: boolean }): Promise<{ node: NodeItem }> {
    return this.request<{ node: NodeItem }>("/api/nodes", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  updateNode(
    nodeId: string,
    payload: { base_url?: string; enabled?: boolean },
  ): Promise<{ node: NodeItem }> {
    return this.request<{ node: NodeItem }>(`/api/nodes/${encodeURIComponent(nodeId)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  }

  deleteNode(nodeId: string): Promise<{ status: string; node_id: string }> {
    return this.request<{ status: string; node_id: string }>(`/api/nodes/${encodeURIComponent(nodeId)}`, {
      method: "DELETE",
    });
  }

  listKeys(): Promise<{ keys: KeyItem[] }> {
    return this.request<{ keys: KeyItem[] }>("/api/keys");
  }

  addKey(payload: { key: string; enabled: boolean }): Promise<{ key: KeyItem }> {
    return this.request<{ key: KeyItem }>("/api/keys", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  updateKey(keyId: string, payload: { key?: string; enabled?: boolean }): Promise<{ key: KeyItem }> {
    return this.request<{ key: KeyItem }>(`/api/keys/${encodeURIComponent(keyId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  }

  toggleKey(keyId: string): Promise<{ key: KeyItem }> {
    return this.request<{ key: KeyItem }>(`/api/keys/${encodeURIComponent(keyId)}/toggle`, {
      method: "PATCH",
    });
  }

  deleteKey(keyId: string): Promise<{ status: string; key_id: string }> {
    return this.request<{ status: string; key_id: string }>(`/api/keys/${encodeURIComponent(keyId)}`, {
      method: "DELETE",
    });
  }

  importKeys(lines: string): Promise<{
    status: string;
    received: number;
    added: number;
    duplicates: number;
    invalid: number;
  }> {
    return this.request("/api/keys/import", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${this.token}`,
        "Content-Type": "text/plain",
      },
      body: lines,
    });
  }

  logs(limit: number): Promise<{ logs: LogItem[] }> {
    return this.request<{ logs: LogItem[] }>(`/api/logs?limit=${Math.max(1, Math.min(500, limit))}`);
  }

  getSearxCompatSettings(): Promise<SearxCompatSettings> {
    return this.request<SearxCompatSettings>("/api/settings/searx-compat");
  }

  updateSearxCompatSettings(payload: {
    enabled: boolean;
    username?: string;
    password?: string;
  }): Promise<SearxCompatSettings> {
    return this.request<SearxCompatSettings>("/api/settings/searx-compat", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  }

  postJson(path: string, payload: unknown): Promise<unknown> {
    return this.request(path, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  async postStream(path: string, payload: unknown, onChunk: (chunk: string) => void): Promise<void> {
    const resp = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${this.token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      const errorPayload = await resp.json().catch(() => ({}));
      throw resolveError(errorPayload, resp.status);
    }

    if (!resp.body) {
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder("utf-8");
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value) {
        onChunk(decoder.decode(value, { stream: true }));
      }
    }
  }
}

export function detectDefaultBaseUrl(): string {
  if (typeof window === "undefined") return "http://127.0.0.1:8080";
  const { protocol, hostname, port } = window.location;
  return `${protocol}//${hostname}${port ? `:${port}` : ""}`;
}
